"""Qt library window for local, page-based handwritten notes."""

import html
import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QDateTime, QEvent, QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPainterPath, QRegion
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QFrame,
                               QGraphicsOpacityEffect, QGridLayout, QHBoxLayout,
                               QApplication, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QSlider, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import i18n, icons, theme
from .ai_ops import AiOperations
from .ask import (ASK_EFFORTS, ASK_MODELS, MCP_CONFIG_FILE, AskPanel, AskPrompt, ClaudeAsk,
                  build_message, build_prompt, build_text_prompt, mcp_config)
from .bridge import BridgeServer
from .chats import CHATS_DIR, ChatStore, chat_title, new_chat as new_chat_record
from .i18n import tr
from .library import Library
from .model import Note, NoteFormatError
from .paths import bridge_info_path, default_library_path
from .qt_canvas import CanvasView, InkCanvas
from .widgets import SegmentedControl, SettingsDialog, link_choices


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
DIAGRAM_NAMES = {"axes_xy": "XY axes", "axes_xyz": "XYZ axes (3D)", "integral": "Integral"}
MAX_WIDTH = 40
TOOLBAR_SIZES = {"small": 26, "medium": 34, "large": 44}  # Icon pixels, in cycle order.
DRAWING_OPACITY = .25  # Toolbar fades while the pen is down, so ink below stays visible.
UI_SETTINGS = "ui.json"  # Window preferences beside the library file.
# Save once the pen has rested this long: writing a whole library after every
# stroke froze the app between letters. Close and Ctrl+S still save at once.
AUTOSAVE_DELAY_MS = 1200
# Every item the toolbar can show: (id, label, group). Separators fall between groups.
TOOLBAR_ITEMS = (("sidebar", "Show/hide sidebar", "view"),
                 ("undo", "Undo", "history"), ("redo", "Redo", "history"),
                 ("lasso", "Lasso select", "tools"), ("eraser", "Eraser", "tools"),
                 *((name.lower().replace(" ", "_"), name, "tools") for name, *_ in PEN_PRESETS),
                 ("shapes", "Shapes", "tools"), ("engineering", "Engineering elements", "insert"),
                 ("ask", "Ask Claude", "ai"),
                 ("new_page", "New page", "extras"), ("paste", "Paste", "extras"),
                 ("fullscreen", "Fullscreen", "extras"), ("settings", "Settings", "extras"))
TOOLBAR_GROUPS = {item: group for item, _, group in TOOLBAR_ITEMS}
DEFAULT_TOOLBAR = tuple(item for item, _, group in TOOLBAR_ITEMS if group != "extras")
SHORTCUTS = ("P pen · E eraser · L lasso · S shapes · A ask Claude · Ctrl+C/V copy/paste · Ctrl+↑/↓ width · "
             "wheel scroll · Shift+wheel sideways · Ctrl+wheel zoom · F11 fullscreen")


class FloatingToolbar(QFrame):
    """Floating card of tools over the page, with its own soft shadow.

    The card and shadow are painted here rather than with a QGraphicsEffect, so the
    toolbar keeps its single effect slot for fading while the pen is down.
    """

    SHADOW = (8, 2, 8, 12)  # Left, top, right and bottom room for the shadow.
    RADIUS = 14

    def __init__(self, parent, name="floatingToolbar"):
        super().__init__(parent)
        self.setObjectName(name)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._layout = QHBoxLayout(self)
        left, top, right, bottom = self.SHADOW
        self._layout.setContentsMargins(left + 5, top + 5, right + 5, bottom + 5)
        self._layout.setSpacing(2)
        self._separators = []

    def card(self):
        left, top, right, bottom = self.SHADOW
        return QRectF(self.rect()).adjusted(left + .5, top + .5, -right - .5, -bottom - .5)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = self.card()
        painter.setPen(Qt.PenStyle.NoPen)
        # A soft, slightly lowered shadow: stacked translucent rounded rects.
        for spread, alpha in ((7, 5), (5, 7), (3, 10), (1.5, 14)):
            painter.setBrush(QColor(28, 28, 30, alpha))
            painter.drawRoundedRect(card.adjusted(-spread, -spread + 3, spread, spread + 3),
                                    self.RADIUS + spread, self.RADIUS + spread)
        painter.setBrush(QColor(theme.SURFACE))
        painter.setPen(QColor(theme.BORDER))
        painter.drawRoundedRect(card, self.RADIUS, self.RADIUS)

    def addWidget(self, widget):
        self._layout.addWidget(widget)

    def widgets(self):
        """Widgets in the strip, left to right, separators excluded."""
        items = (self._layout.itemAt(i).widget() for i in range(self._layout.count()))
        return [widget for widget in items if widget is not None and widget not in self._separators]

    def set_widgets(self, entries):
        """Lay out entries left to right; None draws a separator."""
        while self._layout.count():
            self._layout.takeAt(0)
        for line in self._separators:
            line.deleteLater()
        self._separators = []
        for widget in entries:
            if widget is None:
                line = QFrame(self)
                line.setObjectName("separator")
                line.setFixedSize(1, 20)
                self._separators.append(line)
                self._layout.addSpacing(5)
                self._layout.addWidget(line, 0, Qt.AlignmentFlag.AlignVCenter)
                self._layout.addSpacing(5)
            else:
                self._layout.addWidget(widget)


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
            self._report_error(tr("Library open failed"), exc)

        # Before any widget: their strings are translated as they are built.
        self.language = i18n.set_language(self._load_ui_settings().get("language", i18n.DEFAULT_LANGUAGE))
        self.setWindowTitle("Lapicero")
        self.resize(1280, 800)
        theme.apply(self)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._actions()
        self._sidebar()
        layout.addWidget(self.sidebar)

        content = QWidget()
        content.setObjectName("content")
        column = self._column = QVBoxLayout(content)
        column.setContentsMargins(12, 8, 12, 12)
        column.setSpacing(8)
        layout.addWidget(content, 1)
        self.view = CanvasView()
        self.canvas = self.view.canvas
        self.canvas.image_store = self.library
        self.canvas.installEventFilter(self)
        self.canvas.changed.connect(self._changed)
        column.addWidget(self._header())
        row = QHBoxLayout()
        row.setSpacing(12)
        column.addLayout(row, 1)
        # The page surface: a rounded white card holding the canvas or the placeholder.
        self.page_frame = QFrame()
        self.page_frame.setObjectName("page")
        page = QVBoxLayout(self.page_frame)
        page.setContentsMargins(1, 1, 1, 1)
        page.setSpacing(0)
        page.addWidget(self.view, 1)
        self.placeholder = QLabel(tr("Select a page, or create a subject, section and page with +."))
        self.placeholder.setObjectName("placeholder")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page.addWidget(self.placeholder, 1)
        row.addWidget(self.page_frame, 1)
        self.ask_panel = AskPanel()
        self.ask_panel.hide()
        self.ask_panel.follow_up.connect(self.ask_text)
        self.ask_panel.new_chat.connect(self.new_chat)
        self.ask_panel.history_requested.connect(self._show_history)
        row.addWidget(self.ask_panel)
        self.ask_prompt = AskPrompt(root)
        self.ask_prompt.submitted.connect(self._prompt_submitted)
        self.ask_prompt.cancelled.connect(self._close_ask_prompt)
        self._prompt_region = None
        self.canvas.view_changed.connect(self._place_ask_prompt)
        self.ai = AiOperations(self)
        self._asks = {}  # ask id -> running ClaudeAsk
        self._ask_records = {}  # ask id -> chat it was asked in, until it is answered
        self._session_id = None  # Claude Code session of the current conversation, once known
        self._chat_record = None  # Saved chat shown in the panel; created by its first question
        self.chat_store = ChatStore(self.library.path.parent / CHATS_DIR if self.library.path else None)
        self.canvas.region_requested.connect(self.ask_about)
        self._page_id = None
        self.toolbar_size = self._load_ui_settings().get("toolbar_size", "medium")
        if self.toolbar_size not in TOOLBAR_SIZES:
            self.toolbar_size = "medium"
        self._toolbar()
        self._zoom_pill()
        self._settings()
        for widget in (self.view, self.placeholder, self.page_frame):
            widget.installEventFilter(self)
        self._shortcuts()
        self._refresh()
        self._selection_changed()
        self.bridge = None
        self.bridge_error = None
        if ai_bridge:
            self.start_bridge()

    def _actions(self):
        """Library commands, shared by the + menu and the tree's context menu."""
        def action(text, handler):
            command = QAction(tr(text), self)
            command.triggered.connect(lambda checked=False: handler())
            return command
        self.new_subject_action = action("New subject", self.new_subject)
        self.new_section_action = action("New section", self.new_section)
        self.new_page_action = action("New page", self.new_page)
        self.rename_action = action("Rename…", self.rename_selected)
        self.delete_section_action = action("Delete section…", self.delete_selected)
        self.import_action = action("Import old note…", self.import_note)

    def _sidebar(self):
        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(272)
        sidebar = self._sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar.setContentsMargins(12, 14, 12, 12)
        sidebar.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        logo = QLabel()
        logo.setObjectName("logo")
        logo.setFixedSize(28, 28)
        logo_pixmap = icons.app_logo_pixmap(28 * 2)  # 2x so it stays crisp on high-DPI screens.
        logo_pixmap.setDevicePixelRatio(2)
        logo.setPixmap(logo_pixmap)
        head.addWidget(logo)
        title = QLabel("Lapicero")
        title.setObjectName("appTitle")
        head.addWidget(title, 1)
        self.new_button = QToolButton()
        self.new_button.setObjectName("newButton")
        self.new_button.setText("+")
        self.new_button.setToolTip(tr("New subject, section or page"))
        self.new_button.setAccessibleName(tr("New subject, section or page"))
        self.new_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.new_button)
        menu.addActions([self.new_subject_action, self.new_section_action, self.new_page_action])
        self.new_button.setMenu(menu)
        head.addWidget(self.new_button)
        sidebar.addLayout(head)

        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText(tr("Search pages"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter_tree)
        sidebar.addWidget(self.search)

        label = QLabel(tr("SUBJECTS"))
        label.setObjectName("sectionLabel")
        sidebar.addWidget(label)
        self.tree = QTreeWidget()
        self.tree.setObjectName("tree")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.currentItemChanged.connect(self._selection_changed)
        sidebar.addWidget(self.tree, 1)

        footer = QFrame()
        footer.setObjectName("divider")
        footer.setFixedHeight(1)
        sidebar.addWidget(footer)
        for attribute, text, handler in (("import_button", "Import note…", self.import_note),
                                         ("settings_button", "Settings", self.show_settings)):
            button = QPushButton(tr(text))
            button.setObjectName("footerButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, h=handler: h())
            sidebar.addWidget(button)
            setattr(self, attribute, button)

    def _tree_menu(self, position):
        item = self.tree.itemAt(position)
        if item is not None:
            self.tree.setCurrentItem(item)
        menu = QMenu(self)
        menu.addActions([self.new_subject_action, self.new_section_action, self.new_page_action])
        menu.addSeparator()
        menu.addActions([self.rename_action, self.delete_section_action])
        menu.addSeparator()
        menu.addAction(self.import_action)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _filter_tree(self, text):
        """Show items whose name contains the text, with their ancestors and descendants' matches."""
        needle = text.strip().casefold()

        def visit(item):
            children = [visit(item.child(i)) for i in range(item.childCount())]
            shown = not needle or needle in item.text(0).casefold() or any(children)
            item.setHidden(not shown)
            return shown
        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))

    def _header(self):
        header = self.header = QWidget()
        bar = QHBoxLayout(header)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(10)
        self.breadcrumb = QLabel()
        self.breadcrumb.setObjectName("breadcrumb")
        self.breadcrumb.setTextFormat(Qt.TextFormat.RichText)
        bar.addWidget(self.breadcrumb, 1)
        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("statusDot")
        self.status_dot.hide()  # Shown with the first save state.
        bar.addWidget(self.status_dot)
        # Small save indicator; details (such as a save error) are in its tooltip.
        self.status = QLabel()
        self.status.setObjectName("status")
        bar.addWidget(self.status)
        bar.addSpacing(4)
        self.paper_combo = SegmentedControl()
        self.paper_combo.addItem(icons.paper_icon(True), tr("Grid"), "grid")
        self.paper_combo.addItem(icons.paper_icon(False), tr("Plain"), "plain")
        self.paper_combo.setToolTip(tr("Paper of the selected page"))
        self.paper_combo.currentIndexChanged.connect(
            lambda: self._paper_changed(self.paper_combo.currentData()))
        bar.addWidget(self.paper_combo)
        self.fullscreen_button = QToolButton()
        self.fullscreen_button.setObjectName("headerButton")
        self.fullscreen_button.setIcon(icons.fullscreen_icon())
        self.fullscreen_button.setIconSize(QSize(22, 22))
        self.fullscreen_button.setToolTip(tr("Fullscreen (F11, Esc to leave)"))
        self.fullscreen_button.setAccessibleName(tr("Fullscreen"))
        self.fullscreen_button.setCheckable(True)
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        bar.addWidget(self.fullscreen_button)
        return header

    def _zoom_pill(self):
        pill = self.zoom_pill = FloatingToolbar(self.centralWidget(), "zoomPill")
        canvas = self.canvas
        for text, tip, handler in (("−", "Zoom out", lambda: canvas.set_zoom(canvas.zoom / 1.25)),
                                   ("100%", "Reset zoom (Ctrl+0)", canvas.reset_zoom),
                                   ("+", "Zoom in", lambda: canvas.set_zoom(canvas.zoom * 1.25))):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tr(tip))
            button.setAccessibleName(tr(tip))
            button.clicked.connect(lambda checked=False, h=handler: h())
            pill.addWidget(button)
            if text == "100%":
                self.zoom_label = button
        canvas.view_changed.connect(self._zoom_changed)

    def _zoom_changed(self):
        text = f"{round(self.canvas.zoom * 100)}%"
        if self.zoom_label.text() != text:
            self.zoom_label.setText(text)
            self._place_toolbar()

    def _tool_button(self, toolbar, icon, tip, checkable=False):
        """A toolbar button; set_toolbar_items decides whether and where it shows."""
        button = QToolButton(toolbar)
        button.hide()
        button.setIcon(icon)
        button.setToolTip(tr(tip))
        button.setAccessibleName(tr(tip))
        button.setCheckable(checkable)
        button.setAutoRaise(True)
        side = TOOLBAR_SIZES[self.toolbar_size]
        button.setIconSize(QSize(side, side))
        return button

    def _toolbar(self):
        bar = FloatingToolbar(self.centralWidget())
        bar.setToolTip(tr(SHORTCUTS))
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        bar.customContextMenuRequested.connect(
            lambda position: self.toolbar_menu().exec(bar.mapToGlobal(position)))
        self.toolbar = bar
        self._fade = QGraphicsOpacityEffect(bar)
        self._fade.setEnabled(False)
        bar.setGraphicsEffect(self._fade)
        self.canvas.gesture_changed.connect(self._drawing)
        self.sidebar_button = self._tool_button(bar, icons.sidebar_icon(), "Show/hide sidebar", True)
        self.sidebar_button.setChecked(True)
        self.sidebar_button.toggled.connect(self.sidebar.setVisible)
        self.undo_button = self._tool_button(bar, icons.undo_icon(), "Undo (Ctrl+Z)")
        self.redo_button = self._tool_button(bar, icons.redo_icon(), "Redo (Ctrl+Y)")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
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
                                       tr("{name}: click again for color and width", name=tr(preset.name)), True)
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
            action = menu.addAction(icons.shape_icon(kind), tr(SHAPE_NAMES[kind]))
            action.triggered.connect(lambda checked=False, k=kind: self.choose_shape(k))
            self.shape_actions[kind] = action
        self.shape_button.setMenu(menu)
        self.shape_kind = "rectangle"
        self.shape_button.clicked.connect(lambda: self.choose_shape(self.shape_kind))
        tools.addButton(self.shape_button)
        # Engineering elements: drag a box to place the diagram, like a shape.
        self.diagram_kind = "axes_xy"
        self.diagram_button = self._tool_button(
            bar, icons.diagram_icon(self.diagram_kind), "Engineering elements: drag to place axes or symbols", True)
        self.diagram_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        menu = QMenu(self.diagram_button)
        self.diagram_actions = {}
        for kind in InkCanvas.DIAGRAMS:
            action = menu.addAction(icons.diagram_icon(kind), tr(DIAGRAM_NAMES[kind]))
            action.triggered.connect(lambda checked=False, k=kind: self.choose_diagram(k))
            self.diagram_actions[kind] = action
        self.diagram_button.setMenu(menu)
        self.diagram_button.clicked.connect(lambda: self.choose_diagram(self.diagram_kind))
        tools.addButton(self.diagram_button)
        self.ask_button = self._tool_button(
            bar, icons.ask_icon(), "Ask Claude (A): drag a box around something, then type a question", True)
        self.ask_button.setObjectName("askButton")
        self.ask_button.setText(tr("Ask"))
        self.ask_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.ask_button.clicked.connect(self._ask_mode)
        tools.addButton(self.ask_button)
        # The header is hidden in fullscreen, so the way out moves onto the toolbar.
        self.exit_fullscreen_button = self._tool_button(bar, icons.fullscreen_icon(), "Leave fullscreen (F11 or Esc)")
        self.exit_fullscreen_button.clicked.connect(self.toggle_fullscreen)
        self.exit_fullscreen_button.hide()
        extras = {}
        for item, icon, tip, handler in (
                ("new_page", icons.new_page_icon(), "New page (Ctrl+N)", "new_page"),
                ("paste", icons.paste_icon(), "Paste (Ctrl+V)", "paste"),
                ("fullscreen", icons.fullscreen_icon(), "Fullscreen (F11, Esc to leave)", "toggle_fullscreen"),
                ("settings", icons.settings_icon(), "Settings", "show_settings")):
            extras[item] = self._tool_button(bar, icon, tip)
            extras[item].clicked.connect(lambda checked=False, h=handler: getattr(self, h)())
        self.new_page_action.changed.connect(
            lambda: extras["new_page"].setEnabled(self.new_page_action.isEnabled()))
        pens = [item for item, _, _ in TOOLBAR_ITEMS[5:5 + len(self.pen_buttons)]]
        self.toolbar_buttons = {
            "sidebar": self.sidebar_button, "undo": self.undo_button, "redo": self.redo_button,
            "lasso": self.select_button, "eraser": self.eraser_button,
            **dict(zip(pens, self.pen_buttons)),
            "shapes": self.shape_button, "engineering": self.diagram_button, "ask": self.ask_button,
            **extras}
        assert list(self.toolbar_buttons) == [item for item, _, _ in TOOLBAR_ITEMS]
        self._pen_panel()
        self._use_preset(self.presets[0])
        self.set_toolbar_items(self._load_ui_settings().get("toolbar_items", list(DEFAULT_TOOLBAR)), save=False)

    @staticmethod
    def _clean_toolbar_items(items):
        """Known ids, each once, in the given order; anything unusable means the defaults."""
        if not isinstance(items, list):
            return list(DEFAULT_TOOLBAR)
        clean = []
        for item in items:
            if isinstance(item, str) and item in TOOLBAR_GROUPS and item not in clean:
                clean.append(item)
        return clean

    def set_toolbar_items(self, items, save=True):
        """Show these toolbar items in this order, and hide the rest."""
        self.toolbar_items = self._clean_toolbar_items(items)
        entries, group = [], None
        for item in self.toolbar_items:
            if group is not None and TOOLBAR_GROUPS[item] != group:
                entries.append(None)
            group = TOOLBAR_GROUPS[item]
            entries.append(self.toolbar_buttons[item])
        entries.append(self.exit_fullscreen_button)
        self.toolbar.set_widgets(entries)
        for item, button in self.toolbar_buttons.items():
            button.setVisible(item in self.toolbar_items)
        if hasattr(self, "settings_dialog"):
            self.settings_dialog.set_toolbar_items(self.toolbar_items)
        self._place_toolbar()
        if save:
            self._save_ui_settings()

    def toolbar_menu(self):
        menu = QMenu(self)
        customize = menu.addAction(tr("Customize toolbar…"))
        customize.triggered.connect(lambda checked=False: self.show_settings(toolbar=True))
        return menu

    def _settings(self):
        """Rarely changed options live in a dialog, keeping the toolbar for drawing."""
        self.settings_dialog = SettingsDialog(TOOLBAR_SIZES, ASK_MODELS, ASK_EFFORTS, self)
        self.settings_dialog.set_toolbar_choices(
            [(item, self.toolbar_buttons[item].icon(), tr(label)) for item, label, _ in TOOLBAR_ITEMS],
            DEFAULT_TOOLBAR)
        self.settings_dialog.set_toolbar_items(self.toolbar_items)
        self.settings_dialog.toolbar_changed.connect(self.set_toolbar_items)
        self.size_combo = self.settings_dialog.size_combo
        self.size_combo.setCurrentIndex(self.size_combo.findData(self.toolbar_size))
        self.size_combo.currentIndexChanged.connect(
            lambda: self.set_toolbar_size(self.size_combo.currentData()))
        language = self.settings_dialog.language_choice
        language.setCurrentIndex(max(0, language.findData(self.language)))
        language.currentIndexChanged.connect(self._save_ui_settings)
        settings = self._load_ui_settings()
        # The Ask panel's combos hold the choice; the dialog mirrors them.
        self.ask_model_combo = self.ask_panel.model_combo
        self.ask_effort_combo = self.ask_panel.effort_combo
        for combo, choice, key in ((self.ask_model_combo, self.settings_dialog.model_choice, "ask_model"),
                                   (self.ask_effort_combo, self.settings_dialog.effort_choice, "ask_effort")):
            combo.setCurrentIndex(max(0, combo.findData(settings.get(key))))
            link_choices(combo, choice)
            combo.currentIndexChanged.connect(self._save_ui_settings)

    def show_settings(self, toolbar=False):
        self.settings_dialog.open()
        if toolbar:
            self.settings_dialog.focus_toolbar()

    def _pen_panel(self):
        """Popup with color swatches and width for the active pen preset."""
        self.pen_panel = QFrame(self, Qt.WindowType.Popup)
        self.pen_panel.setObjectName("penPanel")
        grid = QGridLayout(self.pen_panel)
        self.color_buttons = {}
        for index, (name, color) in enumerate(PALETTE):
            button = QToolButton()
            button.setIcon(icons.swatch_icon(color))
            button.setToolTip(tr(name))
            button.setAccessibleName(tr(name))
            button.setAutoRaise(True)
            button.clicked.connect(lambda checked=False, c=color: self.set_preset_color(c))
            grid.addWidget(button, index // 5, index % 5)
            self.color_buttons[color] = button
        grid.addWidget(QLabel(tr("Width (1–{max}):", max=MAX_WIDTH)), 2, 0, 1, 2)
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
        if not button.isVisible():  # Removed from the toolbar: open under the toolbar instead.
            button = self.toolbar
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
        self.shape_kind = kind
        self.canvas.set_shape(kind)
        self.shape_button.setIcon(icons.shape_icon(kind))
        self.shape_button.setChecked(True)
        self.canvas.set_mode("shape")

    def choose_diagram(self, kind):
        """Draw engineering diagrams with the shape gesture; the Shapes button keeps its own kind."""
        self.diagram_kind = kind
        self.canvas.set_shape(kind)
        self.diagram_button.setIcon(icons.diagram_icon(kind))
        self.diagram_button.setChecked(True)
        self.canvas.set_mode("shape")

    def _paper_changed(self, paper):
        self.canvas.set_paper(paper)
        if self._page_id and self.library.page(self._page_id).paper != paper:
            self.library.set_paper(self._page_id, paper)
            self._changed()

    def toggle_fullscreen(self):
        full = not self.isFullScreen()
        # Fullscreen is the page alone: no sidebar, header, margins or card border.
        self.header.setVisible(not full)
        self._column.setContentsMargins(*((0, 0, 0, 0) if full else (12, 8, 12, 12)))
        self.page_frame.layout().setContentsMargins(*((0, 0, 0, 0) if full else (1, 1, 1, 1)))
        self.page_frame.setProperty("bare", full)
        self.page_frame.setStyleSheet("QFrame#page { border: 0; border-radius: 0; }" if full else "")
        self.exit_fullscreen_button.setVisible(full)
        if full:
            self.sidebar.hide()
            self.showFullScreen()
        else:
            self.showNormal()
            self.sidebar.setVisible(self.sidebar_button.isChecked())
        self.fullscreen_button.setChecked(full)
        self._round_view()
        self._place_toolbar()

    def _escape(self):
        if self.ask_prompt.isVisible():
            self.ask_prompt.cancel()
        elif self.canvas.selection:
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
        data = {"toolbar_size": self.toolbar_size, "language": self.language}
        if hasattr(self, "toolbar_items"):
            data["toolbar_items"] = self.toolbar_items
        if hasattr(self, "settings_dialog"):
            # Saved for the next start; this window keeps the language it was built in.
            data["language"] = self.settings_dialog.language_choice.currentData()
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
        widget = self.view if self.view.isVisible() else self.placeholder
        origin = widget.mapTo(self.centralWidget(), QPoint(0, 0))
        self.toolbar.adjustSize()
        # The card, not the shadow around it, sits 12px below the page's top edge.
        self.toolbar.move(origin.x() + widget.width() // 2 - self.toolbar.width() // 2,
                          origin.y() + 12 - FloatingToolbar.SHADOW[1])
        self.toolbar.raise_()
        if hasattr(self, "zoom_pill"):
            pill = self.zoom_pill
            pill.adjustSize()
            # Clear of the scrollbars at the right and bottom edges.
            pill.move(origin.x() + widget.width() - pill.width() - 28,
                      origin.y() + widget.height() - pill.height() - 28)
            pill.setVisible(widget is self.view and self.view.isVisible())
            pill.raise_()

    def _round_view(self):
        """Clip the canvas to the page card's rounded corners."""
        if self.page_frame.property("bare"):
            self.view.clearMask()
            return
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.view.rect()), 15, 15)
        self.view.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def eventFilter(self, watched, event):
        if watched in (self.view, self.placeholder, self.page_frame) and event.type() in (
                QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show, QEvent.Type.Hide):
            if watched is self.view and event.type() == QEvent.Type.Resize:
                self._round_view()
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
            pending = [(parent, section) for section in subject.sections]
            while pending:
                owner, section = pending.pop(0)
                child = QTreeWidgetItem(owner, [section.name])
                child.setData(0, Qt.ItemDataRole.UserRole, ("section", section.id))
                if current == ("section", section.id):
                    match = child
                # Subsections first, then the section's own pages.
                pending[:0] = [(child, nested) for nested in section.sections]
                for page in section.pages:
                    leaf = QTreeWidgetItem(child, [page.name])
                    leaf.setData(0, Qt.ItemDataRole.UserRole, ("page", page.id))
                    if current == ("page", page.id):
                        match = leaf
        self.tree.expandAll()
        self.tree.setCurrentItem(match)
        self.tree.blockSignals(False)
        self._filter_tree(self.search.text())
        self._selection_changed()

    def _selection_changed(self, *_):
        selected = self._selected()
        page_id = selected[1] if selected and selected[0] == "page" else None
        if page_id != self._page_id:
            self._close_ask_prompt()  # Its region belongs to the page being left.
            self._page_id = page_id
            self.canvas.set_note(self.library.page(page_id).note if page_id else Note())
            if page_id:
                self.paper_combo.setCurrentIndex(self.paper_combo.findData(self.library.page(page_id).paper))
        self.canvas.setEnabled(page_id is not None)
        self.view.setVisible(page_id is not None)
        self.placeholder.setVisible(page_id is None)
        self.paper_combo.setEnabled(page_id is not None)
        in_section = self._section_id() is not None
        self.new_section_action.setEnabled(bool(selected))
        self.new_section_action.setText(tr("New subsection" if in_section else "New section"))
        self.new_page_action.setEnabled(in_section)
        self.delete_section_action.setEnabled(bool(selected) and selected[0] in ("subject", "section"))
        self.delete_section_action.setText(
            tr("Delete subject…" if selected and selected[0] == "subject" else "Delete section…"))
        self.import_action.setEnabled(in_section)
        self.import_button.setEnabled(in_section)
        self.rename_action.setEnabled(bool(selected))
        self.undo_button.setEnabled(page_id is not None)
        self.redo_button.setEnabled(page_id is not None)
        self._breadcrumb()
        self._title()

    def _breadcrumb(self):
        names = []
        item = self.tree.currentItem()
        while item is not None:
            names.insert(0, html.escape(item.text(0)))
            item = item.parent()
        if names:
            names[-1] = f'<span style="color:{theme.INK}; font-weight:600">{names[-1]}</span>'
        self.breadcrumb.setText('&nbsp;&nbsp;<span style="color:#A8A8A2">›</span>&nbsp;&nbsp;'.join(names))

    def _title(self):
        # A flag, not Library.dirty: comparing the whole library on every stroke is slow.
        self.setWindowTitle(f"{'*' if self._unsaved else ''}Lapicero — {self.library.path}")

    def _report_error(self, title, exc):
        # Report once per failing save streak; status remains visible until retry succeeds.
        if not self._save_error_shown:
            self._save_error_shown = True
            QMessageBox.warning(self, title, str(exc))
        if hasattr(self, "status"):
            self._set_status(tr("Not saved"), tr("{title}: {error}. Work remains in memory; retry Save (Ctrl+S).",
                                                title=title, error=exc),
                             theme.ERROR)

    def save(self):
        self._autosave.stop()
        try:
            self.library.path.parent.mkdir(parents=True, exist_ok=True)
            self.library.save()
        except (OSError, ValueError) as exc:
            self._report_error(tr("Library save failed"), exc)
            self._title()
            return False
        self._save_error_shown = False
        self._unsaved = False
        self._set_status(tr("Saved"), tr("All changes saved to {path}", path=self.library.path))
        self._title()
        return True

    def _set_status(self, text, detail, color=theme.OK):
        self.status.setText(text)
        self.status.setToolTip(detail)
        self.status_dot.setToolTip(detail)
        self.status_dot.setStyleSheet(f"color: {color};")
        self.status_dot.show()
        self.status.setStyleSheet(f"color: {color};" if color == theme.ERROR else "")

    def _changed(self):
        self._unsaved = True
        if self._autosave_delay <= 0:
            self.save()
            return
        self._set_status(tr("Saving…"), tr("Changes are saved when you pause writing"), theme.BUSY)
        self._title()
        self._autosave.start(self._autosave_delay)

    def _autosave_now(self):
        if self.canvas.gesture_active:
            self._autosave.start(self._autosave_delay)  # Never stall a stroke in progress.
        else:
            self.save()

    def _name(self, title, initial=""):
        value, accepted = QInputDialog.getText(self, tr(title), tr("Name:"), text=initial)
        return value.strip() if accepted and value.strip() else None

    def new_subject(self):
        name = self._name("New subject")
        if name:
            subject = self.library.create_subject(name)
            self._refresh(("subject", subject.id))
            self.save()

    def new_section(self):
        """Top-level section under a subject; a subsection under any section or page."""
        selected = self._selected()
        if not selected:
            return
        parent_id = self._section_id()
        name = self._name("New subsection" if parent_id else "New section")
        if name:
            if parent_id is None:
                section = self.library.create_section(selected[1], name)
            else:
                section = self.library.create_subsection(parent_id, name)
            self._refresh(("section", section.id))
            self.save()

    def delete_selected(self):
        selected = self._selected()
        if selected and selected[0] == "subject":
            self.delete_subject()
        else:
            self.delete_section()

    def delete_subject(self):
        selected = self._selected()
        if not selected or selected[0] != "subject":
            return
        subject = self.library.subject(selected[1])
        choice = QMessageBox.question(
            self, tr("Delete subject"),
            tr("Delete \"{name}\" with all of its sections and pages? This cannot be undone.",
               name=subject.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if choice != QMessageBox.StandardButton.Yes:
            return
        self.library.delete_subject(subject.id)
        self._refresh(None)
        self.save()

    def delete_section(self):
        selected = self._selected()
        if not selected or selected[0] != "section":
            return
        section = self.library.section(selected[1])
        choice = QMessageBox.question(
            self, tr("Delete section"),
            tr("Delete \"{name}\" with all of its pages and subsections? This cannot be undone.",
               name=section.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if choice != QMessageBox.StandardButton.Yes:
            return
        parent = self.tree.currentItem().parent().data(0, Qt.ItemDataRole.UserRole)
        self.library.delete_section(section.id)
        self._refresh(parent)
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
        source, _ = QFileDialog.getOpenFileName(self, tr("Import standalone note"), "", tr("JSON notes (*.json)"))
        if not source:
            return
        try:
            page = self.library.import_legacy_note(section_id, source)
        except (OSError, NoteFormatError, ValueError) as exc:
            QMessageBox.warning(self, tr("Import failed"), str(exc))
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
            self.ask_button.setToolTip(tr("AI bridge failed to start: {error}", error=exc))
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
            # Typed in a box beside the region, which stays marked; Enter sends it here again.
            self._open_ask_prompt(region)
            return None
        question = question.strip()
        if not question:
            return None
        page = self.library.page(self._page_id)
        ask_id = self.ai.create_ask(page, region, question)
        ask = self.ai.asks[ask_id]
        self.ask_panel.add_question(ask_id, page.name, question, ask["png"])
        message = build_message(build_prompt(ask_id, page.name, question, ask["region"]), ask["png"])
        self._run_ask(ask_id, message)
        return ask_id

    def _ask_mode(self):
        """Ask tool: mark an area on the page, or type in the chat panel it opens."""
        self.canvas.set_mode("ask")
        self.ask_panel.show()

    def ask_text(self, question):
        """Ask Claude without a marked area, continuing the current conversation; returns the ask id."""
        question = question.strip()
        if not question:
            return None
        page = self.library.page(self._page_id) if self._page_id is not None else None
        page_name = page.name if page is not None else None
        ask_id = uuid4().hex[:12]
        self.ask_panel.add_question(ask_id, page_name, question)
        self._run_ask(ask_id, build_message(build_text_prompt(page_name, question)))
        return ask_id

    def new_chat(self):
        """Show an empty conversation; the next question starts a new chat.

        Questions still being answered keep running; their answers land in their own chat.
        """
        self._save_chat()
        self._chat_record = None
        self._session_id = None
        self.ask_panel.clear()
        self.ask_panel.open_chat()

    def history_menu(self):
        """Menu of the chats started on the open page, newest first; picking one reopens it."""
        menu = QMenu(self)
        chats = self.chat_store.for_page(self._page_id)
        if not chats:
            empty = menu.addAction(tr("No chats on this page yet"))
            empty.setEnabled(False)
        for chat in chats:
            when = QDateTime.fromSecsSinceEpoch(int(chat.get("updated", 0))).toString("dd/MM/yyyy HH:mm")
            action = menu.addAction(f"{chat_title(chat)}  ·  {when}")
            action.setCheckable(True)
            action.setChecked(self._chat_record is not None and chat["id"] == self._chat_record["id"])
            action.triggered.connect(lambda _checked=False, chat_id=chat["id"]: self.open_chat(chat_id))
        return menu

    def _show_history(self):
        button = self.ask_panel.history_button
        self.history_menu().popup(button.mapToGlobal(QPoint(0, button.height())))

    def open_chat(self, chat_id):
        """Show a saved chat; the next question continues its Claude Code session."""
        chat = self.chat_store.chats.get(chat_id)
        if chat is None or (self._chat_record is not None and chat_id == self._chat_record["id"]):
            return
        self._save_chat()
        self._chat_record = chat
        self._session_id = chat.get("session_id")
        self.ask_panel.load(chat["entries"], running=set(self._asks))

    def _save_chat(self):
        """Write the panel's conversation to the current chat's file."""
        if self._chat_record is None or not self.ask_panel.entries:
            return
        self._chat_record["entries"] = self.ask_panel.saved_entries()
        self._chat_record["session_id"] = self._session_id
        self._store_chat(self._chat_record)

    def _store_chat(self, chat):
        try:
            self.chat_store.save(chat)
        except OSError as exc:
            self._set_status(tr("Chat not saved"), tr("Could not save the chat: {error}", error=exc), theme.ERROR)

    def _set_answer(self, ask_id, text, is_error=False, session_id=""):
        """Put an answer in its chat: the panel when that chat is shown, else its saved file."""
        chat = self._ask_records.pop(ask_id, self._chat_record)
        if chat is not None and chat is not self._chat_record:
            for entry in chat["entries"]:
                if entry.get("ask_id") == ask_id:
                    entry["answer"], entry["error"] = text, is_error
            if session_id:
                chat["session_id"] = session_id
            self._store_chat(chat)
            return
        if session_id:
            self._session_id = session_id  # The next question continues from this answer.
        self.ask_panel.set_answer(ask_id, text, is_error)
        self._save_chat()

    def _run_ask(self, ask_id, message):
        """Start Claude Code for a question already shown in the panel, resuming the conversation."""
        if self._chat_record is None:
            self._chat_record = new_chat_record(self._page_id)
        self._ask_records[ask_id] = self._chat_record
        self._save_chat()
        if not self.start_bridge():
            self._set_answer(ask_id, tr("The AI bridge is not running: {error}", error=self.bridge_error), True)
            return
        config_path = self.bridge.info_path.parent / MCP_CONFIG_FILE
        try:
            config_path.write_text(json.dumps(mcp_config(self.bridge.info_path)), encoding="utf-8")
        except OSError as exc:
            self._set_answer(ask_id, tr("Could not write {path}: {error}", path=config_path, error=exc), True)
            return
        run = ClaudeAsk(ask_id, message, config_path, config_path.parent, program=self.claude_program,
                        model=self.ask_model_combo.currentData(), effort=self.ask_effort_combo.currentData(),
                        resume=self._session_id, parent=self)
        run.finished.connect(self._answered)
        self._asks[ask_id] = run
        run.start()

    def _open_ask_prompt(self, region):
        self._prompt_region = QRectF(region)
        self.canvas.set_pending_region(region)
        self.ask_prompt.open()
        self._place_ask_prompt()

    def _close_ask_prompt(self):
        self._prompt_region = None
        self.canvas.set_pending_region(None)
        self.ask_prompt.hide()

    def _prompt_submitted(self, question):
        region = self._prompt_region
        self._close_ask_prompt()
        if region is not None:
            self.ask_about(region, question)

    def _place_ask_prompt(self):
        """Beside the region (right, else left, else below), kept inside the page."""
        if self._prompt_region is None or not self.ask_prompt.isVisible():
            return
        prompt, gap, pad = self.ask_prompt, 14, 8
        prompt.adjustSize()
        origin = self.canvas.mapTo(self.centralWidget(), QPoint(0, 0))
        rect = self.canvas.to_widget(self._prompt_region).translated(origin.x(), origin.y())
        left_edge, right_edge = origin.x() + pad, origin.x() + self.canvas.width() - pad
        top_edge = max(origin.y() + pad, self.toolbar.geometry().bottom() + pad)
        bottom_edge = origin.y() + self.canvas.height() - pad
        x, y = rect.right() + gap, rect.top()
        if x + prompt.width() > right_edge:
            x = rect.left() - gap - prompt.width()
            if x < left_edge:
                x, y = rect.left(), rect.bottom() + gap
        x = max(left_edge, min(x, right_edge - prompt.width()))
        y = max(top_edge, min(y, bottom_edge - prompt.height()))
        prompt.move(round(x), round(y))
        prompt.raise_()

    claude_program = None  # Tests point this at a fake Claude Code executable.

    def _answered(self, ask_id, text, is_error, session_id=""):
        run = self._asks.pop(ask_id, None)
        if run is not None:
            run.deleteLater()
        self._set_answer(ask_id, text, is_error, session_id)

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
        choice = QMessageBox.question(self, tr("Unsaved library"),
                                      tr("Changes are still in memory. Save before closing?"),
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if choice == QMessageBox.StandardButton.Discard or (choice == QMessageBox.StandardButton.Save and self.save()):
            self.stop_bridge()
            event.accept()
        else:
            if bridge_was_running:
                self.start_bridge()
            event.ignore()
