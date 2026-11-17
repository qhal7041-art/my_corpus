import io
import json
from pathlib import Path
from threading import Event, Timer
import sys
import pytest
from corpus_app.analyzers.registry import public_config
from corpus_app.analyzers.baropy_local import BaropyAnalyzer
from corpus_app.json_corpus import Cancelled
from corpus_app.analyzers import Morpheme

BRIDGE = '''import sys,json,pathlib,time
initial=json.loads(sys.stdin.readline())
runtime=pathlib.Path(initial['runtime'])
(runtime/'var'/'models').mkdir(parents=True,exist_ok=True)
(runtime/'var'/'models'/'model.bin').write_bytes(b'model-asset')
(runtime/'var'/'api-keys.db.pb').write_text(initial['api_key'])
(runtime/'logs').mkdir()
(runtime/'logs'/'run.log').write_text(initial['api_key'])
print('CORPUS_BAROPY:'+json.dumps({'ok':True}),flush=True)
for line in sys.stdin:
 q=json.loads(line)
 if q['text']=='hang': time.sleep(60)
 print('CORPUS_BAROPY:'+json.dumps({'ok':True,'tokens':[['밥','NNG']]}),flush=True)
'''


def bridge(monkeypatch):
    import subprocess
    original = subprocess.Popen
    def launch(args, **kwargs):
        assert 'fixture-secret' not in str(args)
        assert 'fixture-secret' not in str(kwargs.get('env', {}))
        return original([sys.executable, '-u', '-c', BRIDGE], **kwargs)
    monkeypatch.setattr('corpus_app.analyzers.baropy_local.subprocess.Popen', launch)


def test_baropy_model_retained_registration_and_logs_removed(tmp_path, monkeypatch):
    bridge(monkeypatch)
    options = {'model_cache': str(tmp_path / 'models'), 'threads': 2}
    engine = BaropyAnalyzer(options, 'fixture-secret')
    runtime = engine.session
    assert (runtime / 'var' / 'api-keys.db.pb').read_text() == 'fixture-secret'
    assert engine.analyze('밥') == [Morpheme('밥', 'NNG')]
    with pytest.raises(RuntimeError, match='다른 작업'):
        BaropyAnalyzer(options, 'fixture-secret')
    engine.close()
    assert not runtime.exists()
    assert (tmp_path / 'models' / 'models' / 'model.bin').read_bytes() == b'model-asset'
    assert not list((tmp_path / 'models').glob('.corpus-session-*'))
    assert all(b'fixture-secret' not in p.read_bytes() for p in (tmp_path / 'models').rglob('*') if p.is_file())
    second = BaropyAnalyzer(options, 'fixture-secret')
    assert (second.session / 'var' / 'models' / 'model.bin').exists()
    second.close()


def test_baropy_cancel_during_model_wait_is_cancellable(tmp_path, monkeypatch):
    bridge(monkeypatch)
    cancel = Event()
    engine = BaropyAnalyzer({'model_cache': str(tmp_path / 'cache')}, 'fixture-secret', cancel)
    runtime = engine.session
    timer = Timer(.05, cancel.set)
    timer.start()
    try:
        with pytest.raises(Cancelled):
            engine.analyze('hang')
    finally:
        engine.close()
        timer.cancel()
    assert engine.process.poll() is not None
    assert not runtime.exists()
    assert (tmp_path / 'cache' / 'models' / 'model.bin').exists()


def test_real_baropy_sdk_child_registration_analysis_release(tmp_path):
    baropy = pytest.importorskip('baropy')
    fixture = Path(__file__).parent / 'fixtures' / 'baropy_stub_server.py'
    engine = baropy.Bareun(api_key='fixture-secret', binary=[sys.executable, str(fixture)],
                           cache_dir=tmp_path, model_catalog_url='', threads=1, start_timeout=10)
    try:
        result = engine.analyze('밥', split_sentences=False)
        assert result.morphemes.pairs() == [('밥', 'NNG')]
        assert engine.is_loaded
        assert (tmp_path / 'var' / 'api-keys.db.pb').is_file()
        assert 'fixture-secret' not in (tmp_path / 'config' / 'bareun.json').read_text()
    finally:
        # SDK release stops the server but leaves its stdout pipe/HTTP
        # connection to GC. This direct-SDK fixture owns those handles.
        child = engine._child
        try:
            engine.release()
        finally:
            if child is not None and child._proc is not None and child._proc.stdout is not None:
                child._proc.stdout.close()
            engine._drop_conn()
    assert not engine.is_loaded


def test_host_options_sense_dictionary_and_safe_errors(monkeypatch, tmp_path):
    baropy = pytest.importorskip('baropy')
    from corpus_app.analyzers import baropy_host
    from baropy.types import parse_analysis
    calls = []
    class Dicts:
        def put(self, name, **kwargs):
            calls.append(('dict', name, kwargs))
    class Fake:
        def __init__(self, **kwargs):
            calls.append(('create', kwargs))
            self.dicts = Dicts()
        def analyze(self, text, **kwargs):
            calls.append(('analyze', text, kwargs))
            return parse_analysis({'sentences':[{'tokens':[{'morphemes':[
                {'text': {'content':'다리'}, 'tag':'NNG', 'sense':{'senseNo':'005'}}]}]}]})
        def release(self):
            calls.append(('release',))
    monkeypatch.setattr(baropy, 'Bareun', Fake)
    monkeypatch.setattr(baropy_host.signal, 'signal', lambda *args: None)
    initial = {'api_key':'fixture-secret','runtime':str(tmp_path),'options':{'threads':2,'sense':True,'user_nouns':'제주방언\n말뭉치'}}
    output = io.StringIO()
    monkeypatch.setattr(baropy_host.sys, '__stdout__', output)
    monkeypatch.setattr(baropy_host.sys, 'stdin', io.StringIO(json.dumps(initial)+'\n'+json.dumps({'text':'다리'})+'\n'))
    baropy_host.main()
    assert calls[0][1]['api_key'] == 'fixture-secret'
    assert calls[0][1]['background'] is False
    assert calls[1] == ('dict', 'corpus_app', {'np':['제주방언','말뭉치']})
    assert calls[2][2] == {'split_sentences':False,'sense':True,'dicts':['corpus_app']}
    assert '다리__005' in output.getvalue() and 'fixture-secret' not in output.getvalue()
    assert calls[-1] == ('release',)
    assert public_config({'name':'baropy','options':{'threads':2,'user_nouns':'제주'}})['name'] == 'baropy'
    for options in ({'threads':True}, {'threads':0}, {'api_key':'fixture-secret'}):
        with pytest.raises(ValueError):
            public_config({'name':'baropy','options':options})


def test_baropy_ui_key_options_restore_without_key(tmp_path):
    from corpus_app.project import Project, CorpusSource
    from corpus_app.morph_ui import MorphDialog
    project = Project('로컬', target=CorpusSource(str(tmp_path), ['text']))
    dialog = MorphDialog(project, tmp_path / 'local.corpusproj', 'target')
    dialog.show()
    dialog.engine.setCurrentIndex(dialog.engine.findData('baropy'))
    assert dialog.api_key.isVisible() and dialog.local_threads.isVisible()
    assert not dialog.server_dicts.isVisible() and not dialog.bareun_options[0][1].isVisible()
    assert not dialog.run_button.isEnabled()
    dialog.api_key.setText('fixture-secret')
    from corpus_app.analyzers.registry import engine_version
    assert dialog.run_button.isEnabled() == bool(engine_version('baropy'))
    dialog.local_nouns.setPlainText('제주방언')
    config = dialog.config()
    project.analyzer = config
    project.save(tmp_path / 'local.corpusproj')
    assert 'fixture-secret' not in (tmp_path / 'local.corpusproj').read_text()
    restored = Project.load(tmp_path / 'local.corpusproj')
    second = MorphDialog(restored, tmp_path / 'local.corpusproj', 'target')
    assert second.engine.currentData() == 'baropy'
    assert second.local_nouns.toPlainText() == '제주방언'
    assert not second.api_key.text()
    dialog.close(); second.close()


def test_baropy_cache_cannot_modify_source_corpus(tmp_path):
    from corpus_app.morphology import analyze_corpus
    folder = tmp_path / 'source'
    folder.mkdir()
    (folder / 'a.txt').write_text('밥', encoding='utf-8')
    cache = folder / 'model-cache'
    with pytest.raises(ValueError, match='폴더 밖'):
        analyze_corpus(folder, ['text'], {'name':'baropy','options':{'model_cache':str(cache)}}, tmp_path/'results', api_key='fixture-secret')
    assert not cache.exists()
