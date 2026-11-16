"""File-wise morphology with atomic SQLite results and content-based reuse."""
from dataclasses import dataclass, asdict
from pathlib import Path
from threading import Event
from contextlib import closing
import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from .json_corpus import Report, Cancelled, checkpoint, json_files, extract_document
from .analyzers.registry import create, engine_version, public_config, model_identity
from .input_formats import documents, CorpusReadError

FORMAT = 1


@dataclass
class MorphResult:
    report: Report
    path: str
    config: dict
    preview: list
    tokens: int
    reused: bool = False


def pack(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def load_result(filename):
    path = Path(filename).resolve()
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        meta = json.loads(db.execute('SELECT value FROM metadata WHERE key="run"').fetchone()[0])
        if meta.get('format') != FORMAT or not meta.get('complete'):
            raise ValueError('지원하지 않거나 미완료된 형태소 결과입니다.')
        preview = db.execute('SELECT substr(text,1,500), source, utterance_id, token_preview FROM utterances ORDER BY seq LIMIT 100').fetchall()
        report = Report(**meta['report'])
        return MorphResult(report, str(path), meta['config'], preview, meta['tokens'])


def analyze_corpus(folder, selected, config, result_dir, cancel=None, progress=None, *, api_key=''):
    cancel = cancel or Event()
    progress = progress or (lambda *args: None)
    folder = Path(folder).resolve()
    if not folder.is_dir() or selected is None:
        raise ValueError('연결된 폴더와 텍스트 필드를 먼저 선택하세요.')
    config = public_config(config)
    if not engine_version(config['name']):
        raise ValueError('선택한 분석기의 Python 패키지를 먼저 설치하세요.')
    config = json.loads(pack(config))
    config.update({'engine_version': engine_version(config['name']),
                   'preprocessing': 'identity', 'format': FORMAT,
                   'input_policy': 'json-utf8/txt-utf8-or-cp949/excel-cached-values-v1',
                   'source_folder': str(folder), 'field_path': list(selected)})
    result_dir = Path(result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(suffix='.sqlite.tmp', dir=result_dir)
    os.close(fd)
    db = None
    analyzer = None
    report = Report()
    token_count = 0
    try:
        config['model_type'] = model_identity(config['name'], config['options'], cancel)
        db = sqlite3.connect(temporary)
        db.executescript('''
            CREATE TABLE inputs (path TEXT PRIMARY KEY, digest TEXT);
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE utterances (seq INTEGER PRIMARY KEY, source TEXT, utterance_id TEXT,
              text TEXT, tokens TEXT, token_preview TEXT);
        ''')
        fingerprint = hashlib.sha256(pack({'config': config, 'folder': str(folder), 'field': selected}).encode())
        for path in json_files(folder, report, cancel):
            checkpoint(cancel)
            try:
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    while chunk := stream.read(1024 * 1024):
                        checkpoint(cancel)
                        digest.update(chunk)
                relative = path.relative_to(folder).as_posix()
                fingerprint.update(pack([relative, digest.hexdigest()]).encode())
                db.execute('INSERT INTO inputs VALUES (?,?)', (str(path), digest.hexdigest()))
            except OSError as error:
                report.error(path, str(error))
            if report.discovered % 25 == 0 or report.discovered == 1:
                progress(report.discovered, 0, report.failed)
        checkpoint(cancel)
        suffix = '-' + uuid.uuid4().hex if config['name'] == 'bareun' else ''
        destination = result_dir / (fingerprint.hexdigest() + suffix + '.sqlite')
        db.commit()
        if destination.is_file() and not report.failed and config['name'] != 'bareun':
            try:
                cached = load_result(destination)
                if not cached.report.failed:
                    cached.reused = True
                    return cached
            except (sqlite3.Error, ValueError, TypeError, KeyError, IndexError):
                pass
        progress(0, 0, report.failed)
        if config['name'] == 'bareun':
            analyzer = create(config['name'], config.get('options', {}), api_key=api_key)
        else:
            analyzer = create(config['name'], config.get('options', {}))
        checkpoint(cancel)
        report.processed = report.failed
        for path, expected in db.execute('SELECT path,digest FROM inputs ORDER BY path'):
            checkpoint(cancel)
            counters = ('texts', 'missing', 'missing_files', 'non_string', 'empty_arrays')
            before = {key: getattr(report, key) for key in counters}
            tokens_before = token_count
            db.execute('SAVEPOINT corpus_file')
            try:
                digest = hashlib.sha256()
                with Path(path).open('rb') as stream:
                    while chunk := stream.read(1024 * 1024):
                        checkpoint(cancel)
                        digest.update(chunk)
                if digest.hexdigest() != expected:
                    raise CorpusReadError('처리 중 파일이 변경되었습니다. 다시 분석하세요.')
                for document in documents(path, cancel):
                    for row in extract_document(document, selected, path, report, cancel):
                        checkpoint(cancel)
                        tokens = [[token.form, token.pos] for token in analyzer.analyze(row['text'])]
                        checkpoint(cancel)
                        db.execute('INSERT INTO utterances(source,utterance_id,text,tokens,token_preview) VALUES (?,?,?,?,?)',
                            (path, row['utterance_id'], row['text'], pack(tokens),
                             ' '.join(f'{form}/{pos}' for form, pos in tokens[:100])[:1500]))
                        report.texts += 1
                        token_count += len(tokens)
                    del document
                report.missing_files = before['missing_files'] + int(report.missing_files > before['missing_files'])
            except (OSError, CorpusReadError) as error:
                db.execute('ROLLBACK TO corpus_file')
                for key, value in before.items():
                    setattr(report, key, value)
                token_count = tokens_before
                report.error(path, f'{type(error).__name__}: {error}')
            else:
                report.succeeded += 1
            db.execute('RELEASE corpus_file')
            report.processed += 1
            if report.processed % 25 == 0 or report.processed == 1:
                db.commit()
                progress(report.processed, report.succeeded, report.failed)
        checkpoint(cancel)
        metadata = {'format': FORMAT, 'complete': True, 'config': config, 'folder': str(folder),
                    'field': list(selected), 'report': asdict(report), 'tokens': token_count}
        db.execute('INSERT INTO metadata VALUES (?,?)', ('run', pack(metadata)))
        db.commit()
        db.close()
        db = None
        os.replace(temporary, destination)
        progress(report.processed, report.succeeded, report.failed)
        return load_result(destination)
    except Cancelled:
        report.cancelled = True
        return MorphResult(report, '', config, [], token_count)
    finally:
        if analyzer is not None and hasattr(analyzer, 'close'):
            try:
                analyzer.close()
            except Exception:
                pass
        if db is not None:
            db.close()
        if os.path.exists(temporary):
            os.unlink(temporary)
