"""Qt bridge: all filesystem scanning/extraction runs in a worker thread."""
from threading import Event
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from .json_corpus import process_corpus


class CorpusWorker(QObject):
    progress = pyqtSignal(int, int, int)
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, folder, selected=None):
        super().__init__()
        self.folder = folder
        self.selected = selected
        self.cancel = Event()

    @pyqtSlot()
    def run(self):
        try:
            self.result.emit(process_corpus(self.folder, self.cancel, self.progress.emit, self.selected))
        except Exception as error:
            self.error.emit(f"{type(error).__name__}: {error}")
        finally:
            self.finished.emit()


class FunctionWorker(QObject):
    """Reusable worker for disk-backed analysis/result loading."""
    progress = pyqtSignal(int, int, int)
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, function):
        super().__init__()
        self.function = function
        self.cancel = Event()

    @pyqtSlot()
    def run(self):
        try:
            self.result.emit(self.function(self.cancel, self.progress.emit))
        except Exception as error:
            self.error.emit(f'{type(error).__name__}: {error}')
        finally:
            self.function = None
            self.finished.emit()
