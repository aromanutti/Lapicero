# AI bridge (MCP connector + Ask Claude)

Objective: let AI clients see and write ink in a running Lapicero, and ask Claude about a region from inside the app.
Branch: `feat/ai-bridge` (from `feat/handwritten-notes`). Delivery: ask-on-risk. Runner: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest -q`.

## Specs

- S1 — "Necesito que armes un MCP/conector para que las Ias puedan interactuar con mi Lapicero. que pueda ver lo que escribo y tambien escribir si asi lo desea." User chose option 1: live bridge to the running app (localhost only), not direct `library.json` writes. AI writes are normal ink: undoable with Ctrl+Z and autosaved.
- S2 — "que dentro de lapicero pueda seleccionar una parte. como un cuadrado y que ademas pueda escribir algo como una pregunta. y esta se mande automaticamente a una sesion de claude y me responda en la app." User chose option 1: the app launches Claude Code headless (`claude -p`) with the Lapicero MCP server attached; the answer is shown inside the app.
- S3 (assumption) — The bridge accepts only loopback connections carrying a random per-run token stored next to the library; other hosts and requests without the token are refused.
- S4 — "Luego necesito que cambies el puntero para escribir a algo como el de one note. que cuando estas sin apretar esta como un puntito asi medio transparente y luego apretas y se escribe y se nota del color del lapiz." and "necesito que saques la cruceta que es molesta y fea". Pen/shape pointer: translucent dot in the pen color sized like the ink; no crosshair in any tool.
- S5 — "probe ask claude . respondio pero tardo una barbaridad de tiempo en una boludez" and "pone que se pueda elegir modelo y esfuerzo si es posible tambien." Ask Claude must start fast; model and effort are selectable and remembered.

## Tasks

| ID | Specs | Route | Status | Evidence |
| --- | --- | --- | --- | --- |
| T1 | S1, S3 | inline | done | Bridge server, main-thread dispatch, page render/read/write operations, text-to-ink |
| T2 | S1 | inline | done | `lapicero/mcp_server.py` stdio MCP server forwarding to the bridge |
| T3 | S2 | inline | done | Ask tool (rectangle + question), `claude -p` launch, answer panel |
| T4 | S1-S5 | inline | done | README, tests, independent verifier (high-risk items 2 and 4) |
| T6 | S5 | inline | done | `--setting-sources project`, image inline via stream-json, model/effort combos in Settings |
| T5 | S4 | inline | done | `tip_cursor` in qt_canvas.py; tests in test_qt_canvas.py |

## Log

- L1 (2026-11-13) — "Necesito que armes un MCP/conector para que las Ias puedan interactuar con mi Lapicero. que pueda ver lo que escribo y tambien escribir si asi lo desea. Se podria implementar?" Answer: "La 1."
- L2 (2026-11-13) — "La 1. Tambien se podria hacer que por ejemplo se pueda hacer una seleccion acompañado de un mensaje dentro de la app? no se si me explico. pero que dentro de lapicero pueda seleccionar una parte. como un cuadrado y que ademas pueda escribir algo como una pregunta. y esta se mande automaticamente a una sesion de claude y me responda en la app." Then: "vamos con la 1." (Claude Code headless.)
- L3 — Installed `mcp` 2.3.0 into `.venv` (v2 API: `mcp.server.mcpserver.MCPServer`). Route: inline; no writer reason (units depend on the bridge protocol). Risk items 2 (local network surface) and 4 (cross-thread dispatch) apply, so an independent verifier runs at the end.
- L4 (2026-11-13) — User, mid-task: "Luego necesito que cambies el puntero para escribir a algo como el de one note. que cuando estas sin apretar esta como un puntito asi medio transparente y luego apretas y se escribe y se nota del color del lapiz." and "necesito que saques la cruceta que es molesta y fea". Done inline (same file as the ask tool).
- L5 — Evidence: full suite 185 passed (3 consecutive runs) after fixing a Windows connection abort (bridge now reads the bounded body before refusing). MCP stdio end-to-end test passes. Real `claude -p` run not yet exercised (uses the user's subscription). Independent verifier launched.
- L6 (2026-11-13) — User: "probe ask claude . respondio pero tardo una barbaridad de tiempo en una boludez" then "pone que se pueda elegir modelo y esfuerzo si es posible tambien." Measured `claude -p` on a trivial prompt: 99.4s wall with 1.1s API time (user hooks/plugins); 7.6s with `--setting-sources project`. Image now sent inline (stream-json) so no get_ask round trip. Real end-to-end through the app: 12.8s (default model), 9.3s (haiku). Suite: 186 passed.
- L7 — Independent verifier: S1-S3 pass; blocker B1: `read_page` with a huge rectangle froze the main thread (grid drawn line by line). Fixed: rectangles over 20000 units are refused, content area clamped, grid skipped below 3 px spacing. Advisories fixed: host/token checked before reading the body (small refused bodies drained, 15 s socket timeout); AI writes queued before close are applied before the close-time save; the Ask timeout message now wins over the killed process. Accepted: second instance takes over bridge.json; a timed-out write may still land; AI writes split an eraser drag in progress. Regression tests added; suite 190 passed. Committed on `feat/ai-bridge`.
