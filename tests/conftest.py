import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    # QApplication is a process singleton; retain it across all GUI tests.
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()
