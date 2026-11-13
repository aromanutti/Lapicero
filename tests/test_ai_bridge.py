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
image, text = message["content"]
png = base64.b64decode(image["source"]["data"])
assert png.startswith(b"\x89PNG") and "--setting-sources" in args
flags = {name: args[args.index(name) + 1] for name in ("--model", "--effort") if name in args}
from lapicero.mcp_server import call  # The writing tools still reach the app.
pages = call("list_pages")["subjects"][0]["sections"][0]["pages"]
print(json.dumps({"type": "system", "subtype": "init"}))
print(json.dumps({"type": "result", "is_error": False,
                  "result": "Saw %r, %d pages, flags %r" % (text["text"].split("\n")[1], len(pages), flags)}))
'''


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
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *a, **k: ("¿Qué es \"esto\"?", True))
    ask_id = window.ask_about(QRectF(30, 30, 100, 70))
    assert window.ask_panel.isVisible() and window.ask_panel.answer(ask_id) is None
    wait_for(qt, lambda: window.ask_panel.answer(ask_id) is not None)
    answer = window.ask_panel.answer(ask_id)
    assert answer == "Saw '¿Qué es \"esto\"?', 1 pages, flags {}"
    assert "Error" not in window.ask_panel.browser.toPlainText()
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


def test_cancelled_question_does_nothing(window, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *a, **k: ("", False))
    assert window.ask_about(QRectF(0, 0, 50, 50)) is None and window.ask_panel.entries == []


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
