"""Graphite theme: neutral chrome so the ink stays the hero, one blue accent for Ask Claude."""

from pathlib import Path

from PySide6.QtGui import QFont

BG = "#F4F4F1"
SURFACE = "#FFFFFF"
BORDER = "#E4E4DF"
INK = "#1C1C1E"
MUTED = "#6B6B66"
ACCENT = "#2F4FD8"
OK = "#2E9E83"
BUSY = "#D9822B"
ERROR = "#D6453D"
CHEVRON = (Path(__file__).parent / "assets" / "chevron-down.svg").as_posix()
FONT_FAMILIES =["Inter", "Segoe UI Variable Text", "Segoe UI", "Helvetica Neue", "Arial"]

STYLESHEET = f"""
QWidget#root, QWidget#sidebar, QWidget#content {{ background: {BG}; }}
QWidget {{ color: {INK}; }}
QWidget#sidebar {{ border-right: 1px solid {BORDER}; }}

QLabel#logo {{ background: transparent; }}
QLabel#appTitle {{ font-size: 12pt; font-weight: 600; }}
QLabel#sectionLabel {{ color: {MUTED}; font-size: 8pt; font-weight: 600; padding: 4px 6px 0 6px; }}
QLabel#breadcrumb {{ color: {MUTED}; padding-left: 6px; }}
QLabel#status {{ color: {MUTED}; }}
QLabel#placeholder {{ color: {MUTED}; background: {SURFACE}; }}

QLineEdit#search {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 6px 10px; selection-background-color: {ACCENT}; }}
QLineEdit#search:focus {{ border-color: {ACCENT}; }}

QTreeWidget#tree {{ background: transparent; border: 0; outline: 0; }}
QTreeWidget#tree::item {{ min-height: 30px; border-radius: 8px; padding-left: 2px; }}
QTreeWidget#tree::item:hover {{ background: #ECECE8; }}
QTreeWidget#tree::item:selected {{ background: {SURFACE}; color: {INK}; }}

QToolButton#newButton, QToolButton#headerButton {{ border: 0; border-radius: 8px; padding: 6px;
    background: transparent; font-size: 13pt; }}
QToolButton#newButton:hover, QToolButton#headerButton:hover {{ background: #EAEAE6; }}
QToolButton#headerButton:checked {{ background: #E2E2DD; }}
QToolButton#newButton::menu-indicator {{ image: none; width: 0; }}

QPushButton#footerButton {{ text-align: left; border: 0; border-radius: 8px; padding: 8px 10px;
    background: transparent; color: #3A3A37; }}
QPushButton#footerButton:hover {{ background: #ECECE8; }}
QPushButton#footerButton:disabled {{ color: #A8A8A2; }}

QFrame#page {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 16px; }}
/* Toolbar and zoom pill paint their own card and shadow (FloatingToolbar.paintEvent). */
QFrame#floatingToolbar, QFrame#zoomPill {{ background: transparent; border: 0; }}
QFrame#separator {{ background: {BORDER}; border: 0; }}
QFrame#floatingToolbar QToolButton, QFrame#zoomPill QToolButton {{ border: 1px solid transparent;
    border-radius: 10px; padding: 4px; background: transparent; color: #3A3A37; }}
QFrame#zoomPill QToolButton {{ border-radius: 8px; padding: 3px 8px; min-width: 18px; }}
QFrame#floatingToolbar QToolButton:hover, QFrame#zoomPill QToolButton:hover {{ background: #F2F2EF; }}
QFrame#floatingToolbar QToolButton:pressed {{ background: #E6E6E1; }}
QFrame#floatingToolbar QToolButton:checked {{ background: #EDEDE9; border-color: #DCDCD6; }}
QFrame#floatingToolbar QToolButton:disabled {{ color: #B5B5AE; }}
QFrame#floatingToolbar QToolButton::menu-button {{ border: 0; width: 14px; }}
QFrame#floatingToolbar QToolButton::menu-arrow {{ image: url({CHEVRON}); width: 10px; height: 10px; }}
QFrame#floatingToolbar QToolButton#askButton {{ background: #EEF1FD; color: {ACCENT};
    border: 1px solid #D3DBF8; font-weight: 600; padding: 4px 12px 4px 6px; margin-left: 2px; }}
QFrame#floatingToolbar QToolButton#askButton:hover {{ background: #E2E8FB; }}
QFrame#floatingToolbar QToolButton#askButton:checked {{ background: {ACCENT}; color: {SURFACE};
    border-color: {ACCENT}; }}

QFrame#segmented {{ background: #E9E9E5; border-radius: 10px; }}
QFrame#segmented QPushButton {{ border: 0; border-radius: 7px; padding: 5px 12px;
    background: transparent; color: #55554F; }}
QFrame#segmented QPushButton:hover {{ color: {INK}; }}
QFrame#segmented QPushButton:checked {{ background: {SURFACE}; color: {INK}; font-weight: 600; }}
QFrame#segmented QPushButton:disabled {{ color: #A8A8A2; }}

QFrame#askPanel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 16px; }}
QToolButton#textButton {{ border: 0; border-radius: 8px; padding: 4px 10px; background: transparent;
    color: {ACCENT}; font-weight: 600; }}
QToolButton#textButton:hover {{ background: #EEF1FC; }}
QToolButton#textButton:disabled {{ color: #A8A8A2; }}
QFrame#askPanel QPlainTextEdit#askInput:disabled {{ color: {MUTED}; background: #F4F4F1; }}
QLabel#panelTitle {{ font-size: 11pt; font-weight: 600; }}
QFrame#divider {{ background: #EDEDE9; border: 0; }}
QToolButton#closeButton {{ border: 0; border-radius: 8px; padding: 4px 8px; background: transparent; }}
QToolButton#closeButton:hover {{ background: #EFEFEC; }}
QComboBox#chip {{ border: 1px solid {BORDER}; border-radius: 8px; padding: 4px 8px;
    background: {SURFACE}; font-weight: 600; }}
QComboBox#chip:hover {{ border-color: #CFCFC9; }}
QComboBox#chip::drop-down {{ border: 0; width: 18px; }}
QComboBox#chip::down-arrow {{ image: url({CHEVRON}); width: 12px; height: 12px; }}
QComboBox#chip QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER};
    selection-background-color: #F0F0EC; selection-color: {INK}; outline: 0; }}
QLabel#chipLabel {{ color: {MUTED}; }}

QFrame#askPrompt {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
QLabel#askPromptTitle {{ color: {ACCENT}; font-weight: 600; }}
QPlainTextEdit#askInput {{ border: 1px solid #D9D9D3; border-radius: 10px; background: #FAFAF8;
    padding: 4px 6px; selection-background-color: {ACCENT}; }}
QPlainTextEdit#askInput:focus {{ border-color: {ACCENT}; background: {SURFACE}; }}
QPushButton#sendButton {{ background: {ACCENT}; color: {SURFACE}; border: 0; border-radius: 9px;
    padding: 6px 14px; font-weight: 600; }}
QPushButton#sendButton:hover {{ background: #1F3AB0; }}
QPushButton#sendButton:disabled {{ background: #C9D1F2; }}

QDialog#settings {{ background: {SURFACE}; }}
QLabel#dialogTitle {{ font-size: 13pt; font-weight: 600; }}
QLabel#fieldLabel {{ font-weight: 600; }}
QLabel#hint {{ color: {MUTED}; }}
QPushButton#primary {{ background: {INK}; color: {SURFACE}; border: 0; border-radius: 10px;
    padding: 9px 20px; font-weight: 600; }}
QPushButton#primary:hover {{ background: #33333A; }}
QPushButton#secondary {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 7px 14px; color: #3A3A37; }}
QPushButton#secondary:hover {{ background: #F4F4F1; border-color: #CFCFC9; }}
QListWidget#toolbarList {{ background: #FAFAF8; border: 1px solid {BORDER}; border-radius: 12px;
    padding: 6px; outline: 0; }}
QListWidget#toolbarList::item {{ min-height: 30px; border-radius: 8px; padding-left: 4px; color: {INK}; }}
QListWidget#toolbarList::item:hover {{ background: #F0F0EC; }}
QScrollArea#shortcutList, QWidget#shortcutRows {{ background: transparent; }}
QListWidget#toolbarList::item:selected {{ background: #ECECE8; color: {INK}; }}

QFrame#penPanel {{ background: {SURFACE}; border: 1px solid {BORDER}; }}
QFrame#penPanel QToolButton {{ border: 0; border-radius: 8px; padding: 3px; }}
QFrame#penPanel QToolButton:hover {{ background: #EFEFEC; }}

QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 6px; }}
QMenu::item {{ padding: 7px 18px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: #F0F0EC; color: {INK}; }}
QMenu::item:disabled {{ color: #A8A8A2; }}
QMenu::separator {{ height: 1px; background: #EDEDE9; margin: 4px 6px; }}

QToolTip {{ background: {INK}; color: {SURFACE}; border: 0; padding: 6px 8px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: #CFCFC9; border-radius: 3px; }}
QScrollBar::handle:hover {{ background: #B5B5AE; }}
QScrollBar::handle:vertical {{ min-height: 32px; }}
QScrollBar::handle:horizontal {{ min-width: 32px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


def apply(widget):
    """Style a top-level widget and its children; popups parented to it follow."""
    font = QFont(widget.font())
    font.setFamilies(FONT_FAMILIES)
    font.setPointSizeF(10)
    widget.setFont(font)
    widget.setStyleSheet(STYLESHEET)
