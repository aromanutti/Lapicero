"""Qt library window for local, page-based handwritten notes."""

import json
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QFormLayout, QFrame,
                               QGraphicsOpacityEffect, QGridLayout, QGroupBox, QHBoxLayout,
                               QApplication, QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QSlider, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import icons
from .ai_ops import AiOperations
from .ask import (ASK_EFFORTS, ASK_MODELS, MCP_CONFIG_FILE, AskPanel, ClaudeAsk, build_message,
                  build_prompt, mcp_config)
from .bridge import BridgeServer
from .library import Library
from .model import Note, NoteFormatError
from .paths import bridge_info_path, default_library_path
from .qt_canvas import CanvasView, InkCanvas


PALETTE = (("Black", "#202020"), ("Blue", "#205bb5"), ("Red", "#b73535"),
           ("Green", "#237346"), ("Purple", "#743f9e"), ("Orange", "#e07b00"),
           ("Yellow", "#ffe600"), ("Pink", "#e8559b"), ("Cyan", "#1aa3c9"),
           ("Gray", "#7a7a7a"))
HIGHLIGHTER_ALPHA = "80"
# Pen presets in toolbar order; clicking the active pen opens its color/width panel.
PEN_PRESETS = (("Black pen", "#202020", 3, False), ("Blue pen", "#205bb5", 3, False),
               ("Red pen", "#b73535", 3, False), ("Green pen", "#237346", 3, False),
               ("Yellow highlighter", "#ffe600", 16, True),
               ("Pink highlighter", "#e8559b", 16, True))
SHAPE_NAMES = {"line": "Line", "arrow": "Arrow", "rectangle": "Rectangle",
               "ellipse": "Ellipse", "triangle": "Triangle"}
MAX_WIDTH = 40
TOOLBAR_SIZES = {"small": 26, "medium": 34, "large": 44}  # Icon pixels, in cycle order.
DRAWING_OPACITY = .25  # Toolbar fades while the pen is down, so ink below stays visible.
UI_SETTINGS = "ui.json"  # Window preferences beside the library file.
# Save once the pen has rested this long: writing a whole library after every
# stroke froze the app between letters. Close and Ctrl+S still save at once.
AUTOSAVE_DELAY_MS = 1200
SHORTCUTS = ("P pen · E eraser · L lasso · S shapes · A ask Claude · Ctrl+C/V copy/paste · Ctrl+↑/↓ width · "
             "wheel scroll · Shift+wheel sideways · Ctrl+wheel zoom · F11 fullscreen")


class FloatingToolbar(QFrame):
    """Compact OneNote-like tool strip floating over the top of the page."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("floatingToolbar")
        self.setStyleSheet("#floatingToolbar { background: #f7f7f7; border: 1px solid #c9c9c9;"
                           " border-radius: 6px; }")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 2, 4, 2)
        self._layout.setSpacing(1)

    def addWidget(self, widget):
        self._layout.addWidget(widget)

    def addSeparator(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setStyleSheet("color: #d4d4d4;")
        self._layout.addWidget(line)


class PenPreset:
    def __init__(self, name, color, width, highlighter):
        self.name, self.color, self.width, self.highlighter = name, color, width, highlighter

    @property
    def ink(self):
        return self.color + (HIGHLIGHTER_ALPHA if self.highlighter else "")


class LapiceroWindow(QMainWindow):
    def __init__(self, library_path=None, autosave_delay_ms=AUTOSAVE_DELAY_MS, ai_bridge=False):
        super().__init__()
        self._unsaved = False
        self._autosave_delay = autosave_delay_ms
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.timeout.connect(self._autosave_now)
        path = Path(library_path) if library_path is not None else default_library_path()
        self._save_error_shown = False
        try:
            self.library = Library.load(path)
        except FileNotFoundError:
            self.library = Library(path=path)
        except (OSError, ValueError) as exc:
            # A damaged or unreadable target remains unowned. Library.save will
            # refuse to overwrite it, even if the user keeps working in memory.
            self.library = Library(path=path)
            self._report_error("Library open failed", exc)

        self.setWindowTitle("Lapicero")
        self.resize(1280, 800)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        self.sidebar = QWidget()
        sidebar = self._sidebar_layout = QVBoxLayout(self.sidebar)
        layout.addWidget(self.sidebar)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Subjects / Sections / Pages")
        self.tree.setMinimumWidth(235)
        self.tree.currentItemChanged.connect(self._selection_changed)
        sidebar.addWidget(self.tree)
        for attribute, label, handler in (("new_subject_button", "New subject", self.new_subject),
                                          ("new_section_button", "New section", self.new_section),
                                          ("new_page_button", "New page", self.new_page),
                                          ("rename_button", "Rename selected", self.rename_selected),
                                          ("import_button", "Import old note…", self.import_note)):
            button = QPushButton(label)
            button.clicked.connect(handler)
            sidebar.addWidget(button)
            setattr(self, attribute, button)

        self.view = CanvasView()
        self.canvas = self.view.canvas
        self.canvas.image_store = self.library
        self.canvas.installEventFilter(self)
        self.canvas.changed.connect(self._changed)
        layout.addWidget(self.view, 1)
        self.placeholder = QLabel("Select a page, or create Subject → Section → Page in the sidebar.")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.placeholder, 1)
        self.ask_panel = AskPanel()
        self.ask_panel.hide()
        layout.addWidget(self.ask_panel)
        self.ai = AiOperations(self)
        self._asks = {}  # ask id -> running ClaudeAsk
        self.canvas.region_requested.connect(self.ask_about)
        self._page_id = None
        self.toolbar_size = self._load_ui_settings().get("toolbar_size", "medium")
        if self.toolbar_size not in TOOLBAR_SIZES:
            self.toolbar_size = "medium"
        self._toolbar()
        self._settings()
        for widget in (self.view, self.placeholder):
            widget.installEventFilter(self)
        self._shortcuts()
        self._refresh()
        self._selection_changed()
        self.bridge = None
        self.bridge_error = None
        if ai_bridge:
            self.start_bridge()

    def _tool_button(self, toolbar, icon, tip, checkable=False):
        button = QToolButton()
        button.setIcon(icon)
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.setCheckable(checkable)
        button.setAutoRaise(True)
        side = TOOLBAR_SIZES[self.toolbar_size]
        button.setIconSize(QSize(side, side))
        toolbar.addWidget(button)
        return button

    def _toolbar(self):
        bar = FloatingToolbar(self.centralWidget())
        bar.setToolTip(SHORTCUTS)
        self.toolbar = bar
        self._fade = QGraphicsOpacityEffect(bar)
        self._fade.setEnabled(False)
        bar.setGraphicsEffect(self._fade)
        self.canvas.gesture_changed.connect(self._drawing)
        self.sidebar_button = self._tool_button(bar, icons.sidebar_icon(), "Show/hide sidebar", True)
        self.sidebar_button.setChecked(True)
        self.sidebar_button.toggled.connect(self.sidebar.setVisible)
        bar.addSeparator()
        self.undo_button = self._tool_button(bar, icons.undo_icon(), "Undo (Ctrl+Z)")
        self.redo_button = self._tool_button(bar, icons.redo_icon(), "Redo (Ctrl+Y)")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        bar.addSeparator()
        tools = QButtonGroup(self)
        tools.setExclusive(True)
        self.select_button = self._tool_button(
            bar, icons.lasso_icon(), "Lasso select (L): drag to move, Delete to remove", True)
        self.eraser_button = self._tool_button(bar, icons.eraser_icon(), "Eraser (E)", True)
        self.select_button.clicked.connect(lambda: self.canvas.set_mode("select"))
        self.eraser_button.clicked.connect(lambda: self.canvas.set_mode("eraser"))
        tools.addButton(self.select_button)
        tools.addButton(self.eraser_button)
        self.presets = [PenPreset(*preset) for preset in PEN_PRESETS]
        self.pen_buttons = []
        for preset in self.presets:
            button = self._tool_button(bar, icons.pen_icon(preset.color, preset.highlighter),
                                       preset.name + ": click again for color and width", True)
            button.clicked.connect(lambda checked=False, p=preset: self._pen_clicked(p))
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda _=None, p=preset: (self._use_preset(p), self._show_pen_panel(p)))
            tools.addButton(button)
            self.pen_buttons.append(button)
        self.pen_button = self.pen_buttons[0]
        self.shape_button = self._tool_button(bar, icons.shape_icon("rectangle"), "Shapes (S): drag to draw", True)
        self.shape_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        menu = QMenu(self.shape_button)
        self.shape_actions = {}
        for kind in InkCanvas.SHAPES:
            action = menu.addAction(icons.shape_icon(kind), SHAPE_NAMES[kind])
            action.triggered.connect(lambda checked=False, k=kind: self.choose_shape(k))
            self.shape_actions[kind] = action
        self.shape_button.setMenu(menu)
        self.shape_button.clicked.connect(lambda: self.canvas.set_mode("shape"))
        tools.addButton(self.shape_button)
        self.ask_button = self._tool_button(
            bar, icons.ask_icon(), "Ask Claude (A): drag a box around something, then type a question", True)
        self.ask_button.clicked.connect(lambda: self.canvas.set_mode("ask"))
        tools.addButton(self.ask_button)
        bar.addSeparator()
        self.fullscreen_button = self._tool_button(bar, icons.fullscreen_icon(), "Fullscreen (F11, Esc to leave)", True)
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        bar.addSeparator()
        # Small save indicator; details (such as a save error) are in its tooltip.
        self.status = QLabel()
        self.status.setStyleSheet("color: #6b6b6b; padding: 0 4px;")
        bar.addWidget(self.status)
        self._pen_panel()
        self._use_preset(self.presets[0])

    def _settings(self):
        """Rarely changed options live in the sidebar, keeping the toolbar for drawing."""
        self.settings_box = QGroupBox("Settings")
        form = QFormLayout(self.settings_box)
        self.paper_combo = QComboBox()
        self.paper_combo.addItem(icons.paper_icon(True), "Grid", "grid")
        self.paper_combo.addItem(icons.paper_icon(False), "Plain", "plain")
        self.paper_combo.setToolTip("Paper of the selected page")
        self.paper_combo.currentIndexChanged.connect(
            lambda: self._paper_changed(self.paper_combo.currentData()))
        form.addRow("Page paper:", self.paper_combo)
        self.size_combo = QComboBox()
        for name in TOOLBAR_SIZES:
            self.size_combo.addItem(name.capitalize(), name)
        self.size_combo.setCurrentIndex(self.size_combo.findData(self.toolbar_size))
        self.size_combo.setToolTip("Size of the drawing toolbar buttons")
        self.size_combo.currentIndexChanged.connect(
            lambda: self.set_toolbar_size(self.size_combo.currentData()))
        form.addRow("Toolbar size:", self.size_combo)
        settings = self._load_ui_settings()
        self.ask_model_combo = QComboBox()
        self.ask_effort_combo = QComboBox()
        for combo, choices, key, tip in (
                (self.ask_model_combo, ASK_MODELS, "ask_model", "Model that answers Ask Claude questions"),
                (self.ask_effort_combo, ASK_EFFORTS, "ask_effort",
                 "How hard Claude thinks: lower answers faster, higher is more thorough")):
            for label, value in choices:
                combo.addItem(label, value)
            combo.setCurrentIndex(max(0, combo.findData(settings.get(key))))
            combo.setToolTip(tip)
            combo.currentIndexChanged.connect(self._save_ui_settings)
        form.addRow("Claude model:", self.ask_model_combo)
        form.addRow("Claude effort:", self.ask_effort_combo)
        self._sidebar_layout.addWidget(self.settings_box)

    def _pen_panel(self):
        """Popup with color swatches and width for the active pen preset."""
        self.pen_panel = QFrame(self, Qt.WindowType.Popup)
        self.pen_panel.setFrameShape(QFrame.Shape.StyledPanel)
        grid = QGridLayout(self.pen_panel)
        self.color_buttons = {}
        for index, (name, color) in enumerate(PALETTE):
            button = QToolButton()
            button.setIcon(icons.swatch_icon(color))
            button.setToolTip(name)
            button.setAccessibleName(name)
            button.setAutoRaise(True)
            button.clicked.connect(lambda checked=False, c=color: self.set_preset_color(c))
            grid.addWidget(button, index // 5, index % 5)
            self.color_buttons[color] = button
        grid.addWidget(QLabel(f"Width (1–{MAX_WIDTH}):"), 2, 0, 1, 2)
        self.width_slider = QSlider(Qt.Orientation.Horizontal)
        self.width_slider.setRange(1, MAX_WIDTH)
        self.width_slider.valueChanged.connect(self._width_changed)
        grid.addWidget(self.width_slider, 2, 2, 1, 3)

    def _pen_clicked(self, preset):
        if self.active_preset is preset and self.canvas.mode == "pen":
            self._show_pen_panel(preset)
        self._use_preset(preset)

    def _show_pen_panel(self, preset):
        button = self.pen_buttons[self.presets.index(preset)]
        self.pen_panel.adjustSize()
        self.pen_panel.move(button.mapToGlobal(QPoint(0, button.height())))
        self.pen_panel.show()

    def _use_preset(self, preset):
        self.active_preset = preset
        self.pen_buttons[self.presets.index(preset)].setChecked(True)
        self.canvas.set_mode("pen")
        self.canvas.pressure_enabled = not preset.highlighter
        self.canvas.set_pen_color(preset.ink)
        self.width_slider.setValue(preset.width)
        self.canvas.set_pen_width(preset.width)

    def set_preset_color(self, color):
        preset = self.active_preset
        preset.color = color
        self.pen_buttons[self.presets.index(preset)].setIcon(icons.pen_icon(color, preset.highlighter))
        self.canvas.set_pen_color(preset.ink)

    def _width_changed(self, value):
        self.active_preset.width = value
        self.canvas.set_pen_width(value)

    def choose_shape(self, kind):
        self.canvas.set_shape(kind)
        self.shape_button.setIcon(icons.shape_icon(kind))
        self.shape_button.setChecked(True)
        self.canvas.set_mode("shape")

    def _paper_changed(self, paper):
        self.canvas.set_paper(paper)
        if self._page_id and self.library.page(self._page_id).paper != paper:
            self.library.set_paper(self._page_id, paper)
            self._changed()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.sidebar.setVisible(self.sidebar_button.isChecked())
        else:
            self.sidebar.hide()
            self.showFullScreen()
        self.fullscreen_button.setChecked(self.isFullScreen())

    def _escape(self):
        if self.canvas.selection:
            self.canvas.clear_selection()
        elif self.isFullScreen():
            self.toggle_fullscreen()

    def _shortcuts(self):
        for text, callback in (("Ctrl+N", self.new_page), ("Ctrl+O", self.import_note),
                               ("Ctrl+S", self.save), ("Ctrl+Z", self.undo),
                               ("Ctrl+Y", self.redo), ("F11", self.toggle_fullscreen),
                               ("Escape", self._escape), ("Ctrl+0", self.canvas.reset_zoom),
                               ("Ctrl+C", self.copy), ("Ctrl+V", self.paste)):
            action = QAction(self)
            action.setShortcut(QKeySequence(text))
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(callback)
            self.addAction(action)

    def _load_ui_settings(self):
        try:
            data = json.loads((self.library.path.parent / UI_SETTINGS).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def set_toolbar_size(self, name):
        if name not in TOOLBAR_SIZES:
            raise ValueError(f"Toolbar size must be one of {tuple(TOOLBAR_SIZES)}")
        self.toolbar_size = name
        side = TOOLBAR_SIZES[self.toolbar_size]
        for button in self.toolbar.findChildren(QToolButton):
            button.setIconSize(QSize(side, side))
        self._place_toolbar()
        self._save_ui_settings()

    def _save_ui_settings(self):
        data = {"toolbar_size": self.toolbar_size}
        if hasattr(self, "ask_model_combo"):
            data["ask_model"] = self.ask_model_combo.currentData()
            data["ask_effort"] = self.ask_effort_combo.currentData()
        try:
            # A preference is not worth an error dialog; keep it for this session.
            target = self.library.path.parent / UI_SETTINGS
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    def _drawing(self, active):
        self._fade.setOpacity(DRAWING_OPACITY)
        self._fade.setEnabled(active)

    def toolbar_opacity(self):
        return self._fade.opacity() if self._fade.isEnabled() else 1.0

    def _place_toolbar(self):
        """Center the floating toolbar over the page area, just below its top edge."""
        area = (self.view if self.view.isVisible() else self.placeholder).geometry()
        self.toolbar.adjustSize()
        self.toolbar.move(area.center().x() - self.toolbar.width() // 2 + 1, area.top() + 6)
        self.toolbar.raise_()

    def eventFilter(self, watched, event):
        if watched in (self.view, self.placeholder) and event.type() in (
                QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show):
            self._place_toolbar()
        if watched is self.canvas and event.type() == QEvent.Type.KeyPress and self.canvas.isEnabled():
            key, modifiers = event.key(), event.modifiers()
            if modifiers == Qt.KeyboardModifier.NoModifier:
                if key == Qt.Key.Key_P:
                    self._use_preset(self.active_preset)
                    return True
                tool = {Qt.Key.Key_E: self.eraser_button, Qt.Key.Key_L: self.select_button,
                        Qt.Key.Key_S: self.shape_button, Qt.Key.Key_A: self.ask_button}.get(key)
                if tool is not None:
                    tool.click()
                    return True
            if modifiers == Qt.KeyboardModifier.ControlModifier and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self.width_slider.setValue(self.width_slider.value() + (1 if key == Qt.Key.Key_Up else -1))
                return True
        return super().eventFilter(watched, event)

    def _selected(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def _section_id(self):
        item = self.tree.currentItem()
        while item is not None:
            kind, identifier = item.data(0, Qt.ItemDataRole.UserRole)
            if kind == "section":
                return identifier
            item = item.parent()
        return None

    def _refresh(self, select=None):
        current = select or self._selected()
        self.tree.blockSignals(True)
        self.tree.clear()
        match = None
        for subject in self.library.subjects:
            parent = QTreeWidgetItem(self.tree, [subject.name])
            parent.setData(0, Qt.ItemDataRole.UserRole, ("subject", subject.id))
            if current == ("subject", subject.id):
                match = parent
            for section in subject.sections:
                child = QTreeWidgetItem(parent, [section.name])
                child.setData(0, Qt.ItemDataRole.UserRole, ("section", section.id))
                if current == ("section", section.id):
                    match = child
                for page in section.pages:
                    leaf = QTreeWidgetItem(child, [page.name])
                    leaf.setData(0, Qt.ItemDataRole.UserRole, ("page", page.id))
                    if current == ("page", page.id):
                        match = leaf
        self.tree.expandAll()
        self.tree.setCurrentItem(match)
        self.tree.blockSignals(False)
        self._selection_changed()

    def _selection_changed(self, *_):
        selected = self._selected()
        page_id = selected[1] if selected and selected[0] == "page" else None
        if page_id != self._page_id:
            self._page_id = page_id
            self.canvas.set_note(self.library.page(page_id).note if page_id else Note())
            if page_id:
                self.paper_combo.setCurrentIndex(self.paper_combo.findData(self.library.page(page_id).paper))
        self.canvas.setEnabled(page_id is not None)
        self.view.setVisible(page_id is not None)
        self.placeholder.setVisible(page_id is None)
        self.paper_combo.setEnabled(page_id is not None)
        self.new_section_button.setEnabled(bool(selected))
        self.new_page_button.setEnabled(self._section_id() is not None)
        self.import_button.setEnabled(self._section_id() is not None)
        self.rename_button.setEnabled(bool(selected))
        self.undo_button.setEnabled(page_id is not None)
        self.redo_button.setEnabled(page_id is not None)
        self._title()

    def _title(self):
        # A flag, not Library.dirty: comparing the whole library on every stroke is slow.
        self.setWindowTitle(f"{'*' if self._unsaved else ''}Lapicero — {self.library.path}")

    def _report_error(self, title, exc):
        # Report once per failing save streak; status remains visible until retry succeeds.
        if not self._save_error_shown:
            self._save_error_shown = True
            QMessageBox.warning(self, title, str(exc))
        if hasattr(self, "status"):
            self._set_status("Not saved", f"{title}: {exc}. Work remains in memory; retry Save (Ctrl+S).",
                             "#b73535")

    def save(self):
        self._autosave.stop()
        try:
            self.library.path.parent.mkdir(parents=True, exist_ok=True)
            self.library.save()
        except (OSError, ValueError) as exc:
            self._report_error("Library save failed", exc)
            self._title()
            return False
        self._save_error_shown = False
        self._unsaved = False
        self._set_status("Saved", f"All changes saved to {self.library.path}")
        self._title()
        return True

    def _set_status(self, text, detail, color="#6b6b6b"):
        self.status.setText(text)
        self.status.setToolTip(detail)
        self.status.setStyleSheet(f"color: {color}; padding: 0 4px;")
        self._place_toolbar()

    def _changed(self):
        self._unsaved = True
        if self._autosave_delay <= 0:
            self.save()
            return
        self._set_status("Saving…", "Changes are saved when you pause writing")
        self._title()
        self._autosave.start(self._autosave_delay)

    def _autosave_now(self):
        if self.canvas.gesture_active:
            self._autosave.start(self._autosave_delay)  # Never stall a stroke in progress.
        else:
            self.save()

    def _name(self, title, initial=""):
        value, accepted = QInputDialog.getText(self, title, "Name:", text=initial)
        return value.strip() if accepted and value.strip() else None

    def new_subject(self):
        name = self._name("New subject")
        if name:
            subject = self.library.create_subject(name)
            self._refresh(("subject", subject.id))
            self.save()

    def new_section(self):
        selected = self._selected()
        if not selected:
            return
        subject_id = selected[1] if selected[0] == "subject" else None
        if subject_id is None:
            item = self.tree.currentItem()
            while item.parent() is not None:
                item = item.parent()
            subject_id = item.data(0, Qt.ItemDataRole.UserRole)[1]
        name = self._name("New section")
        if name:
            section = self.library.create_section(subject_id, name)
            self._refresh(("section", section.id))
            self.save()

    def new_page(self):
        section_id = self._section_id()
        if section_id is None:
            return
        name = self._name("New page")
        if name:
            page = self.library.create_page(section_id, name)
            self._refresh(("page", page.id))
            self.save()

    def rename_selected(self):
        selected = self._selected()
        if selected is None:
            return
        kind, identifier = selected
        target = getattr(self.library, kind)(identifier)
        name = self._name("Rename " + kind, target.name)
        if name and name != target.name:
            getattr(self.library, "rename_" + kind)(identifier, name)
            self._refresh(selected)
            self.save()

    def import_note(self):
        section_id = self._section_id()
        if section_id is None:
            return
        source, _ = QFileDialog.getOpenFileName(self, "Import standalone note", "", "JSON notes (*.json)")
        if not source:
            return
        try:
            page = self.library.import_legacy_note(section_id, source)
        except (OSError, NoteFormatError, ValueError) as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        self._refresh(("page", page.id))
        self.save()

    def copy(self):
        if self._page_id:
            self.canvas.copy_selection()

    def paste(self):
        if self._page_id and self.canvas.paste():
            self.select_button.setChecked(True)

    def undo(self):
        if self._page_id:
            self.canvas.undo()

    def redo(self):
        if self._page_id:
            self.canvas.redo()

    # AI bridge and Ask Claude ------------------------------------------------

    @property
    def current_page_id(self):
        return self._page_id

    def note_changed_externally(self):
        """An AI tool added ink to some page: autosave it like the user's strokes."""
        self._changed()

    def start_bridge(self):
        """Let local AI tools (the Lapicero MCP server) reach this window."""
        if self.bridge is not None:
            return True
        bridge = BridgeServer(self.ai.handle, bridge_info_path(self.library.path), self)
        try:
            bridge.start()
        except OSError as exc:
            self.bridge_error = str(exc)
            self.ask_button.setToolTip(f"AI bridge failed to start: {exc}")
            return False
        self.bridge = bridge
        return True

    def stop_bridge(self):
        for ask in list(self._asks.values()):
            ask.cancel()
        if self.bridge is not None:
            self.bridge.stop()
            self.bridge = None

    def ask_about(self, region, question=None):
        """Ask Claude about a document region of the open page; returns the ask id or None."""
        if self._page_id is None:
            return None
        if question is None:
            question, ok = QInputDialog.getMultiLineText(
                self, "Ask Claude", "Question about the selected area:")
            if not ok:
                return None
        question = question.strip()
        if not question:
            return None
        page = self.library.page(self._page_id)
        ask_id = self.ai.create_ask(page, region, question)
        self.ask_panel.add_question(ask_id, page.name, question)
        if not self.start_bridge():
            self.ask_panel.set_answer(ask_id, f"The AI bridge is not running: {self.bridge_error}", True)
            return ask_id
        config_path = self.bridge.info_path.parent / MCP_CONFIG_FILE
        try:
            config_path.write_text(json.dumps(mcp_config(self.bridge.info_path)), encoding="utf-8")
        except OSError as exc:
            self.ask_panel.set_answer(ask_id, f"Could not write {config_path}: {exc}", True)
            return ask_id
        ask = self.ai.asks[ask_id]
        message = build_message(build_prompt(ask_id, page.name, question, ask["region"]), ask["png"])
        run = ClaudeAsk(ask_id, message, config_path, config_path.parent, program=self.claude_program,
                        model=self.ask_model_combo.currentData(), effort=self.ask_effort_combo.currentData(),
                        parent=self)
        run.finished.connect(self._answered)
        self._asks[ask_id] = run
        run.start()
        return ask_id

    claude_program = None  # Tests point this at a fake Claude Code executable.

    def _answered(self, ask_id, text, is_error):
        run = self._asks.pop(ask_id, None)
        if run is not None:
            run.deleteLater()
        self.ask_panel.set_answer(ask_id, text, is_error)

    def closeEvent(self, event):
        # Stop the bridge first, then run AI writes already queued, so the save below keeps them.
        bridge_was_running = self.bridge is not None
        if bridge_was_running:
            self.bridge.stop()
            self.bridge = None
        QApplication.sendPostedEvents()
        self.canvas.finalize_current_gesture()
        if self._autosave.isActive():
            self.save()  # Flush the pending autosave; a failure falls through to the prompt.
        if not self.library.dirty:
            self.stop_bridge()  # Also ends running questions.
            event.accept()
            return
        choice = QMessageBox.question(self, "Unsaved library",
                                      "Changes are still in memory. Save before closing?",
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if choice == QMessageBox.StandardButton.Discard or (choice == QMessageBox.StandardButton.Save and self.save()):
            self.stop_bridge()
            event.accept()
        else:
            if bridge_was_running:
                self.start_bridge()
            event.ignore()
