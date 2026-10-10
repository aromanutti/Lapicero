"""Launch Lapicero with ``python main.py``."""

import sys

from PySide6.QtWidgets import QApplication

from lapicero.app import LapiceroWindow


def main():
    app = QApplication(sys.argv)
    window = LapiceroWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
