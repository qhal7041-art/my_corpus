import json
from pathlib import Path
import pytest
from PyQt6.QtWidgets import QApplication
from corpus_app.statistics.analysis import analyze_statistics, settings_checked
from corpus_app.statistics.keyness import analyze_keyness
from corpus_app.tagged_import import import_tagged
from corpus_app.exporting import export_result
from corpus_app.analysis_ui import StatisticsDialog
from corpus_app.ui import MainWindow
from corpus_app.project import Project
from test_ui import wait


def imported(root, name, text):
    path = root / f'{name}.txt'
    path.write_text(text, encoding='utf-8')
    return import_tagged([path], {'mode': 'slash'}, root / 'morph')


def test_punctuation_removed_before_ngrams_without_mutating_tokens(tmp_path):
    source = imported(tmp_path, 'source', '"/SS 동일하/VA ㄴ/ETM 것/NNB ”/SS ?/SF\n')
    before = Path(source.path).read_bytes()
    raw = analyze_statistics(source.path, {'kind':'ngram', 'n':3}, tmp_path / 'stats')
    assert raw.metadata['population'] == 4
    result = analyze_statistics(source.path, {'kind':'ngram', 'n':3, 'exclude_punctuation':True}, tmp_path / 'stats')
    assert result.rows == [['동일하 ㄴ 것', 1, 1_000_000]]
    assert result.metadata['eligible_tokens'] == 3 and result.metadata['population'] == 1
    assert Path(source.path).read_bytes() == before
    empty = analyze_statistics(source.path, {'kind':'ngram', 'n':3, 'exclude_punctuation':True, 'excluded_forms':['것']}, tmp_path / 'stats')
    assert empty.rows == [] and '제외 설정' in empty.metadata['note']


def test_unicode_punctuation_only_and_exact_custom_exclusions(tmp_path):
    source = imported(tmp_path, 'mixed', '…/NNG “/XX ?!/SF C++/NNP +/SW 😊/SW 그것/NP 것/NNB\n')
    result = analyze_statistics(source.path, {'kind':'ngram','n':1,'include_pos':True,
        'exclude_punctuation':True,'excluded_forms':[' 것 ', '+', '것']}, tmp_path / 'stats')
    assert {r[0] for r in result.rows} == {'C++/NNP', '😊/SW', '그것/NP'}
    assert result.metadata['settings']['excluded_forms'] == ['+', '것']
    assert result.metadata['population'] == 3


def test_collocation_excludes_candidates_but_keeps_original_distance(tmp_path):
    source = imported(tmp_path, 'pairs', '밥/NNG "/SS 먹/VV\n')
    settings = {'kind':'collocation', 'left':0, 'right':1, 'minimum':1, 'exclude_punctuation':True}
    narrow = analyze_statistics(source.path, settings, tmp_path / 'stats')
    assert narrow.rows == [] and narrow.metadata['population'] == 0
    wide = analyze_statistics(source.path, {**settings, 'right':2}, tmp_path / 'stats')
    assert len(wide.rows) == 1 and wide.rows[0][:4] == ['밥','NNG','먹','VV']
    assert wide.rows[0][4:9] == [1, 1, 1, 1, 1]
    excluded = analyze_statistics(source.path, {**settings, 'right':2, 'excluded_forms':['먹']}, tmp_path / 'stats')
    assert not excluded.rows


def test_keyness_applies_same_exclusions_and_invalidates_count_cache(tmp_path):
    target = imported(tmp_path, 'target', '"/SS 밥/NNG 것/NNB ?/SF\n')
    ref = imported(tmp_path, 'reference', '책/NNG 것/NNB ”/SS\n')
    settings = {'kind':'keyness', 'n':1, 'confirm_external':True}
    root = tmp_path / 'stats'
    raw = analyze_keyness(target.path, ref.path, settings, root)
    assert (raw.metadata['target_ngrams'], raw.metadata['reference_ngrams']) == (4, 3)
    filtered = analyze_keyness(target.path, ref.path, {**settings, 'exclude_punctuation':True, 'excluded_forms':['것']}, root)
    assert (filtered.metadata['target_ngrams'], filtered.metadata['reference_ngrams']) == (1, 1)
    assert {r[0] for r in filtered.rows} == {'밥','책'}
    assert not any(filtered.metadata['counts_reused'].values())
    reused = analyze_keyness(target.path, ref.path, {**settings, 'exclude_punctuation':True, 'excluded_forms':['것','것'], 'metric':'χ²'}, root)
    assert all(reused.metadata['counts_reused'].values())


@pytest.mark.parametrize('setting', [{'exclude_punctuation':'yes'}, {'excluded_forms':'것'}, {'excluded_forms':['']}, {'excluded_forms':[1]}])
def test_invalid_exclusions_rejected(setting):
    with pytest.raises(ValueError): settings_checked(setting)


def test_ui_filter_saved_restored_and_exported(tmp_path):
    app = QApplication.instance()
    filename = tmp_path / 'study.corpusproj'; Project('제외 필터').save(filename)
    source = imported(tmp_path, 'source', '"/SS 동일하/VA ㄴ/ETM 것/NNB ?/SF\n')
    window = MainWindow(); window.load_project(filename); window.save_morph_result(source)
    dialog = StatisticsDialog(window.project, filename, 'target', window)
    dialog.settings_saved.connect(window.save_statistics_settings)
    dialog.result_saved.connect(window.save_statistics_result)
    dialog.show(); dialog.exclude_punctuation.setChecked(True)
    dialog.excluded_forms.setPlainText('것\n\n것'); dialog.n.setValue(2)
    dialog.run_button.click(); wait(app, lambda: dialog.thread is None)
    assert dialog.last_result.rows == [['동일하 ㄴ', 1, 1_000_000]]
    assert dialog.last_result.metadata['settings']['excluded_forms'] == ['것']
    output = tmp_path / 'result.csv'; export_result(dialog.last_result.path, output)
    meta = json.loads(output.with_suffix('.csv.settings.json').read_text(encoding='utf-8'))
    assert meta['source_metadata']['settings']['exclude_punctuation'] is True
    assert meta['source_metadata']['settings']['excluded_forms'] == ['것']
    dialog.close(); window.close()
    reopened = StatisticsDialog(Project.load(filename), filename, 'target')
    assert reopened.exclude_punctuation.isChecked() and reopened.excluded_forms.toPlainText() == '것'
    reopened.close()
