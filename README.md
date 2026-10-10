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

The virtual environment keeps dependencies out of the global Python installation. To run the tests (including offscreen Qt UI checks):

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python -m pytest -q
Remove-Item Env:QT_QPA_PLATFORM
```

## Organize and draw

The left tree holds **subjects → sections → pages**. Use New subject, New section (under the selected subject), and New page (in the selected or containing section). Rename selected changes the highlighted item. Select a page to draw. Each page is an **infinite canvas** that grows right and down: scroll with the wheel (Shift+wheel sideways, middle-button drag to pan, or the scrollbars), zoom with Ctrl+wheel, and reset zoom with Ctrl+0.

A compact toolbar floats over the top center of the page, like OneNote's, so the page uses the whole window (there is no bottom status bar). Hover its edge for a shortcut list. Its right end shows **Saved** or, in red, **Not saved** (hover for details). Tools:

- **Sidebar** toggle, **Undo** / **Redo**.
- **Lasso select**: draw a free loop around ink; strokes mostly inside are selected (tap a stroke, shape or picture to select just it). Selected ink gets a gray halo inside a dashed frame with eight handles and a rotate handle, like OneNote: drag inside to move; drag a side handle to stretch one direction; drag a corner to deform freely (Shift keeps proportions; pictures always keep them); drag the round handle above to rotate (Shift snaps to 15°). Each change is one undo step. Delete removes the selection; Ctrl+C / Ctrl+V copy and paste it (also into another page); Esc clears it.
- **Eraser**: removes whole strokes; each drag is one undo step. A tablet pen's eraser end erases with any tool.
- **Pens**: four pens and two highlighters (translucent). Click the active pen again (or right-click any pen) to change its color (10 swatches) and width (1–40). Each pen keeps its own settings for the session. With a tablet pen, the four pens follow pen pressure: a light touch draws thinner and a firm press slightly bolder than the chosen width (mouse ink, highlighters and shapes keep an even width).
- **Shapes**: drag to draw a line, arrow, rectangle, ellipse, or triangle. The new shape stays selected with its handles, so you can stretch or rotate it right away; drag outside it to draw the next one; the arrow next to the button picks the kind. Freehand ink still snaps to a clean circle, triangle, square, rectangle, or arrow if you hold the pointer still at the endpoint for about 0.5 seconds.
- **Pictures**: Ctrl+V pastes a picture from the clipboard (Snipping Tool / Win+Shift+S captures, "Copy image" in a browser such as Google Images) or an image file copied in Explorer. It lands near the top-left of the view, shrunk to fit if large, and selected. Pictures always sit **below** the ink, so you can write over them; the eraser never removes them. With the lasso, tap a picture to select it, drag to move, drag the blue corner handle to resize (keeps proportions), Delete to remove, Ctrl+C / Ctrl+V to duplicate. Pictures are saved as PNG files in an `images` folder next to `library.json` (keep both together when backing up).
- **Settings** (bottom of the sidebar): **Page paper** is grid or plain, saved per page. New pages start with grid paper; pages created before this option keep plain paper.
- **Toolbar size** (sidebar Settings): small / medium / large; the choice is remembered in `ui.json` next to `library.json`. While the pen (or any tool) is down, the toolbar fades so the ink below stays visible.
- **Fullscreen** (F11): hides the sidebar; Esc or F11 leaves it.

Ink, eraser, undo/redo, move and paste changes auto-save about 1.2 seconds after you pause (never while the pen is down), so writing never waits for the disk; the toolbar shows **Saving…** until then. Imports and hierarchy changes save at once. Ctrl+S and closing the window save immediately. A crash or power cut can lose at most the strokes from that last moment. By default, it lives at `Documents\Lapicero\library.json` under your user profile; the folder is created when saving. The library format (`{"version":1,"subjects":[...]}`) is **separate** from standalone v1 notes. To bring an old `{"version":1,"strokes":[...]}` JSON note into this library, highlight a section or one of its pages and choose **Import old note…** (or Ctrl+O). Import copies ink into a new page and never modifies or deletes the source. Ink outside the page is proportionally scaled and centered. Do not point the library at a standalone note or another existing unowned file: it will refuse to overwrite it. A corrupt library will likewise remain untouched; keep a backup and resolve the target before trying to save.

If saving fails, the app keeps changes in memory, shows a bounded warning and a persistent status message, and offers Save, Discard, or Cancel on close while changes remain. Cancel keeps the window open; Discard explicitly abandons unsaved work. This is local storage, not synchronization or multi-process editing.

| Shortcut | Behavior |
| --- | --- |
| `P` / `E` / `L` / `S` | Last pen / eraser / lasso / shapes, **only with canvas focus** |
| `Ctrl+Up` / `Ctrl+Down` | Increase / decrease the active pen width by one (clamped 1–40), **only with canvas focus** |
| `Delete` / `Esc` | Delete / clear the lasso selection |
| `Ctrl+C` / `Ctrl+V` | Copy the lasso selection / paste it, or paste a clipboard picture or copied image file (selected, one undo step); works across pages |
| `F11` | Toggle fullscreen (`Esc` also leaves it) |
| `Ctrl+wheel` / `Ctrl+0` | Zoom / reset zoom |
| `Ctrl+Z` / `Ctrl+Y` | Undo / redo on the selected page; no effect without a page |
| `Ctrl+N` | New page in the selected or containing section; no effect without a section |
| `Ctrl+O` | Import a standalone v1 note into the selected or containing section; no effect without a section |
| `Ctrl+S` | Save/retry the current library |

Click the page for canvas focus. The window shortcuts work while navigating the tree; modal name/file dialogs do not activate canvas shortcuts. No legacy file is automatically opened, converted, or overwritten.
