"""Interaction regressions for the presentation layer using real Qt widgets."""
import json
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QPlainTextEdit, QTableWidget
from corpus_app.ui import MainWindow
from corpus_app.project import Project, CorpusSource
from corpus_app.presentation import DetailsPanel, table_item, copy_selection
from corpus_app.morph_ui import MorphDialog
from corpus_app.tagged_import import import_tagged
from corpus_app.analysis_ui import StatisticsDialog
from test_ui import wait


def test_field_search_preserves_extraction_selection(tmp_path):
    app = QApplication.instance()
    folder = tmp_path / 'data'; folder.mkdir()
    (folder / 'data.json').write_text(json.dumps({'utterances': [{'text': '안녕', 'id': 'u1'}], 'other': 123}), encoding='utf-8')
    filename = tmp_path / 'study.corpusproj'
    Project('검색', target=CorpusSource(str(folder), ['utterances', None, 'text'])).save(filename)
    window = MainWindow(); window.show(); window.load_project(filename)
    wait(app, lambda: window.thread is None and window.job_kind == 'extract' and window.last_report is not None)
    report = window.last_report
    window.schema_search.setText('text'); window.filter_tree()
    assert '1개' in window.field_count.text()
    selected = window.tree.selectedItems()[0]
    assert not selected.isHidden() and not selected.parent().isHidden()
    assert selected.parent().isExpanded()
    window.schema_search.setText('없는필드'); window.filter_tree()
    assert window.tree.topLevelItem(0).isHidden()
    window.schema_search.clear(); window.filter_tree()
    assert not window.tree.topLevelItem(0).isHidden()
    assert window.current_source().field_path == ['utterances', None, 'text']
    assert window.last_report is report and window.thread is None
    window.resize(1024, 640); app.processEvents()
    assert window.height() == 640 and window.width() == 1024
    window.close()


def test_history_reopens_reference_snapshot_without_analyzer(tmp_path, monkeypatch):
    app = QApplication.instance()
    filename = tmp_path / 'history.corpusproj'; Project('기록').save(filename)
    source = tmp_path / 'tagged.txt'; source.write_text('밥/NNG 먹/VV\n', encoding='utf-8')
    result = import_tagged([source], {'mode': 'slash'}, filename.with_suffix('.results'))
    window = MainWindow(); window.load_project(filename)
    window.save_morph_result(result, 'reference')
    source.unlink()
    assert not window.history_open.isEnabled()
    item = window.history_tree.topLevelItem(0)
    assert item.text(1) == '참조'
    window.history_tree.setCurrentItem(item)
    assert window.history_open.isEnabled()
    def forbidden(*args, **kwargs):
        raise AssertionError('opening history must not run an analyzer')
    monkeypatch.setattr('corpus_app.morphology.create', forbidden)
    def inspect(dialog):
        # The real history action schedules open_result on entry to Qt's event loop.
        wait(app, lambda: dialog.last_result is not None and dialog.thread is None)
        assert dialog.role == 'reference'
        assert dialog.table.rowCount() == 1
        assert dialog.last_result.tokens == 2
        dialog.close()
    monkeypatch.setattr(MorphDialog, 'exec', inspect)
    window.history_open.click()
    stats = StatisticsDialog(window.project, filename, 'reference')
    stats.show(); stats.resize(1024, 640); app.processEvents()
    assert stats.height() == 640 and stats.width() == 1024
    stats.settings_scroll.ensureWidgetVisible(stats.run_button); app.processEvents()
    assert stats.run_button.isVisibleTo(stats.settings_scroll)
    stats.close(); window.close()


def test_details_toggle_and_copy_keeps_numeric_data():
    app = QApplication.instance()
    editor = QPlainTextEdit(); panel = DetailsPanel(editor, auto_errors=True)
    panel.show(); app.processEvents()
    assert editor.isHidden()
    editor.setPlainText('파일 읽기 실패')
    assert panel.toggle.isChecked() and not editor.isHidden()
    panel.toggle.click(); assert editor.isHidden()
    panel.close()
    table = QTableWidget(2, 2)
    for row, values in enumerate([('밥', 10), ('먹', 2)]):
        for col, value in enumerate(values): table.setItem(row, col, table_item(value))
    table.selectAll(); copy_selection(table)
    assert app.clipboard().text() == '밥\t10\n먹\t2\n'
    assert table.item(0, 1).data(Qt.ItemDataRole.DisplayRole) == 10
    table.sortItems(1)
    assert table.item(0, 1).data(Qt.ItemDataRole.DisplayRole) == 2
