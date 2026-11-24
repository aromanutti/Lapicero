"""Small reusable widgets for the Graphite UI."""

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout,
                               QKeySequenceEdit, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from . import shortcuts
from .i18n import LANGUAGES, tr


class SegmentedControl(QFrame):
    """Exclusive pill buttons with the subset of the QComboBox API the app relies on."""

    currentIndexChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("segmented")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(3, 3, 3, 3)
        self._layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idClicked.connect(self.setCurrentIndex)
        self._data = []
        self._index = -1

    def addItem(self, *args):
        """addItem(text, data=None) or addItem(icon, text, data=None), like QComboBox."""
        icon = None
        if args and isinstance(args[0], QIcon):
            icon, args = args[0], args[1:]
        text, data = args[0], args[1] if len(args) > 1 else None
        button = QPushButton(text)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon is not None:
            button.setIcon(icon)
        self._group.addButton(button, len(self._data))
        self._layout.addWidget(button)
        self._data.append(data)
        if self._index < 0:
            self.setCurrentIndex(0)

    def button(self, index):
        return self._group.button(index)

    def count(self):
        return len(self._data)

    def itemData(self, index):
        return self._data[index]

    def findData(self, data):
        return self._data.index(data) if data in self._data else -1

    def currentIndex(self):
        return self._index

    def currentData(self):
        return self._data[self._index] if self._index >= 0 else None

    def setCurrentIndex(self, index):
        if not 0 <= index < len(self._data) or index == self._index:
            return
        self._index = index
        self._group.button(index).setChecked(True)
        self.currentIndexChanged.emit(index)


def link_choices(first, second):
    """Keep two choice widgets (combo or segmented) on the same data value."""
    def copy(source, target):
        index = target.findData(source.currentData())
        if index >= 0 and index != target.currentIndex():
            target.setCurrentIndex(index)
    first.currentIndexChanged.connect(lambda _: copy(first, second))
    second.currentIndexChanged.connect(lambda _: copy(second, first))
    copy(first, second)


def _label(text, name):
    label = QLabel(text)
    label.setObjectName(name)
    return label


class SettingsDialog(QDialog):
    """Rarely changed options: language, the toolbar, Ask Claude defaults and keyboard shortcuts."""

    toolbar_changed = Signal(list)  # Ids of the items to show, in order.
    shortcut_changed = Signal(str, str)  # Action id, its new key in portable text ("" removes it).
    shortcuts_reset = Signal()

    def __init__(self, toolbar_sizes, models, efforts, parent=None):
        super().__init__(parent)
        self.setObjectName("settings")
        self.setWindowTitle(tr("Settings"))
        self.setMinimumWidth(880)
        self._bindings = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 18)
        outer.setSpacing(10)
        outer.addWidget(_label(tr("Settings"), "dialogTitle"))
        outer.addSpacing(6)
        self.page_choice = SegmentedControl()
        self.page_choice.addItem(tr("General"), "general")
        self.page_choice.addItem(tr("Keyboard shortcuts"), "shortcuts")
        self.page_choice.setToolTip(tr("Settings page"))
        outer.addWidget(self.page_choice, 0, Qt.AlignmentFlag.AlignLeft)
        outer.addSpacing(4)
        self.pages = QStackedWidget()
        self.page_choice.currentIndexChanged.connect(self.pages.setCurrentIndex)
        outer.addWidget(self.pages, 1)
        general = QWidget()
        self.pages.addWidget(general)
        columns = QHBoxLayout(general)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(28)
        layout = QVBoxLayout()
        layout.setSpacing(10)
        columns.addLayout(layout, 1)

        layout.addWidget(_label(tr("Language"), "fieldLabel"))
        layout.addWidget(_label(tr("Restart Lapicero to apply a language change."), "hint"))
        self.language_choice = SegmentedControl()
        for label, code in LANGUAGES:
            self.language_choice.addItem(label, code)
        self.language_choice.setToolTip(tr("Interface language"))
        layout.addWidget(self.language_choice)
        layout.addSpacing(10)

        layout.addWidget(_label(tr("Toolbar size"), "fieldLabel"))
        self.size_combo = SegmentedControl()
        for name in toolbar_sizes:
            self.size_combo.addItem(tr(name.capitalize()), name)
        self.size_combo.setToolTip(tr("Size of the drawing toolbar buttons"))
        layout.addWidget(self.size_combo)
        layout.addSpacing(10)

        layout.addWidget(_label(tr("Claude model"), "fieldLabel"))
        layout.addWidget(_label(tr("Used for new questions; also changeable from the Ask panel."), "hint"))
        self.model_choice = SegmentedControl()
        for label, value in models:
            self.model_choice.addItem(tr(label), value)
        self.model_choice.setToolTip(tr("Model that answers Ask Claude questions"))
        layout.addWidget(self.model_choice)
        layout.addSpacing(6)

        layout.addWidget(_label(tr("Claude effort"), "fieldLabel"))
        layout.addWidget(_label(tr("Lower answers faster, higher is more thorough."), "hint"))
        self.effort_choice = SegmentedControl()
        for label, value in efforts:
            self.effort_choice.addItem(tr(label), value)
        self.effort_choice.setToolTip(tr("How hard Claude thinks"))
        layout.addWidget(self.effort_choice)
        layout.addStretch(1)

        side = QVBoxLayout()
        side.setSpacing(10)
        columns.addLayout(side, 1)
        side.addWidget(_label(tr("Toolbar"), "fieldLabel"))
        side.addWidget(_label(tr("Tick the tools to show and drag them to reorder."), "hint"))
        self.toolbar_list = QListWidget()
        self.toolbar_list.setObjectName("toolbarList")
        self.toolbar_list.setIconSize(QSize(22, 22))
        self.toolbar_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.toolbar_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.toolbar_list.setMinimumHeight(300)
        self.toolbar_list.setAccessibleName(tr("Toolbar"))
        self.toolbar_list.itemChanged.connect(lambda _: self._emit_toolbar())
        # A drag may arrive as a move or as an insert plus a remove: read the order once it settles.
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.timeout.connect(self._emit_toolbar)
        model = self.toolbar_list.model()
        for signal in (model.rowsMoved, model.rowsInserted, model.rowsRemoved):
            signal.connect(lambda *_: self._syncing or self._settle.start(0))
        side.addWidget(self.toolbar_list, 1)
        self.reset_button = QPushButton(tr("Reset to default"))
        self.reset_button.setObjectName("secondary")
        self.reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_button.clicked.connect(lambda: self.toolbar_changed.emit(list(self._default_toolbar)))
        side.addWidget(self.reset_button, 0, Qt.AlignmentFlag.AlignLeft)
        self._choices = {}
        self._default_toolbar = ()
        self._syncing = False
        self._emitted = None
        self.pages.addWidget(self._shortcuts_page())
        outer.addSpacing(8)

        footer = QHBoxLayout()
        footer.addWidget(_label(tr("Changes apply right away"), "hint"), 1)
        done = QPushButton(tr("Done"))
        done.setObjectName("primary")
        done.setDefault(True)
        done.clicked.connect(self.accept)
        footer.addWidget(done)
        outer.addLayout(footer)

    def _shortcuts_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        hint = _label(tr("Click a shortcut and press the new keys. Remove leaves the action "
                         "without one; a key already in use moves to the new action."), "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        scroll = QScrollArea()
        scroll.setObjectName("shortcutList")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(340)
        rows = QWidget()
        rows.setObjectName("shortcutRows")
        grid = QGridLayout(rows)
        grid.setContentsMargins(4, 4, 12, 4)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        self.shortcut_edits = {}
        self.shortcut_remove_buttons = {}
        row, scope = 0, None
        for action, label, _, action_scope in shortcuts.ACTIONS:
            if action_scope != scope:
                scope = action_scope
                title = (tr("On the page (when it has keyboard focus)") if scope == shortcuts.CANVAS
                         else tr("Anywhere in the window"))
                header = _label(title, "fieldLabel")
                grid.addWidget(header, row, 0, 1, 3)
                row += 1
            grid.addWidget(QLabel(tr(label)), row, 0)
            edit = QKeySequenceEdit()
            edit.setMaximumSequenceLength(1)
            edit.setMinimumWidth(170)
            edit.setToolTip(tr("Shortcut for {action}", action=tr(label)))
            edit.setAccessibleName(tr("Shortcut for {action}", action=tr(label)))
            edit.editingFinished.connect(lambda a=action: self._shortcut_edited(a))
            grid.addWidget(edit, row, 1)
            remove = QPushButton(tr("Remove"))
            remove.setObjectName("secondary")
            remove.setCursor(Qt.CursorShape.PointingHandCursor)
            remove.setToolTip(tr("Leave {action} without a shortcut", action=tr(label)))
            remove.clicked.connect(lambda checked=False, a=action: self.shortcut_changed.emit(a, ""))
            grid.addWidget(remove, row, 2)
            self.shortcut_edits[action] = edit
            self.shortcut_remove_buttons[action] = remove
            row += 1
        grid.setRowStretch(row, 1)
        scroll.setWidget(rows)
        layout.addWidget(scroll, 1)
        bottom = QHBoxLayout()
        self.shortcut_notice = _label("", "hint")
        self.shortcut_notice.setWordWrap(True)
        bottom.addWidget(self.shortcut_notice, 1)
        self.reset_shortcuts_button = QPushButton(tr("Restore default shortcuts"))
        self.reset_shortcuts_button.setObjectName("secondary")
        self.reset_shortcuts_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_shortcuts_button.clicked.connect(self.shortcuts_reset.emit)
        bottom.addWidget(self.reset_shortcuts_button)
        layout.addLayout(bottom)
        return page

    def _shortcut_edited(self, action):
        edit = self.shortcut_edits[action]
        key = edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        if key and key != self._bindings.get(action):
            self.shortcut_changed.emit(action, key)

    def set_shortcuts(self, bindings, notice=""):
        """Show these bindings (action -> portable key text, "" for none)."""
        self._bindings = dict(bindings)
        for action, edit in self.shortcut_edits.items():
            key = bindings.get(action, "")
            edit.blockSignals(True)
            edit.setKeySequence(QKeySequence(key, QKeySequence.SequenceFormat.PortableText))
            edit.blockSignals(False)
            self.shortcut_remove_buttons[action].setEnabled(bool(key))
        self.shortcut_notice.setText(notice)

    def focus_shortcuts(self):
        self.page_choice.setCurrentIndex(self.page_choice.findData("shortcuts"))

    def set_toolbar_choices(self, choices, defaults):
        """choices: (id, icon, label) for every item the toolbar can show."""
        self._choices = {item: (icon, label) for item, icon, label in choices}
        self._default_toolbar = tuple(defaults)
        self.set_toolbar_items(defaults)

    def set_toolbar_items(self, items):
        """Mirror the toolbar: shown items first in their order, then the rest unticked."""
        items = [item for item in items if item in self._choices]
        if self.toolbar_list.count() == len(self._choices) and self.toolbar_items() == items:
            return  # Already shown; never rebuild the list from inside its own signal.
        order = items + [item for item in self._choices if item not in items]
        self._syncing = True
        self.toolbar_list.clear()
        for item in order:
            icon, label = self._choices[item]
            row = QListWidgetItem(icon, label)
            row.setData(Qt.ItemDataRole.UserRole, item)
            row.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                         | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
            row.setCheckState(Qt.CheckState.Checked if item in items else Qt.CheckState.Unchecked)
            self.toolbar_list.addItem(row)
        self._syncing = False
        self._emitted = items

    def toolbar_items(self):
        rows = (self.toolbar_list.item(i) for i in range(self.toolbar_list.count()))
        return [row.data(Qt.ItemDataRole.UserRole) for row in rows
                if row.checkState() == Qt.CheckState.Checked]

    def _row(self, item):
        for index in range(self.toolbar_list.count()):
            if self.toolbar_list.item(index).data(Qt.ItemDataRole.UserRole) == item:
                return index
        raise KeyError(item)

    def set_item_checked(self, item, checked):
        self.toolbar_list.item(self._row(item)).setCheckState(
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def move_item(self, item, index):
        """Move a row like a drag does."""
        row = self.toolbar_list.takeItem(self._row(item))
        self.toolbar_list.insertItem(index, row)
        self._emit_toolbar()

    def focus_toolbar(self):
        self.page_choice.setCurrentIndex(self.page_choice.findData("general"))
        self.toolbar_list.setFocus()
        if self.toolbar_list.currentRow() < 0 and self.toolbar_list.count():
            self.toolbar_list.setCurrentRow(0)

    def _emit_toolbar(self):
        items = self.toolbar_items()
        if not self._syncing and items != self._emitted:
            self._emitted = items
            self.toolbar_changed.emit(items)
