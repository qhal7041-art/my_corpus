"""Real Qt event-loop tests; offscreen on a headless machine."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import time
import tracemalloc
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from corpus_app.ui import MainWindow
from corpus_app.project import Project, CorpusSource
from scripts.generate_corpus import generate


def wait(app, condition, timeout=30):
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "Qt worker timed out"
        app.processEvents()
        time.sleep(.001)
    # Drain pending deferred deletes / scheduled extraction.
    app.processEvents()


def test_3000_files_responsive_cancel_and_restore(tmp_path):
    app = QApplication.instance() or QApplication([])
    corpus = tmp_path / "corpus"
    generate(corpus)
    filename = tmp_path / "research.corpusproj"
    project = Project("방언 프로젝트", target=CorpusSource(str(corpus)))
    project.save(filename)
    window = MainWindow()
    window.show()
    ticks = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start()
    tracemalloc.start()
    started = time.monotonic()
    assert window.load_project(filename)
    wait(app, lambda: window.thread is None)
    duration = time.monotonic() - started
    scan_ticks = len(ticks)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    scan = window.last_report
    assert scan.processed == 3000
    assert (scan.succeeded, scan.failed) == (2996, 4)
    assert scan_ticks >= 5, "UI event-loop heartbeat did not run during scan"
    assert window.tree.topLevelItemCount() == 1
    assert scan.fields[("utterances", None, "text")].files == 2766
    # Select through the actual tree signal, not directly through the model.
    from PyQt6.QtWidgets import QTreeWidgetItemIterator
    iterator = QTreeWidgetItemIterator(window.tree)
    from PyQt6.QtCore import Qt
    while iterator.value():
        item = iterator.value()
        if item.data(0, Qt.ItemDataRole.UserRole) == ("utterances", None, "text"):
            item.setSelected(True)
            break
        iterator += 1
    else:
        raise AssertionError("field missing")
    wait(app, lambda: window.thread is None)
    assert window.last_report.texts == 82980
    assert window.preview.rowCount() == 100
    assert window.save_project()
    # Reopen and verify automatic scan + restored preview of selected field.
    reopened = MainWindow()
    reopened.show()
    assert reopened.load_project(filename)
    wait(app, lambda: reopened.thread is None and reopened.job_kind == "extract" and reopened.last_report is not None)
    assert reopened.current_source().folder == str(corpus)
    assert reopened.current_source().field_path == ["utterances", None, "text"]
    assert reopened.last_report.texts == 82980
    # Cancellation via a live GUI button, with no artificial worker delay.
    before = len(ticks)
    reopened.scan()
    cancelled_at = []
    def request_cancel():
        cancelled_at.append(time.monotonic())
        reopened.cancel_button.click()
    QTimer.singleShot(20, request_cancel)
    wait(app, lambda: reopened.thread is None)
    cancel_latency = time.monotonic() - cancelled_at[0]
    partial = reopened.last_report
    assert partial.cancelled
    assert partial.processed < 3000
    assert cancel_latency < 1.0
    assert len(ticks) > before
    # A cancelled task must not prevent a subsequent scan/extraction.
    reopened.scan()
    wait(app, lambda: reopened.thread is None and reopened.job_kind == "extract" and reopened.last_report is not None)
    assert not reopened.last_report.cancelled
    assert reopened.last_report.texts == 82980
    timer.stop()
    window.dirty = reopened.dirty = False
    window.close()
    reopened.close()
    print(json.dumps({"files": 3000, "success": scan.succeeded, "failed": scan.failed,
                      "scan_seconds": round(duration, 3), "scan_heartbeat_ticks": scan_ticks,
                      "python_peak_mib": round(peak / 1024**2, 2),
                      "cancelled_after_files": partial.processed,
                      "cancel_latency_seconds": round(cancel_latency, 3), "texts": 82980}, ensure_ascii=False))


def test_moved_source_reconnect(tmp_path):
    app = QApplication.instance() or QApplication([])
    filename = tmp_path / "study.corpusproj"
    project = Project("이동", target=CorpusSource(str(tmp_path / "absent"), ["text"]))
    project.save(filename)
    window = MainWindow()
    assert window.load_project(filename)
    assert window.thread is None
    assert "이동" in window.summary.text()
    folder = tmp_path / "new"
    folder.mkdir()
    (folder / "one.json").write_text('{"id":"u1","text":"안녕"}', encoding="utf-8")
    # Exercise the reconnect button's dialog return path.
    from unittest.mock import patch
    with patch("corpus_app.ui.QFileDialog.getExistingDirectory", return_value=str(folder)):
        window.connect_button.click()
    wait(app, lambda: window.thread is None and window.job_kind == "extract" and window.last_report is not None)
    assert window.last_report.texts == 1
    assert window.save_project()
    assert Project.load(filename).target.folder == str(folder)
    assert Project.load(filename).target.field_path == ["text"]
    window.close()


def test_new_project_dialog_and_independent_sources(tmp_path):
    from unittest.mock import patch
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QTreeWidgetItemIterator
    app = QApplication.instance() or QApplication([])
    target = tmp_path / "target"
    reference = tmp_path / "reference"
    target.mkdir()
    reference.mkdir()
    (target / "a.json").write_text('{"utterances":[{"id":"u1","text":"대상"}]}', encoding="utf-8")
    (reference / "b.json").write_text('{"document":{"text":"참조"}}', encoding="utf-8")
    filename = tmp_path / "new.corpusproj"
    window = MainWindow()
    with patch("corpus_app.ui.QInputDialog.getText", return_value=("새 연구", True)), patch("corpus_app.ui.QFileDialog.getSaveFileName", return_value=(str(filename), "")):
        window.new_project()
    assert filename.is_file()
    assert Project.load(filename).name == "새 연구"

    def connect_and_select(folder, path):
        with patch("corpus_app.ui.QFileDialog.getExistingDirectory", return_value=str(folder)):
            window.connect_button.click()
        wait(app, lambda: window.thread is None)
        iterator = QTreeWidgetItemIterator(window.tree)
        while iterator.value():
            item = iterator.value()
            if item.data(0, Qt.ItemDataRole.UserRole) == path:
                item.setSelected(True)
                break
            iterator += 1
        else:
            raise AssertionError("field missing")
        wait(app, lambda: window.thread is None)
        assert window.last_report.texts == 1

    connect_and_select(target, ("utterances", None, "text"))
    window.role.setCurrentIndex(1)
    connect_and_select(reference, ("document", "text"))
    assert window.save_project()
    saved = Project.load(filename)
    assert saved.target.field_path == ["utterances", None, "text"]
    assert saved.reference.field_path == ["document", "text"]
    window.close()


def test_close_during_scan_cancels_thread(tmp_path):
    app = QApplication.instance() or QApplication([])
    folder = tmp_path / "corpus"
    generate(folder, 200)
    filename = tmp_path / "study.corpusproj"
    Project("닫기", target=CorpusSource(str(folder))).save(filename)
    window = MainWindow()
    window.show()
    assert window.load_project(filename)
    window.close()
    wait(app, lambda: window.thread is None)
    assert window.last_report.cancelled
    assert not window.isVisible()
