"""MCP server (stdio) that lets AI clients see and write ink in a running Lapicero.

Run with ``python -m lapicero.mcp_server``. It imports no Qt: every tool forwards
to the open app through its loopback bridge (port and token from bridge.json).
"""

import base64
import json
from pathlib import Path
import urllib.error
import urllib.request

from mcp.server.mcpserver import Image, MCPServer

from .paths import bridge_info_path


TIMEOUT = 70.0
NOT_RUNNING = "Lapicero is not running (or its AI bridge is off). Open Lapicero and try again."

INSTRUCTIONS = """Lapicero is a handwritten-notes app: Subjects > Sections > Pages, each page an infinite canvas.
Sections can contain nested subsections.
Coordinates are document units (x grows right, y grows down; 1 unit = 1 pixel at 100% zoom).
Use list_pages to find pages, read_page to see one as an image (the result says which document
rectangle the image covers and its scale, so image pixel (px, py) is document
(region.x + px / scale, region.y + py / scale)). write_text, draw_shape and draw_strokes add ink;
each call is one undo step the user can revert with Ctrl+Z. Write next to existing ink, never over it,
unless the user asks."""

server = MCPServer("lapicero", instructions=INSTRUCTIONS)
# Never route loopback calls (or the token) through a configured HTTP proxy.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(method, **params):
    """Forward one call to the running app and return its result."""
    path = bridge_info_path()
    try:
        info = json.loads(Path(path).read_text(encoding="utf-8"))
        port, token = int(info["port"]), str(info["token"])
    except (OSError, ValueError, KeyError, TypeError):
        raise RuntimeError(NOT_RUNNING) from None
    body = json.dumps({"method": method, "params": {k: v for k, v in params.items() if v is not None}})
    request = urllib.request.Request(f"http://127.0.0.1:{port}/rpc", data=body.encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {token}"})
    try:
        with _opener.open(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))["result"]
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read().decode("utf-8"))["error"]
        except (ValueError, KeyError, UnicodeError):
            message = f"Lapicero answered HTTP {exc.code}"
        raise RuntimeError(message) from None
    except (urllib.error.URLError, OSError):
        raise RuntimeError(NOT_RUNNING) from None


def _with_image(result):
    data = base64.b64decode(result.pop("png_base64"))
    return [json.dumps(result, ensure_ascii=False), Image(data=data, format="png")]


@server.tool(structured_output=False)
def list_pages() -> str:
    """List subjects, nested sections and pages (ids, names, stroke counts) and which page is open."""
    return json.dumps(call("list_pages"), ensure_ascii=False)


@server.tool(structured_output=False)
def read_page(page_id: str | None = None, area: str = "content", x: float | None = None,
              y: float | None = None, width: float | None = None, height: float | None = None) -> list:
    """See a page as a PNG image.

    page_id defaults to the page open in Lapicero. area="content" shows all ink on the page;
    area="view" shows what the user currently sees. Pass x, y, width and height (document units)
    to look at a specific rectangle instead.
    """
    return _with_image(call("read_page", page_id=page_id, area=area, x=x, y=y, width=width, height=height))


@server.tool(structured_output=False)
def write_text(text: str, x: float, y: float, size: float = 24, color: str = "#205bb5",
               max_width: float | None = None, page_id: str | None = None) -> str:
    """Write text as handwriting-style ink with its top-left corner at (x, y).

    size is the font size in document units (24 matches normal handwriting). color is #RRGGBB.
    max_width wraps long lines. Newlines start new lines. Returns the bounds of the new ink.
    """
    return json.dumps(call("write_text", text=text, x=x, y=y, size=size, color=color,
                           max_width=max_width, page_id=page_id))


@server.tool(structured_output=False)
def draw_shape(kind: str, x1: float, y1: float, x2: float, y2: float, color: str = "#205bb5",
               width: float = 3, page_id: str | None = None) -> str:
    """Draw a line, arrow, rectangle, ellipse or triangle from (x1, y1) to (x2, y2)."""
    return json.dumps(call("draw_shape", kind=kind, x1=x1, y1=y1, x2=x2, y2=y2, color=color,
                           width=width, page_id=page_id))


@server.tool(structured_output=False)
def draw_strokes(strokes: list[dict], page_id: str | None = None) -> str:
    """Draw freehand strokes: [{"points": [[x, y], ...], "color": "#RRGGBB", "width": 3}, ...]."""
    return json.dumps(call("draw_strokes", strokes=strokes, page_id=page_id))


@server.tool(structured_output=False)
def get_ask(ask_id: str) -> list:
    """Get a question the user asked from inside Lapicero: the question, its page, and an image of the
    selected region (with the region's document rectangle and scale)."""
    return _with_image(call("get_ask", ask_id=ask_id))


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
