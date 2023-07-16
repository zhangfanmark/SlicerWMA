import os, re, unittest, warnings
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging
import numpy as np
import subprocess
import importlib.metadata, glob, time
import argparse
import multiprocessing
import shutil


# helper class for cleaner multi-operation blocks on a single node.
class It(object):
  def __init__(self, node): self.node = node
  def __enter__(self): return self.node
  def __exit__(self, type, value, traceback): return False

#
# AnatomcalTractParcellation
#

class AnatomcalTractParcellation(ScriptedLoadableModule):

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "AnatomcalTractParcellation" # TODO make this more human readable by adding spaces
    self.parent.categories = ["Diffusion.WMA"]
    self.parent.dependencies = []
    self.parent.contributors = ["Fan Zhang (UESTC, BWH, HMS)"]
    self.parent.helpText = "This module is applying a pre-provided anatomically curated white matter atlas, \
                            along with the computation tools provided in whitematteranalysis, \
                            to perform subject-specific tractography parcellation."
    self.parent.helpText += self.getDefaultModuleDocumentationLink()
    self.parent.acknowledgementText = ""
    
#
# AnatomcalTractParcellationWidget
#

class AnatomcalTractParcellationWidget(ScriptedLoadableModuleWidget):

  def __init__(self, parent=None):
        super(AnatomcalTractParcellationWidget, self).__init__(parent)
        # 其他初始化代码...


  def setup(self):

    ScriptedLoadableModuleWidget.setup(self)

    self.logic = AnatomcalTractParcellationLogic()

    #
    # Message Area: check if WMA and ORG Atlas exist
    #
    uiWidget = slicer.util.loadUI(self.resourcePath('UI/AnatomcalTractParcellation.ui'))
    self.layout.addWidget(uiWidget)
    self.ui = slicer.util.childWidgetVariables(uiWidget)
    self.updateMsgInformation()
    self.statusLabel = qt.QLabel()

    #
    # Install WMA and download ORG atlas
    #
    self.installCollapsibleButton = ctk.ctkCollapsibleButton()
    self.installCollapsibleButton.text = "Installation"
    self.installCollapsibleButton.collapsed = self.wmaInstalled and self.atlasExisted
    self.layout.addWidget(self.installCollapsibleButton)
    parametersFormLayout = qt.QFormLayout(self.installCollapsibleButton)

    self.installWMAButton = qt.QPushButton("Install WMA")
    self.installWMAButton.toolTip = "Install whitematteranalysis software package"
    self.installWMAButton.enabled = not self.wmaInstalled
    parametersFormLayout.addRow(self.installWMAButton)
    self.installWMAButton.connect('clicked(bool)', self.onInstallWMA)

    self.downloadAtlasButton = qt.QPushButton("Download WM atlas")
    self.downloadAtlasButton.toolTip = "Download the ORG white matter atlas"
    self.downloadAtlasButton.enabled = not self.atlasExisted
    parametersFormLayout.addRow(self.downloadAtlasButton)

    #
    # Input parameters area
    #

    self.inputsCollapsibleButton = ctk.ctkCollapsibleButton()
    self.inputsCollapsibleButton.text = "IO"
    self.layout.addWidget(self.inputsCollapsibleButton)
    parametersFormLayout = qt.QFormLayout(self.inputsCollapsibleButton)
    self.downloadAtlasButton.connect('clicked(bool)', self.onDownloadAtlas)

    self.loadmode = None  # Initialize self.loadmode

    #
    # decide the source of input
    #
    def onLocalDiskButtonClicked():
      self.loadmode = "disk"
      self.selectedNodeName = None
      self.polydata = None
      print("load mode:",self.loadmode)

    def onSlicerButtonClicked():
      self.loadmode = "slicer"
      print("load mode:",self.loadmode)

    # select from the local disk
    with It(qt.QLineEdit()) as w:
        self.inputFileGet = w
        w.setReadOnly(True)
        w.setToolTip("Select input file")
    # create the box for choosing the source of the file
    widget = slicer.qMRMLWidget()
    widget.setLayout(qt.QVBoxLayout())  

    groupBox = qt.QGroupBox()
    groupBox.setLayout(qt.QHBoxLayout())  
    widget.layout().addWidget(groupBox)

    buttonGroup = qt.QButtonGroup()

    # Create the "From Local Disk" button
    localDiskButton = qt.QRadioButton("Input from disk")
    buttonGroup.addButton(localDiskButton)
    groupBox.layout().addWidget(localDiskButton)

    # Create the "From Slicer" button
    slicerButton = qt.QRadioButton("Input from Slicer")
    buttonGroup.addButton(slicerButton)
    groupBox.layout().addWidget(slicerButton)

    groupBox.layout().addStretch(1)

    localDiskButton.connect('clicked()', onLocalDiskButtonClicked)
    slicerButton.connect('clicked()', onSlicerButtonClicked)
    

    parametersFormLayout.addRow("", widget)

    #
    # Input file selector
    #

    # load from disk
    def selectInputFile():
      self.inputFileGet.clear()
      inputFile = qt.QFileDialog.getOpenFileName(self.parent, "Select input file")
      if inputFile:
        self.inputFileGet.setText(inputFile)

    with It(qt.QPushButton("Browse")) as button:
        button.clicked.connect(selectInputFile)

    layout = qt.QHBoxLayout()
    layout.addWidget(self.inputFileGet)
    layout.addWidget(button)
    #layout.addWidget(executeButton)
    parametersFormLayout.addRow("Input File:", layout)
    

    # load from slicer
    self.inputSelector = slicer.qMRMLNodeComboBox()
    self.inputSelector.nodeTypes = ["vtkMRMLFiberBundleNode"]
    self.inputSelector.selectNodeUponCreation = True
    self.inputSelector.addEnabled = False
    self.inputSelector.removeEnabled = False
    self.inputSelector.noneEnabled = False
    self.inputSelector.showHidden = False
    self.inputSelector.showChildNodeTypes = False
    self.inputSelector.setMRMLScene( slicer.mrmlScene )
    self.inputSelector.setToolTip( "Pick the tractography data to use for input." )
    parametersFormLayout.addRow("Input FiberBundle: ", self.inputSelector)

    self.onNodeSelectionChanged()

    # 连接选择节点时的回调函数
    self.inputSelector.currentNodeChanged.connect(self.onNodeSelectionChanged)


    #
    # Output folder selector
    #
    
    with It(qt.QLineEdit()) as w:
        self.outputFolderSelector = w
        w.setReadOnly(True)
        w.setToolTip("Select output folder")

    def selectOutputFolder():
      outputfile_path = qt.QFileDialog.getExistingDirectory(self.parent, "Select output folder")
      if outputfile_path:
        #Generate a new folder which replace spaces in the outputfile_path with underscores in order to ensure operation
        if ' ' in outputfile_path: 
          msgBox = qt.QMessageBox()
          msgBox.setIcon(qt.QMessageBox.Information)
          msgBox.setText("Note: The folder path cannot contain Spaces. Spaces in the selected folder path will be automatically replaced with '_'")
          msgBox.setWindowTitle("Note")
          msgBox.setStandardButtons(qt.QMessageBox.Ok)
          msgBox.exec_()
          outputfile_path = outputfile_path.replace(' ', '_')
          self.outputFolderSelector.setText(outputfile_path)
        else:
          self.outputFolderSelector.setText(outputfile_path)

    with It(qt.QPushButton("Browse")) as button:
        button.clicked.connect(selectOutputFolder)

    layout = qt.QHBoxLayout()
    layout.addWidget(self.outputFolderSelector)
    layout.addWidget(button)
    parametersFormLayout.addRow("Output Folder:", layout)

    #
    # Apply Button
    #

    with It(qt.QPushButton("Apply")) as w:
        self.applyButton = w
        w.toolTip = "Run the algorithm."
        w.connect('clicked(bool)', self.onApplyButton)
        parametersFormLayout.addRow("",self.applyButton)

    # Add vertical spacer
    self.layout.addStretch(1)

    #
    # Advanced parameters area
    #

    parametersCollapsibleButton = ctk.ctkCollapsibleButton()
    parametersCollapsibleButton.text = "Advanced parameters"
    self.layout.addWidget(parametersCollapsibleButton)
    parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

    #
    # RegMode selector
    #

    with It(qt.QComboBox()) as w:
        self.regModeSelector = w
        w.addItem("affine")
        w.addItem("affine + nonlinear")
        w.setToolTip("Choose the type of the regmode")
        parametersFormLayout.addRow("RegMode: ", self.regModeSelector)

    #
    # CleanMode selector
    #

    with It(qt.QCheckBox()) as w:
        self.CleanFilesSelector = w
        w.checked = True
        w.setToolTip("Decide whether to keep the intermediate result")
        parametersFormLayout.addRow("Save intermediate result", self.CleanFilesSelector)

    #
    # NumThreads controller
    #

    with It(ctk.ctkSliderWidget()) as w:
        self.NumThreadsSelector = w
        w.minimum = 1
        w.maximum = 8
        w.singleStep = 1
        w.setToolTip("control the NumThreads value")
        parametersFormLayout.addRow("NumThreads: ",self.NumThreadsSelector)
  
  def onNodeSelectionChanged(self):
    self.selected_node = self.inputSelector.currentNode()
    if self.selected_node is not None:
        self.polydata = self.selected_node.GetPolyData()
        self.selectedNodeName = self.selected_node.GetName()
        print("Selected fiber bundle name:", self.selectedNodeName)
        

  def updateMsgInformation(self):
  # Check Xcode Command Line Tools installation
    if os.name == 'posix':
      self.logic.check_install_xcode_cli()

  #update the status of the wma and atlas
    try:
      self.wmaInstalled, msg = self.logic.checkWMAInstall()
      self.ui.wmaInstallationInfo.text = msg
    except Exception as e:
      logging.error(str(e))
      self.ui.wmaInstallationInfo.text = "unknown (corrupted installation?)"

    try:
      self.atlasExisted, msg = self.logic.checkAtlasExist()

      # Get and display the ORG-Atlases version 
      if self.atlasExisted:
        atlasBasepath = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'Resources')
        atlas_p_file = glob.glob(os.path.join(atlasBasepath, 'ORG-Atlases*', 'ORG-800FC-100HCP', 'atlas.p' ))[0]
        version_match = re.search(r'ORG-Atlases-(\d+(\.\d+){0,5})', atlas_p_file)
        if version_match:
            version = version_match.group(1)
            self.ui.atlasDownloadInfo.text = f"Installed (Version: {version})"
        else:
            self.ui.atlasDownloadInfo.text = "Installed (Version: unknown)"
      else:
        self.ui.atlasDownloadInfo.text = msg
    except Exception as e:
      logging.error(str(e))
      self.ui.atlasDownloadInfo.text = "unknown (corrupted download process?)"
    

  def onInstallWMA(self):
    self.ui.wmaInstallationInfo.text = "Installing WMA..."
    
    install = slicer.util.confirmYesNoDisplay("Depending on your internet speed, the installation may take several minutes.  "+\
                      "Slicer will be freezing during this time. Confirm to staring insalling:")

    if install:
      self.logic.installWMA()
    self.wmaInstalled, msg = self.logic.checkWMAInstall()
    self.ui.wmaInstallationInfo.text = msg
    self.installWMAButton.enabled = not self.wmaInstalled

  def onDownloadAtlas(self):
    self.ui.atlasDownloadInfo.text = "Downloading atlas..."

    download = slicer.util.confirmYesNoDisplay("Atlas file size is ~4GB.  "+\
                      "Depending on your internet speed,  this download may take 1 hour.  "+\
                      "Slicer will be freezing during this time.  Confirm to start downloading:")
    if download:
      self.logic.downloadAtlas()
    self.atlasExisted, msg = self.logic.checkAtlasExist()
    self.ui.atlasDownloadInfo.text = msg
    self.downloadAtlasButton.enabled = not self.atlasExisted

  def cleanup(self):
    pass

  def onSelect(self):
    self.applyButton.enabled = self.inputSelector.currentNode() and self.outputSelector.currentNode()

  def reset(self, _msg):
    self.statusLabel.setText("")

  def onApplyButton(self):
    self.statusLabel.setText("")
    logic = AnatomcalTractParcellationLogic()
    logic.run(
              self.loadmode,
              self.inputFileGet.text,
              self.selectedNodeName,
              self.polydata,
              self.outputFolderSelector.text,
              RegMode = self.regModeSelector.currentText,
              CleanMode = self.CleanFilesSelector.checked,
              NumThreads = str(int(self.NumThreadsSelector.value))
          )
              
#
# AnatomcalTractParcellationLogic
#

class AnatomcalTractParcellationLogic(ScriptedLoadableModuleLogic):

  
  # Check whether Xcode Command Line Tools is installed in Slicer Python
  def check_install_xcode_cli(self):
    try:
        # Run the command to check if Xcode is installed
        result = subprocess.run(['xcode-select', '--print-path'], capture_output=True, text=True)
        
        if result.returncode == 0:
            pass
        else:
            msgBox = qt.QMessageBox()
            msgBox.setWindowTitle("Xcode Command Line Tools")
            msgBox.setText("Xcode Command Line Tools is not installed.")
            msgBox.setInformativeText("Run the 'xcode-select --install' Command in the terminal to install the Xcode Command Line Tools.")
            msgBox.setIcon(qt.QMessageBox.Warning)
            msgBox.exec_()
    except Exception as e:
        print("Error checking Xcode installation status:", str(e))
    
    
  @staticmethod
  # check the wma installation
  def checkWMAInstall():

    try:
      importlib.metadata.files('whitematteranalysis')
    except importlib.metadata.PackageNotFoundError as e:
      installed = False
      wmamsg = 'Not Installed'
      logging.warning("WMA has not been installed in the Slicer python enviroment.")
      return installed, wmamsg

    try:
      import whitematteranalysis
      installed = True
      wmamsg = "Installed"
    except ModuleNotFoundError:
      installed = False
      wmamsg = "Not installed"
      logging.error("Fail to import whitematteranalysis. Try to install. ")

    return installed, wmamsg

  @staticmethod
  # check the existence of the altas
  def checkAtlasExist():
    
    atlasBasepath = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'Resources')

    try:
      atlas_p_file = glob.glob(os.path.join(atlasBasepath, 'ORG-Atlases*', 'ORG-800FC-100HCP', 'atlas.p' ))[0]
      exist = True
      atlasmsg = "Installed"
    except Exception as e:
      exist = False
      atlasmsg = "Not installed"
      logging.warning("Can not find ORG atlas. Try to download.")

    return exist, atlasmsg

  @staticmethod
  #install WMA package
  def installWMA():
    if os.name == 'posix':
      # Modify the http.version configuration
      subprocess.run(["git", "config", "--global", "http.version", "HTTP/1.1"])
      # Modify the http.postBuffer configuration
      subprocess.run(["git", "config", "--global", "http.postBuffer", "524288000"])
    slicer.util.pip_install('git+https://github.com/SlicerDMRI/whitematteranalysis.git')

  @staticmethod
  #download atlas
  def downloadAtlas():
    
    pythonSlicerExecutablePath = AnatomcalTractParcellationLogic._executePythonModule()

    try:
      wm_download_anatomically_curated_atlas = [str(p) for p in importlib.metadata.files('whitematteranalysis') if "wm_download_anatomically_curated_atlas.py" in str(p)][0]
      wm_download_anatomically_curated_atlas = os.path.join(os.path.dirname(pythonSlicerExecutablePath), '..', 'lib', 'Python', location, 'wm_download_anatomically_curated_atlas.py')
    except Exception as e:
      logging.error(e)
      logging.error("Cannot find wm_download_anatomically_curated_atlas.py script. Check WMA installation.")

    atlasBasepath = os.path.join(os.path.abspath(os.path.dirname(__file__)), "Resources")
    commandLine = [pythonSlicerExecutablePath, wm_download_anatomically_curated_atlas, atlasBasepath, '-atlas', 'ORG-800FC-100HCP']

    proc = slicer.util.launchConsoleProcess(commandLine, useStartupEnvironment=False)
    slicer.util.logProcessOutput(proc)

  def _executePythonModule():
    import os, sys
    """ Updated based on: https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/util.py
    Execute a Python module as a script in Slicer's Python environment.
    :raises RuntimeError: in case of failure
    """
    # Determine pythonSlicerExecutablePath
    if os.name == 'posix':
        from slicer import app  # noqa: F401
        # If we get to this line then import from "app" is succeeded,
        # which means that we run this function from Slicer Python interpreter.
        # PythonSlicer is added to PATH environment variable in Slicer
        # therefore shutil.which will be able to find it.
        import shutil
        pythonSlicerExecutablePath = shutil.which('PythonSlicer')
        if not pythonSlicerExecutablePath:
            raise RuntimeError("PythonSlicer executable not found")
    
    elif os.name == 'nt':
        # Running from console
        pythonSlicerExecutablePath = os.path.dirname(sys.executable) + "/PythonSlicer" + ".exe"
        if not pythonSlicerExecutablePath:
            raise RuntimeError("PythonSlicer executable not found")

    return pythonSlicerExecutablePath

  def list_vtk_files(self, input_dir):
    # Find input files (JUST vtk)
    input_mask = "{0}/*.vtk".format(input_dir)
    input_mask2 = f"{input_dir}/*.vtp"
    input_pd_fnames = glob.glob(input_mask) + glob.glob(input_mask2)
    input_pd_fnames = sorted(input_pd_fnames)
    return(input_pd_fnames)

  def write_polydata(self, polydata, filename):
    """Write polydata as vtkPolyData format, according to extension."""

    print("Writing ", filename, "...")

    basename, extension = os.path.splitext(filename)

    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetDataModeToBinary()

    writer.SetFileName(filename)
    if (vtk.vtkVersion().GetVTKMajorVersion() >= 6.0):
        writer.SetInputData(polydata)
    else:
        writer.SetInput(polydata)
    writer.Update()

    del writer

    print("Done writing ", filename)

  def harden_transform(self, polydata, transform_node, inverse, outdir):
    #apply harden transform with slicer
    polydata_base_path, polydata_name = os.path.split(polydata)
    output_name = os.path.join(outdir, polydata_name)
    
    if os.path.exists(output_name):
        return
    
    check_load, polydata_node = slicer.util.loadModel(str(polydata), 1)
    if not check_load:  
        print('Could not load polydata file:', polydata)
        return
      
    if polydata_node.GetPolyData().GetNumberOfCells() == 0:
        print('Empty cluster:', polydata)
        shutil.copyfile(polydata, output_name)
        return

    if inverse == "1":
        transform_node.Inverse()
    
    logic = slicer.vtkSlicerTransformLogic()
    t_node_id = transform_node.GetID()

    # harden transform
    polydata_node.SetAndObserveTransformNodeID(t_node_id)
    logic.hardenTransform(polydata_node)
    slicer.util.saveNode(polydata_node, output_name)

  def python_harden_transform(self, inputDirectory, outputDirectory, transform_file, numberOfJobs, inverse_transform=True):
    
    #set the initial settings and apply transform
    inputdir = os.path.abspath(inputDirectory)
    if not os.path.isdir(inputDirectory):
        print("Error: Input directory", inputDirectory, "does not exist.")                
        exit()

    outdir = os.path.abspath(outputDirectory)
    if not os.path.exists(outputDirectory):
        print("Output directory", outputDirectory, "does not exist, creating it.")
        os.makedirs(outdir)             
        
    if transform_file is None:
        print("Error: transform file needs be provided.")
        exit()

    else:
        transform_way = 'individual'
        transform_path = os.path.abspath(transform_file)
        if not os.path.isfile(transform_file):
            print("Error: Input transform file", transform_file, "does not exist or it is not a file.")
            exit() 

    inverse = inverse_transform
      
    if numberOfJobs is not None:
        number_of_jobs = int(numberOfJobs)
    else:
        number_of_jobs = 1

    input_polydatas = self.list_vtk_files(inputdir)
    number_of_polydatas = len(input_polydatas)  

    print("<wm_harden_transform_with_slicer> Starting harden transforms.")
    print("")
    print("=====input directory======\n", inputdir)
    print("=====output directory=====\n", outdir)
    print("=====Way of transform====\n", transform_way)
    print("=====Inverse? ====\n", inverse)
    print("=====Transform file(s) path====\n", transform_path)
    print("=====Number of jobs:====\n", number_of_jobs)
      
    print("======", transform_path, "will be applied to all inputs.\n")

    check_load, transform_node = slicer.util.loadTransform(str(transform_path), 1)
    if not check_load:
        print('Could not load transform file:', transform_path)
        return

    for polydata in input_polydatas:
        print('transforming', polydata)
        self.harden_transform(polydata, transform_node, inverse, outdir)

    output_polydatas = self.list_vtk_files(outdir)
    number_of_results = len(output_polydatas)
    print("<wm_harden_transform_with_slicer> Transform were conducted for", number_of_results, "subjects.")

  def run(self, loadmode, inputFilePath, selectedNodeName, polydata, outputFolderPath, RegMode, CleanMode, NumThreads):

      if loadmode == 'slicer':
        filename = os.path.join(outputFolderPath, selectedNodeName + ".vtp")
        #Prevents write files from being overwritten
        count = 1
        basename, extension = os.path.splitext(filename)
        while os.path.exists(filename):
            filename = f"{basename}({count}){extension}"
            count += 1
        self.write_polydata(polydata, filename)
        input_tractography_path = filename
        print(input_tractography_path)

      elif loadmode == 'disk':
        input_tractography_path = inputFilePath
        print(input_tractography_path)
      
      if os.name == 'posix':
          # Execute code for Unix-like operating systems
          print("Running on a UNIX-like system")
          location = 'bin'
      elif os.name == 'nt':
          # Execute code for Windows operating systems
          print("Running on Windows")
          location = 'script'

      # Get CaseID 
      filename = os.path.basename(input_tractography_path)
      caseID = os.path.splitext(filename)[0]

      # Setup output
      print("<wm_apply_ORG_atlas_to_subject> Fiber clustering result will be stored at:", outputFolderPath)
      if not os.path.exists(outputFolderPath):
        print(' - create an output folder and reload.')
        os.makedirs(outputFolderPath)
      else:
          numfiles = len(glob.glob(os.path.join(outputFolderPath, 'AnatomicalTracts', 'T*.vtp')))
          if numfiles > 1:
              print("")
              print("** Anatomical tracts ({} tracts) are detected in the output folder. Manually remove all files to rerun.".format(numfiles))
              print("")
            
      print(' - output folder exists.')
      print("")

      # Setup white matter parcellation atlas
      atlasBasepath = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'Resources')
      AtlasBaseFolder = str(glob.glob(os.path.join(atlasBasepath, 'ORG-Atlases*'))[0])
      
      #AtlasBaseFolder = os.path.dirname(os.path.dirname(inputFilePath))
      
      RegAtlasFolder = os.path.join(AtlasBaseFolder, 'ORG-RegAtlas-100HCP')
      FCAtlasFolder = os.path.join(AtlasBaseFolder, 'ORG-800FC-100HCP')
      pythonSlicerExecutablePath = AnatomcalTractParcellationLogic._executePythonModule()
      print("<wm_apply_ORG_atlas_to_subject> White matter atlas: ", AtlasBaseFolder)
      print(" - tractography registration atlas:", RegAtlasFolder)
      print(" - fiber clustering atlas:", FCAtlasFolder)
      print("pythonSlicerExecutablePath:", pythonSlicerExecutablePath)
      print("")
      print("<wm_apply_ORG_atlas_to_subject> Tractography registration with mode [", RegMode, "]")
      RegistrationFolder = os.path.join(outputFolderPath, 'TractRegistration')
      print("input_tractography_path:",input_tractography_path)
     
      #start registration  
      wm_register_to_atlas_new = [str(p) for p in importlib.metadata.files('whitematteranalysis') if "wm_register_to_atlas_new.py" in str(p)][0]
      wm_register_to_atlas_new = os.path.join(os.path.dirname(pythonSlicerExecutablePath), '..', 'lib', 'Python', location, 'wm_register_to_atlas_new.py')
      if RegMode == "affine":
          RegTractography = os.path.join(RegistrationFolder, caseID, "output_tractography", caseID+"_reg.vtk")
          
          if not os.path.isfile(RegTractography):
              if input_tractography_path:

                  commandLine = [pythonSlicerExecutablePath, wm_register_to_atlas_new, "-mode", "rigid_affine_fast", input_tractography_path, os.path.join(RegAtlasFolder, "registration_atlas.vtk"), RegistrationFolder]
                  proc = slicer.util.launchConsoleProcess(commandLine, useStartupEnvironment=True)
                  slicer.util.logProcessOutput(proc)

          else:
              print(" - registration has been done.")

      elif RegMode == "affine + nonlinear":
          RegTractography = os.path.join(RegistrationFolder, caseID+"_reg", "output_tractography", caseID+"_reg_reg.vtk")

          if not os.path.isfile(RegTractography):
              if input_tractography_path:

                  commandLine = [pythonSlicerExecutablePath, wm_register_to_atlas_new, "-mode", "affine", input_tractography_path, os.path.join(RegAtlasFolder, "registration_atlas.vtk"), RegistrationFolder]
                  proc = slicer.util.launchConsoleProcess(commandLine, useStartupEnvironment=True)
                  slicer.util.logProcessOutput(proc)
                  affineRegTract = os.path.join(RegistrationFolder, caseID, "output_tractography", caseID+"_reg.vtk")
                  commandLine = [pythonSlicerExecutablePath, wm_register_to_atlas_new, "-mode", "nonrigid", affineRegTract, os.path.join(RegAtlasFolder, "registration_atlas.vtk"), RegistrationFolder]
                  proc = slicer.util.launchConsoleProcess(commandLine, useStartupEnvironment=True)
                  slicer.util.logProcessOutput(proc)
                 
          else:
              print(" - registration has been done.")
              
      print("")
      
      if not os.path.isfile(RegTractography):
          print("")
          print("ERROR: Tractography registration failed. The output registered tractography data can not be found.")
          print("")
                   
      # Get the case ID for fiber clustering
      fn = os.path.basename(RegTractography)
      FCcaseID = os.path.splitext(fn)[0]
      
      #start fiber clustering
      print("<wm_apply_ORG_atlas_to_subject> Fiber clustering for whole-brain 800 fiber cluster parcellation.")
      print(f"Number of processors: {NumThreads}")
      FiberClusteringInitialFolder = os.path.join(outputFolderPath, "FiberClustering/InitialClusters")
      if not os.path.isfile(os.path.join(FiberClusteringInitialFolder, FCcaseID, "cluster_00800.vtp")):
          wm_cluster_from_atlas = [str(p) for p in importlib.metadata.files('whitematteranalysis') if "wm_cluster_from_atlas.py" in str(p)][0]
          wm_cluster_from_atlas = os.path.join(os.path.dirname(pythonSlicerExecutablePath), '..', 'lib', 'Python', location, 'wm_cluster_from_atlas.py')
          commandLine = [
                        pythonSlicerExecutablePath,
                        wm_cluster_from_atlas,
                        '-j', NumThreads,
                        RegTractography,
                        FCAtlasFolder,
                        FiberClusteringInitialFolder,
                        '-norender'
                    ]                       
          process = subprocess.Popen(commandLine, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)                        
          process.wait() 

      else:
          print(" - initial fiber clustering has been done.")
      print("")

      num_files = len(os.listdir(f"{FiberClusteringInitialFolder}/{FCcaseID}"))
      if num_files < 800:
          print("")
          print(f"ERROR: Initial fiber clustering failed. There should be 800 resulting fiber clusters, but only {num_files} generated.")
          print("")
          
      print("<wm_apply_ORG_atlas_to_subject> Outlier fiber removal.")

      FiberClusteringOutlierRemFolder = os.path.join(outputFolderPath, "FiberClustering/OutlierRemovedClusters")
      print(os.path.join(FiberClusteringOutlierRemFolder, f"{FCcaseID}_outlier_removed", "cluster_00800.vtp"))
                                       
      if not os.path.isfile(os.path.join(FiberClusteringOutlierRemFolder, f"{FCcaseID}_outlier_removed", "cluster_00800.vtp")):
                                        
          wm_cluster_remove_outliers = [str(p) for p in importlib.metadata.files('whitematteranalysis') if "wm_cluster_remove_outliers.py" in str(p)][0]
          wm_cluster_remove_outliers = os.path.join(os.path.dirname(pythonSlicerExecutablePath), '..', 'lib', 'Python', location, 'wm_cluster_remove_outliers.py')
          commandLine = [
                        pythonSlicerExecutablePath,
                        wm_cluster_remove_outliers,
                        '-j', NumThreads,                      
                        os.path.join(FiberClusteringInitialFolder, FCcaseID),
                        FCAtlasFolder,
                        FiberClusteringOutlierRemFolder,
                    ]
          process = subprocess.Popen(commandLine, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
          process.wait() 

      else:
          print(" - outlier fiber removal has been done.")
      print("")

      numfiles = len([f for f in glob.glob(f"{FiberClusteringOutlierRemFolder}/{FCcaseID}_outlier_removed/*vtp")])
      if numfiles < 800:
          logging.error("")
          logging.error(f"ERROR: Outlier removal failed. There should be 800 resulting fiber clusters, but only {numfiles} generated.")
          logging.error("")
          
      print("<wm_apply_ORG_atlas_to_subject> Hemisphere location assessment in the atlas space.")
      if not os.path.isfile(os.path.join(FiberClusteringOutlierRemFolder, f"{FCcaseID}_outlier_removed/cluster_location_by_hemisphere.log")):
          wm_assess_cluster_location_by_hemisphere = [str(p) for p in importlib.metadata.files('whitematteranalysis') if "wm_assess_cluster_location_by_hemisphere.py" in str(p)][0]
          wm_assess_cluster_location_by_hemisphere = os.path.join(os.path.dirname(pythonSlicerExecutablePath), '..', 'lib', 'Python', 'bin', 'wm_assess_cluster_location_by_hemisphere.py')
          commandLine = [pythonSlicerExecutablePath, wm_assess_cluster_location_by_hemisphere, '-clusterLocationFile', os.path.join(FCAtlasFolder, "cluster_hemisphere_location.txt"), os.path.join(FiberClusteringOutlierRemFolder, f"{FCcaseID}_outlier_removed")]
          proc = slicer.util.launchConsoleProcess(commandLine, useStartupEnvironment=True)
          slicer.util.logProcessOutput(proc)
          
      else:
          print(" - hemisphere location assessment has been done.")
      print("")

      if not os.path.isfile(f"{FiberClusteringOutlierRemFolder}/{FCcaseID}_outlier_removed/cluster_location_by_hemisphere.log"):
          print("")
          print("ERROR: Hemisphere location assessment failed. There should be a cluster_location_by_hemisphere.log file, stating: \"<wm_assess_cluster_location_by_hemisphere.py> Done!!!\" ")
          print("")
          
      ## notice!
      # Set input and output paths
      FiberClustersInTractographySpace = os.path.join(outputFolderPath, 'FiberClustering', 'TransformedClusters', f"{caseID}")
      tfm_rig = os.path.join(RegistrationFolder, f"{caseID}", 'output_tractography', f"itk_txform_{caseID}.tfm")
      tfm_nonrig = os.path.join(RegistrationFolder, f"{caseID}_reg", 'output_tractography', f"itk_txform_{caseID}_reg.tfm")
      FiberClustersInTractographySpace_tmp = os.path.join(FiberClustersInTractographySpace, 'tmp')
      FCcaseID_outlier_removed = os.path.join(FiberClusteringOutlierRemFolder, f"{FCcaseID}_outlier_removed")
      
      # Apply transforms
      if RegMode == "affine":
          if not os.path.exists(os.path.join(FiberClustersInTractographySpace, 'cluster_00800.vtp')):
              
              self.python_harden_transform(FCcaseID_outlier_removed, FiberClustersInTractographySpace, tfm_rig, NumThreads)
              
          else: 
              print(" - transform has been done.")
      elif RegMode == "affine + nonlinear":
          if not os.path.exists(os.path.join(FiberClustersInTractographySpace_tmp, 'cluster_00800.vtp')):  
              
              self.python_harden_transform(FCcaseID_outlier_removed, FiberClustersInTractographySpace_tmp, tfm_nonrig, NumThreads)     
              
          else:
              print(" - transform has been done.")
          if not os.path.exists(os.path.join(FiberClustersInTractographySpace, 'cluster_00800.vtp')):
              
              self.python_harden_transform(FiberClustersInTractographySpace_tmp, FiberClustersInTractographySpace, tfm_rig, NumThreads)
             
          else:
              print(" - transform has been done.")
              
      print("")

      numfiles = len(glob.glob(f"{FiberClustersInTractographySpace}/*vtp"))
      if numfiles < 800:
          print("")
          print(f"ERROR: Transforming fiber clusters failed. There should be 800 resulting fiber clusters, but only {numfiles} generated.")
          print("")
      
      #start separation
      print("<wm_apply_ORG_atlas_to_subject> Separate fiber clusters by hemisphere.")
      SeparatedClustersFolder = os.path.join(outputFolderPath, 'FiberClustering', 'SeparatedClusters')
      if not os.path.exists(os.path.join(SeparatedClustersFolder, 'tracts_commissural', 'cluster_00800.vtp')):
          wm_separate_clusters_by_hemisphere = [str(p) for p in importlib.metadata.files('whitematteranalysis') if "wm_separate_clusters_by_hemisphere.py" in str(p)][0]
          wm_separate_clusters_by_hemisphere = os.path.join(os.path.dirname(pythonSlicerExecutablePath), '..', 'lib', 'Python', location, 'wm_separate_clusters_by_hemisphere.py')
          commandLine = [pythonSlicerExecutablePath, wm_separate_clusters_by_hemisphere, FiberClustersInTractographySpace, SeparatedClustersFolder]
          proc = slicer.util.launchConsoleProcess(commandLine, useStartupEnvironment=True)
          slicer.util.logProcessOutput(proc)
          
      else:
          print(" - separation has been done.")
      print("")

      numfiles = len(os.listdir(f"{SeparatedClustersFolder}/tracts_commissural"))
      if numfiles < 800:
          print(f"\nERROR: Separating fiber clusters failed. There should be 800 resulting fiber clusters in each folder, but only {numfiles} generated.\n")
      
      #start append    
      print("<wm_apply_ORG_atlas_to_subject> Append clusters into anatomical tracts.")
      AnatomicalTractsFolder = os.path.join(outputFolderPath, "AnatomicalTracts")
      if not os.path.exists(os.path.join(AnatomicalTractsFolder, "T_UF_right.vtp")):
          wm_append_clusters_to_anatomical_tracts = [str(p) for p in importlib.metadata.files('whitematteranalysis') if "wm_append_clusters_to_anatomical_tracts.py" in str(p)][0]
          wm_append_clusters_to_anatomical_tracts = os.path.join(os.path.dirname(pythonSlicerExecutablePath), '..', 'lib', 'Python', location, 'wm_append_clusters_to_anatomical_tracts.py')
          commandLine = [pythonSlicerExecutablePath, wm_append_clusters_to_anatomical_tracts, SeparatedClustersFolder, FCAtlasFolder, AnatomicalTractsFolder]
          proc = slicer.util.launchConsoleProcess(commandLine, useStartupEnvironment=True)
          slicer.util.logProcessOutput(proc)

      else:
          print(" - Appending clusters into anatomical tracts has been done.")
      print("")

      numfiles = len(glob.glob(f"{AnatomicalTractsFolder}/*.vtp"))
      if numfiles < 73:
          print("")
          print("ERROR: Appending clusters into anatomical tracts failed. There should be 73 resulting fiber clusters, but only $numfiles generated.")
          print("")

      #Load the generated anatomical tracts back into Slicer


      def loadVTPFile(file_path):
        scene = slicer.mrmlScene

        # Load the VTP file as a FiberBundle
        loaded_fiber_node = slicer.util.loadFiberBundle(file_path)
        if loaded_fiber_node is None:
            print(f"Failed to load VTP file: {file_path}")
            return

        # Modify the display properties of the loaded FiberBundle
        display_node = loaded_fiber_node.GetDisplayNode()
        if display_node is None:
            display_node = slicer.vtkMRMLFiberBundleDisplayNode()
            scene.AddNode(display_node)
            loaded_fiber_node.SetAndObserveDisplayNodeID(display_node.GetID())

        display_node.SetVisibility(True)

      # Iterate over files in the AnatomicalTractsFolder
      for file_name in os.listdir(AnatomicalTractsFolder):
          if file_name.endswith(".vtp"):
              file_path = os.path.join(AnatomicalTractsFolder, file_name)
              try:
                  loadVTPFile(file_path)
              except Exception as e:
                  print(f"Error loading VTP file: {file_path}")
                  print(f"Error message: {str(e)}")

      scene = slicer.mrmlScene
      for node in scene.GetNodesByClass('vtkMRMLNode'):
          # Check whether the node name starts with "cluster"
          if node.GetName().startswith('cluster'):
              # Remove nodes from the scene
              scene.RemoveNode(node)
      
      #start diffusion
      FiberTractMeasurementsCLI = slicer.modules.fibertractmeasurements.path #find and store the path of cli-module "FiberTractMeasurements"
      wm_diffusion_measurements = [str(p) for p in importlib.metadata.files('whitematteranalysis') if "wm_diffusion_measurements.py" in str(p)][0]
      wm_diffusion_measurements = os.path.join(os.path.dirname(pythonSlicerExecutablePath), '..', 'lib', 'Python', location, 'wm_diffusion_measurements.py')
      print("<wm_apply_ORG_atlas_to_subject> Report diffusion measurements of fiber clusters.")
      if not os.path.isfile(os.path.join(SeparatedClustersFolder, "diffusion_measurements_commissural.csv")):
          commandLine = [pythonSlicerExecutablePath, wm_diffusion_measurements, os.path.join(SeparatedClustersFolder, "tracts_commissural"), os.path.join(SeparatedClustersFolder, "diffusion_measurements_commissural.csv"), FiberTractMeasurementsCLI]
          proc = slicer.util.launchConsoleProcess(commandLine, useStartupEnvironment=True)
          slicer.util.logProcessOutput(proc)

      else:
          print(" - diffusion measurements of commissural clusters has been done.")
      if not os.path.isfile(os.path.join(SeparatedClustersFolder, "diffusion_measurements_left_hemisphere.csv")):
          commandLine = [pythonSlicerExecutablePath, wm_diffusion_measurements, os.path.join(SeparatedClustersFolder, "tracts_left_hemisphere"), os.path.join(SeparatedClustersFolder, "diffusion_measurements_left_hemisphere.csv"), FiberTractMeasurementsCLI]
          proc = slicer.util.launchConsoleProcess(commandLine, useStartupEnvironment=True)
          slicer.util.logProcessOutput(proc)
          
      else:
          print(" - diffusion measurements of left hemisphere clusters has been done.")
      if not os.path.isfile(os.path.join(SeparatedClustersFolder, "diffusion_measurements_right_hemisphere.csv")):
          commandLine = [pythonSlicerExecutablePath, wm_diffusion_measurements, os.path.join(SeparatedClustersFolder, "tracts_right_hemisphere"), os.path.join(SeparatedClustersFolder, "diffusion_measurements_right_hemisphere.csv"), FiberTractMeasurementsCLI]
          proc = slicer.util.launchConsoleProcess(commandLine, useStartupEnvironment=True)
          slicer.util.logProcessOutput(proc)
            
      else:
          print(" - diffusion measurements of right hemisphere clusters has been done.")
      if not os.path.isfile(os.path.join(SeparatedClustersFolder, "diffusion_measurements_right_hemisphere.csv")):
          print("\nERROR: Reporting diffusion measurements of fiber clusters failed. No diffusion measurement (.csv) files generated.\n")
            
      print("")

      print("<wm_apply_ORG_atlas_to_subject> Report diffusion measurements of the anatomical tracts.")
      csv_path = os.path.join(AnatomicalTractsFolder, "diffusion_measurements_anatomical_tracts.csv")
      if not os.path.isfile(csv_path):
        commandLine = [pythonSlicerExecutablePath, wm_diffusion_measurements, AnatomicalTractsFolder, csv_path, FiberTractMeasurementsCLI]
        proc = slicer.util.launchConsoleProcess(commandLine, useStartupEnvironment=True)
        slicer.util.logProcessOutput(proc)
        
      else:
        print(" - diffusion measurements of anatomical tracts has been done.")

      if not os.path.isfile(csv_path):
        print("")
        print("ERROR: Reporting diffusion measurements of fiber clusters. failed. No diffusion measurement (.csv) files generated.")
        print("")
        
      print("")

      #Clear unnecessary intermediate results based on selection
      if not CleanMode:
          print("<wm_apply_ORG_atlas_to_subject> Clean files using maximal removal.")
          os.system(f"rm -rf {outputFolderPath}/TractRegistration/*/output_tractography/*vtk")
          os.system(f"rm -rf {outputFolderPath}/TractRegistration/*/iteration*")
          os.system(f"rm -rf {outputFolderPath}/FiberClustering/InitialClusters/*")
          os.system(f"rm -rf {outputFolderPath}/FiberClustering/OutlierRemovedClusters/*")
          os.system(f"rm -rf {outputFolderPath}/FiberClustering/TransformedClusters/*")
          print("<wm_apply_ORG_atlas_to_subject> Clean files using minimal removal.")
          os.system(f"rm -rf {outputFolderPath}/FiberClustering/InitialClusters")
          os.system(f"rm -rf {outputFolderPath}/FiberClustering/TransformedClusters")
      else:
          print("<wm_apply_ORG_atlas_to_subject> Clean files using minimal removal.")
          os.system(f"rm -rf {outputFolderPath}/FiberClustering/InitialClusters")
          os.system(f"rm -rf {outputFolderPath}/FiberClustering/TransformedClusters")