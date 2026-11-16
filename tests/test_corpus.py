import json
from threading import Event
import pytest
from corpus_app.project import Project, CorpusSource
from corpus_app.json_corpus import process_corpus, display_path


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def mixed(folder):
    write(folder / "a.json", {"utterances": [{"id": "u1", "text": "밥 묵었나?"}, {"utterance_id": "u2", "text": "응"}, {"id": "u3", "text": 7}, {}]})
    write(folder / "nested" / "b.JSON", {"utterances": [{"id": "u4", "text": "반갑수다"}], "dialect": "제주"})
    write(folder / "c.json", {"other": "구조가 다름"})
    (folder / "broken.json").write_text('{"broken":', encoding="utf-8")


def test_mixed_schema_and_extraction(tmp_path):
    mixed(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    schema = process_corpus(tmp_path)
    assert (schema.processed, schema.succeeded, schema.failed) == (4, 3, 1)
    assert schema.fields[("utterances", None, "text")].files == 2
    assert schema.fields[("utterances", None, "text")].types == {"string", "number"}
    assert schema.fields[("dialect",)].files == 1
    assert schema.fields[()].files == 3
    result = process_corpus(tmp_path, selected=("utterances", None, "text"))
    assert (result.texts, result.missing, result.missing_files, result.non_string) == (3, 2, 2, 1)
    assert [row["utterance_id"] for row in result.preview] == ["u1", "u2", "u4"]
    assert all(row["source"].endswith(("a.json", "b.JSON")) for row in result.preview)
    assert "JSONDecodeError" in result.errors[0][1]
    assert before == {p: p.read_bytes() for p in before}


def test_project_roundtrip_and_move(tmp_path):
    folder = tmp_path / "research"
    folder.mkdir()
    (folder / "target").mkdir()
    (folder / "reference").mkdir()
    project = Project("방언 연구", CorpusSource(str(folder / "target"), ["utterances", None, "text"]),
                      CorpusSource(str(folder / "reference"), ["document", "text"]),
                      analyzer={"name": "kiwi", "options": {"normalize_coda": True}},
                      analysis_settings={"n": 3}, results=[{"type": "ngram", "path": "results/frequency.csv"}])
    project.save(folder / "study.corpusproj")
    assert not PathLikeAbsolute((folder / "study.corpusproj").read_text())
    moved = tmp_path / "moved"
    folder.rename(moved)
    restored = Project.load(moved / "study.corpusproj")
    assert restored.target.folder == str(moved / "target")
    assert restored.target.field_path == ["utterances", None, "text"]
    assert restored.reference.field_path == ["document", "text"]
    assert restored.analyzer == project.analyzer
    assert restored.results == project.results
    assert restored.analysis_settings == {"n": 3}
    restored.target.folder = str(moved / "new-location")
    restored.save(moved / "study.corpusproj")
    assert Project.load(moved / "study.corpusproj").target.field_path == project.target.field_path


def PathLikeAbsolute(payload):
    return json.loads(payload)["target"]["folder"].startswith("/")


def test_root_array_special_keys_and_empty(tmp_path):
    write(tmp_path / "data.json", [{"a.b": {"[*]": "텍스트"}}, {"a.b": {"[*]": None}}])
    selected = (None, "a.b", "[*]")
    assert display_path(selected) == '$[*]["a.b"]["[*]"]'
    schema = process_corpus(tmp_path)
    assert selected in schema.fields
    result = process_corpus(tmp_path, selected=selected)
    assert result.texts == 1 and result.non_string == 1
    write(tmp_path / "empty.json", [])
    result = process_corpus(tmp_path, selected=selected)
    assert result.empty_arrays == 1


def test_preview_is_bounded_and_bom(tmp_path):
    (tmp_path / "data.json").write_text(json.dumps(["가" * 2000] * 150), encoding="utf-8-sig")
    result = process_corpus(tmp_path, selected=(None,))
    assert result.texts == 150
    assert len(result.preview) == 100
    assert len(result.preview[0]["text"]) == 500


def test_cancel_partial(tmp_path):
    for i in range(80):
        write(tmp_path / f"{i}.json", {"text": "말"})
    cancel = Event()
    def progress(done, success, failure):
        cancel.set()
    report = process_corpus(tmp_path, cancel, progress)
    assert report.cancelled and report.processed < 80
    assert report.processed == report.succeeded


def test_missing_folder(tmp_path):
    with pytest.raises(ValueError, match="폴더가 없습니다"):
        process_corpus(tmp_path / "absent")


@pytest.mark.parametrize("data", [{"version": 2}, {"version": 1, "name": "a", "target": {"field_path": [3]}}, {"version": 1, "name": "a", "results": {}}])
def test_invalid_project(tmp_path, data):
    write(tmp_path / "bad.corpusproj", data)
    with pytest.raises(ValueError):
        Project.load(tmp_path / "bad.corpusproj")


def test_invalid_encoding_and_nan_continue(tmp_path):
    (tmp_path / "invalid.json").write_bytes(b'\xff\xff')
    (tmp_path / "nan.json").write_text('{"v": NaN}')
    write(tmp_path / "ok.json", {"text": "정상"})
    result = process_corpus(tmp_path)
    assert (result.succeeded, result.failed) == (1, 2)
