"""Ask Claude about a page region: run Claude Code headless and show its answer."""

import base64
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QImage
# QtWebEngine must be imported before the QApplication exists; importing it here does that.
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QComboBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QToolButton, QVBoxLayout)

from .i18n import tr
from .icons import history_icon


ASK_TIMEOUT_MS = 5 * 60 * 1000
MCP_CONFIG_FILE = "claude-mcp.json"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANSWERS_PAGE = Path(__file__).resolve().parent / "assets" / "web" / "answers.html"
# (label, value passed to claude); None keeps the user's Claude Code default.
ASK_MODELS = (("Claude Code default", None), ("Fable", "fable"), ("Opus", "opus"),
              ("Sonnet", "sonnet"), ("Haiku", "haiku"))
ASK_EFFORTS = (("Default", None), ("Low", "low"), ("Medium", "medium"), ("High", "high"),
               ("Extra high", "xhigh"), ("Max", "max"))
SYSTEM_PROMPT = (
    "You are answering a question asked from inside Lapicero, a handwritten-notes app. "
    "Your final message is shown in a narrow side panel of the app: answer in the language of the "
    "question, keep it concise, and use Markdown sparingly. The panel renders LaTeX with KaTeX: write "
    "every formula, symbol and equation in LaTeX, inline as $...$ and displayed as $$...$$ on its own "
    "lines; never write math as plain text or Unicode. The user may ask follow-up questions in the same "
    "conversation. You can only use the Lapicero tools.")


def build_prompt(ask_id, page_name, question, region):
    x, y, w, h = (region[k] for k in ("x", "y", "width", "height"))
    return (f"Question from Lapicero (ask_id: {ask_id}, page: {page_name!r}):\n{question}\n\n"
            f"The attached image is the area the user selected: document rectangle x={x:g}, y={y:g}, "
            f"width={w:g}, height={h:g}. Answer directly. Write on the page (write_text, draw_shape, "
            "draw_strokes) only when the user asks for it or a drawing clearly helps; put it next to that "
            "rectangle without covering existing ink.")


def build_text_prompt(page_name, question):
    """A question typed in the panel, with no marked area."""
    where = f"the open page is {page_name!r}" if page_name else "no page is open"
    return (f"Question from Lapicero ({where}):\n{question}\n\n"
            "No area was marked. Answer directly; read the page with the Lapicero tools only when the "
            "question is about it.")


def build_message(prompt, png=None):
    """One stream-json user message: the region image first (when there is one), then the question."""
    content = [{"type": "text", "text": prompt}]
    if png is not None:
        content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                       "data": base64.b64encode(png).decode("ascii")}})
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"


def mcp_config(bridge_file):
    """Claude Code config that starts this checkout's MCP server with the app's Python."""
    return {"mcpServers": {"lapicero": {
        "type": "stdio", "command": sys.executable, "args": ["-m", "lapicero.mcp_server"],
        "env": {"PYTHONPATH": str(PROJECT_ROOT), "LAPICERO_BRIDGE": str(bridge_file)}}}}


def claude_arguments(config_path, model=None, effort=None, resume=None):
    # The question and image go through stdin, so no user text needs command-line quoting.
    # Loading only project settings (none exist in the library folder) skips the user's
    # hooks and plugins, which made each question take well over a minute to start.
    # Sessions are kept so a follow-up question can resume the conversation.
    arguments = ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                 "--setting-sources", "project",
                 "--mcp-config", str(config_path), "--strict-mcp-config",
                 "--tools", "", "--allowedTools", "mcp__lapicero",
                 "--append-system-prompt", SYSTEM_PROMPT]
    if model:
        arguments += ["--model", model]
    if effort:
        arguments += ["--effort", effort]
    if resume:
        arguments += ["--resume", resume]
    return arguments


def parse_result(stdout, stderr, exit_code):
    """(answer text, is_error, session id or "") from `claude -p --output-format stream-json` output."""
    data, session_id = None, ""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if isinstance(event.get("session_id"), str):
            session_id = event["session_id"]
        if event.get("type") == "result":
            data = event
    if isinstance(data, dict) and isinstance(data.get("result"), str):
        text = data["result"].strip() or tr("(Claude returned an empty answer)")
        return text, bool(data.get("is_error")), session_id
    detail = (stderr or stdout).strip()[-600:] or tr("exit code {code}", code=exit_code)
    return tr("Claude Code failed: {detail}", detail=detail), True, session_id


class ClaudeAsk(QObject):
    """One headless Claude Code run; emits finished(ask_id, text, is_error, session_id) once.

    The process is spawned and read on a background thread: creating the Claude Code
    process alone can take seconds on Windows, which froze the window when done here.
    """

    finished = Signal(str, str, bool, str)
    _completed = Signal(str, bool, str)  # Worker thread -> main thread (queued).

    def __init__(self, ask_id, message, config_path, workdir, program=None, model=None, effort=None,
                 resume=None, parent=None):
        super().__init__(parent)
        self.ask_id = ask_id
        self._prompt = message.encode("utf-8")
        self._done = False
        self._cancelled = False
        self._process = None
        self._lock = threading.Lock()
        # program: an executable path, or [executable, *leading arguments] (tests use a fake).
        command = list(program) if isinstance(program, (list, tuple)) else [program or shutil.which("claude") or "claude"]
        self._command = [*command, *claude_arguments(config_path, model, effort, resume)]
        self._workdir = str(workdir)
        self._completed.connect(self._emit)
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._timed_out)

    def start(self):
        self._timeout.start(ASK_TIMEOUT_MS)
        threading.Thread(target=self._run, name=f"claude-ask-{self.ask_id}", daemon=True).start()

    def cancel(self):
        with self._lock:
            self._cancelled = True
            process = self._process
        if process is not None and process.poll() is None:
            process.kill()
            try:
                process.wait(2)
            except subprocess.TimeoutExpired:
                pass

    def _run(self):
        try:
            process = subprocess.Popen(
                self._command, cwd=self._workdir, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            self._completed.emit(tr("Claude Code was not found. Install it and sign in once by running `claude` "
                                    "in a terminal, then ask again."), True, "")
            return
        with self._lock:
            self._process = process
            cancelled = self._cancelled
        if cancelled:
            process.kill()
        stdout, stderr = process.communicate(self._prompt)
        if not cancelled:
            self._completed.emit(*parse_result(stdout.decode("utf-8", "replace"),
                                               stderr.decode("utf-8", "replace"), process.returncode))

    def _emit(self, text, is_error, session_id=""):
        if not self._done:
            self._done = True
            self._timeout.stop()
            self.finished.emit(self.ask_id, text, is_error, session_id)

    def _timed_out(self):
        self._emit(tr("Claude took more than 5 minutes; the question was cancelled."), True)
        self.cancel()


class AskPrompt(QFrame):
    """Floating box beside an Ask region: type a question, Enter sends, Esc cancels."""

    submitted = Signal(str)
    cancelled = Signal()
    WIDTH = 340

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("askPrompt")
        self.setFixedWidth(self.WIDTH)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(20, 20, 18, 46))
        self.setGraphicsEffect(shadow)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        title = QLabel(tr("Ask Claude about this area"))
        title.setObjectName("askPromptTitle")
        layout.addWidget(title)
        self.input = QPlainTextEdit()
        self.input.setObjectName("askInput")
        self.input.setPlaceholderText(tr("What do you want to ask?"))
        self.input.setAccessibleName(tr("Question about the marked area"))
        self.input.setFixedHeight(76)
        self.input.installEventFilter(self)
        layout.addWidget(self.input)
        footer = QHBoxLayout()
        self.input.setToolTip(tr("Enter sends · Shift+Enter starts a new line · Esc cancels"))
        hint = QLabel(tr("Enter to send · Esc to cancel"))
        hint.setObjectName("hint")
        footer.addWidget(hint, 1)
        self.send_button = QPushButton(tr("Send"))
        self.send_button.setObjectName("sendButton")
        self.send_button.clicked.connect(self.submit)
        footer.addWidget(self.send_button)
        layout.addLayout(footer)
        self.hide()

    def open(self):
        self.input.clear()
        self.show()
        self.raise_()
        self.input.setFocus()

    def submit(self):
        text = self.input.toPlainText().strip()
        if text:
            self.hide()
            self.submitted.emit(text)

    def cancel(self):
        if self.isVisible():
            self.hide()
            self.cancelled.emit()

    def eventFilter(self, watched, event):
        if watched is self.input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and \
                    not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.submit()
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.cancel()
                return True
        return super().eventFilter(watched, event)


class _AnswersPage(QWebEnginePage):
    """Answers page: links open in the system browser, nothing else navigates away."""

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if navigation_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            if url.scheme() in ("http", "https", "mailto"):
                QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)


class AskPanel(QFrame):
    """Right-hand chat with Claude: questions, answers (Markdown + LaTeX) and a follow-up box."""

    follow_up = Signal(str)
    new_chat = Signal()
    history_requested = Signal()
    THUMBNAIL_SIDE = 480  # Area images are kept this small in the panel and in saved chats.

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("askPanel")
        self.setMinimumWidth(320)
        self.setMaximumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(18, 12, 10, 12)
        title = QLabel(tr("Ask Claude"))
        title.setObjectName("panelTitle")
        header.addWidget(title, 1)
        self.history_button = QToolButton()
        self.history_button.setObjectName("closeButton")
        self.history_button.setIcon(history_icon())
        self.history_button.setToolTip(tr("Chats on this page"))
        self.history_button.setAccessibleName(tr("Chats on this page"))
        self.history_button.clicked.connect(self.history_requested)
        header.addWidget(self.history_button)
        self.new_chat_button = QToolButton()
        self.new_chat_button.setObjectName("textButton")
        self.new_chat_button.setText(tr("New chat"))
        self.new_chat_button.setToolTip(tr("Start a new conversation"))
        self.new_chat_button.clicked.connect(self.new_chat)
        header.addWidget(self.new_chat_button)
        self.close_button = QToolButton()
        self.close_button.setObjectName("closeButton")
        self.close_button.setText("✕")
        self.close_button.setToolTip(tr("Hide answers"))
        self.close_button.setAccessibleName(tr("Hide answers"))
        self.close_button.clicked.connect(self.hide)
        header.addWidget(self.close_button)
        layout.addLayout(header)
        layout.addWidget(self._divider())
        self.view = QWebEngineView()
        self.view.setPage(_AnswersPage(self.view))
        self.view.page().setBackgroundColor(QColor("#FFFFFF"))
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._page_ready = False
        self.view.loadFinished.connect(self._page_loaded)
        self.view.setUrl(QUrl.fromLocalFile(str(ANSWERS_PAGE)))
        layout.addWidget(self.view, 1)
        layout.addWidget(self._divider())
        composer = QVBoxLayout()
        composer.setContentsMargins(12, 10, 12, 6)
        composer.setSpacing(6)
        self.input = QPlainTextEdit()
        self.input.setObjectName("askInput")
        self.input.setAccessibleName(tr("Question for Claude"))
        self.input.setToolTip(tr("Enter sends · Shift+Enter starts a new line"))
        self.input.setFixedHeight(64)
        self.input.installEventFilter(self)
        composer.addWidget(self.input)
        row = QHBoxLayout()
        self.hint = QLabel()
        self.hint.setObjectName("hint")
        row.addWidget(self.hint, 1)
        self.send_button = QPushButton(tr("Send"))
        self.send_button.setObjectName("sendButton")
        self.send_button.clicked.connect(self.submit)
        row.addWidget(self.send_button)
        composer.addLayout(row)
        layout.addLayout(composer)
        # Per-question choices; the Settings dialog mirrors them.
        footer = QHBoxLayout()
        footer.setContentsMargins(12, 4, 12, 12)
        footer.setSpacing(6)
        self.model_combo = self._chip(footer, tr("Model"), ASK_MODELS, tr("Model that answers Ask Claude questions"))
        self.effort_combo = self._chip(footer, tr("Effort"), ASK_EFFORTS,
                                       tr("How hard Claude thinks: lower answers faster, higher is more thorough"))
        footer.addStretch(1)
        layout.addLayout(footer)
        self.entries = []  # [ask_id, page name or None, question, answer or None, is_error, image data URL]
        self._render()

    @staticmethod
    def _divider():
        line = QFrame()
        line.setObjectName("divider")
        line.setFixedHeight(1)
        return line

    @staticmethod
    def _chip(layout, text, choices, tip):
        label = QLabel(text)
        label.setObjectName("chipLabel")
        combo = QComboBox()
        combo.setObjectName("chip")
        combo.setToolTip(tip)
        combo.setAccessibleName(text)
        for name, value in choices:
            combo.addItem(tr(name), value)
        layout.addWidget(label)
        layout.addWidget(combo)
        return combo

    @property
    def waiting(self):
        """True while Claude is still answering a question of this conversation."""
        return any(entry[3] is None for entry in self.entries)

    def open_chat(self):
        self.show()
        self.input.setFocus()

    def submit(self):
        text = self.input.toPlainText().strip()
        if text and not self.waiting:
            self.input.clear()
            self.follow_up.emit(text)

    def eventFilter(self, watched, event):
        if watched is self.input and event.type() == QEvent.Type.KeyPress and \
                event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and \
                not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.submit()
            return True
        return super().eventFilter(watched, event)

    def add_question(self, ask_id, page_name, question, png=None):
        self.entries.append([ask_id, page_name, question, None, False, self._thumbnail(png)])
        self._render()
        self.show()

    @classmethod
    def _thumbnail(cls, png):
        """A small PNG data URL of an area image (None without one)."""
        if not png:
            return None
        image = QImage.fromData(png)
        if image.isNull():
            return None
        if max(image.width(), image.height()) > cls.THUMBNAIL_SIDE:
            image = image.scaled(cls.THUMBNAIL_SIDE, cls.THUMBNAIL_SIDE, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return "data:image/png;base64," + base64.b64encode(bytes(data)).decode("ascii")

    def saved_entries(self):
        """The conversation in the form chats are saved in."""
        return [{"ask_id": ask_id, "page": page_name, "question": question, "answer": answer, "error": is_error,
                 "image": image} for ask_id, page_name, question, answer, is_error, image in self.entries]

    def load(self, saved, running=()):
        """Show a saved conversation. A question without an answer is still thinking when its
        ask id is in running, and is shown as interrupted otherwise."""
        self.entries = []
        for entry in saved:
            ask_id, answer, is_error = entry.get("ask_id", ""), entry.get("answer"), bool(entry.get("error"))
            if answer is None and ask_id not in running:
                answer, is_error = tr("No answer: the question was interrupted."), True
            self.entries.append([ask_id, entry.get("page"), entry.get("question", ""), answer, is_error,
                                 entry.get("image")])
        self._render()
        self.open_chat()

    def set_answer(self, ask_id, text, is_error=False):
        for entry in self.entries:
            if entry[0] == ask_id:
                entry[3], entry[4] = text, is_error
        self._render()

    def answer(self, ask_id):
        return next((entry[3] for entry in self.entries if entry[0] == ask_id), None)

    def clear(self):
        self.entries = []
        self._render()

    def plain_text(self):
        """The conversation as plain text: what the page shows, without formatting."""
        parts = []
        for _, page_name, question, answer, is_error, _ in self.entries:
            body = tr("Thinking…") if answer is None else (tr("Error: {error}", error=answer) if is_error else answer)
            parts.append("\n".join(filter(None, (page_name, question, body))))
        return "\n\n".join(parts)

    def _page_loaded(self, ok):
        self._page_ready = ok
        self._render()

    def _render(self):
        waiting = self.waiting
        self.input.setEnabled(not waiting)
        self.send_button.setEnabled(not waiting)
        self.input.setPlaceholderText(tr("Claude is answering…") if waiting else
                                      tr("Ask a follow-up…") if self.entries else tr("Ask Claude anything…"))
        self.hint.setText(tr("Continues this conversation") if self.entries else
                          tr("Or press A to ask about an area"))
        self.new_chat_button.setEnabled(bool(self.entries))
        if not self._page_ready:
            return
        state = {"empty": tr("Ask a question below, or press A and mark an area of the page to ask about it."),
                 "thinking": tr("Thinking"),
                 "turns": [{"page": page_name, "question": question, "answer": answer, "error": is_error,
                            "image": image}
                           for _, page_name, question, answer, is_error, image in self.entries]}
        self.view.page().runJavaScript(f"renderThread({json.dumps(state)})")
