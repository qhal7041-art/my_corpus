"""Disk-backed, utterance-aware collocation and N-gram statistics (no Qt)."""
from collections import Counter, deque
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from threading import Event
import hashlib
import json
import math
import os
import sqlite3
import tempfile
from ..json_corpus import checkpoint, Cancelled
from ..morphology import load_result, pack


@dataclass
class StatisticsResult:
    path: str
    metadata: dict
    columns: list
    rows: list
    cancelled: bool = False


def score_pair(count, left, right, population, metric):
    expected = left * right / population
    if metric == 'MI':
        return math.log2(count / expected)
    if metric == 't-score':
        return (count - expected) / math.sqrt(count)
    if metric == 'logDice':
        return 14 + math.log2(2 * count / (left + right))
    raise ValueError('지원하지 않는 연어 지표입니다.')


def load_statistics(path, sort='frequency', limit=100, cancel=None, *, low_expected_only=False):
    if sort not in ('frequency', 'score') or limit not in (10, 100, 1000):
        raise ValueError('지원하지 않는 결과 정렬/미리보기 크기입니다.')
    cancel = cancel or Event()
    try:
        checkpoint(cancel)
        filename = Path(path).resolve()
        with closing(sqlite3.connect(filename.as_uri() + '?mode=ro', uri=True)) as db:
            db.set_progress_handler(lambda: int(cancel.is_set()), 1000)
            record = db.execute('SELECT value FROM metadata WHERE key="statistics"').fetchone()
            if not record:
                raise ValueError('통계 결과 파일이 아닙니다.')
            metadata = json.loads(record[0])
            if metadata.get('format') != 1 or not metadata.get('complete'):
                raise ValueError('지원하지 않거나 미완료인 통계 결과입니다.')
            condition = 'WHERE low_expected=1' if low_expected_only and metadata.get('kind') == 'keyness' else ''
            rows = [json.loads(row[0]) for row in db.execute(
                f'SELECT row_json FROM results {condition} ORDER BY {sort} DESC,label ASC LIMIT ?', (limit,))]
            return StatisticsResult(str(filename), metadata, metadata['columns'], rows)
    except (Cancelled, sqlite3.OperationalError):
        if cancel.is_set():
            return StatisticsResult('', {}, [], [], cancelled=True)
        raise


def settings_checked(settings):
    settings = dict(settings)
    kind = settings.get('kind', 'ngram')
    if kind not in ('ngram', 'collocation'):
        raise ValueError('지원하지 않는 통계 분석 종류입니다.')
    if not isinstance(settings.get('pos', ''), str):
        raise ValueError('품사 필터는 문자열이어야 합니다.')
    settings.setdefault('pos', '')
    settings.setdefault('cross_utterances', False)
    if type(settings['cross_utterances']) is not bool:
        raise ValueError('발화 경계 설정이 올바르지 않습니다.')
    if kind == 'ngram':
        settings.setdefault('n', 2)
        settings.setdefault('include_pos', False)
        if type(settings['n']) is not int or not 1 <= settings['n'] <= 10 or type(settings['include_pos']) is not bool:
            raise ValueError('n은 1~10, 품사 포함은 참/거짓이어야 합니다.')
    else:
        settings.setdefault('left', 2)
        settings.setdefault('right', 2)
        settings.setdefault('minimum', 2)
        settings.setdefault('center', '')
        settings.setdefault('metric', 'MI')
        if any(type(settings[k]) is not int or not 0 <= settings[k] <= 50 for k in ('left', 'right')) or settings['left'] + settings['right'] == 0:
            raise ValueError('좌/우 범위는 0~50이며 합은 1 이상이어야 합니다.')
        if type(settings['minimum']) is not int or settings['minimum'] < 1:
            raise ValueError('최소 공기 빈도는 1 이상의 정수여야 합니다.')
        if not isinstance(settings['center'], str) or settings['metric'] not in ('MI', 't-score', 'logDice'):
            raise ValueError('중심어나 연어 지표가 올바르지 않습니다.')
    settings['kind'] = kind
    return settings


def analyze_statistics(source, settings, result_dir, cancel=None, progress=None, *, sort='frequency', limit=None):
    settings = settings_checked(settings)
    if sort not in ('frequency', 'score') or limit not in (None, 10, 100, 1000):
        raise ValueError('지원하지 않는 결과 정렬/미리보기 크기입니다.')
    cancel, progress = cancel or Event(), progress or (lambda *args: None)
    source = Path(source).resolve()
    original = load_result(source)
    kind = settings['kind']
    prefixes = tuple(v.strip().rstrip('*') for v in settings['pos'].split(',') if v.strip())
    def eligible(token):
        return not prefixes or token[1].startswith(prefixes)
    root = Path(result_dir)
    root.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=root, suffix='.sqlite.tmp')
    os.close(fd)
    db = None
    total_tokens = total_items = units = result_count = 0
    try:
        db = sqlite3.connect(temporary)
        db.set_progress_handler(lambda: int(cancel.is_set()), 1000)
        db.executescript('''CREATE TABLE counts(a TEXT,b TEXT,n INTEGER,PRIMARY KEY(a,b));
            CREATE TABLE frequency(token TEXT PRIMARY KEY,n INTEGER);
            CREATE TABLE results(seq INTEGER PRIMARY KEY,label TEXT,frequency INTEGER,score REAL,row_json TEXT);
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);''')
        batch, words = Counter(), Counter()
        def flush():
            db.executemany('INSERT INTO counts VALUES (?,?,?) ON CONFLICT(a,b) DO UPDATE SET n=n+excluded.n',
                           [(a, b, count) for (a, b), count in batch.items()])
            db.executemany('INSERT INTO frequency VALUES (?,?) ON CONFLICT(token) DO UPDATE SET n=n+excluded.n', words.items())
            batch.clear()
            words.clear()
        def add(a, b=''):
            nonlocal total_items
            batch[(a, b)] += 1
            total_items += 1
            if len(batch) >= 5000:
                flush()
        left, right = settings.get('left', 0), settings.get('right', 0)
        window = deque(maxlen=left + right + 1)
        grams = deque(maxlen=settings.get('n', 1))
        def center_at(buffer, index):
            token = buffer[index]
            if not eligible(token):
                return
            for other_index in range(max(0, index - left), min(len(buffer), index + right + 1)):
                if other_index != index and eligible(buffer[other_index]):
                    add(pack(token), pack(buffer[other_index]))
        def finish_window():
            if kind == 'collocation':
                buffer = list(window)
                for index in range(max(0, len(buffer) - right), len(buffer)):
                    center_at(buffer, index)
            window.clear()
            grams.clear()
        previous_file = None
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as input_db:
            for source_file, encoded in input_db.execute('SELECT source,tokens FROM utterances ORDER BY seq'):
                checkpoint(cancel)
                if previous_file is not None and (not settings['cross_utterances'] or source_file != previous_file):
                    finish_window()
                previous_file = source_file
                tokens = json.loads(encoded)
                if not isinstance(tokens, list):
                    raise ValueError('형태소 결과의 토큰 목록이 손상되었습니다.')
                for token in tokens:
                    checkpoint(cancel)
                    if not isinstance(token, list) or len(token) != 2 or any(not isinstance(t, str) or not t for t in token):
                        raise ValueError('형태소 결과에 잘못된 형태소/품사 쌍이 있습니다.')
                    if eligible(token):
                        total_tokens += 1
                        words[pack(token)] += 1
                        if len(words) >= 5000:
                            flush()
                    if kind == 'ngram':
                        if eligible(token):
                            grams.append(token if settings['include_pos'] else token[0])
                            if len(grams) == settings['n']:
                                add(pack(list(grams)))
                    else:
                        window.append(token)
                        if len(window) > right:
                            center_at(list(window), len(window) - right - 1)
                units += 1
                if units % 100 == 0 or units == 1:
                    progress(units, total_tokens, total_items)
        finish_window()
        flush()
        checkpoint(cancel)
        if kind == 'ngram':
            columns = ['N-gram', '빈도', '상대 빈도 / 백만 N-gram']
            for encoded, count in db.execute('SELECT a,n FROM counts'):
                checkpoint(cancel)
                gram = json.loads(encoded)
                label = ' '.join(f'{v[0]}/{v[1]}' if isinstance(v, list) else v for v in gram)
                row = [label, count, count / total_items * 1_000_000]
                db.execute('INSERT INTO results(label,frequency,score,row_json) VALUES (?,?,?,?)', (label, count, count, pack(row)))
                result_count += 1
        else:
            columns = ['중심 형태소', '중심 품사', '결합 형태소', '결합 품사', '중심 토큰 빈도', '결합 토큰 빈도',
                       '공기 빈도', '중심 슬롯 주변합', '결합 슬롯 주변합', settings['metric']]
            db.executescript('''CREATE TABLE lm AS SELECT a AS token,SUM(n) AS n FROM counts GROUP BY a;
                CREATE TABLE rm AS SELECT b AS token,SUM(n) AS n FROM counts GROUP BY b;
                CREATE UNIQUE INDEX li ON lm(token); CREATE UNIQUE INDEX ri ON rm(token);''')
            query = '''SELECT c.a,c.b,c.n,lm.n,rm.n,f1.n,f2.n FROM counts c
                JOIN lm ON lm.token=c.a JOIN rm ON rm.token=c.b
                JOIN frequency f1 ON f1.token=c.a JOIN frequency f2 ON f2.token=c.b WHERE c.n>=?'''
            for a, b, count, x, y, fx, fy in db.execute(query, (settings['minimum'],)):
                checkpoint(cancel)
                first, second = json.loads(a), json.loads(b)
                if settings['center'] and first[0] != settings['center'].strip():
                    continue
                score = score_pair(count, x, y, total_items, settings['metric'])
                row = [*first, *second, fx, fy, count, x, y, score]
                db.execute('INSERT INTO results(label,frequency,score,row_json) VALUES (?,?,?,?)',
                           (pack([first, second]), count, score, pack(row)))
                result_count += 1
        note = ''
        if not total_items:
            note = '선택 품사와 경계 조건에서 생성된 N-gram/공기 슬롯이 0입니다. n·탐색 범위·발화 길이·품사 필터를 확인하세요.'
        elif not result_count:
            note = '최소 빈도 또는 중심어 조건에 맞는 후보가 없습니다.'
        metadata = {'format': 1, 'complete': True, 'kind': kind, 'settings': settings,
                    'source': str(source), 'producer': original.config, 'columns': columns,
                    'utterances': units, 'eligible_tokens': total_tokens, 'population': total_items,
                    'result_count': result_count, 'note': note,
                    'boundary': 'file boundaries always preserved; utterances crossed only when enabled'}
        db.execute('INSERT INTO metadata VALUES (?,?)', ('statistics', pack(metadata)))
        db.commit()
        db.close()
        db = None
        # Hash the completed immutable result, including settings and counts.
        digest = hashlib.sha256()
        with open(temporary, 'rb') as stream:
            while chunk := stream.read(1024 * 1024):
                checkpoint(cancel)
                digest.update(chunk)
        destination = root / ('statistics-' + digest.hexdigest() + '.sqlite')
        os.replace(temporary, destination)
        progress(units, total_tokens, total_items)
        return load_statistics(destination, sort, limit or (10 if kind == 'ngram' else 100), cancel)
    except (Cancelled, sqlite3.OperationalError):
        if not cancel.is_set():
            raise
        return StatisticsResult('', {}, [], [], cancelled=True)
    finally:
        if db is not None:
            db.close()
        if os.path.exists(temporary):
            os.unlink(temporary)
