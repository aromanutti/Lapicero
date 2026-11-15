"""Launch Lapicero with ``python main.py``."""

import os
import sys

from PySide6.QtWidgets import QApplication

from lapicero.app import LapiceroWindow
from lapicero.icons import app_icon


def main():
    if sys.platform == "win32":
        # Own taskbar identity, so Windows shows Lapicero's icon instead of python's.
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Lapicero.Notes")
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    # The AI bridge lets local AI tools see and write ink; set LAPICERO_AI_BRIDGE=0 to turn it off.
    window = LapiceroWindow(ai_bridge=os.environ.get("LAPICERO_AI_BRIDGE", "1") != "0")
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
