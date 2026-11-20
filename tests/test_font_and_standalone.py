import pytest
from PyQt6.QtWidgets import QApplication, QLabel
from corpus_app.presentation import preferred_font_family
from corpus_app.ui import MainWindow
from corpus_app.project import Project
from corpus_app.tagged_import import import_tagged
from corpus_app.analysis_ui import StatisticsDialog
from test_ui import wait


def test_installed_korean_font_priority():
    fonts = ['Segoe UI', 'Malgun Gothic', 'Noto Sans CJK KR', 'Apple SD Gothic Neo']
    assert preferred_font_family(fonts, 'win32') == 'Malgun Gothic'
    assert preferred_font_family(fonts, 'darwin') == 'Apple SD Gothic Neo'
    assert preferred_font_family(fonts, 'linux') == 'Noto Sans CJK KR'
    assert preferred_font_family(['Segoe UI'], 'win32') is None
    assert preferred_font_family(['맑은 고딕'], 'win32') == '맑은 고딕'


@pytest.mark.parametrize('width,height', [(1280,820), (1024,640), (800,600)])
def test_welcome_labels_have_room_for_complete_text(width, height):
    app = QApplication.instance()
    window = MainWindow(); window.show(); window.resize(width, height)
    for _ in range(5): app.processEvents()
    assert (window.width(),window.height()) == (width,height)
    for label in window.stack.widget(0).findChildren(QLabel):
        assert label.height() >= label.heightForWidth(label.width()), label.text()
    assert window.welcome_scroll.horizontalScrollBar().maximum() == 0
    assert window.welcome_new.isVisible() and window.welcome_open.isVisible()
    window.close()


@pytest.mark.parametrize('saved_kind', ['ngram', 'keyness'])
def test_target_only_ngram_without_reference_even_after_saved_keyness(tmp_path, monkeypatch, saved_kind):
    app = QApplication.instance()
    filename = tmp_path / 'study.corpusproj'
    project = Project('대상 자료만')
    project.analysis_settings['statistics'] = {'kind': saved_kind, 'reference_result':'missing.sqlite'}
    project.save(filename)
    text = tmp_path / 'tagged.txt'
    text.write_text('밥/NNG 먹/VV 다/EF\n밥/NNG 먹/VV\n', encoding='utf-8')
    result = import_tagged([text], {'mode':'slash'}, filename.with_suffix('.results'))
    window = MainWindow(); window.load_project(filename); window.save_morph_result(result, 'target')
    assert not window.project.reference.folder
    def forbidden(*args, **kwargs):
        raise AssertionError('target-only N-gram must not invoke reference analysis')
    monkeypatch.setattr('corpus_app.analysis_ui.analyze_keyness', forbidden)
    dialog = StatisticsDialog(window.project, filename, 'target', window)
    dialog.result_saved.connect(window.save_statistics_result)
    dialog.settings_saved.connect(window.save_statistics_settings)
    dialog.show(); app.processEvents()
    assert dialog.kind.currentData() == 'ngram'
    assert dialog.reference.currentData() is None and not dialog.reference.isVisible()
    assert '참조 말뭉치는 필요하지 않습니다' in dialog.mode_hint.text()
    assert dialog.run_button.isEnabled()
    dialog.run_button.click(); wait(app, lambda: dialog.thread is None)
    assert dialog.last_result.metadata['population'] == 3
    assert {row[0]:row[1] for row in dialog.last_result.rows} == {'밥 먹':2, '먹 다':1}
    relative = dialog.current_result_path
    dialog.close(); window.close()
    reopened = StatisticsDialog(Project.load(filename),filename,'target')
    reopened.load_path(relative); wait(app,lambda:reopened.thread is None)
    assert reopened.last_result.metadata['population'] == 3
    reopened.close()
