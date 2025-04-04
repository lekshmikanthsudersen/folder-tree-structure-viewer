import os
import sys
import logging
import time # For formatting dates
import subprocess # For open_in_explorer on Windows
from PySide6 import QtWidgets, QtGui, QtCore

# --- Constants ---
APP_NAME = "Folder Tree Viewer"
APP_VERSION = "1.1" # Example version
DEVELOPER_NAME = "Sudersen Lekshmikanth"
SUPPORT_URL = "https://buymeacoffee.com/sudersen"
FULL_PATH_ROLE = QtCore.Qt.UserRole + 1 # Custom data role

# --- Helper Functions ---
# format_size and format_date...
def format_size(size_bytes):
    """Converts bytes to human-readable string."""
    if size_bytes is None: return "N/A" # Handle None case
    try:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024**2:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024**3:
            return f"{size_bytes / 1024**2:.1f} MB"
        else:
            return f"{size_bytes / 1024**3:.1f} GB"
    except TypeError:
        return "N/A" # Handle unexpected types

def format_date(timestamp):
    """Formats timestamp into a readable date string."""
    if timestamp is None: return "N/A" # Handle None case
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))
    except (ValueError, TypeError, OSError): # Catch more potential errors
        return "Invalid Date"

# --- Filter Proxy Model ---
class FolderFilterProxyModel(QtCore.QSortFilterProxyModel):
    """Proxy model to filter the tree based on search text."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_text = ""

    def set_filter_text(self, text):
        self._filter_text = text.lower()
        self.invalidateFilter() # Important: trigger filter update

    def filterAcceptsRow(self, source_row, source_parent_index):
        """Overrides base class method to implement custom filtering."""
        if not self._filter_text: # No filter text, accept everything
            return True

        source_model = self.sourceModel()
        if not source_model: return True # Should not happen if setup correctly

        source_index = source_model.index(source_row, 0, source_parent_index)
        if not source_index.isValid():
            return False

        # Check if the item itself matches
        item_text = source_model.data(source_index, QtCore.Qt.DisplayRole)
        if item_text and self._filter_text in item_text.lower():
            return True

        # --- Recursive Check: Keep parent if any child matches ---
        if source_model.hasChildren(source_index):
            for i in range(source_model.rowCount(source_index)):
                if self.filterAcceptsRow(i, source_index):
                    return True

        return False


# --- Main Window (Now QMainWindow) ---
class FolderTreeView(QtWidgets.QMainWindow): # Inherit from QMainWindow
    def __init__(self):
        super().__init__()
        self._block_item_changed_signal = False
        self._context_menu_index = QtCore.QModelIndex()
        self._current_scan_path = None # Keep track of the scanned path
        self.init_ui()

    def init_ui(self):
        # Use App Name and Developer in Title
        self.setWindowTitle(f"{APP_NAME} by {DEVELOPER_NAME}")
        self.setGeometry(100, 100, 900, 700)

        # --- Central Widget and Main Layout ---
        # QMainWindow requires a central widget
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)

        # --- Menu Bar ---
        self.create_menu_bar()

        # --- Layouts ---
        top_layout = QtWidgets.QHBoxLayout()
        search_layout = QtWidgets.QHBoxLayout()
        bottom_layout = QtWidgets.QHBoxLayout()

        # --- Widgets ---
        self.select_button = QtWidgets.QPushButton(QtGui.QIcon.fromTheme("folder-open"), " Select Folder")
        self.folder_path_edit = QtWidgets.QLineEdit()
        self.folder_path_edit.setPlaceholderText("Select a folder to view its structure...")
        self.folder_path_edit.setReadOnly(True)

        self.search_label = QtWidgets.QLabel("Filter:")
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Type to filter tree...")
        self.search_edit.setClearButtonEnabled(True)

        # --- Stacked Widget for Tree View / Intro Text ---
        self.stacked_widget = QtWidgets.QStackedWidget()

        # --- Intro Widget ---
        self.intro_widget = QtWidgets.QWidget()
        intro_layout = QtWidgets.QVBoxLayout(self.intro_widget)
        intro_layout.addStretch(1) # Push text to center
        self.intro_label = QtWidgets.QLabel(
            f"<h2>Welcome to {APP_NAME}!</h2>"
            "<p>Select a folder using the button above to view its structure.</p>"
            "<p>You can then:</p>"
            "<ul>"
            "<li>Explore the hierarchy</li>"
            "<li>Filter files and folders</li>"
            "<li>See file sizes and modification dates</li>"
            "<li>Check/uncheck items to include them when copying</li>"
            "<li>Right-click for more options</li>"
            "</ul>"
        )
        self.intro_label.setAlignment(QtCore.Qt.AlignCenter)
        self.intro_label.setWordWrap(True)
        intro_layout.addWidget(self.intro_label)
        intro_layout.addStretch(1)

        # --- Tree View Widget ---
        self.tree_view = QtWidgets.QTreeView()
        self.tree_view.setSortingEnabled(True)
        self.tree_view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree_view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree_view.setDragDropMode(QtWidgets.QAbstractItemView.NoDragDrop)
        self.tree_view.setUniformRowHeights(True) # Performance hint
        self.tree_view.setAlternatingRowColors(True) # Use QSS for styling this

        # --- Add Widgets to Stacked Widget ---
        self.stacked_widget.addWidget(self.intro_widget)
        self.stacked_widget.addWidget(self.tree_view)
        self.stacked_widget.setCurrentWidget(self.intro_widget) 


        # --- Status Bar ---
        # QMainWindow has a built-in status bar
        self.statusBar().showMessage("Ready. Select a folder.")
        # self.status_label = QtWidgets.QLabel("Ready. Select a folder.")

        # --- Bottom Controls ---
        self.copy_button = QtWidgets.QPushButton(QtGui.QIcon.fromTheme("edit-copy"), " Copy Checked Tree")
        self.copy_button.setEnabled(False)


        # --- Model Setup ---
        self.model = QtGui.QStandardItemModel()
        self.model.setColumnCount(3)
        self.model.setHeaderData(0, QtCore.Qt.Horizontal, "Name")
        self.model.setHeaderData(1, QtCore.Qt.Horizontal, "Size")
        self.model.setHeaderData(2, QtCore.Qt.Horizontal, "Date Modified")

        self.proxy_model = FolderFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setFilterKeyColumn(0)
        self.proxy_model.setRecursiveFilteringEnabled(True)

        self.tree_view.setModel(self.proxy_model)

        self.tree_view.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.tree_view.setColumnWidth(1, 100)
        self.tree_view.setColumnWidth(2, 150)

        # --- Assemble Layouts ---
        top_layout.addWidget(self.select_button)
        top_layout.addWidget(self.folder_path_edit)

        search_layout.addWidget(self.search_label)
        search_layout.addWidget(self.search_edit)

        # Bottom layout now only needs copy button if using status bar
        # bottom_layout.addWidget(self.status_label) # Remove if using QStatusBar
        bottom_layout.addStretch(1)
        bottom_layout.addWidget(self.copy_button)

        main_layout.addLayout(top_layout)
        main_layout.addLayout(search_layout)
        # Add the STACKED WIDGET instead of the tree_view directly
        main_layout.addWidget(self.stacked_widget)
        main_layout.addLayout(bottom_layout)

        # --- Connect Signals ---
        self.select_button.clicked.connect(self.select_folder)
        self.copy_button.clicked.connect(self.copy_tree_to_clipboard)
        self.model.itemChanged.connect(self.handle_item_changed)
        self.search_edit.textChanged.connect(self.proxy_model.set_filter_text)
        self.tree_view.customContextMenuRequested.connect(self.show_context_menu)

        self.apply_styles()

    def create_menu_bar(self):
        """Creates the main menu bar."""
        menu_bar = self.menuBar()

        # --- File Menu ---
        # file_menu = menu_bar.addMenu("&File")
        # exit_action = QtGui.QAction(QtGui.QIcon.fromTheme("application-exit"), "E&xit", self)
        # exit_action.triggered.connect(self.close)
        # file_menu.addAction(exit_action)

        # --- Help Menu ---
        help_menu = menu_bar.addMenu("&Help")

        about_action = QtGui.QAction("&About", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

        support_action = QtGui.QAction(QtGui.QIcon.fromTheme("help-donate"), "Support the Developer", self) # Example icon
        support_action.triggered.connect(self.open_support_link)
        help_menu.addAction(support_action)


    def show_about_dialog(self):
        """Displays the About dialog box."""
        about_text = (
            f"<h2>{APP_NAME} v{APP_VERSION}</h2>"
            f"<p>Developed by: {DEVELOPER_NAME}</p>"
            "<p>A utility to view, filter, and copy folder structures.</p>"
            "<p>Built with Python and Qt (PySide6).</p>"
            "<hr>"
            "<p>If you find this tool useful, consider supporting the developer:</p>"
            # The QMessageBox.about text supports rich text links
            f"<p><a href='{SUPPORT_URL}'>Buy Me a Coffee</a></p>"
        )
        QtWidgets.QMessageBox.about(self, f"About {APP_NAME}", about_text)

    def open_support_link(self):
         """Opens the developer support link in the default web browser."""
         url = QtCore.QUrl(SUPPORT_URL)
         if not QtGui.QDesktopServices.openUrl(url):
             logging.warning("Could not open support URL: %s", SUPPORT_URL)
             QtWidgets.QMessageBox.warning(self, "Cannot Open URL",
                                             f"Could not open the support link:\n{SUPPORT_URL}\n"
                                             "Please copy and paste it into your browser.")

    def apply_styles(self):

        self.setStyleSheet("""
            QMainWindow, QWidget { /* Apply base styles to both if needed */
                font-size: 10pt;
                background-color: #353535;
                color: #e0e0e0;
            }
            /* Style intro label specifically if needed */
            QLabel#introLabel {
                font-size: 12pt;
                color: #cccccc;
                 /* Add padding, margins as needed */
            }
            QMenuBar {
                background-color: #424242;
                color: #e0e0e0;
                border-bottom: 1px solid #555555;
            }
            QMenuBar::item {
                background-color: transparent;
                padding: 4px 8px;
            }
            QMenuBar::item:selected {
                background-color: #5a5a5a;
            }
            QMenu {
                background-color: #424242;
                color: #e0e0e0;
                border: 1px solid #555555;
            }
            QMenu::item:selected {
                background-color: #0078d7;
                color: white;
            }
            QStatusBar {
                color: #aaaaaa;
                background-color: #353535;
                border-top: 1px solid #555555;
            }
            /* Existing styles from previous version... */
            QLineEdit, QPushButton, QTreeView {
                border: 1px solid #555555;
                padding: 5px;
                background-color: #424242;
                color: #e0e0e0;
                border-radius: 3px;
            }
            QPushButton { padding: 5px 15px; outline: none; }
            QPushButton:hover { background-color: #5a5a5a; }
            QPushButton:pressed { background-color: #4f4f4f; }
            QPushButton:disabled { background-color: #484848; color: #888888; }
            QLineEdit { selection-background-color: #0078d7; selection-color: white; }
            QTreeView { alternate-background-color: #3e3e3e; padding: 5px; border-radius: 3px; }
            QTreeView::item { padding: 4px 0px; border-radius: 2px; }
            QTreeView::item:selected { background-color: #0078d7; color: white; }
            QTreeView::item:!enabled { color: #a85555; }
            QHeaderView::section { background-color: #4a4a4a; color: #e0e0e0; padding: 4px; border: 1px solid #555555; border-bottom: 2px solid #6a6a6a; }
            QScrollBar:vertical { border: 1px solid #555555; background: #424242; width: 12px; margin: 0px; }
            QScrollBar::handle:vertical { background: #6a6a6a; min-height: 20px; border-radius: 6px; }
        """)
        # Set object name for intro label if specific styling needed
        self.intro_label.setObjectName("introLabel")


    @QtCore.Slot()
    def select_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Folder", self._current_scan_path or os.path.expanduser("~")
        )
        if folder:
            self._current_scan_path = folder # Store the path
            self.folder_path_edit.setText(folder)
            self.update_status(f"Scanning folder: {os.path.basename(folder)}...")
            self.search_edit.clear()
            QtCore.QCoreApplication.processEvents()
            # Switch to tree view *before* populating (optional, shows empty tree during scan)
            # self.stacked_widget.setCurrentWidget(self.tree_view)
            success = self.populate_tree(folder)
            # Switch view *after* attempting to populate
            if success:
                self.stacked_widget.setCurrentWidget(self.tree_view)
            else:
                 # If initial scan fails, stay on intro/show error
                 self.stacked_widget.setCurrentWidget(self.intro_widget)


    def populate_tree(self, root_folder):
        # Reset view state before populating
        self.copy_button.setEnabled(False)
        # Switch to intro view while clearing/scanning if preferred
        # self.stacked_widget.setCurrentWidget(self.intro_widget)
        # QtCore.QCoreApplication.processEvents()

        try:
            self.model.itemChanged.disconnect(self.handle_item_changed)
        except RuntimeError: pass
        self.model.clear()
        self.model.setHorizontalHeaderLabels(["Name", "Size", "Date Modified"])
        invisible_root = self.model.invisibleRootItem()

        scan_successful = False # Flag to track success
        try:
            # --- Start recursive population ---
            # Add the root folder itself as the first top-level item
            self.add_folder_item_recursive(root_folder, invisible_root)

            self.update_status("Scan complete. Check/uncheck items. Right-click for options.")
            self.copy_button.setEnabled(True)
            scan_successful = True
        except Exception as e:
            self.update_status(f"Error during scan: {e}")
            QtWidgets.QMessageBox.critical(self, "Scan Error", f"An error occurred during the initial scan:\n{e}")
            logging.error("Scan Error", exc_info=True)
            self.copy_button.setEnabled(False)
            scan_successful = False
        finally:
            self.model.itemChanged.connect(self.handle_item_changed)
            # Expand the first item only if scan was successful
            if scan_successful:
                root_proxy_index = self.proxy_model.index(0, 0)
                if root_proxy_index.isValid():
                    self.tree_view.expand(root_proxy_index)
        return scan_successful # Return success status


    def add_folder_item_recursive(self, current_path, parent_item):
        """
        Adds the item for current_path and then recursively scans its contents.
        Now handles the top-level item correctly.
        """
        base_name = os.path.basename(current_path) if current_path else "Unknown"
        item_name = QtGui.QStandardItem(base_name) # Column 0: Name
        item_size = QtGui.QStandardItem("")         # Column 1: Size
        item_date = QtGui.QStandardItem("")         # Column 2: Date
        item_name.setEditable(False)
        item_size.setEditable(False)
        item_date.setEditable(False)
        item_size.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        try:
            stat_info = os.stat(current_path)
            item_name.setData(current_path, FULL_PATH_ROLE)
            item_name.setToolTip(current_path)
            item_name.setCheckable(True)
            item_name.setCheckState(QtCore.Qt.CheckState.Checked)
            item_name.setIcon(QtGui.QIcon.fromTheme("folder-open", QtGui.QIcon(":/qt-project.org/styles/commonstyle/images/diropen-16.png"))) # Use open icon
            item_date.setText(format_date(stat_info.st_mtime))
            # Append row early so children can be added
            parent_item.appendRow([item_name, item_size, item_date])

        except Exception as e: # Handle stat error for the folder itself
            item_name.setText(f"{base_name} [Access Error]")
            item_name.setToolTip(f"{current_path}\nError: {e}")
            item_name.setCheckable(False)
            item_name.setForeground(QtGui.QBrush(QtCore.Qt.GlobalColor.red))
            item_size.setText("N/A")
            item_date.setText("N/A")
            parent_item.appendRow([item_name, item_size, item_date])
            logging.error("Error stating path %s", current_path, exc_info=True)
            return # Stop recursion for this path if we can't stat it

        # --- Scan Contents (only if stat succeeded) ---
        try:
            entries = sorted(os.scandir(current_path), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
            for entry in entries:
                try:
                    entry_stat = entry.stat(follow_symlinks=False)
                    # Create items for the entry row
                    entry_name_item = QtGui.QStandardItem(entry.name)
                    entry_name_item.setData(entry.path, FULL_PATH_ROLE)
                    entry_name_item.setToolTip(entry.path)
                    entry_name_item.setEditable(False)
                    entry_name_item.setCheckable(True)
                    entry_name_item.setCheckState(QtCore.Qt.CheckState.Checked)

                    entry_size_item = QtGui.QStandardItem()
                    entry_size_item.setEditable(False)
                    entry_size_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

                    entry_date_item = QtGui.QStandardItem(format_date(entry_stat.st_mtime))
                    entry_date_item.setEditable(False)

                    if entry.is_dir(follow_symlinks=False):
                        entry_name_item.setIcon(QtGui.QIcon.fromTheme("folder", QtGui.QIcon(":/qt-project.org/styles/commonstyle/images/directory-16.png"))) # Closed folder icon
                        item_name.appendRow([entry_name_item, entry_size_item, entry_date_item])
                        self.add_folder_item_recursive(entry.path, entry_name_item) # Recurse
                    else:
                        entry_name_item.setIcon(QtGui.QIcon.fromTheme("text-x-generic", QtGui.QIcon(":/qt-project.org/styles/commonstyle/images/file-16.png")))
                        entry_size_item.setText(format_size(entry_stat.st_size))
                        item_name.appendRow([entry_name_item, entry_size_item, entry_date_item])

                except OSError as e: # Handle errors for specific entries inside the loop
                    error_item = QtGui.QStandardItem(f"{entry.name} [OS Error]")
                    # ... (error handling as before) ...
                    error_size = QtGui.QStandardItem("N/A")
                    error_date = QtGui.QStandardItem("N/A")
                    item_name.appendRow([error_item, error_size, error_date])
                    logging.warning("OS Error scanning entry %s: %s", entry.path, e.strerror)

        except PermissionError:
            # Indicate inability to scan contents, but keep folder item
             logging.warning("Permission denied scanning contents of %s", current_path)
             # Add a placeholder child item indicating failure?
             perm_denied_item = QtGui.QStandardItem("[Contents Hidden - Permission Denied]")
             perm_denied_item.setEditable(False)
             perm_denied_item.setCheckable(False)
             perm_denied_item.setForeground(QtGui.QBrush(QtCore.Qt.GlobalColor.red))
             item_name.appendRow([perm_denied_item, QtGui.QStandardItem(""), QtGui.QStandardItem("")])

        except Exception as e:
            logging.error("Error scanning contents of %s", current_path, exc_info=True)
            # Indicate generic scan error
            scan_error_item = QtGui.QStandardItem("[Error Scanning Contents]")
            # ... (style as error) ...
            item_name.appendRow([scan_error_item, QtGui.QStandardItem(""), QtGui.QStandardItem("")])

    # --- handle_item_changed  ---
    @QtCore.Slot(QtGui.QStandardItem)
    def handle_item_changed(self, item):
        """ Handles check state changes, including recursion """
        if self._block_item_changed_signal: return
        if item.column() == 0 and item.isCheckable():
            check_state = item.checkState()
            self._block_item_changed_signal = True
            try:
                # Find the actual item in column 0 if needed (handles multi-column changes better)
                name_item_index = self.model.index(item.row(), 0, item.parent().index() if item.parent() else QtCore.QModelIndex())
                name_item = self.model.itemFromIndex(name_item_index)
                if name_item and name_item.hasChildren(): # Only recurse if it has children
                    self.update_children_checkstate(name_item, check_state)
            finally:
                self._block_item_changed_signal = False

    # --- update_children_checkstate ---
    def update_children_checkstate(self, parent_name_item, state):
        """ Recursively sets check state for children (accessing item at column 0) """
        for row in range(parent_name_item.rowCount()):
            child_name_item = parent_name_item.child(row, 0) # Checkbox is in column 0
            if child_name_item and child_name_item.isCheckable():
                if child_name_item.checkState() != state:
                    child_name_item.setCheckState(state)
                if child_name_item.hasChildren():
                     self.update_children_checkstate(child_name_item, state)


    # --- copy_tree_to_clipboard  ---
    @QtCore.Slot()
    def copy_tree_to_clipboard(self):
        self.update_status("Generating text for clipboard...")
        QtCore.QCoreApplication.processEvents()
        text_lines = []
        # Use proxy model's root for iteration
        invisible_root_proxy = self.proxy_model.index(0,0).parent() # Get proxy root
        for row in range(self.proxy_model.rowCount(invisible_root_proxy)):
            proxy_index = self.proxy_model.index(row, 0, invisible_root_proxy)
            if not proxy_index.isValid(): continue
            # Start recursive generation using the PROXY index
            # Pass True for is_last_sibling based on loop index
            self.generate_text_recursive_v2(proxy_index, "", row == (self.proxy_model.rowCount(invisible_root_proxy) - 1), text_lines)

        final_text = "\n".join(text_lines)
        if final_text:
            clipboard = QtGui.QGuiApplication.clipboard()
            clipboard.setText(final_text)
            self.update_status("Formatted structure copied to clipboard.")
        else:
            self.update_status("Nothing to copy (no visible/checked items or tree empty).")

    # --- generate_text_recursive_v2  ---
    def generate_text_recursive_v2(self, proxy_index, prefix, is_last_sibling, output_lines):
        source_index = self.proxy_model.mapToSource(proxy_index)
        if not source_index.isValid(): return
        item = self.model.itemFromIndex(source_index) # Get item from SOURCE model
        if not item: return

        if item.isCheckable() and item.checkState() == QtCore.Qt.CheckState.Checked:
            item_text = item.text()
            connector = "└─ " if is_last_sibling else "├─ "
            output_lines.append(f"{prefix}{connector}{item_text}")
            prefix_for_children = prefix + ("   " if is_last_sibling else "│  ")
            num_children = self.proxy_model.rowCount(proxy_index) # Count children in PROXY
            for row in range(num_children):
                child_proxy_index = self.proxy_model.index(row, 0, proxy_index)
                if child_proxy_index.isValid():
                    is_last_child = (row == num_children - 1)
                    self.generate_text_recursive_v2(child_proxy_index, prefix_for_children, is_last_child, output_lines)


    # --- Context Menu  ---
    @QtCore.Slot(QtCore.QPoint)
    def show_context_menu(self, point):
        proxy_index = self.tree_view.indexAt(point)
        if not proxy_index.isValid(): return
        source_index = self.proxy_model.mapToSource(proxy_index)
        if not source_index.isValid(): return
        item = self.model.itemFromIndex(source_index)
        if not item: return
        path = item.data(FULL_PATH_ROLE)
        if not path: return

        menu = QtWidgets.QMenu(self)
        action_show = QtGui.QAction(QtGui.QIcon.fromTheme("folder"), "Show in File Explorer", self)
        action_show.triggered.connect(lambda checked=False, p=path: self.open_in_explorer(p))
        menu.addAction(action_show)
        action_open = QtGui.QAction(QtGui.QIcon.fromTheme("document-open"), "Open", self)
        action_open.triggered.connect(lambda checked=False, p=path: self.open_item(p))
        if os.path.isdir(path): action_open.setEnabled(False)
        menu.addAction(action_open)
        menu.addSeparator()
        action_copy_path = QtGui.QAction("Copy Full Path", self)
        action_copy_path.triggered.connect(lambda checked=False, p=path: self.copy_path(p))
        menu.addAction(action_copy_path)
        menu.exec(self.tree_view.viewport().mapToGlobal(point))

    # --- open_in_explorer, open_item, copy_path  ---
    def open_in_explorer(self, path):
        try:
            norm_path = os.path.normpath(path) # Normalize path
            if sys.platform == 'win32':
                 if os.path.isdir(norm_path): os.startfile(norm_path)
                 else: subprocess.run(['explorer', '/select,', norm_path], check=True) # Added check=True
            elif sys.platform == 'darwin':
                 subprocess.run(['open', '-R' if os.path.isfile(norm_path) else norm_path], check=True)
            else: # Linux
                 subprocess.run(['xdg-open', os.path.dirname(norm_path) if os.path.isfile(norm_path) else norm_path], check=True)
            self.update_status(f"Opened/Selected: {os.path.basename(norm_path)}")
        except Exception as e:
            logging.error("Failed to open in explorer: %s", path, exc_info=True)
            QtWidgets.QMessageBox.warning(self, "Error", f"Could not open location for '{os.path.basename(path)}':\n{e}")
            self.update_status(f"Error opening location for: {os.path.basename(path)}")

    def open_item(self, path):
        if os.path.isfile(path):
            if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path)):
                 logging.error("Failed to open item: %s", path)
                 QtWidgets.QMessageBox.warning(self, "Error", f"Could not open file '{os.path.basename(path)}'.")
                 self.update_status(f"Error opening: {os.path.basename(path)}")
            else:
                 self.update_status(f"Opened: {os.path.basename(path)}")

    def copy_path(self, path):
        try:
            clipboard = QtGui.QGuiApplication.clipboard()
            clipboard.setText(path)
            self.update_status(f"Path copied: {os.path.basename(path)}")
        except Exception as e:
            logging.error("Failed to copy path: %s", path, exc_info=True)
            self.update_status(f"Error copying path for: {os.path.basename(path)}")


    # --- update_status (Use QStatusBar) ---
    def update_status(self, message):
        self.statusBar().showMessage(message, 5000) # Show for 5 seconds
        logging.info("Status Update: %s", message)

# --- Main execution---
if __name__ == '__main__':
    log_file = 'folder_viewer.log'
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)-7s] %(message)s',
        handlers=[
            logging.FileHandler(log_file, mode='w'),
            logging.StreamHandler()
        ]
    )
    logging.info("Application starting...")

    app = QtWidgets.QApplication(sys.argv)
    app.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    app.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)

    app_icon_path = "folder_icon.png" # I can edit my desired icons here
    if os.path.exists(app_icon_path):
         app.setWindowIcon(QtGui.QIcon(app_icon_path))
         logging.info("Application icon set from: %s", app_icon_path)
    else:
         logging.warning("Application icon file not found: %s", app_icon_path)
         app.setWindowIcon(QtGui.QIcon.fromTheme("folder"))

    window = FolderTreeView()
    window.show()
    logging.info("Main window shown.")

    try:
        sys.exit(app.exec())
    except Exception as e:
        logging.critical("Application crashed.", exc_info=True)
        sys.exit(1)