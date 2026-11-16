"""Streaming by file, bounded schema/preview, cancellable JSON exploration.

Paths are tuples of literal keys and None (array wildcard), never evaluated code.
Only a single JSON document is materialized at once.
"""
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
import json
import os
import re
import time

MAX_SCHEMA_FIELDS = 10000
MAX_PREVIEW = 100
MAX_ERRORS = 100
MAX_EXAMPLE = 160


class Cancelled(Exception):
    pass


def checkpoint(cancel):
    if cancel.is_set():
        raise Cancelled()


def display_path(path):
    result = "$"
    for key in path:
        if key is None:
            result += "[*]"
        elif re.fullmatch(r"[^\W\d]\w*", key, re.UNICODE):
            result += "." + key
        else:
            result += "[" + json.dumps(key, ensure_ascii=False) + "]"
    return result


def value_type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "number"


def example(value):
    kind = value_type(value)
    if kind == "object":
        return f"객체 ({len(value)}개 키)"
    if kind == "array":
        return f"배열 ({len(value)}개 항목)"
    if isinstance(value, str):
        return value[:MAX_EXAMPLE]
    return str(value)[:MAX_EXAMPLE]


@dataclass
class FieldInfo:
    path: tuple
    types: set = field(default_factory=set)
    examples: dict = field(default_factory=dict)
    files: int = 0


@dataclass
class Report:
    discovered: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    errors: list = field(default_factory=list)
    cancelled: bool = False
    fields: dict = field(default_factory=dict)
    schema_limited: bool = False
    texts: int = 0
    missing: int = 0
    missing_files: int = 0
    non_string: int = 0
    empty_arrays: int = 0
    preview: list = field(default_factory=list)

    def error(self, path, reason):
        self.failed += 1
        if len(self.errors) < MAX_ERRORS:
            self.errors.append((str(path), str(reason)))


def json_files(folder, report, cancel):
    """Do not retain a list of all file names or follow directory symlinks."""
    def onerror(error):
        report.error(error.filename or folder, error)
    for root, directories, files in os.walk(folder, followlinks=False, onerror=onerror):
        checkpoint(cancel)
        directories.sort()
        for name in sorted(files):
            checkpoint(cancel)
            if name.lower().endswith(".json"):
                path = Path(root) / name
                report.discovered += 1
                yield path


def read_json(path):
    # UTF-8 with or without BOM. Strictly reject nonstandard NaN/Infinity.
    def invalid(value):
        raise ValueError(f"유효하지 않은 JSON 상수: {value}")
    with path.open(encoding="utf-8-sig") as stream:
        return json.load(stream, parse_constant=invalid)


def inspect_document(document, fields, cancel):
    def children(path, value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield path + (key,), child
        else:
            for child in value:
                yield path + (None,), child

    seen = set()
    limited = False
    # Iterator stack avoids duplicating large arrays in memory.
    stack = [((), document)]
    iterators = []
    while stack or iterators:
        checkpoint(cancel)
        if not stack:
            try:
                stack.append(next(iterators[-1]))
            except StopIteration:
                iterators.pop()
            continue
        path, value = stack.pop()
        if path not in fields:
            if len(fields) >= MAX_SCHEMA_FIELDS:
                limited = True
                continue
            fields[path] = FieldInfo(path)
        info = fields[path]
        kind = value_type(value)
        info.types.add(kind)
        info.examples.setdefault(kind, example(value))
        seen.add(path)
        if isinstance(value, (dict, list)):
            iterators.append(children(path, value))
    for path in seen:
        fields[path].files += 1
    return limited


def extract_document(document, selected, source, report, cancel):
    """Yield text with nearest containing object's utterance ID.

    Missing counts are failed traversal branches; an empty array has its own
    count. Non-strings count terminal matches, including null/object/array.
    """
    missing_before = report.missing

    def visit(value, depth, utterance_id):
        checkpoint(cancel)
        if isinstance(value, dict):
            for key in ("utterance_id", "utteranceId", "id"):
                candidate = value.get(key)
                if isinstance(candidate, (str, int)) and not isinstance(candidate, bool):
                    utterance_id = str(candidate)
                    break
        if depth == len(selected):
            if isinstance(value, str):
                yield {"text": value, "source": str(source), "utterance_id": utterance_id or ""}
            else:
                report.non_string += 1
            return
        key = selected[depth]
        if key is None:
            if isinstance(value, list):
                if not value:
                    report.empty_arrays += 1
                for child in value:
                    yield from visit(child, depth + 1, utterance_id)
            else:
                report.missing += 1
        elif isinstance(value, dict) and key in value:
            yield from visit(value[key], depth + 1, utterance_id)
        else:
            report.missing += 1

    yield from visit(document, 0, "")
    if report.missing > missing_before:
        report.missing_files += 1


def process_corpus(folder, cancel=None, progress=None, selected=None):
    """Scan or preview extraction. A cancelled report is explicitly partial."""
    cancel = cancel or Event()
    report = Report()
    last_update = 0.0
    if not Path(folder).is_dir():
        raise ValueError("말뭉치 폴더가 없습니다. ‘폴더 연결/재연결’로 경로를 지정하세요.")
    try:
        for path in json_files(folder, report, cancel):
            checkpoint(cancel)
            try:
                document = read_json(path)
                checkpoint(cancel)
                if selected is None:
                    report.schema_limited |= inspect_document(document, report.fields, cancel)
                else:
                    for row in extract_document(document, selected, path, report, cancel):
                        report.texts += 1
                        if len(report.preview) < MAX_PREVIEW:
                            # Preview never retains complete very long utterances.
                            report.preview.append({**row, "text": row["text"][:500]})
                del document
                report.succeeded += 1
            except (OSError, UnicodeError, ValueError, RecursionError) as error:
                report.error(path, f"{type(error).__name__}: {error}")
            report.processed += 1
            now = time.monotonic()
            if progress and (report.processed % 25 == 0 or now - last_update >= .1):
                progress(report.processed, report.succeeded, report.failed)
                last_update = now
    except Cancelled:
        report.cancelled = True
    if progress:
        progress(report.processed, report.succeeded, report.failed)
    return report
