"""Isolate pyutagger's process-wide chdir, sys.exit and native library state."""
from pathlib import Path
from queue import Queue, Empty
from threading import Thread
import subprocess
import sys
import json
from . import Morpheme

PREFIX = 'CORPUS_UTAGGER:'


class UTaggerAnalyzer:
    def status(self):
        from .registry import status
        return status('utagger', self.options)

    def supported_options(self):
        return {'version': ('utagger3', 'utagger4', 'utagger4hj')}

    def __init__(self, options):
        self.options = dict(options)
        self.process = subprocess.Popen([sys.executable, '-m', 'corpus_app.analyzers.utagger_host'],
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
        try:
            self.exchange({'version': options.get('version', 'utagger4')}, timeout=120)
        except Exception:
            self.close()
            raise

    def exchange(self, message, timeout=30):
        try:
            self.process.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
            self.process.stdin.flush()
            response = self.responses.get(timeout=timeout)
            if not response or not response.get('ok'):
                raise RuntimeError('UTagger 초기화/분석 실패: 설치 경로·OS별 라이브러리·모델을 확인하세요.')
            return response.get('tokens', [])
        except (BrokenPipeError, OSError, Empty):
            self.close()
            raise RuntimeError('UTagger 프로세스가 종료되었거나 제한 시간을 초과했습니다.') from None

    def analyze(self, text):
        if not text.strip():
            return []
        return [Morpheme(form, pos) for form, pos in self.exchange({'text': text})]

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        for stream in (self.process.stdin, self.process.stdout):
            if stream and not stream.closed:
                stream.close()
        if hasattr(self, 'reader'):
            self.reader.join(timeout=1)
