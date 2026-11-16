"""버전이 명시된 프로젝트 파일. 원본 말뭉치는 수정하지 않는다."""
from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import os
import tempfile


@dataclass
class CorpusSource:
    folder: str = ""
    # None is an array wildcard; strings are literal object keys.
    field_path: list[str | None] | None = None


@dataclass
class Project:
    name: str
    target: CorpusSource = field(default_factory=CorpusSource)
    reference: CorpusSource = field(default_factory=CorpusSource)
    analyzer: dict = field(default_factory=lambda: {"name": "kiwi", "options": {}})
    analysis_settings: dict = field(default_factory=dict)
    results: list[dict] = field(default_factory=list)
    version: int = 1

    def save(self, filename: str | Path):
        """Atomic replacement leaves the previous project intact if writing fails."""
        path = Path(filename)
        payload = asdict(self)
        # Relative paths survive moving a project together with its corpora.
        for role in ("target", "reference"):
            folder = payload[role]["folder"]
            if folder:
                payload[role]["folder"] = os.path.relpath(folder, path.parent.resolve())
        fd, temporary = tempfile.mkstemp(prefix=".corpus-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @classmethod
    def load(cls, filename: str | Path):
        path = Path(filename).resolve()
        with path.open(encoding="utf-8-sig") as stream:
            data = json.load(stream)
        if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
            raise ValueError("지원하지 않는 프로젝트 형식/버전입니다.")
        if not isinstance(data.get("name"), str) or not data["name"].strip():
            raise ValueError("프로젝트 이름이 없습니다.")
        sources = {}
        for role in ("target", "reference"):
            source = data.get(role, {})
            if not isinstance(source, dict) or not isinstance(source.get("folder", ""), str):
                raise ValueError("말뭉치 경로 형식이 올바르지 않습니다.")
            selected = source.get("field_path")
            if selected is not None and (not isinstance(selected, list) or any(x is not None and not isinstance(x, str) for x in selected)):
                raise ValueError("텍스트 필드 경로 형식이 올바르지 않습니다.")
            folder = source.get("folder", "")
            sources[role] = CorpusSource(str((path.parent / folder).resolve()) if folder else "", selected)
        for key, expected in (("analyzer", dict), ("analysis_settings", dict), ("results", list)):
            if not isinstance(data.get(key, expected()), expected):
                raise ValueError(f"{key} 설정 형식이 올바르지 않습니다.")
        return cls(name=data["name"], **sources, analyzer=data.get("analyzer", {}),
                   analysis_settings=data.get("analysis_settings", {}), results=data.get("results", []))
