import os
import sys
import shutil
import getpass

from enum import Enum
from collections import deque
from PySide2 import QtCore, QtWidgets, QtGui

from dcc.userinterface import qproxywindow, qiconlibrary
from dcc.perforce import clientutils, cmds, isConnected

import logging
logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


class QFileStatus(Enum):

    Unchanged = 0
    Add = 1
    Delete = 2
    Edit = 3


class QDepotItem(QtGui.QStandardItem):
    """
    Overload of QStandardItem used to display depot items.
    """

    __icons__ = {
        QFileStatus.Unchanged: qiconlibrary.getIconByName('p4v_file'),
        QFileStatus.Add: qiconlibrary.getIconByName('p4v_file_add'),
        QFileStatus.Delete: qiconlibrary.getIconByName('p4v_file_delete'),
        QFileStatus.Edit: qiconlibrary.getIconByName('p4v_file_edit')
    }

    def __init__(self, sourcePath, targetPath):
        """
        Overloaded method called after a new instance has been created.

        :type sourcePath: str
        :type targetPath: str
        """

        # Call parent method
        #
        super(QDepotItem, self).__init__()

        # Declare class variables
        #
        self._sourcePath, self._targetPath = sourcePath, targetPath

        self._filename = os.path.split(sourcePath)[1]
        self._status = self.evaluateFileStatus(sourcePath, targetPath)

    def data(self, role=QtCore.Qt.UserRole):
        """
        Overloaded method used to retrieve data based on the supplied role.

        :type role: int
        :rtype: object
        """

        # Inspect data role
        #
        if role == QtCore.Qt.DisplayRole:

            return self._filename

        elif role == QtCore.Qt.DecorationRole:

            return self.__class__.__icons__[self._status]

        else:

            return super(QDepotItem, self).data(role=role)

    def sourcePath(self):
        """
        Method used to retrieve the source path for this item.

        :rtype: str
        """

        return self._sourcePath

    def targetPath(self):
        """
        Method used to retrieve the target path for this item.

        :rtype: str
        """

        return self._targetPath

    def status(self):
        """
        Method used to retrieve the file status for this item.

        :rtype: QFileStatus
        """

        return self._status

    @staticmethod
    def evaluateFileStatus(sourcePath, targetPath):
        """
        Static method used to evaluate the file status for a given pair of files.

        :type sourcePath: str
        :type targetPath: str
        :rtype: QFileStatus
        """

        # Check if source file exists
        #
        if os.path.exists(sourcePath):

            # Check if target file exists
            #
            if os.path.exists(targetPath):

                # Check if files are identical
                #
                if QP4ckageMerger.isIdentical(sourcePath, targetPath):

                    return QFileStatus.Unchanged

                else:

                    return QFileStatus.Edit

            else:

                return QFileStatus.Delete

        else:

            return QFileStatus.Add


class QP4ckageMerger(qproxywindow.QProxyWindow):
    """
    Overload of QProxyWindow used to display changelist updates.
    """

    __escapechars__ = ''.join([chr(char) for char in range(1, 32)])

    def __init__(self, *args, **kwargs):
        """
        Overloaded method called after a new instance has been created.

        :keyword parent: QtWidgets.QWidget
        :keyword flags: QtCore.Qt.WindowFlags
        """

        # Call parent method
        #
        super(QP4ckageMerger, self).__init__(*args, **kwargs)

        # Declare class variables
        #
        self._sourceDirectory = ''
        self._targetDirectory = ''

        self._clients = None
        self._currentClient = None

        self._changelists = None
        self._currentChangelist = None

    def __build__(self):
        """
        Private method used to build the user interface.

        :rtype: None
        """

        # Call parent method
        #
        super(QP4ckageMerger, self).__build__()

        # Set window properties
        #
        self.setObjectName('P4ckageMerger')
        self.setWindowTitle('|| P4ckage Merger')
        self.setMinimumSize(QtCore.QSize(400, 600))

        # Create central widget
        #
        self.setCentralWidget(QtWidgets.QWidget())
        self.centralWidget().setLayout(QtWidgets.QVBoxLayout())

        # Create path fields
        #
        self.packagesLayout = QtWidgets.QHBoxLayout()

        self.packagesGroupBox = QtWidgets.QGroupBox('Python Packages:')
        self.packagesGroupBox.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.packagesGroupBox.setLayout(self.packagesLayout)

        # Create source line edit
        #
        self.sourceLabel = QtWidgets.QLabel('Source Package:')
        self.sourceLabel.setFixedSize(QtCore.QSize(85, 20))
        self.sourceLabel.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

        self.sourceLineEdit = QtWidgets.QLineEdit('')
        self.sourceLineEdit.setReadOnly(True)
        self.sourceLineEdit.setFixedHeight(20)
        self.sourceLineEdit.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.sourceLineEdit.textChanged.connect(self.sourceChanged)

        self.sourceButton = QtWidgets.QPushButton('...')
        self.sourceButton.clicked.connect(self.changeSource)

        self.sourceLayout = QtWidgets.QHBoxLayout()
        self.sourceLayout.addWidget(self.sourceLabel)
        self.sourceLayout.addWidget(self.sourceLineEdit)
        self.sourceLayout.addWidget(self.sourceButton)

        # Create target line edit
        #
        self.targetLabel = QtWidgets.QLabel('Target Package:')
        self.targetLabel.setFixedSize(QtCore.QSize(85, 20))
        self.targetLabel.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

        self.targetLineEdit = QtWidgets.QLineEdit('')
        self.targetLineEdit.setReadOnly(True)
        self.targetLineEdit.setFixedHeight(20)
        self.targetLineEdit.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.targetLineEdit.textChanged.connect(self.targetChanged)

        self.targetButton = QtWidgets.QPushButton('...')
        self.targetButton.clicked.connect(self.changeTarget)

        self.targetLayout = QtWidgets.QHBoxLayout()
        self.targetLayout.addWidget(self.targetLabel)
        self.targetLayout.addWidget(self.targetLineEdit)
        self.targetLayout.addWidget(self.targetButton)

        # Create diff button
        #
        self.diffButton = QtWidgets.QPushButton('Diff')
        self.diffButton.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.diffButton.clicked.connect(self.diff)

        # Assemble path fields
        #
        self.fieldsLayout = QtWidgets.QVBoxLayout()
        self.fieldsLayout.addLayout(self.sourceLayout)
        self.fieldsLayout.addLayout(self.targetLayout)

        self.packagesLayout.addLayout(self.fieldsLayout)
        self.packagesLayout.addWidget(self.diffButton)

        self.centralWidget().layout().addWidget(self.packagesGroupBox)

        # Create splitter widgets
        #
        self.packageModel = QtGui.QStandardItemModel()
        self.packageModel.setHorizontalHeaderLabels(['Name'])

        self.packageTreeView = QtWidgets.QTreeView()
        self.packageTreeView.setEditTriggers(QtWidgets.QTreeView.NoEditTriggers)
        self.packageTreeView.setAlternatingRowColors(True)
        self.packageTreeView.setUniformRowHeights(True)
        self.packageTreeView.setExpandsOnDoubleClick(False)
        self.packageTreeView.setStyleSheet('QTreeView:Item { height: 24px; }')

        self.packageTreeView.setModel(self.packageModel)

        self.packageTreeView.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.packageTreeView.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)

        self.centralWidget().layout().addWidget(self.packageTreeView)

        # Create changelist settings
        #
        self.settingsLayout = QtWidgets.QVBoxLayout()

        self.settingsGroupBox = QtWidgets.QGroupBox('Perforce Settings:')
        self.settingsGroupBox.setLayout(self.settingsLayout)

        # Create workspace widgets
        #
        self.userLabel = QtWidgets.QLabel('User:')
        self.userLabel.setFixedSize(QtCore.QSize(65, 20))
        self.userLabel.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.userLabel.setAlignment(QtCore.Qt.AlignRight)

        self.userLineEdit = QtWidgets.QLineEdit(os.environ.get('P4USER', getpass.getuser()))
        self.userLineEdit.setFixedHeight(20)
        self.userLineEdit.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        self.refreshButton = QtWidgets.QPushButton(qiconlibrary.getIconByName('refresh'), '')
        self.refreshButton.setFixedSize(QtCore.QSize(20, 20))
        self.refreshButton.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.refreshButton.clicked.connect(self.refreshWorkspaces)

        self.userLayout = QtWidgets.QHBoxLayout()
        self.userLayout.addWidget(self.userLabel)
        self.userLayout.addWidget(self.userLineEdit)
        self.userLayout.addWidget(self.refreshButton)

        self.portLabel = QtWidgets.QLabel('Port:')
        self.portLabel.setFixedSize(QtCore.QSize(65, 20))
        self.portLabel.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.portLabel.setAlignment(QtCore.Qt.AlignRight)

        self.portLineEdit = QtWidgets.QLineEdit(os.environ.get('P4PORT', 'localhost:1666'))
        self.portLineEdit.setFixedHeight(20)
        self.portLineEdit.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        self.portLayout = QtWidgets.QHBoxLayout()
        self.portLayout.addWidget(self.portLabel)
        self.portLayout.addWidget(self.portLineEdit)

        self.workspaceLabel = QtWidgets.QLabel('Workspace:')
        self.workspaceLabel.setFixedSize(QtCore.QSize(65, 20))
        self.workspaceLabel.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.workspaceLabel.setAlignment(QtCore.Qt.AlignRight)

        self.workspaceComboBox = QtWidgets.QComboBox()
        self.workspaceComboBox.setFixedHeight(20)
        self.workspaceComboBox.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.workspaceComboBox.currentIndexChanged.connect(self.workspaceChanged)

        self.workspaceLayout = QtWidgets.QHBoxLayout()
        self.workspaceLayout.addWidget(self.workspaceLabel)
        self.workspaceLayout.addWidget(self.workspaceComboBox)

        # Create changelist widgets
        #
        self.changelistLabel = QtWidgets.QLabel('Changelist:')
        self.changelistLabel.setFixedSize(QtCore.QSize(65, 20))
        self.changelistLabel.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.changelistLabel.setAlignment(QtCore.Qt.AlignRight)

        self.changelistComboBox = QtWidgets.QComboBox()
        self.changelistComboBox.setFixedHeight(20)
        self.changelistComboBox.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.changelistComboBox.currentIndexChanged.connect(self.changelistChanged)

        self.changelistLayout = QtWidgets.QHBoxLayout()
        self.changelistLayout.addWidget(self.changelistLabel)
        self.changelistLayout.addWidget(self.changelistComboBox)

        self.settingsLayout.addLayout(self.userLayout)
        self.settingsLayout.addLayout(self.portLayout)
        self.settingsLayout.addLayout(self.workspaceLayout)
        self.settingsLayout.addLayout(self.changelistLayout)

        self.centralWidget().layout().addWidget(self.settingsGroupBox)

        # Create commit button
        #
        self.commitButton = QtWidgets.QPushButton('Commit')
        self.commitButton.clicked.connect(self.commit)

        self.centralWidget().layout().addWidget(self.commitButton)

    def showEvent(self, event):
        """
        Overloaded method called after the window has been shown.

        :type event: QtGui.QShowEvent
        :rtype: None
        """

        # Call inherited method
        #
        super(QP4ckageMerger, self).showEvent(event)

        # Populate workspaces
        #
        self.refreshWorkspaces()

    @property
    def sourceDirectory(self):
        """
        Getter method that returns the source directory.

        :rtype: str
        """

        return self._sourceDirectory

    @property
    def targetDirectory(self):
        """
        Getter method that returns the target directory.

        :rtype: str
        """

        return self._targetDirectory

    @staticmethod
    def iterItems(item, column=0):
        """
        Generator method used to iterate through the immediate children belonging to the supplied item.
        An additional column keyword can be supplied to offset the lookup.

        :type item: QtGui.QStandardItem
        :type column: int
        :rtype: iter
        """

        # Iterate through rows
        #
        for i in range(item.rowCount()):

            yield item.child(i, column)

    def walk(self):
        """
        Generator method used to iterate through ALL of the tree view items.

        :rtype: iter
        """

        # Consume items in queue
        #
        queue = deque([self.topLevelItem()])

        while len(queue):

            # Pop and yield item
            #
            item = queue.popleft()
            yield item

            # Add item's children to queue
            #
            queue.extend(self.iterItems(item))

    def topLevelItems(self, column=0):
        """
        Method used to retrieve the top level items from the item model.
        An additional column keyword can be supplied to offset the lookup.

        :type column: int
        :rtype: list[QtGui.QStandardItem]
        """

        return list(self.iterItems(self.packageModel.invisibleRootItem(), column=column))

    def topLevelItem(self, column=0):
        """
        Method used to retrieve the top level item from the item model.
        An additional column keyword can be supplied to offset the lookup.

        :type column: int
        :rtype: QtGui.QStandardItem
        """

        return self.topLevelItems(column=column)[0]

    @classmethod
    def findChildByName(cls, parent, name, column=0):
        """
        Class method used to locate a child from the supplied parent using a name.
        An additional column keyword can be supplied to offset the lookup.

        :type parent: QtGui.QStandardItem
        :type name: str
        :type column: int
        :rtype: QtGui.QStandardItem
        """

        # Collect rows with text
        #
        rows = [x for x in cls.iterItems(parent, column=column) if x.text() == name]
        numRows = len(rows)

        if numRows:

            return rows[0]

        else:

            return None

    def findChildByPath(self, path):
        """
        Method used to retrieve an item using a string path with a compatible delimiter.

        :type path: str
        :rtype: QtGui.QStandardItem
        """

        # Check for redundancy
        #
        item = self.topLevelItem()

        if path == '.':

            return item

        # Iterate through sub paths
        #
        queue = deque(path.split(os.sep))

        while len(queue):

            name = queue.popleft()
            item = self.findChildByName(item, name)

        return item

    def isSourceFile(self, filePath):
        """
        Method used to determine if the supplied file originates from the source directory.

        :type filePath: str
        :rtype: bool
        """

        return filePath.startswith(self._sourceDirectory)

    def isTargetFile(self, filePath):
        """
        Method used to determine if the supplied file originates from the target directory.

        :type filePath: str
        :rtype: bool
        """

        return filePath.startswith(self._targetDirectory)

    @classmethod
    def removeEscapeChars(cls, string):
        """
        Removes any escape characters from the supplied string.
        This method supports both python 2 and 3.

        :type string: str
        :rtype: str
        """

        # Inspect python version
        #
        if sys.version_info.major == 2:

            return string.translate('', cls.__escapechars__)

        else:

            return string.translate(str.maketrans('', '', cls.__escapechars__))

    @classmethod
    def isIdentical(cls, sourcePath, targetPath):
        """
        Evaluates if the two supplied files are identical.

        :type sourcePath: str
        :type targetPath: str
        :rtype: bool
        """

        # Try and compare files
        # If it's a binary file then assume they're not identical
        #
        try:

            # Open files and compare
            # A direct string comparison should be the fastest method
            #
            with open(sourcePath, 'r') as sourceFile, open(targetPath, 'r') as targetFile:

                # Compare strings without escape characters
                #
                source = cls.removeEscapeChars(sourceFile.read())
                target = cls.removeEscapeChars(targetFile.read())

                return source == target

        except UnicodeDecodeError:

            return False

    def makePathRelative(self, filePath):
        """
        Method used to generate a relative path from the supplied file path.

        :type filePath: str
        :rtype: str
        """

        # Inspect origin of file
        #
        if self.isSourceFile(filePath):

            return os.path.relpath(filePath, self._sourceDirectory)

        else:

            return os.path.relpath(filePath, self._targetDirectory)

    def changeSource(self, pressed=False):
        """
        Slot method called whenever the source button is pressed.
        This method will prompt the user with a directory dialog to change the package source.

        :type pressed: bool
        :rtype: None
        """

        # Prompt user
        #
        sourceDirectory = QtWidgets.QFileDialog.getExistingDirectory(
            parent=self,
            caption='Select Package',
            dir=self._sourceDirectory,
            options=QtWidgets.QFileDialog.ShowDirsOnly
        )

        # Inspect results
        #
        if os.path.isdir(sourceDirectory):

            self.sourceLineEdit.setText(sourceDirectory)

    def sourceChanged(self, text):
        """
        Slot method called whenever the source line edit is changed.

        :type text: str
        :rtype: None
        """

        self._sourceDirectory = os.path.normpath(text)

    def changeTarget(self, pressed=False):
        """
        Slot method called whenever the target button is pressed.
        This method will prompt the user with a directory dialog to change the package source.

        :type pressed: bool
        :rtype: None
        """

        # Prompt user
        #
        targetDirectory = QtWidgets.QFileDialog.getExistingDirectory(
            parent=self,
            caption='Select Package',
            dir=self._targetDirectory,
            options=QtWidgets.QFileDialog.ShowDirsOnly
        )

        # Inspect results
        #
        if os.path.isdir(targetDirectory):

            self.targetLineEdit.setText(targetDirectory)

    def targetChanged(self, text):
        """
        Slot method called whenever the target line edit is changed.

        :type text: str
        :rtype: None
        """

        self._targetDirectory = os.path.normpath(text)

    def diff(self):
        """
        Diffs the current source and target directories.

        :rtype: None
        """

        # Check if source directory is valid
        #
        if not os.path.isdir(self._sourceDirectory) or not os.path.isdir(self._targetDirectory):

            log.warning('Unable to evaluate package directories!')
            return

        # Reset package model
        #
        self.packageModel.setRowCount(0)

        # Add top level item
        #
        name = os.path.split(self._sourceDirectory)[1]
        topLevelItem = QtGui.QStandardItem(qiconlibrary.getIconByName('p4v_folder'), name)

        self.packageModel.invisibleRootItem().appendRow(topLevelItem)

        # Add source directory
        #
        self.addDirectoryItem(self._sourceDirectory)
        self.addDirectoryItem(self._targetDirectory)

        # Expand all items
        #
        self.packageTreeView.expandAll()

    def addFileItem(self, filePath, parent=None):
        """
        Method used to add a new file item to the tree view.
        This method will inspect to determine if the item already exists.

        :type filePath: str
        :type parent: QtGui.QStandardItem
        :rtype: None
        """

        # Check if file item already exists
        #
        relativePath = self.makePathRelative(filePath)
        item = self.findChildByPath(relativePath)

        if item is not None:

            return

        # Get item arguments
        #
        sourcePath = None
        targetPath = None

        if self.isSourceFile(filePath):

            sourcePath = filePath
            targetPath = os.path.join(self._targetDirectory, relativePath)

        else:

            sourcePath = os.path.join(self._sourceDirectory, relativePath)
            targetPath = filePath

        # Create new item
        #
        item = QDepotItem(sourcePath, targetPath)
        parent.appendRow(item)

    def addDirectoryItem(self, directory, parent=None):
        """
        Method used to add a new directory item to the tree view.
        This method will inspect to determine if the item already exists.

        :type directory: str
        :type parent: QtGui.QStandardItem
        :rtype: None
        """

        # Check if directory item already exists
        #
        relativePath = self.makePathRelative(directory)
        item = self.findChildByPath(relativePath)

        if item is None:

            # Create new item
            #
            name = os.path.split(directory)[1]
            item = QtGui.QStandardItem(qiconlibrary.getIconByName('p4v_folder'), name)

            parent.appendRow(item)

        # Iterate through children
        #
        for filename in os.listdir(directory):

            # Concatenate file path
            #
            filePath = os.path.join(directory, filename)

            if os.path.isfile(filePath) and not filePath.endswith('.pyc'):

                self.addFileItem(filePath, parent=item)

            elif os.path.isdir(filePath):

                self.addDirectoryItem(filePath, parent=item)

            else:

                log.info('Skipping: %s' % filePath)
                continue

    def refreshWorkspaces(self, pressed=False):
        """
        Slot method called whenever the user clicks the refresh button.
        This method will repopulate the workspaces based on the user credentials.

        :type pressed: bool
        :rtype: None
        """

        # Collect clients from user input
        #
        user = self.userLineEdit.text()
        port = self.portLineEdit.text()

        self._clients = clientutils.ClientSpecs(user=user, port=port)

        # Populate combo box with new clients
        #
        self.workspaceComboBox.clear()
        self.workspaceComboBox.addItems([x.name for x in self._clients.values()])

    def workspaceChanged(self, index):
        """
        Slot method called whenever the selected workspace combobox item is changed.
        This method will repopulate the changelist combo box based on the client changelists.

        :type index: int
        :rtype: None
        """

        # Get selected client
        #
        comboBox = self.sender()  # type: QtWidgets.QComboBox
        self._currentClient = self._clients[comboBox.currentText()]

        # Append changelist items if client exists
        #
        self.changelistComboBox.clear()

        if self._currentClient is not None:

            self._changelists = ['default']
            self._changelists.extend([x['change'] for x in self._currentClient.getChangelists()])

            self.changelistComboBox.addItems(self._changelists)

    def changelistChanged(self, index):
        """
        Slot method called whenever the selected changelist combobox item is changed.
        This method will store an internal reference to the newly selected item.

        :type index: int
        :rtype: None
        """

        self._currentChangelist = self._changelists[index]

    def makeDirectories(self, directory):
        """
        Creates all of the directories from the supplied path.
        For simplicity sake this method will ignore any pre-existing directories.

        :type directory: str
        :rtype: None
        """

        try:

            return os.makedirs(directory)

        except OSError as exception:

            log.debug(exception)
            return

    def commit(self):
        """
        Method used to commit the found changes to the user specified changelist.
        This method cannot run without a valid perforce connection!
        :rtype: None
        """

        # Inspect user input
        #
        user = self.userLineEdit.text()
        port = self.portLineEdit.text()
        client = self.workspaceComboBox.currentText()
        changelist = self.changelistComboBox.currentText()

        if not client or not changelist:

            QtWidgets.QMessageBox.warning(self, 'P4ckageMerger', 'Unable to connect to server!')
            return

        # Walk through tree
        #
        for item in self.walk():

            # Check if this is a depot item
            #
            if not isinstance(item, QDepotItem):

                continue

            # Inspect item status
            #
            log.info('Inspecting: %s' % item.text())

            sourcePath = item.sourcePath()
            targetPath = item.targetPath()
            status = item.status()

            if status == QFileStatus.Edit:

                log.info('Editing: %s -> %s' % (targetPath, sourcePath))

                cmds.edit(sourcePath, user=user, port=port, client=client, changelist=changelist)
                shutil.copy(targetPath, sourcePath)

            elif status == QFileStatus.Add:

                log.info('Adding: %s -> %s' % (targetPath, sourcePath))

                self.makeDirectories(os.path.dirname(sourcePath))
                shutil.copy(targetPath, sourcePath)

                cmds.add(sourcePath, user=user, port=port, client=client, changelist=changelist)

            elif status == QFileStatus.Delete:

                log.info('Deleting: %s' % sourcePath)
                cmds.delete(sourcePath, user=user, port=port, client=client, changelist=changelist)

            else:

                continue
