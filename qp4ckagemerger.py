import os
import sys
import shutil

from Qt import QtCore, QtWidgets, QtGui
from collections import deque
from enum import Enum
from dcc.ui import quicwindow, qiconlibrary
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

    # region Dunderscores
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
    # endregion

    # region Methods
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
    # endregion


class QP4ckageMerger(quicwindow.QUicWindow):
    """
    Overload of QProxyWindow used to display changelist updates.
    """

    # region Dunderscores
    __escapechars__ = ''.join([chr(char) for char in range(1, 32)])

    def __init__(self, *args, **kwargs):
        """
        Private method called after a new instance has been created.

        :key parent: QtWidgets.QWidget
        :key flags: QtCore.Qt.WindowFlags
        :rtype: None
        """

        # Call parent methods
        #
        super(QP4ckageMerger, self).__init__(*args, **kwargs)

        # Declare private variables
        #
        self._sourceDirectory = ''
        self._targetDirectory = ''
        self._clients = None
        self._currentClient = None
        self._changelists = None
        self._currentChangelist = None
    # endregion
    
    # region Properties
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
    # endregion
    
    # region Methods
    def postLoad(self):
        """
        Called after the user interface has been loaded.

        :rtype: None
        """

        # Initialize package item model
        #
        self.packageItemModel = QtGui.QStandardItemModel(parent=self)
        self.packageItemModel.setObjectName('packageItemModel')
        self.packageItemModel.setHorizontalHeaderLabels(['Name'])

        self.packageTreeView.setModel(self.packageItemModel)

    def loadSettings(self):
        """
        Loads the user settings.

        :rtype: None
        """

        # Call parent method
        #
        super(QP4ckageMerger, self).loadSettings()

        # Load user settings
        #
        user = self.settings.value('editor/user', defaultValue=os.environ.get('P4USER' ''))
        self.userLineEdit.setText(user)

        port = self.settings.value('editor/port', defaultValue=os.environ.get('P4PORT', ''))
        self.portLineEdit.setText(port)

    def saveSettings(self):
        """
        Saves the user settings.

        :rtype: None
        """

        # Call parent method
        #
        super(QP4ckageMerger, self).saveSettings()

        # Save user settings
        #
        self.settings.setValue('editor/user', self.userLineEdit.text())
        self.settings.setValue('editor/port', self.portLineEdit.text())

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

        return list(self.iterItems(self.packageItemModel.invisibleRootItem(), column=column))

    def topLevelItem(self, column=0):
        """
        Method used to retrieve the top level item from the item model.
        An additional column keyword can be supplied to offset the lookup.

        :type column: int
        :rtype: QtGui.QStandardItem
        """

        return self.topLevelItems(column=column)[0]

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
    # endregion
    
    # region Events
    def showEvent(self, event):
        """
        Overloaded method called after the window has been shown.

        :type event: QtGui.QShowEvent
        :rtype: None
        """

        # Call inherited method
        #
        super(QP4ckageMerger, self).showEvent(event)

        # Populate clients
        #
        self.refreshPushButton.click()
    # endregion
    
    # region Slots
    @QtCore.Slot(bool)
    def on_sourcePushButton_clicked(self, checked=False):
        """
        Clicked slot method responsible for updating the source directory.
        This method will prompt the user with a directory dialog to change this value.

        :type checked: bool
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

    @QtCore.Slot(str)
    def on_sourceLineEdit_textChanged(self, text):
        """
        Text changed slot method responsible for updating the internal source directory.

        :type text: str
        :rtype: None
        """

        self._sourceDirectory = os.path.normpath(text)

    @QtCore.Slot(bool)
    def on_targetPushButton_clicked(self, checked=False):
        """
        Clicked slot method responsible for updating the target directory.
        This method will prompt the user with a directory dialog to change this value.

        :type checked: bool
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

    @QtCore.Slot(str)
    def on_targetLineEdit_textChanged(self, text):
        """
        Text changed slot method responsible for updating the internal target directory.

        :type text: str
        :rtype: None
        """

        self._targetDirectory = os.path.normpath(text)

    @QtCore.Slot(bool)
    def on_diffPushButton_clicked(self, checked=False):
        """
        Clicked slot method responsible for diffing the source and target packages.

        :type checked: bool
        :rtype: None
        """

        # Check if source directory is valid
        #
        if not os.path.isdir(self._sourceDirectory) or not os.path.isdir(self._targetDirectory):

            log.warning('Unable to evaluate package directories!')
            return

        # Reset package model
        #
        self.packageItemModel.setRowCount(0)

        # Add top level item
        #
        name = os.path.split(self._sourceDirectory)[1]
        topLevelItem = QtGui.QStandardItem(qiconlibrary.getIconByName('p4v_folder'), name)

        self.packageItemModel.invisibleRootItem().appendRow(topLevelItem)

        # Add source directory
        #
        self.addDirectoryItem(self._sourceDirectory)
        self.addDirectoryItem(self._targetDirectory)

        # Expand all items
        #
        self.packageTreeView.expandAll()

    @QtCore.Slot(bool)
    def on_refreshPushButton_clicked(self, checked=False):
        """
        Clicked slot method responsible for repopulating the clients based on the current user credentials.

        :type checked: bool
        :rtype: None
        """

        # Collect clients from user input
        #
        user = self.userLineEdit.text()
        port = self.portLineEdit.text()

        self._clients = clientutils.ClientSpecs(user=user, port=port)

        # Populate combo box with new clients
        #
        self.clientComboBox.clear()
        self.clientComboBox.addItems([x.name for x in self._clients.values()])

    @QtCore.Slot(int)
    def on_clientComboBox_currentIndexChanged(self, index):
        """
        Current index changed slot method responsible for updating the changelists associated with selected client.

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

    @QtCore.Slot(int)
    def on_changelistComboBox_currentIndexChanged(self, index):
        """
        Current index changed slot method responsible for updating the internal changelist.

        :type index: int
        :rtype: None
        """

        self._currentChangelist = self._changelists[index]

    @QtCore.Slot(bool)
    def on_commitPushButton_clicked(self, checked=False):
        """
        Clicked slot method responsible for committing the found changes to the specified changelist.

        :type checked: bool
        :rtype: None
        """

        # Inspect user input
        #
        user = self.userLineEdit.text()
        port = self.portLineEdit.text()
        client = self.clientComboBox.currentText()
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
    # endregion
