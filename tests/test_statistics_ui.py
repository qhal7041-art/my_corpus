from pathlib import Path
from unittest.mock import patch
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from corpus_app.project import Project
from corpus_app.ui import MainWindow
from corpus_app.analysis_ui import TaggedImportDialog, StatisticsDialog
from test_ui import wait


def test_tagged_txt_import_ngram_collocation_save_and_reopen(tmp_path, monkeypatch):
    app = QApplication.instance()
    filename = tmp_path / 'pretagged.corpusproj'
    Project('사전 분석').save(filename)
    source = tmp_path / 'tagged.txt'
    source.write_text(''.join(f'단어{i % 50}/NNG 을/JKO 먹/VV 다/EF\n' for i in range(3000)), encoding='utf-8-sig')
    def forbidden(*args, **kwargs):
        raise AssertionError('pretagged statistics must not invoke any morphological analyzer')
    monkeypatch.setattr('corpus_app.morphology.create', forbidden)
    window = MainWindow()
    window.show()
    assert window.load_project(filename)
    importer = TaggedImportDialog(window.project, filename, 'target', window)
    importer.result_saved.connect(window.save_morph_result)
    importer.show()
    ticks = []
    timer = QTimer(); timer.setInterval(5); timer.timeout.connect(lambda: ticks.append(1)); timer.start()
    with patch('corpus_app.analysis_ui.QFileDialog.getOpenFileNames', return_value=([str(source)], '')):
        importer.choose.click()
    importer.run_button.click()
    wait(app, lambda: importer.thread is None)
    assert importer.last_result.report.texts == 3000
    assert importer.last_result.tokens == 12000
    assert importer.table.rowCount() == 100
    assert Project.load(filename).results[0]['config']['name'] == 'imported'
    importer.close()
    stats = StatisticsDialog(window.project, filename, 'target', window)
    stats.settings_saved.connect(window.save_statistics_settings)
    stats.result_saved.connect(window.save_statistics_result)
    stats.show()
    stats.run_button.click()
    wait(app, lambda: stats.thread is None)
    assert stats.last_result.metadata['population'] == 9000
    assert stats.last_result.metadata['result_count'] == 52
    assert stats.table.rowCount() == 10
    assert stats.table.item(0, 1).data(0) == 3000
    stats.kind.setCurrentIndex(stats.kind.findData('collocation'))
    stats.center.setText('먹')
    stats.metric.setCurrentText('logDice')
    stats.run_button.click()
    wait(app, lambda: stats.thread is None)
    assert stats.last_result.metadata['kind'] == 'collocation'
    assert stats.table.columnCount() == 10
    assert stats.table.item(0, 0).text() == '먹'
    assert len(ticks) > 5
    timer.stop()
    stats.close()
    saved = Project.load(filename)
    assert len([r for r in saved.results if r['type'] == 'statistics']) == 2
    assert saved.analysis_settings['statistics']['center'] == '먹'
    # Original tagged files are no longer needed to inspect immutable statistics.
    source.unlink()
    reopened = StatisticsDialog(saved, filename, 'target')
    assert reopened.center.text() == '먹'
    reopened.saved.setCurrentIndex(reopened.saved.count() - 1)
    reopened.sort.setCurrentIndex(reopened.sort.findData('score'))
    reopened.limit.setCurrentIndex(reopened.limit.findData(1000))
    reopened.open_button.click()
    wait(app, lambda: reopened.thread is None)
    assert reopened.last_result.metadata['kind'] == 'collocation'
    assert reopened.table.rowCount() == 52
    assert reopened.last_result.rows[0][-1] >= reopened.last_result.rows[-1][-1]
    reopened.close()
    window.close()
