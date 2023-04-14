import os, unittest, warnings
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging
import numpy as np

import importlib.metadata, glob, time

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
    self.inputsCollapsibleButton.text = "Inputs"
    self.layout.addWidget(self.inputsCollapsibleButton)
    parametersFormLayout = qt.QFormLayout(self.inputsCollapsibleButton)
    self.downloadAtlasButton.connect('clicked(bool)', self.onDownloadAtlas)







    #
    # input volume selector
    #
    self.inputSelector = slicer.qMRMLNodeComboBox()
    self.inputSelector.nodeTypes = ["vtkMRMLDiffusionWeightedVolumeNode"]
    self.inputSelector.selectNodeUponCreation = True
    self.inputSelector.addEnabled = False
    self.inputSelector.removeEnabled = False
    self.inputSelector.noneEnabled = False
    self.inputSelector.showHidden = False
    self.inputSelector.showChildNodeTypes = False
    self.inputSelector.setMRMLScene( slicer.mrmlScene )
    self.inputSelector.setToolTip( "Pick the input to the algorithm." )
    parametersFormLayout.addRow("Input Volume: ", self.inputSelector)

    #
    # output volume selector
    #
    self.outputSelector = slicer.qMRMLNodeComboBox()
    self.outputSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.outputSelector.selectNodeUponCreation = True
    self.outputSelector.addEnabled = True
    self.outputSelector.removeEnabled = True
    self.outputSelector.noneEnabled = True
    self.outputSelector.showHidden = False
    self.outputSelector.showChildNodeTypes = False
    self.outputSelector.setMRMLScene( slicer.mrmlScene )
    self.outputSelector.setToolTip( "Pick the output to the algorithm." )
    parametersFormLayout.addRow("Output Volume: ", self.outputSelector)

    #
    # Apply Button
    #
    self.applyButton = qt.QPushButton("Apply")
    self.applyButton.toolTip = "Run the algorithm."
    self.applyButton.enabled = False
    parametersFormLayout.addRow(self.applyButton)

    # connections
    self.applyButton.connect('clicked(bool)', self.onApplyButton)
    self.inputSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onSelect)
    self.outputSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onSelect)

    # Add vertical spacer
    self.layout.addStretch(1)

    # Refresh Apply button state
    self.onSelect()


  def updateMsgInformation(self):
    
    try:
      self.wmaInstalled, msg = self.logic.checkWMAInstall()
      self.ui.wmaInstallationInfo.text = msg
    except Exception as e:
      logging.error(str(e))
      self.ui.wmaInstallationInfo.text = "unknown (corrupted installation?)"
    
    try:
      self.atlasExisted, msg = self.logic.checkAtlasExist()
      self.ui.atlasDownloadInfo.text = msg
    except Exception as e:
      logging.error(str(e))
      self.ui.atlasDownloadInfo.text = "unknown (corrupted download process?)"


  def onInstallWMA(self):
    self.ui.wmaInstallationInfo.text = "Installing WMA..."
    
    install = slicer.util.confirmYesNoDisplay("Depending on your internet speed,  the installation may take several minutes.  "+\
                      "Slicer will be freezing during this time.  Confirm to staring insalling:")
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

  def onApplyButton(self):
    logic = AnatomcalTractParcellationLogic()
    logic.run(self.inputSelector.currentNode(), self.outputSelector.currentNode())

#
# AnatomcalTractParcellationLogic
#

class AnatomcalTractParcellationLogic(ScriptedLoadableModuleLogic):

  @staticmethod
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
  def checkAtlasExist():
    
    atlasBasepath = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'Resources')

    try:
      atlas_p_file = glob.glob(os.path.join(atlasBasepath, 'ORG-Atlases*', 'ORG-800FC-100HCP', 'atlas.p' ))[0]
      exist = True
      atlasmsg = "Exist"
    except Exception as e:
      exist = False
      atlasmsg = "Not Exist"
      logging.warning("Can not find ORG atlas. Try to download.")

    return exist, atlasmsg


  @staticmethod
  def installWMA():

    slicer.util.pip_install('git+https://github.com/SlicerDMRI/whitematteranalysis.git')


  @staticmethod
  def downloadAtlas():
    
    pythonSlicerExecutablePath = AnatomcalTractParcellationLogic._executePythonModule()

    try:
      wm_download_anatomically_curated_atlas = [str(p) for p in importlib.metadata.files('whitematteranalysis') if "wm_download_anatomically_curated_atlas.py" in str(p)][0]
      wm_download_anatomically_curated_atlas = os.path.join(os.path.dirname(pythonSlicerExecutablePath), '..', 'lib', 'Python', 'bin', 'wm_download_anatomically_curated_atlas.py')
    except Exception as e:
      logging.error(e)
      logging.error("Cannot find wm_download_anatomically_curated_atlas.py script. Check WMA installation.")

    atlasBasepath = os.path.join(os.path.abspath(os.path.dirname(__file__)), "Resources")
    commandLine = [pythonSlicerExecutablePath, wm_download_anatomically_curated_atlas, atlasBasepath, '-atlas', 'ORG-2000FC-100HCP']

    proc = slicer.util.launchConsoleProcess(commandLine, useStartupEnvironment=False)
    slicer.util.logProcessOutput(proc)


  def _executePythonModule():
    """ Updated based on: https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/util.py

    Execute a Python module as a script in Slicer's Python environment.
    :raises RuntimeError: in case of failure
    """
    # Determine pythonSlicerExecutablePath
    try:
        from slicer import app  # noqa: F401
        # If we get to this line then import from "app" is succeeded,
        # which means that we run this function from Slicer Python interpreter.
        # PythonSlicer is added to PATH environment variable in Slicer
        # therefore shutil.which will be able to find it.
        import shutil
        pythonSlicerExecutablePath = shutil.which('PythonSlicer')
        if not pythonSlicerExecutablePath:
            raise RuntimeError("PythonSlicer executable not found")
    except ImportError:
        # Running from console
        import os
        import sys
        pythonSlicerExecutablePath = os.path.dirname(sys.executable) + "/PythonSlicer"
        if os.name == 'nt':
            pythonSlicerExecutablePath += ".exe"

    return pythonSlicerExecutablePath







  def hasImageData(self,volumeNode):
    """This is an example logic method that
    returns true if the passed in volume
    node has valid image data
    """
    if not volumeNode:
      logging.debug('hasImageData failed: no volume node')
      return False
    if volumeNode.GetImageData() is None:
      logging.debug('hasImageData failed: no image data in volume node')
      return False
    return True

  def calculate_baseline(self, dwi_array, grads_array, bvals_array, threshold=10):
      # the last (3,) of a diffusion weighted volume array is the gradient volumes
      num_grads = dwi_array.shape[-1]

      # get the indices where bvalues are less than 'threshold'
      b0_vol_indices = np.where(bvals_array <= threshold)

      b0_vols = np.take(dwi_array, *b0_vol_indices, axis=3)
      baseline = np.mean(b0_vols, axis=3)

      return baseline


  def run(self, inputVolume, outputVolume):
    """
    Run the actual algorithm
    """

    logging.info('Processing started')

    assert inputVolume and inputVolume.IsA("vtkMRMLDiffusionWeightedVolumeNode")
    assert outputVolume and outputVolume.IsA("vtkMRMLScalarVolumeNode")

    # copy image position and orientation to output volume
    ijktoras = vtk.vtkMatrix4x4()
    inputVolume.GetIJKToRASMatrix(ijktoras)
    outputVolume.SetIJKToRASMatrix(ijktoras)

    # get the image data as numpy arrays (no copy)
    dwi_array = slicer.util.arrayFromVolume(inputVolume)
    grads_array = vtk.util.numpy_support.vtk_to_numpy(inputVolume.GetDiffusionGradients())
    bvals_array = vtk.util.numpy_support.vtk_to_numpy(inputVolume.GetBValues())

    # calculate baseline image
    baseline = self.calculate_baseline(dwi_array, grads_array, bvals_array)

    # update the output image data
    slicer.util.updateVolumeFromArray(outputVolume, baseline)

    logging.info('Processing completed')

    return True


class AnatomcalTractParcellationTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear(0)

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_AnatomcalTractParcellation1()

  def test_AnatomcalTractParcellation1(self):
    """ Ideally you should have several levels of tests.  At the lowest level
    tests should exercise the functionality of the logic with different inputs
    (both valid and invalid).  At higher levels your tests should emulate the
    way the user would interact with your code and confirm that it still works
    the way you intended.
    One of the most important features of the tests is that it should alert other
    developers when their changes will have an impact on the behavior of your
    module.  For example, if a developer removes a feature that you depend on,
    your test should break so they know that the feature is needed.
    """

    self.delayDisplay("Starting the test")
    #
    # first, get some data
    #
    import SampleData
    SampleData.downloadFromURL(
      nodeNames='FA',
      fileNames='FA.nrrd',
      uris='http://slicer.kitware.com/midas3/download?items=5767')
    self.delayDisplay('Finished with download and loading')

    volumeNode = slicer.util.getNode(pattern="FA")
    logic = AnatomcalTractParcellationLogic()
    self.assertIsNotNone( logic.hasImageData(volumeNode) )
    self.delayDisplay('Test passed!')
