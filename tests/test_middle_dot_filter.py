import hashlib
import os
import sqlite3
import pytest
from corpus_app.statistics.analysis import analyze_statistics, settings_checked, PUNCTUATION_FILTER_VERSION
from corpus_app.statistics.keyness import analyze_keyness
from corpus_app.morphology import pack
from corpus_app.project import Project
from corpus_app.analysis_ui import StatisticsDialog
from test_token_exclusions import imported


@pytest.mark.parametrize('dot', ['·', 'ㆍ', 'ᆞ', '⋅', '∙', '・', '･'])
def test_middle_dot_variants_are_excluded_independent_of_pos(tmp_path, dot):
    source = imported(tmp_path, 'dates', f'5/SN {dot}/NNG 18/SN\n')
    raw = analyze_statistics(source.path, {'n':3}, tmp_path / 'stats')
    assert raw.rows[0][0] == f'5 {dot} 18'
    filtered = analyze_statistics(source.path, {'n':2, 'exclude_punctuation':True}, tmp_path / 'stats')
    assert filtered.rows == [['5 18', 1, 1_000_000]]
    assert filtered.metadata['eligible_tokens'] == 2
    assert filtered.metadata['settings']['punctuation_filter_version'] == PUNCTUATION_FILTER_VERSION
    # Preserve a dot inside a lexical token, numbers, and ordinary math symbols.
    mixed = imported(tmp_path, 'mixed', f'5{dot}18/NNP +/SW\n')
    kept = analyze_statistics(mixed.path, {'n':1, 'exclude_punctuation':True}, tmp_path / 'stats')
    assert {row[0] for row in kept.rows} == {f'5{dot}18', '+'}


def test_middle_dot_collocation_keeps_original_distance(tmp_path):
    source = imported(tmp_path, 'dates', '5/SN ㆍ/NNG 18/SN\n')
    settings = {'kind':'collocation', 'left':0, 'right':1, 'minimum':1, 'exclude_punctuation':True}
    assert not analyze_statistics(source.path, settings, tmp_path / 'stats').rows
    wide = analyze_statistics(source.path, {**settings, 'right':2}, tmp_path / 'stats')
    assert wide.rows[0][:4] == ['5','SN','18','SN']
    assert wide.rows[0][4:9] == [1,1,1,1,1]


def test_old_filtered_keyness_cache_not_reused_for_new_rule(tmp_path):
    target = imported(tmp_path, 'target', '5/SN ㆍ/NNG 18/SN\n')
    reference = imported(tmp_path, 'reference', '6/SN ⋅/SW 19/SN\n')
    root = tmp_path / 'stats'
    # Construct a valid pre-fix cache: old "punctuation only" settings, 3 unigrams.
    old = analyze_statistics(target.path, {'n':1}, root)
    old_settings = settings_checked({'kind':'ngram','n':1,'exclude_punctuation':True})
    old_settings.pop('punctuation_filter_version')
    old.metadata['settings'] = old_settings
    with sqlite3.connect(old.path) as db:
        db.execute('UPDATE metadata SET value=? WHERE key="statistics"', (pack(old.metadata),))
    digest = hashlib.sha256(pack(old_settings).encode())
    with open(target.path, 'rb') as stream: digest.update(stream.read())
    cache = root / '.ngram-counts'; cache.mkdir()
    old_cache = cache / (digest.hexdigest() + '.sqlite')
    os.replace(old.path, old_cache)
    settings = {'n':1, 'exclude_punctuation':True, 'confirm_external':True}
    result = analyze_keyness(target.path, reference.path, settings, root)
    assert result.metadata['target_ngrams'] == result.metadata['reference_ngrams'] == 2
    assert not any(result.metadata['counts_reused'].values())
    assert {row[0] for row in result.rows} == {'5','18','6','19'}
    again = analyze_keyness(target.path, reference.path, {**settings, 'metric':'χ²'}, root)
    assert all(again.metadata['counts_reused'].values())
    assert old_cache.exists()


def test_result_summary_shows_saved_filter_not_current_checkbox(tmp_path):
    source = imported(tmp_path, 'dates', '5/SN ㆍ/NNG 18/SN\n')
    result = analyze_statistics(source.path, {'n':2,'exclude_punctuation':True}, tmp_path / 'stats')
    dialog = StatisticsDialog(Project('필터 확인'),tmp_path / 'study.corpusproj','target')
    dialog.exclude_punctuation.setChecked(False)
    dialog.show_result(result)
    assert '문장부호·가운뎃점 제외: 켜짐' in dialog.summary.text()
    result.metadata['settings'].pop('punctuation_filter_version')
    dialog.show_result(result)
    assert '이전 제외 기준' in dialog.summary.text()
    result.metadata['settings']['exclude_punctuation'] = False
    dialog.exclude_punctuation.setChecked(True)
    dialog.show_result(result)
    assert '문장부호·가운뎃점 제외: 꺼짐' in dialog.summary.text()
    dialog.close()
