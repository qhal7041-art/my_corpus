import json
import sqlite3
from pathlib import Path
from threading import Event
import pytest
from corpus_app import morphology
from corpus_app.analyzers import Morpheme
from corpus_app.analyzers.kiwi import KiwiAnalyzer, user_words
from corpus_app.analyzers.registry import status


class Words:
    def analyze(self, text):
        return [Morpheme(word, 'NNG') for word in text.split()]


def setup_corpus(tmp_path):
    folder = tmp_path / 'corpus'
    folder.mkdir()
    (folder / 'one.json').write_text(json.dumps({'utterances': [{'id': 'u1', 'text': '밥 먹다'}, {'text': None}, {}]}, ensure_ascii=False), encoding='utf-8')
    return folder


def test_real_kiwi_and_user_dictionary():
    engine = KiwiAnalyzer({'user_dictionary': '코덱스방언연구 NNP 100', 'normalize_coda': True})
    result = engine.analyze('코덱스방언연구를 시작합니다.')
    assert any(t.form == '코덱스방언연구' and t.pos == 'NNP' for t in result)
    assert any(t.pos.startswith('J') for t in result)
    assert status('kiwi').available
    assert not status('bareun').available and not status('utagger').available


def test_cache_persistence_and_invalidation(tmp_path, monkeypatch):
    monkeypatch.setattr(morphology, 'create', lambda *args: Words())
    folder = setup_corpus(tmp_path)
    directory = tmp_path / 'results'
    config = {'name': 'kiwi', 'options': {}}
    result = morphology.analyze_corpus(folder, ['utterances', None, 'text'], config, directory)
    assert result.report.texts == 1 and result.tokens == 2
    assert result.report.missing == 1 and result.report.non_string == 1
    with sqlite3.connect(result.path) as db:
        row = db.execute('SELECT text,tokens,utterance_id FROM utterances').fetchone()
        assert json.loads(row[1]) == [['밥', 'NNG'], ['먹다', 'NNG']]
        assert row[2] == 'u1'
    monkeypatch.setattr(morphology, 'create', lambda *args: pytest.fail('cache must not initialize model'))
    reused = morphology.analyze_corpus(folder, ['utterances', None, 'text'], config, directory)
    assert reused.reused and reused.path == result.path
    loaded = morphology.load_result(result.path)
    assert loaded.config['field_path'] == ['utterances', None, 'text']
    monkeypatch.setattr(morphology, 'create', lambda *args: Words())
    path = folder / 'one.json'
    content = path.read_text(encoding='utf-8')
    path.write_text(content.replace('먹다', '잔다'), encoding='utf-8')
    edited = morphology.analyze_corpus(folder, ['utterances', None, 'text'], config, directory)
    assert edited.path != result.path and not edited.reused
    different = morphology.analyze_corpus(folder, ['utterances', None, 'text'], {'name': 'kiwi', 'options': {'split_complex': True}}, directory)
    assert different.path != edited.path
    alternate = morphology.analyze_corpus(folder, ['other'], config, directory)
    assert alternate.path != edited.path and alternate.report.texts == 0
    (folder / 'bad.json').write_text('{broken', encoding='utf-8')
    mixed = morphology.analyze_corpus(folder, ['utterances', None, 'text'], config, directory)
    assert mixed.report.succeeded == 1 and mixed.report.failed == 1
    assert not morphology.analyze_corpus(folder, ['utterances', None, 'text'], config, directory).reused


def test_cancel_and_model_failure_leave_no_partial_results(tmp_path, monkeypatch):
    folder = setup_corpus(tmp_path)
    directory = tmp_path / 'results'
    cancel = Event()
    class Cancels:
        def analyze(self, text):
            cancel.set()
            return [Morpheme('밥', 'NNG')]
    monkeypatch.setattr(morphology, 'create', lambda *args: Cancels())
    result = morphology.analyze_corpus(folder, ['utterances', None, 'text'], {'name': 'kiwi'}, directory, cancel)
    assert result.report.cancelled and not result.path
    assert not list(directory.iterdir())
    def fails(*args):
        raise RuntimeError('model unavailable')
    monkeypatch.setattr(morphology, 'create', fails)
    with pytest.raises(RuntimeError):
        morphology.analyze_corpus(folder, ['utterances', None, 'text'], {'name': 'kiwi'}, directory)
    assert not list(directory.iterdir())


def test_invalid_dictionary_and_corrupt_cache(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        user_words('형식오류')
    with pytest.raises(ValueError):
        user_words('단어 NNP NaN')
    monkeypatch.setattr(morphology, 'create', lambda *args: Words())
    folder = setup_corpus(tmp_path)
    args = (folder, ['utterances', None, 'text'], {'name': 'kiwi'}, tmp_path / 'results')
    result = morphology.analyze_corpus(*args)
    Path(result.path).write_bytes(b'corrupt')
    rebuilt = morphology.analyze_corpus(*args)
    assert rebuilt.tokens == 2 and not rebuilt.reused
