"""AI bridge, MCP server and Ask Claude tests (offscreen Qt, real loopback sockets)."""

import asyncio
import base64
import json
import os
from pathlib import Path
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog

from lapicero.app import LapiceroWindow
from lapicero.bridge import BridgeError
from lapicero.ink_text import text_strokes
from lapicero.model import Stroke


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def qt():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt, tmp_path, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (next(names), True))
    names = iter(["Math", "Algebra", "Page 1", "Page 2"])
    widget = LapiceroWindow(library_path=tmp_path / "library.json", autosave_delay_ms=0, ai_bridge=True)
    widget.show()
    widget.new_subject()
    widget.new_section()
    widget.new_page()
    widget.canvas.note.add_stroke(Stroke(((40, 40), (120, 90)), "#202020", 3))
    qt.processEvents()
    yield widget
    widget.library._saved = widget.library._data()
    widget.close()


def pump(qt, worker, timeout=30):
    """Run a blocking call on a thread while the Qt main loop serves the bridge."""
    box = {}

    def run():
        try:
            box["value"] = worker()
        except BaseException as exc:  # Re-raised on the test thread.
            box["error"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + timeout
    while thread.is_alive() and time.monotonic() < deadline:
        qt.processEvents()
        time.sleep(.005)
    thread.join(1)
    assert not thread.is_alive(), "call did not finish"
    if "error" in box:
        raise box["error"]
    return box["value"]


def post(window, body, token=None, host=None):
    port = window.bridge.port
    request = urllib.request.Request(f"http://127.0.0.1:{port}/rpc", data=json.dumps(body).encode(), method="POST")
    request.add_header("Authorization", f"Bearer {token or window.bridge.token}")
    if host:
        request.add_header("Host", host)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=20) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


# Bridge security and dispatch ------------------------------------------------

def test_bridge_file_has_port_and_token_and_is_removed_on_close(window, tmp_path):
    info = json.loads((tmp_path / "bridge.json").read_text(encoding="utf-8"))
    assert info["port"] == window.bridge.port and info["token"] == window.bridge.token
    window.stop_bridge()
    assert not (tmp_path / "bridge.json").exists()


def test_bridge_rejects_wrong_token_and_foreign_host(qt, window):
    status, body = pump(qt, lambda: post(window, {"method": "list_pages"}, token="nope"))
    assert status == 401 and "token" in body["error"]
    status, body = pump(qt, lambda: post(window, {"method": "list_pages"}, host="evil.example:80"))
    assert status == 403


def test_bridge_runs_calls_on_the_main_thread(qt, window):
    seen = []
    original = window.ai.handle
    window.bridge._handler = lambda m, p: (seen.append(threading.current_thread()), original(m, p))[1]
    status, body = pump(qt, lambda: post(window, {"method": "list_pages"}))
    assert status == 200 and seen == [threading.main_thread()]
    page = window.library.subjects[0].sections[0].pages[0]
    assert body["result"]["current_page_id"] == page.id
    assert body["result"]["subjects"][0]["sections"][0]["pages"][0] == {
        "id": page.id, "name": "Page 1", "strokes": 1, "pictures": 0}


def test_bridge_reports_refusals_and_hides_internal_errors(qt, window):
    status, body = pump(qt, lambda: post(window, {"method": "read_page", "params": {"page_id": "missing"}}))
    assert status == 400 and "missing" in body["error"]
    status, body = pump(qt, lambda: post(window, {"method": "list_pages", "params": {"bogus": 1}}))
    assert status == 400 and "Invalid parameters" in body["error"]
    window.bridge._handler = lambda m, p: 1 / 0
    status, body = pump(qt, lambda: post(window, {"method": "list_pages"}))
    assert status == 500 and "ZeroDivision" not in body["error"]


def test_bridge_refuses_big_unauthorized_body_without_reading_it(qt, window):
    import socket

    def probe():
        with socket.create_connection(("127.0.0.1", window.bridge.port), timeout=10) as sock:
            sock.sendall(f"POST /rpc HTTP/1.1\r\nHost: 127.0.0.1:{window.bridge.port}\r\n"
                         "Authorization: Bearer wrong\r\nContent-Length: 1000000\r\n\r\n".encode())
            return sock.recv(200)

    started = time.monotonic()
    assert pump(qt, probe).startswith(b"HTTP/1.0 401") and time.monotonic() - started < 5


def test_write_queued_before_close_is_saved(qt, window, tmp_path):
    from concurrent.futures import Future
    future = Future()
    window.bridge._job.emit(("write_text", {"text": "late", "x": 10, "y": 400}, future))
    count = len(window.canvas.note.strokes)
    window.close()
    assert future.result(timeout=1)["strokes_added"] > 0
    saved = json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))
    assert len(saved["subjects"][0]["sections"][0]["pages"][0]["strokes"]) > count
    assert window.bridge is None and not (tmp_path / "bridge.json").exists()


# Operations ------------------------------------------------------------------

def test_read_page_renders_content_as_png(window):
    result = window.ai.read_page()
    image = QImage.fromData(base64.b64decode(result["png_base64"]), "PNG")
    region = result["region"]
    assert not image.isNull() and not result["empty"]
    assert image.width() == pytest.approx(region["width"] * result["scale"], abs=1)
    assert region["x"] <= 40 and region["x"] + region["width"] >= 120
    # The ink is dark where the stroke passes.
    px = int((80 - region["x"]) * result["scale"])
    py = int((65 - region["y"]) * result["scale"])
    assert QImage.fromData(base64.b64decode(result["png_base64"])).pixelColor(px, py).lightness() < 128


def test_read_page_explicit_rect_and_view(window):
    result = window.ai.read_page(x=0, y=0, width=50, height=25)
    assert result["region"] == {"x": 0, "y": 0, "width": 50, "height": 25} and result["scale"] == 2.0
    view = window.ai.read_page(area="view")["region"]
    assert view["width"] == pytest.approx(window.canvas.visible_rect().width())
    with pytest.raises(BridgeError):
        window.ai.read_page(x=0, y=0, width=10)


def test_write_text_adds_ink_as_one_undo_step_and_saves(window, tmp_path):
    before = len(window.canvas.note.strokes)
    result = window.ai.write_text("Hola", 200, 100, size=30, color="#b73535")
    note = window.canvas.note
    assert result["strokes_added"] == len(note.strokes) - before > 0
    assert all(s.color == "#b73535" for s in note.strokes[before:])
    assert result["bounds"]["x"] >= 195 and result["bounds"]["y"] >= 95
    saved = json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))
    stored = saved["subjects"][0]["sections"][0]["pages"][0]["strokes"]
    assert len(stored) == len(note.strokes)
    window.undo()
    assert len(window.canvas.note.strokes) == before


def test_write_to_page_that_is_not_open(window):
    page2 = window.library.subjects[0].sections[0].pages
    window.new_page()  # Opens "Page 2"; Page 1 is now in the background.
    first = window.library.subjects[0].sections[0].pages[0]
    window.ai.draw_shape("rectangle", 10, 10, 60, 40, page_id=first.id)
    assert len(first.note.strokes) == 2 and window.canvas.note is not first.note
    assert not window.ai.read_page(page_id=first.id)["empty"]
    assert len(page2) == 2


def test_read_page_rejects_huge_rectangles_quickly(window):
    started = time.monotonic()
    with pytest.raises(BridgeError, match="limited"):
        window.ai.read_page(x=0, y=0, width=1e308, height=1e308)
    big = window.ai.read_page(x=0, y=0, width=20000, height=20000)  # Largest allowed: grid skipped.
    assert big["scale"] < .1 and time.monotonic() - started < 5


def test_draw_strokes_and_validation(window):
    result = window.ai.draw_strokes([{"points": [[0, 0], [10, 10]], "color": "#237346", "width": 2}])
    assert result["strokes_added"] == 1 and window.canvas.note.strokes[-1].color == "#237346"
    for bad in ([], [{"points": "x"}], [{"points": [[0, 0]], "color": "red"}]):
        with pytest.raises(BridgeError):
            window.ai.handle("draw_strokes", {"strokes": bad})
    with pytest.raises(BridgeError):
        window.ai.handle("draw_shape", {"kind": "star", "x1": 0, "y1": 0, "x2": 1, "y2": 1})
    with pytest.raises(BridgeError):
        window.ai.handle("nope", {})


def test_no_open_page_needs_page_id(qt, tmp_path):
    widget = LapiceroWindow(library_path=tmp_path / "empty.json")
    try:
        with pytest.raises(BridgeError, match="No page is open"):
            widget.ai.read_page()
    finally:
        widget.close()


def test_text_strokes_wrap_lines():
    one = text_strokes("abc def ghi", 0, 0, size=20)
    wrapped = text_strokes("abc def ghi", 0, 0, size=20, max_width=40)
    top = lambda strokes: max(y for s in strokes for _, y in s.points)
    assert top(wrapped) > top(one) + 20
    with pytest.raises(ValueError):
        text_strokes("   ", 0, 0)


# Ask Claude ------------------------------------------------------------------

def drag(canvas, start, end):
    for kind, (x, y) in (("Press", start), ("Move", end), ("Release", end)):
        etype = {"Press": QEvent.Type.MouseButtonPress, "Move": QEvent.Type.MouseMove,
                 "Release": QEvent.Type.MouseButtonRelease}[kind]
        button = Qt.MouseButton.NoButton if kind == "Move" else Qt.MouseButton.LeftButton
        buttons = Qt.MouseButton.NoButton if kind == "Release" else Qt.MouseButton.LeftButton
        point = QPointF(x, y)
        event = QMouseEvent(etype, point, point, point, button, buttons, Qt.KeyboardModifier.NoModifier,
                            Qt.MouseEventSource.MouseEventNotSynthesized)
        getattr(canvas, f"mouse{kind}Event")(event)


def test_ask_tool_emits_dragged_region_without_adding_ink(window):
    regions = []
    window.canvas.region_requested.connect(regions.append)
    window.canvas.region_requested.disconnect(window.ask_about)
    window.ask_button.click()
    before = list(window.canvas.note.strokes)
    drag(window.canvas, (30, 30), (130, 100))
    drag(window.canvas, (5, 5), (7, 7))  # Too small: ignored.
    assert regions == [QRectF(30, 30, 100, 70)] and window.canvas.note.strokes == before


FAKE_CLAUDE = r'''
import base64, json, os, sys
args = sys.argv[1:]
config = json.load(open(args[args.index("--mcp-config") + 1], encoding="utf-8"))
server = config["mcpServers"]["lapicero"]
sys.path.insert(0, server["env"]["PYTHONPATH"])
os.environ.update(server["env"])
message = json.loads(sys.stdin.readline())["message"]
*image, text = message["content"]
suffix = ""
if image:
    png = base64.b64decode(image[0]["source"]["data"])
    assert png.startswith(b"\x89PNG")
else:
    suffix += " (no image)"
assert "--setting-sources" in args and "--no-session-persistence" not in args
flags = {name: args[args.index(name) + 1] for name in ("--model", "--effort") if name in args}
resume = args[args.index("--resume") + 1] if "--resume" in args else None
if resume:
    suffix += " (resumed %s)" % resume
import time
time.sleep(float(os.environ.get("FAKE_DELAY", "0")))  # Lets a test act while Claude is "thinking".
from lapicero.mcp_server import call  # The writing tools still reach the app.
pages = call("list_pages")["subjects"][0]["sections"][0]["pages"]
session = os.environ.get("FAKE_SESSION", "session-1")
print(json.dumps({"type": "system", "subtype": "init", "session_id": session}))
print(json.dumps({"type": "result", "is_error": False, "session_id": session,
                  "result": "Saw %r, %d pages, flags %r%s" % (text["text"].split("\n")[1], len(pages), flags,
                                                              suffix)}))
'''


def page_html(qt, panel):
    """The answers page's rendered HTML, once it has loaded and drawn the conversation."""
    box = {}
    wait_for(qt, lambda: panel._page_ready)
    panel.view.page().runJavaScript("document.getElementById('thread').innerHTML", 0,
                                    lambda html: box.setdefault("html", html))
    wait_for(qt, lambda: "html" in box)
    return box["html"]


def wait_for(qt, condition, timeout=30):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        qt.processEvents()
        time.sleep(.01)
    assert condition()


def test_ask_runs_claude_with_question_on_stdin_and_shows_answer(qt, window, tmp_path, monkeypatch):
    fake = tmp_path / "fake_claude.py"
    fake.write_text(FAKE_CLAUDE, encoding="utf-8")
    window.claude_program = [sys.executable, str(fake)]
    assert window.ask_about(QRectF(30, 30, 100, 70)) is None  # Opens the prompt beside the region.
    window.ask_prompt.input.setPlainText("¿Qué es \"esto\"?")
    QTest.keyClick(window.ask_prompt.input, Qt.Key.Key_Return)
    ask_id = window.ask_panel.entries[-1][0]
    assert not window.ask_prompt.isVisible() and window.canvas.pending_region is None
    assert window.ask_panel.isVisible() and window.ask_panel.answer(ask_id) is None
    wait_for(qt, lambda: window.ask_panel.answer(ask_id) is not None)
    answer = window.ask_panel.answer(ask_id)
    assert answer == "Saw '¿Qué es \"esto\"?', 1 pages, flags {}"
    assert "Error" not in window.ask_panel.plain_text()
    config = json.loads((tmp_path / "claude-mcp.json").read_text(encoding="utf-8"))
    assert config["mcpServers"]["lapicero"]["env"]["LAPICERO_BRIDGE"] == str(tmp_path / "bridge.json")


def test_ask_passes_chosen_model_and_effort_and_remembers_them(qt, window, tmp_path):
    fake = tmp_path / "fake_claude.py"
    fake.write_text(FAKE_CLAUDE, encoding="utf-8")
    window.claude_program = [sys.executable, str(fake)]
    window.ask_model_combo.setCurrentIndex(window.ask_model_combo.findData("haiku"))
    window.ask_effort_combo.setCurrentIndex(window.ask_effort_combo.findData("low"))
    ask_id = window.ask_about(QRectF(0, 0, 50, 50), question="hi")
    wait_for(qt, lambda: window.ask_panel.answer(ask_id) is not None)
    assert window.ask_panel.answer(ask_id).endswith("{'--model': 'haiku', '--effort': 'low'}")
    settings = json.loads((tmp_path / "ui.json").read_text(encoding="utf-8"))
    assert settings["ask_model"] == "haiku" and settings["ask_effort"] == "low"
    reopened = LapiceroWindow(library_path=tmp_path / "library.json")
    try:
        assert reopened.ask_model_combo.currentData() == "haiku"
        assert reopened.ask_effort_combo.currentData() == "low"
        assert reopened.toolbar_size == settings["toolbar_size"]
    finally:
        reopened.library._saved = reopened.library._data()
        reopened.close()


def test_ask_timeout_message_is_shown(qt, window, tmp_path, monkeypatch):
    import lapicero.ask as ask_module
    monkeypatch.setattr(ask_module, "ASK_TIMEOUT_MS", 300)
    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    window.claude_program = [sys.executable, str(sleeper)]
    ask_id = window.ask_about(QRectF(0, 0, 50, 50), question="hi")
    wait_for(qt, lambda: window.ask_panel.answer(ask_id) is not None)
    assert "more than 5 minutes" in window.ask_panel.answer(ask_id)


def test_ask_reports_missing_claude(qt, window, monkeypatch):
    window.claude_program = str(Path(os.devnull).parent / "definitely-missing-claude.exe")
    ask_id = window.ask_about(QRectF(0, 0, 50, 50), question="hi")
    wait_for(qt, lambda: window.ask_panel.answer(ask_id) is not None)
    assert "not found" in window.ask_panel.answer(ask_id)


def test_cancelled_question_does_nothing(qt, window):
    window.ask_about(QRectF(0, 0, 50, 50))
    window.ask_prompt.input.setPlainText("never sent")
    QTest.keyClick(window.ask_prompt.input, Qt.Key.Key_Escape)
    assert not window.ask_prompt.isVisible() and window.canvas.pending_region is None
    assert window.ask_panel.entries == []
    window.ask_about(QRectF(0, 0, 50, 50))
    window.ask_prompt.send_button.click()  # Empty question: nothing is sent, the box stays.
    assert window.ask_prompt.isVisible() and window.ask_panel.entries == []
    window._escape()
    assert not window.ask_prompt.isVisible()


def test_ask_prompt_marks_the_region_and_sits_beside_it(qt, window, monkeypatch):
    from PySide6.QtCore import QPoint
    window.resize(1400, 900)
    qt.processEvents()
    region = QRectF(80, 160, 200, 120)
    window.ask_about(region)
    qt.processEvents()
    assert window.canvas.pending_region == region and window.ask_prompt.isVisible()
    assert window.ask_prompt.input.hasFocus() or not window.isActiveWindow()
    origin = window.canvas.mapTo(window.centralWidget(), QPoint(0, 0))
    marked = window.canvas.to_widget(region).translated(origin.x(), origin.y())
    assert window.ask_prompt.x() >= marked.right() and not window.ask_prompt.geometry().intersects(marked.toRect())
    QTest.keyClick(window.ask_prompt.input, Qt.Key.Key_A)
    QTest.keyClick(window.ask_prompt.input, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.ask_prompt.isVisible() and window.ask_prompt.input.toPlainText() == "a\n"
    names = iter(["Other page"])
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (next(names), True))
    window.tree.setCurrentItem(window.tree.topLevelItem(0).child(0))
    window.new_page()  # Switching pages drops the prompt and its mark.
    assert not window.ask_prompt.isVisible() and window.canvas.pending_region is None


# MCP server end to end ---------------------------------------------------------

def test_mcp_server_over_stdio_lists_tools_and_reads_page(qt, window, tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "lapicero.mcp_server"],
                                   env={**os.environ, "PYTHONPATH": str(ROOT),
                                        "LAPICERO_BRIDGE": str(tmp_path / "bridge.json")})

    async def session():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = {tool.name for tool in (await client.list_tools()).tools}
                page = await client.call_tool("read_page", {})
                wrote = await client.call_tool("write_text", {"text": "hi", "x": 300, "y": 300})
                return tools, page, wrote

    tools, page, wrote = pump(qt, lambda: asyncio.run(session()), timeout=60)
    assert tools == {"list_pages", "read_page", "write_text", "draw_shape", "draw_strokes", "get_ask"}
    kinds = [block.type for block in page.content]
    assert kinds == ["text", "image"] and not page.is_error
    assert json.loads(page.content[0].text)["page_name"] == "Page 1"
    assert not wrote.is_error and json.loads(wrote.content[0].text)["strokes_added"] > 0


def test_mcp_call_without_running_app_explains(tmp_path, monkeypatch):
    from lapicero import mcp_server
    monkeypatch.setenv("LAPICERO_BRIDGE", str(tmp_path / "missing.json"))
    with pytest.raises(RuntimeError, match="not running"):
        mcp_server.call("list_pages")


def test_slow_claude_start_does_not_freeze_the_window(qt, window, tmp_path, monkeypatch):
    import lapicero.ask as ask_module
    fake = tmp_path / "fake_claude.py"
    fake.write_text(FAKE_CLAUDE, encoding="utf-8")
    window.claude_program = [sys.executable, str(fake)]
    real_popen = ask_module.subprocess.Popen

    def slow_popen(*args, **kwargs):  # Spawning claude.exe takes seconds on some machines.
        time.sleep(1.5)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(ask_module.subprocess, "Popen", slow_popen)
    started = time.monotonic()
    ask_id = window.ask_about(QRectF(0, 0, 50, 50), question="hi")
    assert time.monotonic() - started < .5
    assert window.ask_panel.isVisible() and "Thinking" in window.ask_panel.plain_text()
    wait_for(qt, lambda: window.ask_panel.answer(ask_id) is not None)
    assert window.ask_panel.answer(ask_id).startswith("Saw 'hi'")


def test_follow_up_without_an_area_continues_the_conversation(qt, window, tmp_path, monkeypatch):
    fake = tmp_path / "fake_claude.py"
    fake.write_text(FAKE_CLAUDE, encoding="utf-8")
    window.claude_program = [sys.executable, str(fake)]
    monkeypatch.setenv("FAKE_SESSION", "session-1")
    first = window.ask_about(QRectF(0, 0, 50, 50), question="what is this?")
    assert not window.ask_panel.input.isEnabled()  # One question at a time per conversation.
    wait_for(qt, lambda: window.ask_panel.answer(first) is not None)
    assert window.ask_panel.input.isEnabled()
    window.ask_panel.input.setPlainText("and why?")
    QTest.keyClick(window.ask_panel.input, Qt.Key.Key_Return)
    second = window.ask_panel.entries[-1][0]
    assert window.ask_panel.input.toPlainText() == ""
    wait_for(qt, lambda: window.ask_panel.answer(second) is not None)
    assert window.ask_panel.answer(second) == "Saw 'and why?', 1 pages, flags {} (no image) (resumed session-1)"
    assert [entry[2] for entry in window.ask_panel.entries] == ["what is this?", "and why?"]


def test_question_without_an_area_or_open_page_starts_a_conversation(qt, window, tmp_path):
    fake = tmp_path / "fake_claude.py"
    fake.write_text(FAKE_CLAUDE, encoding="utf-8")
    window.claude_program = [sys.executable, str(fake)]
    window._page_id = None
    ask_id = window.ask_text("what is a derivative?")
    wait_for(qt, lambda: window.ask_panel.answer(ask_id) is not None)
    assert window.ask_panel.answer(ask_id) == "Saw 'what is a derivative?', 1 pages, flags {} (no image)"
    assert window.ask_panel.entries[-1][1] is None and window.ask_panel.entries[-1][5] is None


def test_new_chat_clears_the_panel_and_does_not_resume(qt, window, tmp_path):
    fake = tmp_path / "fake_claude.py"
    fake.write_text(FAKE_CLAUDE, encoding="utf-8")
    window.claude_program = [sys.executable, str(fake)]
    first = window.ask_text("one")
    wait_for(qt, lambda: window.ask_panel.answer(first) is not None)
    window.ask_panel.new_chat_button.click()
    assert window.ask_panel.entries == [] and not window.ask_panel.new_chat_button.isEnabled()
    second = window.ask_text("two")
    wait_for(qt, lambda: window.ask_panel.answer(second) is not None)
    assert window.ask_panel.answer(second) == "Saw 'two', 1 pages, flags {} (no image)"


def test_ask_button_opens_the_chat_panel(qt, window):
    window.ask_button.click()
    assert window.canvas.mode == "ask" and window.ask_panel.isVisible()


def test_answers_render_latex_and_markdown_without_raw_html(qt, window):
    panel = window.ask_panel
    panel.add_question("a1", "Page 1", "integral of $x$?", png=None)
    panel.set_answer("a1", r"**Yes**: $\int x\,dx = \frac{x^2}{2}$" "\n\n" r"$$e^{i\pi}+1=0$$" "\n\n"
                           "`$not math$` <script>alert(1)</script>")
    html = page_html(qt, panel)
    assert "<strong>Yes</strong>" in html
    assert html.count('class="katex"') >= 3 and 'class="katex-display"' in html  # Question, inline, display.
    assert "<code>$not math$</code>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html


def fake_claude(window, tmp_path):
    fake = tmp_path / "fake_claude.py"
    fake.write_text(FAKE_CLAUDE, encoding="utf-8")
    window.claude_program = [sys.executable, str(fake)]


def menu_chats(window):
    return [action for action in window.history_menu().actions() if action.isEnabled()]


def test_chats_are_saved_per_page_and_listed_newest_first(qt, window, tmp_path, monkeypatch):
    fake_claude(window, tmp_path)
    assert [a.text() for a in window.history_menu().actions()] == ["No chats on this page yet"]
    monkeypatch.setenv("FAKE_SESSION", "session-a")
    first = window.ask_about(QRectF(0, 0, 50, 50), question="first chat")
    wait_for(qt, lambda: window.ask_panel.answer(first) is not None)
    window.new_chat()
    monkeypatch.setenv("FAKE_SESSION", "session-b")
    second = window.ask_text("second chat")
    wait_for(qt, lambda: window.ask_panel.answer(second) is not None)
    titles = [action.text().split("  ·  ")[0] for action in menu_chats(window)]
    assert titles == ["second chat", "first chat"]
    assert [action.isChecked() for action in menu_chats(window)] == [True, False]
    files = sorted((tmp_path / "chats").glob("*.json"))
    assert len(files) == 2
    saved = {json.loads(path.read_text(encoding="utf-8"))["session_id"]: json.loads(path.read_text(encoding="utf-8"))
             for path in files}
    assert saved["session-a"]["entries"][0]["image"].startswith("data:image/png;base64,")
    assert saved["session-b"]["entries"][0]["answer"].startswith("Saw 'second chat'")
    window.new_page()  # Another page has its own, empty history.
    assert menu_chats(window) == []


def test_reopened_chat_shows_its_messages_and_continues_its_session(qt, window, tmp_path, monkeypatch):
    fake_claude(window, tmp_path)
    monkeypatch.setenv("FAKE_SESSION", "session-a")
    first = window.ask_text("old question")
    wait_for(qt, lambda: window.ask_panel.answer(first) is not None)
    window.new_chat()
    assert window.ask_panel.entries == []
    menu_chats(window)[0].trigger()
    assert [entry[2] for entry in window.ask_panel.entries] == ["old question"]
    follow = window.ask_text("and then?")
    wait_for(qt, lambda: window.ask_panel.answer(follow) is not None)
    assert window.ask_panel.answer(follow).endswith("(resumed session-a)")
    assert len(list((tmp_path / "chats").glob("*.json"))) == 1  # Same chat, not a new one.


def test_history_survives_restart_and_marks_interrupted_questions(qt, window, tmp_path):
    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    window.claude_program = [sys.executable, str(sleeper)]
    page_id = window.current_page_id
    window.ask_text("never answered")
    window.stop_bridge()  # Closing the app stops the question.
    reopened = LapiceroWindow(library_path=tmp_path / "library.json")
    try:
        reopened._page_id = page_id  # History lists the open page's chats.
        actions = [a for a in reopened.history_menu().actions() if a.isEnabled()]
        assert [a.text().split("  ·  ")[0] for a in actions] == ["never answered"]
        actions[0].trigger()
        entry = reopened.ask_panel.entries[0]
        assert entry[3] == "No answer: the question was interrupted." and entry[4] is True
        assert reopened.ask_panel.input.isEnabled()  # Not stuck waiting forever.
    finally:
        reopened.library._saved = reopened.library._data()
        reopened.close()


def test_damaged_chat_file_does_not_hide_the_others(tmp_path):
    from lapicero.chats import ChatStore, new_chat
    store = ChatStore(tmp_path)
    chat = new_chat("page-1")
    chat["entries"] = [{"question": "kept", "answer": "yes", "error": False}]
    store.save(chat)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    reloaded = ChatStore(tmp_path)
    assert [c["id"] for c in reloaded.for_page("page-1")] == [chat["id"]]
    assert reloaded.load_errors and reloaded.load_errors[0].startswith("broken.json")
    assert not list(tmp_path.glob("*.tmp"))


def test_switching_chats_keeps_the_pending_question_running(qt, window, tmp_path, monkeypatch):
    fake_claude(window, tmp_path)
    monkeypatch.setenv("FAKE_SESSION", "session-slow")
    monkeypatch.setenv("FAKE_DELAY", "1.5")
    slow = window.ask_text("slow question")
    window.new_chat()  # Leave while Claude is still answering.
    monkeypatch.setenv("FAKE_DELAY", "0")
    monkeypatch.setenv("FAKE_SESSION", "session-other")
    other = window.ask_text("other question")
    wait_for(qt, lambda: window.ask_panel.answer(other) is not None)
    assert [entry[2] for entry in window.ask_panel.entries] == ["other question"]  # Not mixed in.
    old = next(chat for chat in window.chat_store.chats.values() if chat["session_id"] != "session-other")
    wait_for(qt, lambda: old["entries"][0]["answer"] is not None)
    assert old["entries"][0]["answer"].startswith("Saw 'slow question'") and not old["entries"][0]["error"]
    assert old["session_id"] == "session-slow"
    saved = json.loads((tmp_path / "chats" / f"{old['id']}.json").read_text(encoding="utf-8"))
    assert saved["entries"][0]["answer"] == old["entries"][0]["answer"]
    window.open_chat(old["id"])
    assert window.ask_panel.answer(slow).startswith("Saw 'slow question'")


def test_reopening_a_chat_while_it_is_answering_shows_the_answer_when_it_arrives(qt, window, tmp_path, monkeypatch):
    fake_claude(window, tmp_path)
    monkeypatch.setenv("FAKE_DELAY", "1.5")
    slow = window.ask_text("slow question")
    chat_id = window._chat_record["id"]
    window.new_chat()
    window.open_chat(chat_id)
    assert window.ask_panel.answer(slow) is None and not window.ask_panel.input.isEnabled()  # Still thinking.
    wait_for(qt, lambda: window.ask_panel.answer(slow) is not None)
    assert window.ask_panel.answer(slow).startswith("Saw 'slow question'")
