"""Small reusable widgets for the Graphite UI."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout)

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
    """Rarely changed options: language, toolbar size and the defaults for Ask Claude."""

    def __init__(self, toolbar_sizes, models, efforts, parent=None):
        super().__init__(parent)
        self.setObjectName("settings")
        self.setWindowTitle(tr("Settings"))
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(10)
        layout.addWidget(_label(tr("Settings"), "dialogTitle"))
        layout.addSpacing(6)

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
        layout.addSpacing(14)

        footer = QHBoxLayout()
        footer.addWidget(_label(tr("Changes apply right away"), "hint"), 1)
        done = QPushButton(tr("Done"))
        done.setObjectName("primary")
        done.setDefault(True)
        done.clicked.connect(self.accept)
        footer.addWidget(done)
        layout.addLayout(footer)
