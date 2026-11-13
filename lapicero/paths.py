"""Default file locations shared by the app and the Qt-free MCP server."""

import os
from pathlib import Path


BRIDGE_FILE = "bridge.json"  # Port and token of the running app's AI bridge.
BRIDGE_ENV = "LAPICERO_BRIDGE"  # Overrides the bridge file location for the MCP server.


def default_library_path():
    return Path.home() / "Documents" / "Lapicero" / "library.json"


def bridge_info_path(library_path=None):
    """Bridge file next to the library (or the env override when no library is given)."""
    if library_path is None:
        override = os.environ.get(BRIDGE_ENV)
        if override:
            return Path(override)
        library_path = default_library_path()
    return Path(library_path).parent / BRIDGE_FILE
