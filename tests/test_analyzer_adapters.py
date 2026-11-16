import json
from pathlib import Path
from threading import Event
import pytest
from PyQt6.QtWidgets import QLineEdit
from corpus_app.analyzers.registry import public_config, model_identity
from corpus_app.analyzers.bareun import BareunAnalyzer
from corpus_app.analyzers import Morpheme
from corpus_app.morph_ui import MorphDialog
from corpus_app.project import Project, CorpusSource
from corpus_app import morphology


def test_bareun_real_sdk_request_and_response(monkeypatch):
    pytest.importorskip('bareunpy')
    from bareunpy.bareun import language_service_pb2 as pb
    calls = []
    class Stub:
        def __init__(self, address, **kwargs):
            assert address == 'https://api.bareun.ai:443'
            assert kwargs['timeout_ms'] == 30000
        def analyze_syntax(self, req, headers):
            calls.append((req, headers))
            response = pb.AnalyzeSyntaxResponse()
            token = response.sentences.add().tokens.add()
            morph = token.morphemes.add()
            morph.text.content = '밥'
            morph.tag = pb.Morpheme.Tag.Value('NNG')
            return response
        def close(self):
            pass
    monkeypatch.setattr('bareunpy.bareun.language_service_connect.LanguageServiceClientSync', Stub)
    engine = BareunAnalyzer({'auto_spacing': False, 'auto_jointing': True, 'custom_dicts': ['study']}, 'session-secret')
    tokens = engine.analyze('밥')
    assert tokens == [Morpheme('밥', 'NNG')]
    request, headers = calls[0]
    assert request.document.content == '밥'
    assert not request.auto_split_sentence and not request.auto_spacing
    assert request.auto_jointing and list(request.custom_dict_names) == ['study']
    assert headers['api-key'] == 'session-secret'
    def fail(*args, **kwargs):
        raise RuntimeError('server echoed session-secret')
    engine.client.analyze_syntax = fail
    with pytest.raises(RuntimeError) as error:
        engine.analyze('밥')
    assert 'session-secret' not in str(error.value)
    engine.close()
    assert not engine._key


def test_key_not_saved_and_bareun_no_automatic_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(morphology, 'engine_version', lambda name: 'test')
    folder = tmp_path / 'source'
    folder.mkdir()
    (folder / 'one.txt').write_text('밥', encoding='utf-8')
    keys, closed = [], []
    class Fake:
        def analyze(self, text):
            return [Morpheme('밥', 'NNG')]
        def close(self):
            closed.append(True)
    def create(name, options, **kwargs):
        keys.append(kwargs['api_key'])
        return Fake()
    monkeypatch.setattr(morphology, 'create', create)
    config = {'name': 'bareun', 'options': {'auto_spacing': True, 'auto_jointing': True, 'custom_dicts': []}}
    a = morphology.analyze_corpus(folder, ['text'], config, tmp_path / 'results', api_key='session-secret')
    b = morphology.analyze_corpus(folder, ['text'], config, tmp_path / 'results', api_key='second-secret')
    assert a.path != b.path and not a.reused and not b.reused
    assert keys == ['session-secret', 'second-secret'] and len(closed) == 2
    project = Project('바른', target=CorpusSource(str(folder), ['text']), analyzer=config,
                      results=[{'type': 'morphology', 'path': a.path, 'config': a.config}])
    project.save(tmp_path / 'study.corpusproj')
    for path in [Path(a.path), Path(b.path), tmp_path / 'study.corpusproj']:
        assert b'session-secret' not in path.read_bytes()
        assert b'second-secret' not in path.read_bytes()
    assert morphology.load_result(a.path).tokens == 1
    with pytest.raises(ValueError):
        public_config({'name': 'bareun', 'options': {'api_key': 'do-not-save'}})
    with pytest.raises(ValueError):
        public_config({'name': 'bareun', 'api_key': 'do-not-save'})


def test_bareun_ui_direct_key_and_restore_without_key(tmp_path, monkeypatch):
    from corpus_app.analyzers import AnalyzerStatus
    monkeypatch.setattr('corpus_app.morph_ui.status', lambda *args: AnalyzerStatus('바른', True, 'test'))
    project = Project('직접 입력', target=CorpusSource(str(tmp_path), ['text']))
    dialog = MorphDialog(project, tmp_path / 'study.corpusproj', 'target')
    dialog.show()
    dialog.engine.setCurrentIndex(1)
    assert dialog.api_key.isVisible()
    assert dialog.api_key.echoMode() == QLineEdit.EchoMode.Password
    assert not dialog.run_button.isEnabled()
    dialog.api_key.setText('session-secret')
    assert dialog.run_button.isEnabled()
    dialog.server_dicts.setText('a, b')
    assert dialog.config() == {'name': 'bareun', 'options': {'auto_spacing': True, 'auto_jointing': True, 'custom_dicts': ['a', 'b']}}
    saved = []
    dialog.settings_saved.connect(saved.append)
    dialog.save_options.click()
    assert 'session-secret' not in json.dumps(saved)
    dialog.engine.setCurrentIndex(2)
    assert not dialog.api_key.isVisible() and dialog.utagger_version.isVisible()
    dialog.engine.setCurrentIndex(0)
    assert not dialog.api_key.isVisible() and dialog.dictionary.isVisible()
    dialog.close()
    assert not dialog.api_key.text()
    restored = MorphDialog(Project('복원', analyzer=saved[0]), tmp_path / 'study.corpusproj', 'target')
    assert not restored.api_key.text()
    assert restored.server_dicts.text() == 'a, b'
    restored.close()


def test_utagger_model_identity_invalidates_on_data_change(tmp_path, monkeypatch):
    root = tmp_path / 'utagger4'
    (root / 'bin').mkdir(parents=True)
    (root / 'bin' / 'UTagger4.so').write_bytes(b'library')
    (root / 'data').write_bytes(b'first')
    monkeypatch.setattr('corpus_app.analyzers.registry.utagger_root', lambda version: root)
    a = model_identity('utagger', {'version': 'utagger4'}, Event())
    (root / 'data').write_bytes(b'other')
    b = model_identity('utagger', {'version': 'utagger4'}, Event())
    assert a != b


def test_utagger_subprocess_protocol_and_parent_cwd(tmp_path, monkeypatch):
    import subprocess, sys
    from corpus_app.analyzers.utagger import UTaggerAnalyzer
    # Substitute only the child process launch, exercise the real IPC adapter.
    original = subprocess.Popen
    script = '''import sys,json
for line in sys.stdin:
 q=json.loads(line)
 print('CORPUS_UTAGGER:'+json.dumps({'ok':True,'tokens':[['테스트__01','NNG']] if 'text' in q else []}),flush=True)
'''
    def launch(*args, **kwargs):
        kwargs['cwd'] = str(tmp_path)
        return original([sys.executable, '-u', '-c', script], **kwargs)
    monkeypatch.setattr('corpus_app.analyzers.utagger.subprocess.Popen', launch)
    before = Path.cwd()
    engine = UTaggerAnalyzer({'version': 'utagger4'})
    try:
        assert engine.analyze('테스트') == [Morpheme('테스트__01', 'NNG')]
        assert Path.cwd() == before
    finally:
        engine.close()
    assert engine.process.poll() is not None


def test_project_rejects_credentials_in_saved_config(tmp_path):
    filename = tmp_path / 'bad.corpusproj'
    project = Project('키 차단', analyzer={'name': 'bareun', 'options': {}, 'api_key': 'not-a-real-key'})
    with pytest.raises(ValueError):
        project.save(filename)
    assert not filename.exists()


def test_utagger_child_crash_and_timeout_are_contained(tmp_path, monkeypatch):
    import subprocess, sys
    from corpus_app.analyzers.utagger import UTaggerAnalyzer
    original = subprocess.Popen
    def crash(*args, **kwargs):
        return original([sys.executable, '-c', 'raise SystemExit(3)'], **kwargs)
    monkeypatch.setattr('corpus_app.analyzers.utagger.subprocess.Popen', crash)
    before = Path.cwd()
    with pytest.raises(RuntimeError):
        UTaggerAnalyzer({'version': 'utagger4'})
    assert Path.cwd() == before
    script = '''import sys,json,time
sys.stdin.readline()
print('CORPUS_UTAGGER:'+json.dumps({'ok':True}),flush=True)
sys.stdin.readline()
time.sleep(60)
'''
    def hangs(*args, **kwargs):
        return original([sys.executable, '-u', '-c', script], **kwargs)
    monkeypatch.setattr('corpus_app.analyzers.utagger.subprocess.Popen', hangs)
    engine = UTaggerAnalyzer({'version': 'utagger4'})
    with pytest.raises(RuntimeError):
        engine.exchange({'text': '테스트'}, timeout=.05)
    assert engine.process.poll() is not None
    engine.close()
