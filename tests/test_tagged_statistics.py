import json
import math
from pathlib import Path
from threading import Event
import pytest
from openpyxl import Workbook
from corpus_app.tagged_import import import_tagged, import_database, parse_path, slash_tokens
from corpus_app.statistics.analysis import analyze_statistics, load_statistics
from corpus_app.json_corpus import display_path


def imported(tmp_path, content, filename='tagged.txt'):
    path = tmp_path / filename
    path.write_text(content, encoding='utf-8')
    return import_tagged([path], {'mode': 'slash'}, tmp_path / 'inputs')


def test_slash_import_preserves_forms_pos_and_failed_file_rollback(tmp_path):
    assert list(slash_tokens('밥/NNG+을/JKO //SP++/SW C++/NNP', True)) == [['밥','NNG'], ['을','JKO'], ['/','SP'], ['+','SW'], ['C++','NNP']]
    good = tmp_path / 'good.txt'
    good.write_text('밥/NNG 을/JKO 먹/VV 다/EF\n\n//SP +/SW 배__05/NNG\n', encoding='utf-8-sig')
    bad = tmp_path / 'bad.txt'
    bad.write_text('정상/NNG\n품사누락\n', encoding='utf-8')
    before = [good.read_bytes(), bad.read_bytes()]
    result = import_tagged([good, bad], {'mode': 'slash'}, tmp_path / 'results')
    assert (result.report.succeeded, result.report.failed, result.report.texts, result.tokens) == (1, 1, 2, 7)
    assert result.preview[1][2] == 'line:3'
    assert '//SP +/SW 배__05/NNG' in result.preview[1][3]
    assert before == [good.read_bytes(), bad.read_bytes()]
    copied = import_database(result.path, tmp_path / 'copy')
    assert copied.tokens == 7 and copied.config['name'] == 'imported'
    cancel = Event(); cancel.set()
    partial = import_database(result.path, tmp_path / 'cancel-copy', cancel)
    assert partial.report.cancelled and not list((tmp_path / 'cancel-copy').iterdir())


def test_json_mapping_empty_utterance_and_safe_path(tmp_path):
    source = tmp_path / 'tokens.json'
    source.write_text(json.dumps({'utterances': [
        {'id': 'u1', 'tokens': [{'lex': '밥', 'tag': 'NNG'}]},
        {'id': 'u2', 'tokens': [['먹', 'VV']]}, {'id': 'u3', 'tokens': []}]}, ensure_ascii=False), encoding='utf-8')
    result = import_tagged([source], {'mode': 'json', 'path': '$.utterances[*].tokens', 'form_key': 'lex', 'pos_key': 'tag'}, tmp_path / 'results')
    assert result.tokens == 2 and result.report.texts == 3
    assert [v[2] for v in result.preview] == ['u1', 'u2', 'u3']
    path = [None, 'a.b', '[*]', '한글']
    assert parse_path(display_path(path)) == path
    for invalid in ('text', '$.__class__()', '$[0]', '$[foo]', '$..x'):
        with pytest.raises(ValueError):
            parse_path(invalid)
    with pytest.raises(ValueError, match='발화가 없습니다'):
        import_tagged([source], {'mode': 'json', 'path': '$.missing'}, tmp_path / 'empty')


def test_tsv_cp949_and_excel_grouping(tmp_path):
    text = tmp_path / 'tagged.tsv'
    text.write_bytes('밥\tNNG\n먹\tVV\n\n다\tEF\n'.encode('cp949'))
    tsv = import_tagged([text], {'mode': 'tsv'}, tmp_path / 'tsv-results')
    assert tsv.tokens == 3 and tsv.report.texts == 2
    filename = tmp_path / 'tokens.xlsx'
    workbook = Workbook(); sheet = workbook.active; sheet.title = '발화'
    for row in [['id', '형태소', '품사'], ['a', '밥', 'NNG'], ['a', '먹', 'VV'], ['b', '다', 'EF']]:
        sheet.append(row)
    workbook.save(filename)
    excel = import_tagged([filename], {'mode': 'excel', 'form_key': 'B', 'pos_key': '품사', 'id_key': 'id'}, tmp_path / 'excel-results')
    assert excel.tokens == 3 and excel.report.texts == 2
    assert [r[2] for r in excel.preview] == ['발화!a', '발화!b']


def test_ngram_boundaries_pos_and_total_denominator(tmp_path):
    source = imported(tmp_path, '밥/NNG 먹/VV\n밥/NNG\n')
    result = analyze_statistics(source.path, {'kind': 'ngram', 'n': 2}, tmp_path / 'stats')
    assert result.rows == [['밥 먹', 1, 1000000.0]]
    assert result.metadata['population'] == 1
    cross = analyze_statistics(source.path, {'kind': 'ngram', 'n': 2, 'cross_utterances': True}, tmp_path / 'stats')
    assert cross.metadata['population'] == 2
    assert {row[0] for row in cross.rows} == {'밥 먹', '먹 밥'}
    tags = analyze_statistics(source.path, {'kind': 'ngram', 'n': 2, 'include_pos': True}, tmp_path / 'stats')
    assert tags.rows[0][0] == '밥/NNG 먹/VV'
    filtered = analyze_statistics(source.path, {'kind': 'ngram', 'n': 2, 'pos': 'NN*'}, tmp_path / 'stats')
    assert filtered.metadata['population'] == 0 and filtered.metadata['note']
    merged = analyze_statistics(source.path, {'kind': 'ngram', 'n': 2, 'pos': 'NN*', 'cross_utterances': True}, tmp_path / 'stats')
    assert merged.rows[0][0] == '밥 밥'
    a = tmp_path / 'a.txt'; b = tmp_path / 'b.txt'
    a.write_text('밥/NNG'); b.write_text('먹/VV')
    files = import_tagged([a, b], {'mode': 'slash'}, tmp_path / 'inputs')
    boundaries = analyze_statistics(files.path, {'kind': 'ngram', 'n': 2, 'cross_utterances': True}, tmp_path / 'stats')
    assert boundaries.metadata['population'] == 0


@pytest.mark.parametrize('metric,expected', [('MI', 1.0), ('t-score', 1 / math.sqrt(2)), ('logDice', 14.0)])
def test_collocation_scores_marginals_and_center_not_conditioning_background(tmp_path, metric, expected):
    source = imported(tmp_path, '가/NNG 나/NNG 가/NNG\n')
    settings = {'kind': 'collocation', 'left': 1, 'right': 1, 'minimum': 1, 'metric': metric}
    result = analyze_statistics(source.path, settings, tmp_path / 'stats')
    assert result.metadata['population'] == 4 and result.metadata['result_count'] == 2
    row = next(row for row in result.rows if row[0] == '가')
    assert row[4:9] == [2, 1, 2, 2, 2]
    assert row[9] == pytest.approx(expected)
    settings['center'] = '가'
    centered = analyze_statistics(source.path, settings, tmp_path / 'stats')
    assert len(centered.rows) == 1 and centered.rows[0][9] == pytest.approx(expected)
    settings['minimum'] = 3
    none = analyze_statistics(source.path, settings, tmp_path / 'stats')
    assert not none.rows and none.metadata['note']


def test_collocation_pos_keeps_original_distances(tmp_path):
    source = imported(tmp_path, '가/NNG 는/JX 나/NNG\n')
    settings = {'kind': 'collocation', 'left': 1, 'right': 1, 'minimum': 1, 'pos': 'NN*'}
    adjacent = analyze_statistics(source.path, settings, tmp_path / 'stats')
    assert adjacent.metadata['population'] == 0
    wide = analyze_statistics(source.path, {**settings, 'left': 2, 'right': 2}, tmp_path / 'stats')
    assert wide.metadata['population'] == 2
    assert len(wide.rows) == 2
    sorted_result = load_statistics(wide.path, 'score', 10)
    assert sorted_result.rows[0][-1] >= sorted_result.rows[-1][-1]


def test_cancel_import_and_statistics_remove_partial_outputs(tmp_path):
    source = tmp_path / 'many.txt'
    source.write_text(('밥/NNG 먹/VV 다/EF\n' * 1000), encoding='utf-8')
    cancel = Event()
    partial = import_tagged([source], {'mode': 'slash'}, tmp_path / 'cancel-import', cancel,
                            lambda *args: cancel.set())
    assert partial.report.cancelled and not list((tmp_path / 'cancel-import').iterdir())
    source_result = import_tagged([source], {'mode': 'slash'}, tmp_path / 'inputs')
    cancel.clear()
    result = analyze_statistics(source_result.path, {'kind': 'ngram', 'n': 2}, tmp_path / 'cancel-stats', cancel,
                                lambda *args: cancel.set())
    assert result.cancelled and not list((tmp_path / 'cancel-stats').iterdir())
    with pytest.raises(ValueError):
        analyze_statistics(source_result.path, {'kind': 'collocation', 'left': 0, 'right': 0}, tmp_path / 'bad')


def test_large_distinct_candidates_flush_to_disk(tmp_path):
    source = imported(tmp_path, ' '.join(f'w{i}/NNG' for i in range(6005)) + '\n')
    ngram = analyze_statistics(source.path, {'kind':'ngram','n':2}, tmp_path / 'stats')
    assert ngram.metadata['population'] == 6004 and ngram.metadata['result_count'] == 6004
    assert len(ngram.rows) == 10
    colloc = analyze_statistics(source.path, {'kind':'collocation','left':1,'right':1,'minimum':1}, tmp_path / 'stats')
    assert colloc.metadata['population'] == 12008 and colloc.metadata['result_count'] == 12008
    assert len(colloc.rows) == 100
    assert len(load_statistics(colloc.path, 'score', 1000).rows) == 1000
    score_first = analyze_statistics(source.path, {'kind':'collocation','left':1,'right':1,'minimum':1}, tmp_path / 'stats', sort='score', limit=10)
    assert score_first.rows == load_statistics(colloc.path, 'score', 10).rows
