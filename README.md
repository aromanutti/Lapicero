# Lapicero

Lapicero is a local handwritten-notes app for Windows 10/11. It has no installer, account, cloud sync, or typed text. A mouse works; tablet pen input is supported by Qt, but actual handwriting feel, palm rejection, and device drivers still need a trial on your physical tablet.

## Set up and run (PowerShell)

From this folder, with Python available on your PATH:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip install pytest
.\.venv\Scripts\python main.py
```

For a one-click launch, run `powershell -ExecutionPolicy Bypass -File .\create_shortcut.ps1` once. It adds a **Lapicero** shortcut to the Desktop and Start menu that opens the app without a console window; press **Ctrl+Alt+L** to open it from anywhere, or pin it to the taskbar and use **Win+number**.

The virtual environment keeps dependencies out of the global Python installation. To run the tests (including offscreen Qt UI checks):

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python -m pytest -q
Remove-Item Env:QT_QPA_PLATFORM
```

## Organize and draw

The left tree holds **subjects → sections → pages**. Create items with the **+** button at the top of the sidebar (New subject, New section, New page in the selected or containing section), or right-click the tree for the same commands plus Rename and Delete section. The search box filters the tree by name, keeping each match's subject and section visible. New section with a subject selected adds a top-level section; with a section or page selected it adds a **subsection** inside that section, so sections nest to any depth. Delete section removes the highlighted section with all its pages and subsections after you confirm; it cannot be undone. Rename changes the highlighted item. Select a page to draw. Each page is an **infinite canvas** that grows right and down: scroll with the wheel (Shift+wheel sideways, middle-button drag to pan, or the scrollbars), zoom with Ctrl+wheel, and reset zoom with Ctrl+0.

A compact toolbar floats over the top center of the page, like OneNote's, so the page uses the whole window (there is no bottom status bar). Hover its edge for a shortcut list. Its right end shows **Saved** or, in red, **Not saved** (hover for details). Tools:

- **Sidebar** toggle, **Undo** / **Redo**.
- **Lasso select**: draw a free loop around ink; strokes mostly inside are selected (tap a stroke, shape or picture to select just it). Selected ink gets a gray halo inside a dashed frame with eight handles and a rotate handle, like OneNote: drag inside to move; drag a side handle to stretch one direction; drag a corner to deform freely (Shift keeps proportions; pictures always keep them); drag the round handle above to rotate (Shift snaps to 15°). Each change is one undo step. Delete removes the selection; Ctrl+C / Ctrl+V copy and paste it (also into another page); Esc clears it.
- **Eraser**: removes whole strokes; each drag is one undo step. A tablet pen's eraser end erases with any tool.
- **Pens**: four pens and two highlighters (translucent). Click the active pen again (or right-click any pen) to change its color (10 swatches) and width (1–40). Each pen keeps its own settings for the session. With a tablet pen, the four pens follow pen pressure: a light touch draws thinner and a firm press slightly bolder than the chosen width (mouse ink, highlighters and shapes keep an even width).
- **Pointer**: with a pen or shape tool the pointer is a see-through dot in the ink color, about as wide as the ink (it follows zoom); the eraser shows a ring the size of what it erases. There is no crosshair.
- **Ask Claude** (`A`): drag a box around something on the page; the box stays marked and a small prompt opens beside it. Type your question and press Enter (Shift+Enter for a new line, Esc to cancel). Lapicero runs Claude Code in the background (`claude -p`, with your own Claude sign-in); the answer appears in the **Ask Claude** panel on the right (✕ hides it). Claude sees only the box you drew, and may also write next to it when that helps; that ink is one Ctrl+Z step like any other. Needs [Claude Code](https://claude.com/claude-code) installed and signed in once (run `claude` in a terminal). An answer that takes over 5 minutes is cancelled. **Model** and **Effort** at the bottom of the Ask Claude panel (also in **Settings**) choose who answers and how hard it thinks (lower effort and Haiku/Sonnet answer faster; *Claude Code default* keeps your own choice); both are remembered in `ui.json`. Questions run without your personal Claude Code hooks and plugins, so they start in seconds.
  - **Conversations**: the panel is a chat. Type in the box at its bottom to ask without marking anything, or to follow up on the last answer (Enter sends); marking another area adds that question, with its image, to the same conversation. **New chat** starts over. The clock button lists the chats started on the open page (newest first); pick one to read it again and keep asking in it. Chats are saved one file each in the `chats` folder next to `library.json`, with small copies of the marked areas. Follow-ups resume the same Claude Code session (`claude --resume`), so these sessions are saved by Claude Code like any other.
  - **Math**: answers render Markdown and LaTeX (`$…$` inline, `$$…$$` on its own line) with a bundled copy of KaTeX, so formulas display without internet. Claude is told to write all math in LaTeX.
- **Shapes**: drag to draw a line, arrow, rectangle, ellipse, or triangle. The new shape stays selected with its handles, so you can stretch or rotate it right away; drag outside it to draw the next one; the arrow next to the button picks the kind. Freehand ink snaps to a clean line, integral sign, circle, ellipse, triangle, square, rectangle, or arrow if you hold the pointer still at the endpoint for about 0.5 seconds. Keep the pen down after it snaps to edit it before lifting: lines and arrows pivot on their start, so dragging changes their length and direction; closed shapes grow, shrink, and rotate around their center.
- **Engineering elements**: the button after Shapes draws labeled coordinate axes and symbols. Drag a box: **XY axes** put the origin at its lower left with X right and Y up; **XYZ axes (3D)** draw an oblique right-handed frame with Z up, Y right and X toward you; **Integral** draws a clean ∫ as tall as the box. The arrow next to the button picks the kind. The axes are ordinary ink strokes, added as one undo step and left selected so you can move, stretch or rotate them. A hand-drawn integral sign also snaps to a clean ∫ when you hold the pen still at its end, like the shapes below.
- **Pictures**: Ctrl+V pastes a picture from the clipboard (Snipping Tool / Win+Shift+S captures, "Copy image" in a browser such as Google Images) or an image file copied in Explorer. It lands near the top-left of the view, shrunk to fit if large, and selected. Pictures always sit **below** the ink, so you can write over them; the eraser never removes them. With the lasso, tap a picture to select it, drag to move, drag the blue corner handle to resize (keeps proportions), Delete to remove, Ctrl+C / Ctrl+V to duplicate. Pictures are saved as PNG files in an `images` folder next to `library.json` (keep both together when backing up).
- **Page paper** (Grid / Plain, top right above the page): saved per page. New pages start with grid paper; pages created before this option keep plain paper.
- **Language** (**Settings**): English or Spanish (Español); remembered in `ui.json` and applied the next time Lapicero starts.
- **Toolbar size** (**Settings**, at the bottom of the sidebar): small / medium / large; the choice is remembered in `ui.json` next to `library.json`. While the pen (or any tool) is down, the toolbar fades so the ink below stays visible.
- **Fullscreen** (F11, or the button top right): hides the sidebar; Esc or F11 leaves it.
- **Zoom** pill (bottom right of the page): −, reset to 100%, +.

Ink, eraser, undo/redo, move and paste changes auto-save about 1.2 seconds after you pause (never while the pen is down), so writing never waits for the disk; the toolbar shows **Saving…** until then. Imports and hierarchy changes save at once. Ctrl+S and closing the window save immediately. A crash or power cut can lose at most the strokes from that last moment. By default, it lives at `Documents\Lapicero\library.json` under your user profile; the folder is created when saving. The library format (`{"version":1,"subjects":[...]}`) is **separate** from standalone v1 notes. To bring an old `{"version":1,"strokes":[...]}` JSON note into this library, highlight a section or one of its pages and choose **Import old note…** (or Ctrl+O). Import copies ink into a new page and never modifies or deletes the source. Ink outside the page is proportionally scaled and centered. Do not point the library at a standalone note or another existing unowned file: it will refuse to overwrite it. A corrupt library will likewise remain untouched; keep a backup and resolve the target before trying to save.

If saving fails, the app keeps changes in memory, shows a bounded warning and a persistent status message, and offers Save, Discard, or Cancel on close while changes remain. Cancel keeps the window open; Discard explicitly abandons unsaved work. This is local storage, not synchronization or multi-process editing.

| Shortcut | Behavior |
| --- | --- |
| `P` / `E` / `L` / `S` / `A` | Last pen / eraser / lasso / shapes / Ask Claude, **only with canvas focus** |
| `Ctrl+Up` / `Ctrl+Down` | Increase / decrease the active pen width by one (clamped 1–40), **only with canvas focus** |
| `Delete` / `Esc` | Delete / clear the lasso selection |
| `Ctrl+C` / `Ctrl+V` | Copy the lasso selection / paste it, or paste a clipboard picture or copied image file (selected, one undo step); works across pages |
| `F11` | Toggle fullscreen (`Esc` also leaves it) |
| `Ctrl+wheel` / `Ctrl+0` | Zoom / reset zoom |
| `Ctrl+Z` / `Ctrl+Y` | Undo / redo on the selected page; no effect without a page |
| `Ctrl+N` | New page in the selected or containing section; no effect without a section |
| `Ctrl+O` | Import a standalone v1 note into the selected or containing section; no effect without a section |
| `Ctrl+S` | Save/retry the current library |

## Connect AI tools (MCP)

While Lapicero is open, AI apps that speak MCP (Claude Code, Claude Desktop, and others) can look at your pages and write on them through the `lapicero` MCP server. Its tools:

| Tool | What it does |
| --- | --- |
| `list_pages` | Subjects → nested sections → pages, with ids, and which page is open |
| `read_page` | A page (or what you are looking at, or any rectangle) as an image |
| `write_text` | Writes text as handwriting-style ink at a position |
| `draw_shape` / `draw_strokes` | Draws a line, arrow, rectangle, ellipse, triangle, or freehand strokes |
| `get_ask` | A question asked with **Ask Claude**, with the selected area as an image |

Everything an AI writes is ordinary ink: Ctrl+Z removes each tool call in one step, and it is autosaved. To add the server to Claude Code (PowerShell, from this folder):

```powershell
claude mcp add lapicero --scope user -e PYTHONPATH="$PWD" -- "$PWD\.venv\Scripts\python.exe" -m lapicero.mcp_server
```

Other apps take the same command (`<this folder>\.venv\Scripts\python.exe -m lapicero.mcp_server`) with the environment variable `PYTHONPATH=<this folder>`.

How it connects: on start, Lapicero opens a bridge on `127.0.0.1` only (a random port) and writes the port and a random secret to `bridge.json` next to `library.json`; the MCP server needs that secret, so other computers and web pages cannot use it. The file is removed when Lapicero closes. To keep the bridge off, start Lapicero with the environment variable `LAPICERO_AI_BRIDGE=0` (Ask Claude then starts it only when you ask). Any program running under your Windows account can read `bridge.json`, just as it can read `library.json`.

Click the page for canvas focus. The window shortcuts work while navigating the tree; modal name/file dialogs do not activate canvas shortcuts. No legacy file is automatically opened, converted, or overwritten.
