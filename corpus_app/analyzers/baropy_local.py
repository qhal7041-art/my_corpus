"""Baropy runs in a cancellable helper process with disposable registration state.

Only model files survive. Runtime logs, credentials, license files and custom
registrations live in a private temporary cache, removed after server exit.
"""
from pathlib import Path
from queue import Queue, Empty
from threading import Thread, Event
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import shutil
import time
import uuid
from . import Morpheme
from ..json_corpus import checkpoint

PREFIX = 'CORPUS_BAROPY:'


def default_model_cache():
    return str(Path(tempfile.gettempdir()) / 'corpus-desktop-baropy-models')


class BaropyAnalyzer:
    def status(self):
        from .registry import status
        return status('baropy')

    def supported_options(self):
        return {'threads': int, 'sense': bool, 'user_nouns': str, 'model_cache': str}

    def __init__(self, options, api_key, cancel=None):
        if not api_key.strip():
            raise ValueError('바른 로컬 API 키를 분석 창에 입력하세요.')
        self.options = dict(options)
        self.cancel = cancel or Event()
        self.process = None
        self.lock = None
        self.session = None
        self.root = Path(options.get('model_cache') or default_model_cache()).expanduser().resolve()
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.lock = sqlite3.connect(self.root / 'model-lock.sqlite', timeout=0)
            try:
                self.lock.execute('BEGIN EXCLUSIVE')
            except sqlite3.OperationalError:
                raise RuntimeError('다른 작업이 이 바른 모델 캐시를 사용하고 있습니다. 작업 종료 후 다시 시도하세요.') from None
            self.session = Path(tempfile.mkdtemp(prefix='.corpus-session-', dir=self.root))
            runtime = self.session
            (runtime / 'var').mkdir()
            if (self.root / 'models').exists():
                os.replace(self.root / 'models', runtime / 'var' / 'models')
            checkpoint(self.cancel)
            self.process = subprocess.Popen([sys.executable, '-m', 'corpus_app.analyzers.baropy_host'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf-8', cwd=str(Path(__file__).resolve().parents[2]))
            self.responses = Queue()
            def read():
                try:
                    for line in self.process.stdout:
                        if PREFIX in line:
                            try:
                                self.responses.put(json.loads(line.split(PREFIX, 1)[1]))
                            except ValueError:
                                continue
                finally:
                    self.responses.put(None)
            self.reader = Thread(target=read, daemon=True)
            self.reader.start()
            self.exchange({'api_key': api_key.strip(), 'runtime': str(runtime), 'options': options}, timeout=30)
        except BaseException:
            self.close()
            raise

    def exchange(self, message, timeout=1860):
        try:
            self.process.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
            self.process.stdin.flush()
            deadline = time.monotonic() + timeout
            while True:
                checkpoint(self.cancel)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError('바른 로컬 응답 제한 시간을 초과했습니다. 모델 캐시·네트워크를 확인하세요.')
                try:
                    response = self.responses.get(timeout=min(.1, remaining))
                    break
                except Empty:
                    continue
            if not response or not response.get('ok'):
                code = (response or {}).get('code', '')
                hints = {'AuthError': 'API 키·라이선스·등록 서버 연결을 확인하세요.',
                         'ModelFetchError': '모델 다운로드 네트워크와 디스크 공간을 확인하세요.',
                         'ServerStartError': '지원 OS·메모리·모델 파일·시작 제한 시간을 확인하세요.'}
                raise RuntimeError('바른 로컬 초기화/분석 실패. ' + hints.get(code, 'SDK 설치·키·모델 캐시를 확인하세요.'))
            return response.get('tokens', [])
        except (BrokenPipeError, OSError):
            raise RuntimeError('바른 로컬 작업 프로세스가 종료되었습니다.') from None

    def analyze(self, text):
        if not text.strip():
            return []
        return [Morpheme(form, pos) for form, pos in self.exchange({'text': text})]

    def close(self):
        try:
            if self.process is not None:
                if self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=12)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait()
                if hasattr(self, 'reader'):
                    self.reader.join(timeout=2)
                for stream in (self.process.stdin, self.process.stdout):
                    if stream and not stream.closed:
                        stream.close()
            if self.session is not None:
                runtime = self.session
                models = runtime / 'var' / 'models'
                recovered = False
                try:
                    if models.exists():
                        destination = self.root / 'models'
                        if destination.exists():
                            destination = self.root / ('models-recovered-' + uuid.uuid4().hex)
                        deadline = time.monotonic() + 10
                        while True:
                            try:
                                os.replace(models, destination)
                                break
                            except PermissionError:
                                if time.monotonic() >= deadline:
                                    raise
                                time.sleep(.1)
                    recovered = True
                finally:
                    # Remove SDK key database, license, logs, traces and local dictionaries.
                    if not recovered:
                        # Preserve model files if a platform file lock prevents a move.
                        for child in runtime.iterdir():
                            entries = list(child.iterdir()) if child.name == 'var' and child.is_dir() else [child]
                            for entry in entries:
                                if entry == models:
                                    continue
                                if entry.is_dir() and not entry.is_symlink():
                                    shutil.rmtree(entry)
                                else:
                                    entry.unlink(missing_ok=True)
                        self.session = None
                        raise RuntimeError('모델 이동에 실패했습니다. 임시 폴더의 모델을 보존했으며 등록 정보는 삭제했습니다.') from None
                    deadline = time.monotonic() + 10
                    while True:
                        try:
                            shutil.rmtree(runtime)
                            break
                        except PermissionError:
                            if time.monotonic() >= deadline:
                                raise
                            time.sleep(.1)
                    self.session = None
        finally:
            if self.lock is not None:
                self.lock.close()
                self.lock = None
