"""Import pretagged data into the same immutable utterance database as analyzers."""
from pathlib import Path
from threading import Event
from dataclasses import asdict
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
from .json_corpus import Report, checkpoint, Cancelled
from .input_formats import documents, text_encoding
from .morphology import FORMAT, pack, load_result, MorphResult


def parse_path(text):
    """Parse the displayed JSON path; no eval or executable expressions."""
    if not text.startswith('$'):
        raise ValueError('JSON 경로는 $로 시작해야 합니다.')
    result, position = [], 1
    decoder = json.JSONDecoder()
    while position < len(text):
        if text.startswith('[*]', position):
            result.append(None)
            position += 3
        elif text[position] == '.':
            match = re.match(r'[^\W\d]\w*', text[position + 1:], re.UNICODE)
            if not match:
                raise ValueError('올바르지 않은 점 표기 경로입니다.')
            result.append(match[0])
            position += len(match[0]) + 1
        elif text[position] == '[':
            try:
                key, consumed = decoder.raw_decode(text[position + 1:])
            except ValueError:
                raise ValueError('대괄호 키는 JSON 문자열로 입력하세요.') from None
            end = position + 1 + consumed
            if not isinstance(key, str) or end >= len(text) or text[end] != ']':
                raise ValueError('대괄호 키는 문자열 또는 [*]만 지원합니다.')
            result.append(key)
            position = end + 1
        else:
            raise ValueError('지원하지 않는 JSON 경로 표기입니다.')
    return result


def selected_values(value, path, cancel, identifier='', report=None):
    checkpoint(cancel)
    if isinstance(value, dict):
        for name in ('utterance_id', 'utteranceId', 'id'):
            if isinstance(value.get(name), (str, int)) and not isinstance(value.get(name), bool):
                identifier = str(value[name])
                break
    if not path:
        yield value, identifier
    elif path[0] is None and isinstance(value, list):
        for child in value:
            yield from selected_values(child, path[1:], cancel, identifier, report)
    elif isinstance(path[0], str) and isinstance(value, dict) and path[0] in value:
        yield from selected_values(value[path[0]], path[1:], cancel, identifier, report)
    elif report is not None:
        report.missing += 1


def valid_pair(form, pos):
    if not isinstance(form, str) or not form or not isinstance(pos, str) or not pos.strip():
        raise ValueError('형태소/품사는 비어 있지 않은 문자열이어야 합니다. 숫자·누락 품사는 자동 추정하지 않습니다.')
    return [form, pos.strip()]


def slash_tokens(line, plus_delimited=False):
    for word in line.split():
        start = 0
        if plus_delimited:
            for index, char in enumerate(word):
                prefix = word[start:index]
                if char == '+' and '/' in prefix and '/' in word[index + 1:]:
                    form, pos = prefix.rsplit('/', 1)
                    if form and pos and '+' not in pos:
                        yield valid_pair(form, pos)
                        start = index + 1
        token = word[start:]
        if '/' not in token:
            raise ValueError('형태소/품사 형식이 아닙니다.')
        yield valid_pair(*token.rsplit('/', 1))


def column(row, name):
    if name in row:
        return row[name]
    matches = [value for key, value in row.items() if key.split(': ', 1)[-1] == name or key.split(': ', 1)[0] == name]
    if len(matches) != 1:
        raise ValueError(f'열을 고유하게 찾을 수 없습니다: {name}. 중복 열은 A, B 등의 열 문자로 지정하세요.')
    return matches[0]


def tagged_units(path, config, report, cancel):
    mode = config['mode']
    if mode == 'json':
        selected = parse_path(config.get('path', '$.utterances[*].tokens'))
        for document in documents(path, cancel):
            for value, identifier in selected_values(document, selected, cancel, report=report):
                # An array is one utterance, not one token. Empty arrays preserve boundaries.
                if not isinstance(value, list):
                    raise ValueError('JSON 선택 경로는 발화별 형태소 배열을 가리켜야 합니다. 마지막 [*]를 제외해 보세요.')
                tokens = []
                for token in value:
                    checkpoint(cancel)
                    if isinstance(token, dict):
                        tokens.append(valid_pair(token.get(config.get('form_key', 'form')), token.get(config.get('pos_key', 'pos'))))
                    elif isinstance(token, (list, tuple)) and len(token) == 2:
                        tokens.append(valid_pair(*token))
                    else:
                        raise ValueError('각 토큰은 형태소·품사 객체 또는 [형태소, 품사] 쌍이어야 합니다.')
                yield identifier, tokens
    elif mode in ('slash', 'tsv'):
        with Path(path).open(encoding=text_encoding(Path(path), cancel)) as stream:
            pending = []
            number = 0
            for number, line in enumerate(stream, 1):
                checkpoint(cancel)
                if mode == 'slash':
                    if line.strip():
                        try:
                            tokens = list(slash_tokens(line, config.get('plus_delimited', False)))
                        except ValueError as error:
                            raise ValueError(f'{number}행: {error}') from None
                        yield f'line:{number}', tokens
                elif not line.strip():
                    if pending:
                        yield f'block-end:{number}', pending
                        pending = []
                else:
                    parts = line.rstrip('\r\n').split('\t')
                    if len(parts) != 2:
                        raise ValueError(f'{number}행: TSV는 형태소와 품사 두 열이어야 합니다 (헤더 없음).')
                    pending.append(valid_pair(*parts))
            if pending:
                yield f'block-end:{number}', pending
    elif mode == 'excel':
        previous, tokens, identifier = None, [], ''
        for document in documents(path, cancel):
            checkpoint(cancel)
            for sheet, content in document.get('sheets', {}).items():
                for row in content['rows']:
                    group = str(column(row, config['id_key'])) if config.get('id_key') else 'sheet'
                    if group in ('None', ''):
                        raise ValueError('발화 ID 열에 빈 값이 있습니다.')
                    key = (sheet, group)
                    if previous is not None and previous != key:
                        yield identifier, tokens
                        tokens = []
                    previous, identifier = key, f'{sheet}!{group}'
                    tokens.append(valid_pair(column(row, config.get('form_key', 'form')), column(row, config.get('pos_key', 'pos'))))
        if previous is not None:
            yield identifier, tokens
    else:
        raise ValueError('지원하지 않는 사전 분석 형식입니다.')


def import_tagged(files, config, result_dir, cancel=None, progress=None):
    cancel, progress = cancel or Event(), progress or (lambda *args: None)
    files = list(dict.fromkeys(str(Path(path).resolve()) for path in files))
    if not files:
        raise ValueError('불러올 파일을 선택하세요.')
    result_dir = Path(result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(suffix='.sqlite.tmp', dir=result_dir)
    os.close(fd)
    db = None
    report = Report()
    count = 0
    last_update = 0.0
    def update(force=False):
        nonlocal last_update
        now = time.monotonic()
        if force or now - last_update >= .1:
            progress(report.texts, report.succeeded, report.failed)
            last_update = now
    producer = {'name': 'imported', 'engine_version': 'pretagged-v1', 'options': dict(config),
                'preprocessing': 'none; forms and POS preserved', 'original_text': 'reconstructed from imported forms',
                'boundary': 'one JSON array/TXT line/TSV block/Excel consecutive ID group'}
    fingerprint = hashlib.sha256(pack(producer).encode())
    try:
        db = sqlite3.connect(temporary)
        db.executescript('''CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE inputs(path TEXT PRIMARY KEY,digest TEXT);
            CREATE TABLE utterances(seq INTEGER PRIMARY KEY, source TEXT, utterance_id TEXT, text TEXT, tokens TEXT, token_preview TEXT);''')
        for filename in files:
            checkpoint(cancel)
            path = Path(filename).resolve()
            report.discovered += 1
            counters = {key: getattr(report, key) for key in ('texts', 'missing', 'missing_files')}
            before = count
            db.execute('SAVEPOINT input_file')
            try:
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    while chunk := stream.read(1024 * 1024):
                        checkpoint(cancel)
                        digest.update(chunk)
                fingerprint.update(pack([str(path), digest.hexdigest()]).encode())
                db.execute('INSERT INTO inputs VALUES (?,?)', (str(path), digest.hexdigest()))
                for identifier, tokens in tagged_units(path, config, report, cancel):
                    checkpoint(cancel)
                    db.execute('INSERT INTO utterances(source,utterance_id,text,tokens,token_preview) VALUES (?,?,?,?,?)',
                        (str(path), identifier, ' '.join(form for form, pos in tokens), pack(tokens),
                         ' '.join(f'{form}/{pos}' for form, pos in tokens[:100])[:1500]))
                    report.texts += 1
                    count += len(tokens)
                    if report.texts % 100 == 0:
                        update()
                report.missing_files += int(report.missing > counters['missing'])
            except (OSError, ValueError, UnicodeError, RecursionError) as error:
                db.execute('ROLLBACK TO input_file')
                for key, value in counters.items():
                    setattr(report, key, value)
                count = before
                report.error(path, str(error))
            else:
                report.succeeded += 1
            db.execute('RELEASE input_file')
            db.commit()
            report.processed += 1
            update()
        checkpoint(cancel)
        update(True)
        if report.succeeded == 0 or report.texts == 0:
            reasons = '\n'.join(f'{path}: {reason}' for path, reason in report.errors[:5])
            raise ValueError('가져온 발화가 없습니다. 경로/열/형태소·품사 형식을 확인하세요.\n' + reasons)
        metadata = {'format': FORMAT, 'complete': True, 'config': producer,
                    'report': asdict(report), 'tokens': count}
        db.execute('INSERT INTO metadata VALUES (?,?)', ('run', pack(metadata)))
        db.commit()
        db.close()
        db = None
        destination = result_dir / ('import-' + fingerprint.hexdigest() + '.sqlite')
        os.replace(temporary, destination)
        return load_result(destination)
    except Cancelled:
        report.cancelled = True
        return MorphResult(report, '', producer, [], count)
    finally:
        if db is not None:
            db.close()
        if os.path.exists(temporary):
            os.unlink(temporary)


def import_database(filename, result_dir, cancel=None, progress=None):
    """Copy a verified application result; never mutate or run the source DB."""
    cancel = cancel or Event()
    progress = progress or (lambda *args: None)
    try:
        original = load_result(filename)
    except (OSError, sqlite3.Error, TypeError, ValueError, KeyError, IndexError):
        raise ValueError('이 앱에서 저장한 완료된 형태소 SQLite 결과를 선택하세요. 통계 DB/다른 프로그램 DB는 가져올 수 없습니다.') from None
    root = Path(result_dir)
    root.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=root, suffix='.sqlite.tmp')
    try:
        digest = hashlib.sha256()
        copied = 0
        with os.fdopen(fd, 'wb') as output, Path(filename).open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                checkpoint(cancel)
                output.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
                progress(copied // (1024 * 1024), 0, 0)
        destination = root / ('import-db-' + digest.hexdigest() + '.sqlite')
        load_result(temp)
        os.replace(temp, destination)
        return load_result(destination)
    except Cancelled:
        return MorphResult(Report(cancelled=True), '', original.config, [], 0)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
