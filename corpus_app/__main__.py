import sys
from PyQt6.QtWidgets import QApplication
from .ui import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("말뭉치 연구실")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
