"""Two-corpus N-gram keyness, with a shared counting policy and reusable counts."""
from contextlib import closing
from pathlib import Path
from threading import Event
import hashlib
import json
import math
import os
import sqlite3
import tempfile
from .analysis import StatisticsResult, analyze_statistics, load_statistics, settings_checked
from ..analyzers.registry import public_config
from ..analyzers.kiwi import user_words
from ..json_corpus import checkpoint, Cancelled
from ..morphology import load_result, pack


def comparison_signature(config):
    """Extraction paths may differ; analyzer, normalization and dictionary may not."""
    name = config.get('name')
    if name == 'imported':
        return {'name': 'imported', 'preprocessing': config.get('preprocessing')}
    clean = public_config({'name': name, 'options': config.get('options', {})})
    options = clean['options']
    if name == 'kiwi':
        effective = {key: options.get(key, False) for key in ('normalize_coda', 'split_complex', 'compatible_jamo')}
        effective['dictionary'] = user_words(options.get('user_dictionary', ''))
    elif name == 'bareun':
        effective = {key: options.get(key, True) for key in ('auto_spacing', 'auto_jointing')}
        effective['custom_dicts'] = options.get('custom_dicts', [])
    elif name == 'baropy':
        effective = {'sense': options.get('sense', False), 'user_nouns': [v.strip() for v in options.get('user_nouns', '').splitlines() if v.strip()]}
    else:
        effective = {'version': options.get('version', 'utagger4')}
    if not config.get('engine_version') or not config.get('model_type') or not config.get('preprocessing'):
        raise ValueError('분석기/모델/전처리 기록이 없습니다. 동일 설정으로 형태소 분석한 결과를 다시 선택하세요.')
    return {'name': name, 'version': config['engine_version'], 'model': config['model_type'],
            'preprocessing': config['preprocessing'], 'options': effective}


def check_compatible(target, reference, confirmed=False):
    first, second = comparison_signature(target), comparison_signature(reference)
    if first != second:
        raise ValueError('대상·참조의 분석기, 버전, 전처리 또는 사전/옵션이 다릅니다. 형태소 분석 창에서 같은 설정으로 분석한 결과를 선택하세요. JSON 필드 경로는 서로 달라도 됩니다.')
    uncertain = first['name'] in ('imported', 'bareun', 'baropy')
    if uncertain and not confirmed:
        raise ValueError('사전 분석 파일 또는 버전 미고정 바른 결과는 자동 검증이 제한됩니다. 분석 방식·품사 체계·전처리·사전이 같음을 확인한 뒤 확인란을 선택하세요.')
    return {'signature': first, 'mode': 'user_confirmed' if uncertain else 'recorded_settings_match',
            'note': '외부 생산 과정/가변 서버 모델과 사전 내용의 동일성은 사용자가 확인했습니다.' if uncertain else '저장된 분석기·버전·전처리·사전·옵션 일치 확인'}


def contingency(a, c, target_total, reference_total, metric):
    if any(type(v) is not int for v in (a, c, target_total, reference_total)) or target_total <= 0 or reference_total <= 0 or not 0 <= a <= target_total or not 0 <= c <= reference_total:
        raise ValueError('유효한 두 말뭉치의 발생 횟수/전체 N-gram 수가 필요합니다.')
    b, d = target_total - a, reference_total - c
    total = target_total + reference_total
    expected = [target_total * (a + c) / total, target_total * (b + d) / total,
                reference_total * (a + c) / total, reference_total * (b + d) / total]
    observed = [a, b, c, d]
    if metric == 'G²':
        statistic = 2 * sum(o * math.log(o / e) for o, e in zip(observed, expected) if o and e)
    elif metric == 'χ²':
        statistic = sum((o - e) ** 2 / e for o, e in zip(observed, expected) if e)
    else:
        raise ValueError('핵심도 지표는 G² 또는 χ²이어야 합니다.')
    product = a * reference_total - c * target_total
    direction = '대상' if product > 0 else '참조' if product < 0 else '동일'
    return max(0.0, statistic), direction, min(expected), any(e < 5 for e in expected)


def ngram_counts(source, settings, root, cancel, progress):
    signature = hashlib.sha256(pack(settings).encode())
    with Path(source).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            checkpoint(cancel)
            signature.update(chunk)
    cache = root / '.ngram-counts'
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / (signature.hexdigest() + '.sqlite')
    if destination.exists():
        try:
            result = load_statistics(destination, 'frequency', 10, cancel)
            checkpoint(cancel)
            if result.metadata.get('kind') == 'ngram' and result.metadata.get('settings') == settings:
                # Verify counts and denominator before reusing a damaged or incomplete cache.
                with closing(sqlite3.connect(destination.as_uri() + '?mode=ro', uri=True)) as db:
                    db.set_progress_handler(lambda: int(cancel.is_set()), 1000)
                    total = db.execute('SELECT COALESCE(SUM(n),0) FROM counts').fetchone()[0]
                if total == result.metadata['population']:
                    return destination, result.metadata, True
        except (sqlite3.Error, ValueError, KeyError, TypeError):
            checkpoint(cancel)
    with tempfile.TemporaryDirectory(prefix='.counts-run-', dir=root) as temporary:
        result = analyze_statistics(source, settings, temporary, cancel, progress)
        checkpoint(cancel)
        os.replace(result.path, destination)
        return destination, result.metadata, False


def analyze_keyness(target, reference, settings, result_dir, cancel=None, progress=None, *, sort='score', limit=10):
    cancel, progress = cancel or Event(), progress or (lambda *args: None)
    if sort not in ('frequency', 'score') or limit not in (10, 100, 1000):
        raise ValueError('지원하지 않는 결과 정렬/미리보기 크기입니다.')
    metric = settings.get('metric', 'G²')
    if metric not in ('G²', 'χ²'):
        raise ValueError('핵심도 지표는 G² 또는 χ²이어야 합니다.')
    shared = settings_checked({'kind': 'ngram', 'n': settings.get('n', 2), 'pos': settings.get('pos', ''),
                              'include_pos': settings.get('include_pos', False), 'cross_utterances': settings.get('cross_utterances', False)})
    target, reference = Path(target).resolve(), Path(reference).resolve()
    first, second = load_result(target), load_result(reference)
    compatibility = check_compatible(first.config, second.config, settings.get('confirm_external') is True)
    root = Path(result_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    temporary, db = None, None
    try:
        progress(-1, 0, 0)
        t_path, t_meta, t_reused = ngram_counts(target, shared, root, cancel, lambda units, tokens, n: progress(-1, units, n))
        progress(-2, 0, 0)
        r_path, r_meta, r_reused = ngram_counts(reference, shared, root, cancel, lambda units, tokens, n: progress(-2, units, n))
        checkpoint(cancel)
        t_total, r_total = t_meta['population'], r_meta['population']
        fd, temporary = tempfile.mkstemp(dir=root, suffix='.sqlite.tmp')
        os.close(fd)
        db = sqlite3.connect(temporary, uri=True)
        db.set_progress_handler(lambda: int(cancel.is_set()), 1000)
        db.executescript('''CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE results(seq INTEGER PRIMARY KEY,label TEXT,frequency INTEGER,score REAL,row_json TEXT,low_expected INTEGER);''')
        columns = ['N-gram', '대상 빈도', '참조 빈도', '대상 상대 빈도 / 백만', '참조 상대 빈도 / 백만',
                   metric, '상대적으로 높은 말뭉치', '최소 기대빈도', '기대빈도 5 미만']
        result_count, low_count, note = 0, 0, ''
        if not t_total or not r_total:
            empty = '·'.join(name for name, total in [('대상', t_total), ('참조', r_total)] if total == 0)
            note = f'{empty} 말뭉치에서 n={shared["n"]}의 전체 N-gram 수가 0입니다. 발화 길이·품사 필터·경계를 확인하세요. 2×2 통계를 계산하지 않았습니다.'
        else:
            db.execute('ATTACH DATABASE ? AS target', (t_path.as_uri() + '?mode=ro',))
            db.execute('ATTACH DATABASE ? AS reference', (r_path.as_uri() + '?mode=ro',))
            query = '''SELECT keys.a,COALESCE(t.n,0),COALESCE(r.n,0)
                FROM (SELECT a FROM target.counts UNION SELECT a FROM reference.counts) AS keys
                LEFT JOIN target.counts t ON t.a=keys.a AND t.b=''
                LEFT JOIN reference.counts r ON r.a=keys.a AND r.b='' '''
            for encoded, a, c in db.execute(query):
                checkpoint(cancel)
                score, direction, minimum, low = contingency(a, c, t_total, r_total, metric)
                gram = json.loads(encoded)
                label = ' '.join(f'{v[0]}/{v[1]}' if isinstance(v, list) else v for v in gram)
                row = [label, a, c, a / t_total * 1000000, c / r_total * 1000000, score, direction, minimum, '예' if low else '아니오']
                db.execute('INSERT INTO results(label,frequency,score,row_json,low_expected) VALUES (?,?,?,?,?)', (label, a, score, pack(row), int(low)))
                result_count += 1
                low_count += int(low)
                if result_count % 1000 == 0:
                    progress(result_count, 0, 0)
        metadata = {'format': 1, 'complete': True, 'kind': 'keyness', 'columns': columns,
                    'settings': {**shared, 'kind': 'keyness', 'metric': metric, 'confirm_external': settings.get('confirm_external') is True},
                    'source': str(target), 'reference': str(reference), 'producer': first.config, 'reference_producer': second.config,
                    'compatibility': compatibility, 'target_ngrams': t_total, 'reference_ngrams': r_total,
                    'counts_reused': {'target': t_reused, 'reference': r_reused},
                    'utterances': t_meta['utterances'], 'reference_utterances': r_meta['utterances'],
                    'eligible_tokens': t_meta['eligible_tokens'], 'reference_eligible_tokens': r_meta['eligible_tokens'],
                    'population': t_total, 'result_count': result_count, 'note': note,
                    'low_expected_count': low_count,
                    'table': '[[a, target_ngrams-a], [c, reference_ngrams-c]]; no Yates correction',
                    'boundary': t_meta['boundary']}
        db.execute('INSERT INTO metadata VALUES (?,?)', ('statistics', pack(metadata)))
        db.commit()
        db.close(); db = None
        digest = hashlib.sha256()
        with open(temporary, 'rb') as stream:
            while chunk := stream.read(1024 * 1024):
                checkpoint(cancel)
                digest.update(chunk)
        checkpoint(cancel)
        destination = root / ('keyness-' + digest.hexdigest() + '.sqlite')
        os.replace(temporary, destination)
        return load_statistics(destination, sort, limit, cancel)
    except (Cancelled, sqlite3.OperationalError):
        if not cancel.is_set():
            raise
        return StatisticsResult('', {}, [], [], cancelled=True)
    finally:
        if db is not None:
            db.close()
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
