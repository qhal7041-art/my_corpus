from pathlib import Path
from threading import Event
import shutil
import pytest
from openpyxl import Workbook
from corpus_app.json_corpus import process_corpus, Cancelled
from corpus_app.input_formats import documents
from corpus_app import morphology
from corpus_app.analyzers import Morpheme

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples' / 'formats'


def test_txt_lines_bom_and_bad_encoding(tmp_path):
    (tmp_path / 'good.txt').write_text('첫 발화\n\n 두 번째 발화 \r\n', encoding='utf-8-sig')
    (tmp_path / 'bad.txt').write_bytes(b'partial\n\xff\xff')
    report = process_corpus(tmp_path)
    assert (report.succeeded, report.failed) == (1, 1)
    assert report.fields[('text',)].files == 1
    report = process_corpus(tmp_path, selected=['text'])
    assert report.texts == 2 and report.failed == 1
    assert [row['utterance_id'] for row in report.preview] == ['line:1', 'line:3']
    assert report.preview[1]['text'] == ' 두 번째 발화 '


def test_cp949_txt(tmp_path):
    (tmp_path / 'korean.txt').write_bytes('한글 발화\n다음 줄'.encode('cp949'))
    report = process_corpus(tmp_path, selected=['text'])
    assert report.texts == 2 and report.failed == 0
    assert report.preview[0]['text'] == '한글 발화'


@pytest.mark.parametrize('suffix,expected_id', [('xlsx', 'e1'), ('xls', 'l1')])
def test_excel_columns_ids_and_morphology(tmp_path, monkeypatch, suffix, expected_id):
    original = EXAMPLES / ('utterances.xlsx' if suffix == 'xlsx' else 'legacy.xls')
    folder = tmp_path / 'source'
    folder.mkdir()
    shutil.copy(original, folder)
    (folder / ('broken.' + suffix)).write_bytes(b'bad workbook')
    selected = ['sheets', '발화', 'rows', None, 'B: 발화']
    schema = process_corpus(folder)
    assert schema.failed == 1 and schema.succeeded == 1
    assert schema.fields[tuple(selected)].files == 1
    report = process_corpus(folder, selected=selected)
    assert report.texts == 2 and report.non_string == 0
    assert report.preview[0]['utterance_id'] == expected_id
    class Fake:
        def analyze(self, text):
            return [Morpheme(text, 'NNG')]
    monkeypatch.setattr(morphology, 'create', lambda *args: Fake())
    result = morphology.analyze_corpus(folder, selected, {'name': 'kiwi'}, tmp_path / 'results')
    assert result.report.texts == 2 and result.tokens == 2 and result.report.failed == 1
    assert result.preview[0][2] == expected_id


def test_duplicate_headers_types_and_cancel(tmp_path):
    w = Workbook()
    s = w.active
    s.title = '발화'
    s.append(['text', 'text', None])
    s.append(['문장', 5, None])
    s.append(['다음 문장', None, '다른 내용'])
    filename = tmp_path / 'rows.xlsx'
    w.save(filename)
    report = process_corpus(tmp_path)
    assert ('sheets','발화','rows', None, 'A: text') in report.fields
    assert ('sheets','발화','rows', None, 'B: text') in report.fields
    extracted = process_corpus(tmp_path, selected=['sheets','발화','rows', None, 'B: text'])
    assert extracted.texts == 0 and extracted.non_string == 2
    cancel = Event()
    iterator = documents(filename, cancel)
    next(iterator)
    cancel.set()
    with pytest.raises(Cancelled):
        next(iterator)
    iterator.close()


def test_excel_real_ui_and_kiwi(tmp_path):
    from PyQt6.QtWidgets import QApplication
    from corpus_app.project import Project, CorpusSource
    from corpus_app.ui import MainWindow
    from corpus_app.morph_ui import MorphDialog
    from test_ui import wait
    app = QApplication.instance()
    folder = tmp_path / 'corpus'
    folder.mkdir()
    shutil.copy(EXAMPLES / 'utterances.xlsx', folder)
    filename = tmp_path / 'excel.corpusproj'
    selected = ['sheets', '발화', 'rows', None, 'B: 발화']
    Project('엑셀', target=CorpusSource(str(folder), selected)).save(filename)
    window = MainWindow()
    assert window.load_project(filename)
    wait(app, lambda: window.thread is None and window.job_kind == 'extract' and window.last_report is not None)
    assert window.last_report.texts == 2
    dialog = MorphDialog(window.project, filename, 'target', window)
    dialog.settings_saved.connect(window.save_analyzer_settings)
    dialog.result_saved.connect(window.save_morph_result)
    dialog.run_button.click()
    wait(app, lambda: dialog.thread is None)
    assert dialog.last_result.tokens > 2
    assert dialog.table.rowCount() == 2
    assert dialog.table.item(0, 3).text() == 'e1'
    dialog.run_button.click()
    wait(app, lambda: dialog.thread is None)
    assert dialog.last_result.reused
    assert Project.load(filename).target.field_path == selected
    dialog.close()
    window.close()
