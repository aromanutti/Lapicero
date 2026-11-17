"""Small reusable widgets for the Graphite UI."""

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QVBoxLayout)

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
    """Rarely changed options: language, the toolbar and the defaults for Ask Claude."""

    toolbar_changed = Signal(list)  # Ids of the items to show, in order.

    def __init__(self, toolbar_sizes, models, efforts, parent=None):
        super().__init__(parent)
        self.setObjectName("settings")
        self.setWindowTitle(tr("Settings"))
        self.setMinimumWidth(880)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 18)
        outer.setSpacing(10)
        outer.addWidget(_label(tr("Settings"), "dialogTitle"))
        outer.addSpacing(6)
        columns = QHBoxLayout()
        columns.setSpacing(28)
        outer.addLayout(columns, 1)
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
        outer.addSpacing(8)

        footer = QHBoxLayout()
        footer.addWidget(_label(tr("Changes apply right away"), "hint"), 1)
        done = QPushButton(tr("Done"))
        done.setObjectName("primary")
        done.setDefault(True)
        done.clicked.connect(self.accept)
        footer.addWidget(done)
        outer.addLayout(footer)

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
        self.toolbar_list.setFocus()
        if self.toolbar_list.currentRow() < 0 and self.toolbar_list.count():
            self.toolbar_list.setCurrentRow(0)

    def _emit_toolbar(self):
        items = self.toolbar_items()
        if not self._syncing and items != self._emitted:
            self._emitted = items
            self.toolbar_changed.emit(items)
