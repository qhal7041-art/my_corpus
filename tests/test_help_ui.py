"""Help is accessible without changing settings or initializing analyzers."""
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox
from corpus_app.help_ui import HELP, HelpField
from corpus_app.morph_ui import MorphDialog
from corpus_app.analysis_ui import StatisticsDialog
from corpus_app.project import Project


def fields(dialog):
    return {field.help_button.key: field for field in dialog.findChildren(HelpField)}


def test_morph_help_tracks_engine_options_and_opens_without_analysis(tmp_path, monkeypatch):
    app = QApplication.instance()
    def forbidden(*args, **kwargs):
        raise AssertionError('help must not initialize analysis')
    monkeypatch.setattr('corpus_app.morphology.create', forbidden)
    dialog = MorphDialog(Project('도움말'), tmp_path / 'study.corpusproj', 'target')
    dialog.show(); app.processEvents()
    options = fields(dialog)
    expected = {
        'kiwi': {'engine', 'normalize_coda', 'split_complex', 'compatible_jamo', 'user_dictionary'},
        'bareun': {'engine', 'bareun_key', 'auto_spacing', 'auto_jointing', 'server_dicts'},
        'utagger': {'engine', 'utagger_version'},
        'baropy': {'engine', 'bareun_key', 'threads', 'sense', 'user_nouns', 'model_cache'},
    }
    saved = []; dialog.settings_saved.connect(saved.append)
    for engine, visible in expected.items():
        dialog.engine.setCurrentIndex(dialog.engine.findData(engine)); app.processEvents()
        assert {key for key, field in options.items() if field.isVisible()} == visible
        before = dialog.config()
        dialog.api_key.setText('test-secret-not-for-help')
        for key in visible:
            button = options[key].help_button
            assert '?' == button.text() and button.toolTip() and button.accessibleName()
            button.click(); app.processEvents()
            popup = button.popup
            assert popup.isVisible() and popup.informativeText()
            assert 'test-secret-not-for-help' not in popup.informativeText() + popup.detailedText()
            popup.accept(); app.processEvents()
            assert button.popup is None
        assert dialog.config() == before and not saved and dialog.thread is None
    dialog.close()


def test_keyboard_help_does_not_toggle_checkbox_and_stays_available_when_disabled(tmp_path):
    app = QApplication.instance()
    dialog = MorphDialog(Project('키보드'), tmp_path / 'study.corpusproj', 'target')
    dialog.show(); app.processEvents()
    field = fields(dialog)['normalize_coda']
    before = field.control.isChecked()
    field.control.setEnabled(False)
    assert field.help_button.isEnabled()
    field.help_button.setFocus()
    QTest.keyClick(field.help_button, Qt.Key.Key_Space); app.processEvents()
    assert field.help_button.popup.isVisible()
    popup = field.help_button.popup
    details_button = next(b for b in popup.buttons() if popup.buttonRole(b) == QMessageBox.ButtonRole.ActionRole)
    assert details_button.text() == '자세히 보기'
    details_button.click(); app.processEvents()
    assert details_button.text() == '자세한 설명 접기'
    details_button.click(); app.processEvents()
    assert details_button.text() == '자세히 보기'
    assert field.control.isChecked() == before
    field.help_button.popup.reject(); app.processEvents()
    dialog.close()


def test_statistics_help_tracks_modes_and_matches_slot_calculation(tmp_path):
    app = QApplication.instance()
    dialog = StatisticsDialog(Project('통계'), tmp_path / 'study.corpusproj', 'target')
    dialog.show(); app.processEvents()
    options = fields(dialog)
    for kind in ('ngram', 'collocation', 'keyness', 'ngram'):
        dialog.kind.setCurrentIndex(dialog.kind.findData(kind)); app.processEvents()
        for key in ('n', 'include_pos'):
            assert options[key].isVisible() == (kind != 'collocation')
        for key in ('center', 'left', 'right', 'minimum', 'metric'):
            assert options[key].isVisible() == (kind == 'collocation')
        for key in ('reference', 'confirm', 'keyness'):
            assert options[key].isVisible() == (kind == 'keyness')
    # Formula wording must use the slot margins, not simple token frequencies.
    options['metric'].help_button.show_help(); app.processEvents()
    assert '전체 유효 슬롯 수' in options['metric'].help_button.popup.detailedText()
    assert '탐색 거리를 압축하지' in HELP['pos'][2]
    options['metric'].help_button.popup.accept(); dialog.close()
