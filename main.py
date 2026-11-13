"""Launch Lapicero with ``python main.py``."""

import os
import sys

from PySide6.QtWidgets import QApplication

from lapicero.app import LapiceroWindow


def main():
    app = QApplication(sys.argv)
    # The AI bridge lets local AI tools see and write ink; set LAPICERO_AI_BRIDGE=0 to turn it off.
    window = LapiceroWindow(ai_bridge=os.environ.get("LAPICERO_AI_BRIDGE", "1") != "0")
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
