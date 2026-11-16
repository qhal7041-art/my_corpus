"""Bounded records for JSON documents, TXT lines and Excel worksheet rows."""
from pathlib import Path
import codecs

SUPPORTED_SUFFIXES = {'.json', '.txt', '.xlsx', '.xls'}


class CorpusReadError(ValueError):
    """A reader failure, distinguished from an analyzer failure."""


def text_encoding(path, cancel):
    from .json_corpus import checkpoint
    decoder = codecs.getincrementaldecoder('utf-8-sig')('strict')
    try:
        with path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                checkpoint(cancel)
                decoder.decode(chunk)
            decoder.decode(b'', final=True)
        return 'utf-8-sig'
    except UnicodeDecodeError:
        return 'cp949'


def columns(values):
    from openpyxl.utils import get_column_letter
    return [f'{get_column_letter(i + 1)}: {value if value is not None else "(열 이름 없음)"}'
            for i, value in enumerate(values)]


def excel_record(sheet, number, names, values):
    row = dict(zip(names, values))
    identifier = f'{sheet}!{number}'
    raw_headers = {name.split(': ', 1)[1]: value for name, value in zip(names, values)}
    for key in ('utterance_id', 'utteranceId', 'id', '발화 ID', '발화ID'):
        candidate = raw_headers.get(key)
        if isinstance(candidate, (str, int, float)) and not isinstance(candidate, bool) and candidate != '':
            identifier = str(candidate)
            break
    return {'id': identifier, 'sheets': {sheet: {'rows': [row]}}}


def documents(path, cancel):
    from .json_corpus import Cancelled
    try:
        yield from _documents(path, cancel)
    except Cancelled:
        raise
    except Exception as error:
        raise CorpusReadError(f'{type(error).__name__}: {error}') from error


def _documents(path, cancel):
    from .json_corpus import read_json, checkpoint
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == '.json':
        yield read_json(path)
    elif suffix == '.txt':
        with path.open(encoding=text_encoding(path, cancel)) as stream:
            for number, line in enumerate(stream, 1):
                checkpoint(cancel)
                text = line.rstrip('\r\n')
                if text.strip():
                    yield {'id': f'line:{number}', 'text': text}
    elif suffix == '.xlsx':
        from openpyxl import load_workbook
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in workbook.worksheets:
                rows = sheet.iter_rows(values_only=True)
                names = columns(next(rows, ()))
                for number, values in enumerate(rows, 2):
                    checkpoint(cancel)
                    if any(value is not None for value in values):
                        yield excel_record(sheet.title, number, names, values)
        finally:
            workbook.close()
    elif suffix == '.xls':
        import xlrd
        workbook = xlrd.open_workbook(path, on_demand=True)
        try:
            for sheet_index in range(workbook.nsheets):
                sheet = workbook.sheet_by_index(sheet_index)
                if not sheet.nrows:
                    workbook.unload_sheet(sheet_index)
                    continue
                names = columns(sheet.row_values(0))
                for index in range(1, sheet.nrows):
                    checkpoint(cancel)
                    values = sheet.row_values(index)
                    if any(value != '' for value in values):
                        yield excel_record(sheet.name, index + 1, names, values)
                workbook.unload_sheet(sheet_index)
        finally:
            workbook.release_resources()
    else:
        raise ValueError(f'지원하지 않는 파일 형식: {suffix}')
