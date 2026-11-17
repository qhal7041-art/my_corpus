"""Streaming CSV/XLSX exports of complete saved results and their exact settings."""
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
import csv
import json
import os
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from zipfile import ZipFile, ZIP_DEFLATED
from .json_corpus import checkpoint, Cancelled

MAX_EXCEL_ROWS = 1048576
MAX_EXCEL_TEXT = 32767


@dataclass
class ExportResult:
    files: list
    rows: int
    cancelled: bool = False
    warnings: list = field(default_factory=list)


class CommitRecoveryError(RuntimeError):
    pass


def descriptor(db):
    row = db.execute('SELECT value FROM metadata WHERE key="statistics"').fetchone()
    if row:
        meta = json.loads(row[0])
        kind = 'statistics'
        columns = meta['columns']
        if db.execute('SELECT COUNT(*) FROM results').fetchone()[0] != meta['result_count']:
            raise ValueError('통계 결과의 행 수와 메타데이터가 다릅니다.')
    else:
        row = db.execute('SELECT value FROM metadata WHERE key="run"').fetchone()
        if not row:
            raise ValueError('이 앱에서 저장한 결과 파일이 아닙니다.')
        meta = json.loads(row[0])
        kind = 'morphology'
        columns = ['발화 순번', '토큰 순번', '원본 파일', '발화 ID', '형태소', '품사']
        if db.execute('SELECT COUNT(*) FROM utterances').fetchone()[0] != meta['report']['texts']:
            raise ValueError('형태소 결과의 발화 수와 메타데이터가 다릅니다.')
    if meta.get('format') != 1 or not meta.get('complete'):
        raise ValueError('지원하지 않거나 미완료인 결과입니다.')
    return kind, meta, columns


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def protect_inputs(source, metadata, kind, outputs, db):
    """Reject selecting a known input as an output (including CSV's sidecar)."""
    targets = {os.path.normcase(str(path.resolve())) for path in outputs}
    if os.path.normcase(str(source.resolve())) in targets:
        raise ValueError('결과 DB 자체를 내보내기 파일로 덮어쓸 수 없습니다.')
    for entry in metadata.get('report', {}).get('errors', []):
        if entry and os.path.normcase(str(Path(entry[0]).resolve())) in targets:
            raise ValueError('원본 실패 파일도 덮어쓸 수 없습니다. 다른 위치를 선택하세요.')
    producers = [metadata.get('config', {}), metadata.get('producer', {}), metadata.get('reference_producer', {})]
    for producer in producers:
        folder = producer.get('source_folder')
        if folder and any(path.exists() and path.is_relative_to(Path(folder).resolve()) for path in outputs):
            raise ValueError('원본 말뭉치 폴더의 기존 파일을 덮어쓸 수 없습니다. 다른 위치를 선택하세요.')
    def inspect(connection):
        for (name,) in connection.execute('SELECT DISTINCT source FROM utterances'):
            if os.path.normcase(str(Path(name).resolve())) in targets:
                raise ValueError('원본 말뭉치 파일은 내보내기로 덮어쓸 수 없습니다. 다른 위치를 선택하세요.')
    if kind == 'morphology':
        inspect(db)
    else:
        for field_name in ('source', 'reference'):
            filename = metadata.get(field_name)
            if filename and Path(filename).is_file():
                with closing(readonly(filename)) as input_db:
                    inspect(input_db)


def result_rows(db, kind, metadata, include_text, sort, cancel):
    if kind == 'statistics':
        for (encoded,) in db.execute(f'SELECT row_json FROM results ORDER BY {sort} DESC,label ASC'):
            checkpoint(cancel)
            row = json.loads(encoded)
            if not isinstance(row, list) or len(row) != len(metadata['columns']):
                raise ValueError('통계 행의 열 수가 올바르지 않습니다.')
            yield row
    else:
        token_total = 0
        for sequence, source, identifier, text, encoded in db.execute('SELECT seq,source,utterance_id,text,tokens FROM utterances ORDER BY seq'):
            checkpoint(cancel)
            tokens = json.loads(encoded)
            if not isinstance(tokens, list):
                raise ValueError('형태소 토큰 목록이 올바르지 않습니다.')
            if not tokens:
                row = [sequence, '', source, identifier, '', '']
                yield row + [text] if include_text else row
            for order, token in enumerate(tokens, 1):
                checkpoint(cancel)
                if not isinstance(token, list) or len(token) != 2 or any(not isinstance(v, str) or not v for v in token):
                    raise ValueError('형태소/품사 쌍이 올바르지 않습니다.')
                token_total += 1
                row = [sequence, order, source, identifier, *token]
                yield row + [text] if include_text else row
        if token_total != metadata['tokens']:
            raise ValueError('형태소 개수와 저장된 메타데이터가 다릅니다.')


def csv_value(value, safe):
    if safe and isinstance(value, str) and (value.lstrip(' \t\r\n').startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r'))):
        return "'" + value
    if safe and type(value) is int and abs(value) >= 10 ** 15:
        return "'" + str(value)
    return value


def excel_value(sheet, value):
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    if type(value) is int and abs(value) >= 10 ** 15:
        value = str(value)
    if isinstance(value, str):
        if len(value.encode('utf-16-le')) // 2 > MAX_EXCEL_TEXT:
            raise ValueError('Excel 한 셀의 32,767자 제한을 넘었습니다. CSV를 사용하거나 원문 포함을 해제하세요. 내용을 잘라 저장하지 않았습니다.')
        if ILLEGAL_CHARACTERS_RE.search(value):
            raise ValueError('Excel에서 허용하지 않는 제어 문자가 있습니다. CSV로 내보내세요.')
        cell = WriteOnlyCell(sheet, value=value)
        cell.data_type = 's'  # Preserve =,+,-,@ as literal strings, not formulas.
        return cell
    return value


def flatten_settings(value, prefix=''):
    if isinstance(value, dict) and value:
        for key, child in value.items():
            yield from flatten_settings(child, prefix + '.' + str(key) if prefix else str(key))
    else:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        parts, start, units = [], 0, 0
        for index, char in enumerate(encoded):
            size = 2 if ord(char) > 0xffff else 1
            if units + size > 30000:
                parts.append(encoded[start:index])
                start, units = index, 0
            units += size
        parts.append(encoded[start:])
        for number, part in enumerate(parts, 1):
            yield [prefix, number, len(parts), part]


class CancellableFile:
    def __init__(self, stream, cancel):
        self.stream, self.cancel, self.interrupted = stream, cancel, False

    def write(self, data):
        if self.cancel.is_set() and not self.interrupted:
            self.interrupted = True  # Let ZipFile finish its exception cleanup.
            raise Cancelled()
        return self.stream.write(data)

    def __getattr__(self, name):
        return getattr(self.stream, name)


def close_workbook(workbook):
    """Openpyxl's write-only XML temp files also need cleanup on cancellation."""
    if workbook is None:
        return
    for sheet in workbook.worksheets:
        if not sheet.closed:
            sheet.close()
        writer = getattr(sheet, '_writer', None)
        if writer is not None and isinstance(writer.out, str) and os.path.isfile(writer.out):
            writer.cleanup()
    workbook.close()


def commit_outputs(staged, stage, overwrite):
    if not overwrite and any(target.exists() for _, target in staged):
        raise FileExistsError('같은 이름의 출력 파일 또는 설정 파일이 있습니다. 덮어쓰기를 확인하거나 다른 이름을 선택하세요.')
    backups, installed = {}, []
    try:
        for index, (_, target) in enumerate(staged):
            if target.exists():
                backup = stage / f'backup-{index}'
                os.replace(target, backup)
                backups[target] = backup
        for prepared, target in staged:
            os.replace(prepared, target)
            installed.append(target)
    except BaseException:
        failed = []
        for target in installed:
            if target not in backups:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    failed.append(str(target))
        for target, backup in backups.items():
            try:
                os.replace(backup, target)
            except OSError:
                failed.append(str(backup))
        if failed:
            raise CommitRecoveryError('출력 교체/복원에 실패했습니다. 기존 백업과 임시 파일을 보존했습니다: ' + ', '.join(failed)) from None
        raise


def export_result(source, destination, *, cancel=None, progress=None, sort='frequency', include_text=True,
                  csv_safe=True, overwrite=False):
    cancel, progress = cancel or Event(), progress or (lambda *args: None)
    source, destination = Path(source).resolve(), Path(destination).resolve()
    extension = destination.suffix.lower()
    if extension not in ('.csv', '.xlsx') or sort not in ('frequency', 'score'):
        raise ValueError('출력 형식은 .csv 또는 .xlsx, 정렬은 frequency/score여야 합니다.')
    if not destination.parent.is_dir():
        raise ValueError('저장 폴더가 없습니다.')
    sidecar = destination.with_suffix(destination.suffix + '.settings.json')
    outputs = [destination, sidecar] if extension == '.csv' else [destination]
    if not overwrite and any(path.exists() for path in outputs):
        raise FileExistsError('출력 파일이 이미 있습니다. 덮어쓰기 확인 또는 다른 파일명이 필요합니다.')
    stage = Path(tempfile.mkdtemp(prefix='.corpus-export-', dir=destination.parent))
    workbook, keep_stage = None, False
    result = ExportResult([], 0)
    try:
        checkpoint(cancel)
        with closing(readonly(source)) as db:
            db.set_progress_handler(lambda: int(cancel.is_set()), 1000)
            kind, metadata, columns = descriptor(db)
            columns = list(columns)
            if kind == 'morphology' and include_text:
                columns.append('원문 / 재구성 텍스트')
            protect_inputs(source, metadata, kind, outputs, db)
            settings = {'export_schema': 1, 'source_kind': kind, 'source_file': str(source), 'source_metadata': metadata,
                        'exported_at_utc': datetime.now(timezone.utc).isoformat(),
                        'columns': columns, 'sort': sort if kind == 'statistics' else 'utterance/token order',
                        'include_text': include_text if kind == 'morphology' else False,
                        'csv_safe_text': csv_safe if extension == '.csv' else False,
                        'row_policy': 'one token per row; zero-token utterances have a blank token index' if kind == 'morphology' else 'all saved candidates, independent of UI preview',
                        'excel_text_policy': 'strings are literal; integers with 16+ digits are text',
                        'csv_text_policy': "when enabled: prefix formula-leading strings and 16+ digit integers with apostrophe"}
            count, last_update = 0, 0.0
            rows = result_rows(db, kind, metadata, include_text, sort, cancel)
            prepared = stage / ('data' + extension)
            if extension == '.csv':
                with prepared.open('w', encoding='utf-8-sig', newline='') as stream:
                    writer = csv.writer(stream)
                    writer.writerow(columns)
                    for row in rows:
                        checkpoint(cancel)
                        writer.writerow([csv_value(value, csv_safe) for value in row])
                        count += 1
                        now = time.monotonic()
                        if count % 1000 == 0 or now - last_update >= .1:
                            progress(count, 0, 0); last_update = now
                    stream.flush(); os.fsync(stream.fileno())
                settings['exported_rows'] = count
                settings['output_format'] = 'csv/utf-8-sig'
                staged_settings = stage / 'settings.json'
                with staged_settings.open('w', encoding='utf-8') as stream:
                    json.dump(settings, stream, ensure_ascii=False, indent=2, allow_nan=False)
                    stream.flush(); os.fsync(stream.fileno())
                staged = [(prepared, destination), (staged_settings, sidecar)]
            else:
                from openpyxl import Workbook
                workbook = Workbook(write_only=True)
                sheet_index, sheet_rows = 1, 1
                sheet = workbook.create_sheet('결과_1')
                sheet.append([excel_value(sheet, value) for value in columns])
                for row in rows:
                    checkpoint(cancel)
                    if sheet_rows >= MAX_EXCEL_ROWS:
                        sheet_index += 1
                        sheet = workbook.create_sheet(f'결과_{sheet_index}')
                        sheet.append([excel_value(sheet, value) for value in columns])
                        sheet_rows = 1
                    sheet.append([excel_value(sheet, value) for value in row])
                    count += 1; sheet_rows += 1
                    now = time.monotonic()
                    if count % 1000 == 0 or now - last_update >= .1:
                        progress(count, 0, 0); last_update = now
                settings.update(exported_rows=count, output_format='xlsx', result_sheets=sheet_index)
                settings_sheet = workbook.create_sheet('분석 설정')
                settings_sheet.append(['항목', '부분', '전체 부분', 'JSON 값'])
                for row in flatten_settings(settings):
                    checkpoint(cancel)
                    settings_sheet.append([excel_value(settings_sheet, value) for value in row])
                with prepared.open('w+b') as stream:
                    # A managed archive also closes correctly when cancellation
                    # interrupts compression; Workbook.save does not use a context.
                    from openpyxl.writer.excel import ExcelWriter
                    workbook.properties.modified = datetime.now(timezone.utc).replace(tzinfo=None)
                    with ZipFile(CancellableFile(stream, cancel), 'w', ZIP_DEFLATED, allowZip64=True) as archive:
                        ExcelWriter(workbook, archive).write_data()
                    stream.flush(); os.fsync(stream.fileno())
                staged = [(prepared, destination)]
            checkpoint(cancel)
            # Commit only after the DB snapshot has been fully consumed and files closed.
        commit_outputs(staged, stage, overwrite)
        result = ExportResult([str(path) for path in outputs], count)
        progress(count, count, 0)
        return result
    except (Cancelled, sqlite3.OperationalError):
        if not cancel.is_set():
            raise
        result = ExportResult([], 0, cancelled=True)
        return result
    except CommitRecoveryError:
        keep_stage = True
        raise
    finally:
        close_workbook(workbook)
        if not keep_stage:
            try:
                shutil.rmtree(stage)
            except OSError:
                result.warnings.append('임시 파일/기존 백업을 정리하지 못했습니다: ' + str(stage))
