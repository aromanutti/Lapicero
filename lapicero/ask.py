"""Ask Claude about a page region: run Claude Code headless and show its answer."""

import base64
import json
from pathlib import Path
import shutil
import sys

from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QTextBrowser, QToolButton, QVBoxLayout


ASK_TIMEOUT_MS = 5 * 60 * 1000
MCP_CONFIG_FILE = "claude-mcp.json"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# (label, value passed to claude); None keeps the user's Claude Code default.
ASK_MODELS = (("Claude Code default", None), ("Fable", "fable"), ("Opus", "opus"),
              ("Sonnet", "sonnet"), ("Haiku", "haiku"))
ASK_EFFORTS = (("Default", None), ("Low", "low"), ("Medium", "medium"), ("High", "high"),
               ("Extra high", "xhigh"), ("Max", "max"))
SYSTEM_PROMPT = (
    "You are answering a question asked from inside Lapicero, a handwritten-notes app. "
    "Your final message is shown in a narrow side panel of the app: answer in the language of the "
    "question, keep it concise, and use Markdown sparingly. You can only use the Lapicero tools.")


def build_prompt(ask_id, page_name, question, region):
    x, y, w, h = (region[k] for k in ("x", "y", "width", "height"))
    return (f"Question from Lapicero (ask_id: {ask_id}, page: {page_name!r}):\n{question}\n\n"
            f"The attached image is the area the user selected: document rectangle x={x:g}, y={y:g}, "
            f"width={w:g}, height={h:g}. Answer directly. Write on the page (write_text, draw_shape, "
            "draw_strokes) only when the user asks for it or a drawing clearly helps; put it next to that "
            "rectangle without covering existing ink.")


def build_message(prompt, png):
    """One stream-json user message: the region image first, then the question."""
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                            "data": base64.b64encode(png).decode("ascii")}},
               {"type": "text", "text": prompt}]
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"


def mcp_config(bridge_file):
    """Claude Code config that starts this checkout's MCP server with the app's Python."""
    return {"mcpServers": {"lapicero": {
        "type": "stdio", "command": sys.executable, "args": ["-m", "lapicero.mcp_server"],
        "env": {"PYTHONPATH": str(PROJECT_ROOT), "LAPICERO_BRIDGE": str(bridge_file)}}}}


def claude_arguments(config_path, model=None, effort=None):
    # The question and image go through stdin, so no user text needs command-line quoting.
    # Loading only project settings (none exist in the library folder) skips the user's
    # hooks and plugins, which made each question take well over a minute to start.
    arguments = ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                 "--no-session-persistence", "--setting-sources", "project",
                 "--mcp-config", str(config_path), "--strict-mcp-config",
                 "--tools", "", "--allowedTools", "mcp__lapicero",
                 "--append-system-prompt", SYSTEM_PROMPT]
    if model:
        arguments += ["--model", model]
    if effort:
        arguments += ["--effort", effort]
    return arguments


def parse_result(stdout, stderr, exit_code):
    """(answer text, is_error) from `claude -p --output-format stream-json` output."""
    data = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            data = event
    if isinstance(data, dict) and isinstance(data.get("result"), str):
        return data["result"].strip() or "(Claude returned an empty answer)", bool(data.get("is_error"))
    detail = (stderr or stdout).strip()[-600:] or f"exit code {exit_code}"
    return f"Claude Code failed: {detail}", True


class ClaudeAsk(QObject):
    """One headless Claude Code run; emits finished(ask_id, text, is_error) once."""

    finished = Signal(str, str, bool)

    def __init__(self, ask_id, message, config_path, workdir, program=None, model=None, effort=None,
                 parent=None):
        super().__init__(parent)
        self.ask_id = ask_id
        self._prompt = message.encode("utf-8")
        self._done = False
        self.process = QProcess(self)
        # program: an executable path, or [executable, *leading arguments] (tests use a fake).
        command = list(program) if isinstance(program, (list, tuple)) else [program or shutil.which("claude") or "claude"]
        self.process.setProgram(command[0])
        self.process.setArguments([*command[1:], *claude_arguments(config_path, model, effort)])
        self.process.setWorkingDirectory(str(workdir))
        self.process.started.connect(self._send_prompt)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._timed_out)

    def start(self):
        self._timeout.start(ASK_TIMEOUT_MS)
        self.process.start()

    def cancel(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(2000)

    def _send_prompt(self):
        self.process.write(self._prompt)
        self.process.closeWriteChannel()

    def _emit(self, text, is_error):
        if not self._done:
            self._done = True
            self._timeout.stop()
            self.finished.emit(self.ask_id, text, is_error)

    def _finished(self, exit_code, _status):
        stdout = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        stderr = bytes(self.process.readAllStandardError()).decode("utf-8", "replace")
        self._emit(*parse_result(stdout, stderr, exit_code))

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._emit("Claude Code was not found. Install it and sign in once by running `claude` "
                       "in a terminal, then ask again.", True)

    def _timed_out(self):
        self._emit("Claude took more than 5 minutes; the question was cancelled.", True)
        self.cancel()


class AskPanel(QFrame):
    """Right-hand panel listing questions and Claude's answers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(300)
        self.setMaximumWidth(420)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("<b>Ask Claude</b>")
        header.addWidget(title, 1)
        self.close_button = QToolButton()
        self.close_button.setText("✕")
        self.close_button.setToolTip("Hide answers")
        self.close_button.setAutoRaise(True)
        self.close_button.clicked.connect(self.hide)
        header.addWidget(self.close_button)
        layout.addLayout(header)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        layout.addWidget(self.browser, 1)
        self.entries = []  # [ask_id, page name, question, answer or None, is_error]

    def add_question(self, ask_id, page_name, question):
        self.entries.append([ask_id, page_name, question, None, False])
        self._render()
        self.show()

    def set_answer(self, ask_id, text, is_error=False):
        for entry in self.entries:
            if entry[0] == ask_id:
                entry[3], entry[4] = text, is_error
        self._render()
        self.show()

    def answer(self, ask_id):
        return next((entry[3] for entry in self.entries if entry[0] == ask_id), None)

    def _render(self):
        parts = []
        for _, page_name, question, answer, is_error in reversed(self.entries):
            quoted = "\n".join(f"> {line}" for line in question.splitlines())
            body = "*Thinking…*" if answer is None else (f"**Error:** {answer}" if is_error else answer)
            parts.append(f"**{page_name}**\n\n{quoted}\n\n{body}")
        self.browser.setMarkdown("\n\n---\n\n".join(parts))
