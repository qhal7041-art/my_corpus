import codecs
import csv
import json
from pathlib import Path
from threading import Event
import pytest
from openpyxl import load_workbook
from corpus_app.tagged_import import import_tagged
from corpus_app.statistics.analysis import analyze_statistics
from corpus_app.statistics.keyness import analyze_keyness
from corpus_app.exporting import export_result


def morphology(tmp_path, text='밥/NNG 먹/VV\n'):
    source=tmp_path/'source.txt';source.write_text(text,encoding='utf-8')
    return import_tagged([source],{'mode':'slash'},tmp_path/'results')


def csv_rows(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.reader(stream))


def test_morph_csv_bom_all_tokens_settings_and_exact_source_preserved(tmp_path):
    result=morphology(tmp_path,'밥/NNG 먹/VV\n국/NNG\n')
    before=Path(result.path).read_bytes()
    destination=tmp_path/'형태소.csv'
    exported=export_result(result.path,destination)
    assert exported.rows==3 and len(exported.files)==2
    assert destination.read_bytes().startswith(codecs.BOM_UTF8)
    rows=csv_rows(destination)
    assert rows[1][4:6]==['밥','NNG']
    assert rows[3][4:6]==['국','NNG']
    settings=json.loads((tmp_path/'형태소.csv.settings.json').read_text(encoding='utf-8'))
    assert settings['exported_rows']==3 and settings['source_metadata']['config']['name']=='imported'
    assert Path(result.path).read_bytes()==before
    with pytest.raises(FileExistsError):
        export_result(result.path,destination)


def test_xlsx_literal_text_sheet_splitting_and_full_settings(tmp_path,monkeypatch):
    result=morphology(tmp_path,'=1+1/NNG +/SW -/SW @name/NNP\n')
    monkeypatch.setattr('corpus_app.exporting.MAX_EXCEL_ROWS',3)
    destination=tmp_path/'전체.xlsx'
    exported=export_result(result.path,destination)
    assert exported.rows==4
    book=load_workbook(destination,data_only=False)
    assert book.sheetnames==['결과_1','결과_2','분석 설정']
    assert book['결과_1']['E2'].value=='=1+1' and book['결과_1']['E2'].data_type=='s'
    assert book['결과_1']['E3'].value=='+'
    assert book['결과_2']['E2'].value=='-'
    settings={row[0].value:row[3].value for row in book['분석 설정'].iter_rows(min_row=2)}
    assert settings['exported_rows']=='4'
    book.close()
    safe=tmp_path/'safe.csv';raw=tmp_path/'raw.csv'
    export_result(result.path,safe,csv_safe=True)
    export_result(result.path,raw,csv_safe=False)
    assert csv_rows(safe)[1][4]=="'=1+1" and csv_rows(raw)[1][4]=='=1+1'


def test_export_complete_statistics_not_preview_and_keyness_metadata(tmp_path):
    target=morphology(tmp_path,' '.join(f'w{i}/NNG' for i in range(1205))+'\n')
    stats=analyze_statistics(target.path,{'kind':'ngram','n':1},tmp_path/'results')
    assert len(stats.rows)==10
    dest=tmp_path/'all.csv';exported=export_result(stats.path,dest)
    assert exported.rows==1205 and len(csv_rows(dest))==1206
    second_file=tmp_path/'reference.txt';second_file.write_text('별개/NNG w0/NNG',encoding='utf-8')
    reference=import_tagged([second_file],{'mode':'slash'},tmp_path/'results')
    keyness=analyze_keyness(target.path,reference.path,{'n':1,'metric':'G²','confirm_external':True},tmp_path/'results')
    xlsx=tmp_path/'keyness.xlsx';export_result(keyness.path,xlsx,sort='score')
    book=load_workbook(xlsx,read_only=True)
    assert book['결과_1'].max_row is None or book['결과_1'].max_row==1207
    data=list(book['결과_1'].values)
    assert len(data)==1207 and data[0][5]=='G²'
    settings={row[0]:row[3] for row in book['분석 설정'].values if row[0]!='항목'}
    assert settings['source_metadata.target_ngrams']=='1205'
    assert settings['source_metadata.reference_ngrams']=='2'
    assert settings['source_metadata.settings.n']=='1'
    book.close()


def test_cancel_preserves_existing_pair_and_cleans_xlsx_xml(tmp_path):
    result=morphology(tmp_path,'밥/NNG 먹/VV\n'*1000)
    cancel=Event()
    dest=tmp_path/'old.csv';sidecar=tmp_path/'old.csv.settings.json'
    dest.write_bytes(b'old-csv');sidecar.write_bytes(b'old-settings')
    out=export_result(result.path,dest,cancel=cancel,progress=lambda *args:cancel.set(),overwrite=True)
    assert out.cancelled and dest.read_bytes()==b'old-csv' and sidecar.read_bytes()==b'old-settings'
    assert not list(tmp_path.glob('.corpus-export-*'))
    from openpyxl.worksheet._writer import ALL_TEMP_FILES
    previous=set(ALL_TEMP_FILES)
    cancel.clear();xlsx=tmp_path/'cancel.xlsx'
    out=export_result(result.path,xlsx,cancel=cancel,progress=lambda *args:cancel.set())
    assert out.cancelled and not xlsx.exists()
    assert set(ALL_TEMP_FILES)==previous


def test_long_excel_cell_fails_without_truncating_or_replacing_target(tmp_path):
    result=morphology(tmp_path,('가'*33000)+'/NNG\n')
    dest=tmp_path/'existing.xlsx';dest.write_bytes(b'original')
    with pytest.raises(ValueError,match='32,767'):
        export_result(result.path,dest,overwrite=True)
    assert dest.read_bytes()==b'original'
    assert not list(tmp_path.glob('.corpus-export-*'))
    csv_path=tmp_path/'long.csv';export_result(result.path,csv_path)
    assert len(csv_rows(csv_path)[1][4])==33000


def test_pair_commit_failure_restores_both_existing_files(tmp_path,monkeypatch):
    from corpus_app import exporting
    result=morphology(tmp_path)
    dest=tmp_path/'old.csv';meta=tmp_path/'old.csv.settings.json'
    dest.write_bytes(b'previous csv');meta.write_bytes(b'previous json')
    original=exporting.os.replace
    def fail(source,target):
        if Path(source).name=='settings.json':
            raise OSError('simulated second output failure')
        return original(source,target)
    monkeypatch.setattr(exporting.os,'replace',fail)
    with pytest.raises(OSError,match='simulated'):
        export_result(result.path,dest,overwrite=True)
    assert dest.read_bytes()==b'previous csv' and meta.read_bytes()==b'previous json'
    assert not list(tmp_path.glob('.corpus-export-*'))


def test_export_does_not_overwrite_original_input(tmp_path):
    from openpyxl import Workbook
    source=tmp_path/'source.xlsx';book=Workbook();sheet=book.active
    sheet.append(['id','form','pos']);sheet.append(['u1','밥','NNG']);book.save(source)
    original=source.read_bytes()
    result=import_tagged([source],{'mode':'excel','form_key':'form','pos_key':'pos','id_key':'id'},tmp_path/'results')
    with pytest.raises(ValueError,match='원본'):
        export_result(result.path,source,overwrite=True)
    assert source.read_bytes()==original


def test_settings_long_text_is_split_without_loss_and_empty_keyness_export(tmp_path):
    import sqlite3
    target=morphology(tmp_path,'밥/NNG\n')
    long_value='고유명사 NNP\n'*5000
    with sqlite3.connect(target.path) as db:
        data=json.loads(db.execute('SELECT value FROM metadata WHERE key="run"').fetchone()[0])
        data['config']['long_test_dictionary']=long_value
        db.execute('UPDATE metadata SET value=? WHERE key="run"',(json.dumps(data),))
    output=tmp_path/'settings.xlsx';export_result(target.path,output)
    book=load_workbook(output,read_only=True)
    parts=[row for row in book['분석 설정'].values if row[0]=='source_metadata.config.long_test_dictionary']
    assert len(parts)>1
    assert json.loads(''.join(row[3] for row in sorted(parts,key=lambda r:r[1])))==long_value
    book.close()
    keyness=analyze_keyness(target.path,target.path,{'n':2,'confirm_external':True},tmp_path/'results')
    empty=tmp_path/'empty.csv';exported=export_result(keyness.path,empty)
    assert exported.rows==0 and len(csv_rows(empty))==1
    meta=json.loads((tmp_path/'empty.csv.settings.json').read_text(encoding='utf-8'))
    assert meta['source_metadata']['target_ngrams']==0 and '0' in meta['source_metadata']['note']


def test_cancel_during_xlsx_archive_creation(tmp_path,monkeypatch):
    from openpyxl.writer.excel import ExcelWriter
    from openpyxl.worksheet._writer import ALL_TEMP_FILES
    result=morphology(tmp_path,'밥/NNG 먹/VV\n'*10)
    cancel=Event();original=ExcelWriter.write_data;previous=set(ALL_TEMP_FILES)
    def interrupted(writer):
        cancel.set()
        return original(writer)
    monkeypatch.setattr(ExcelWriter,'write_data',interrupted)
    path=tmp_path/'during-save.xlsx'
    exported=export_result(result.path,path,cancel=cancel)
    assert exported.cancelled and not path.exists()
    assert set(ALL_TEMP_FILES)==previous
    assert not list(tmp_path.glob('.corpus-export-*'))


def test_collocation_export_contains_metric_window_and_all_columns(tmp_path):
    source=morphology(tmp_path,'가/NNG 나/NNG 가/NNG\n')
    statistics=analyze_statistics(source.path,{'kind':'collocation','left':1,'right':1,'minimum':1,'metric':'logDice'},tmp_path/'results')
    destination=tmp_path/'연어.csv';result=export_result(statistics.path,destination,sort='score')
    rows=csv_rows(destination)
    assert result.rows==2 and rows[0][-1]=='logDice'
    assert all(float(row[-1])==pytest.approx(14) for row in rows[1:])
    settings=json.loads((tmp_path/'연어.csv.settings.json').read_text(encoding='utf-8'))
    assert settings['source_metadata']['settings']['left']==settings['source_metadata']['settings']['right']==1
    assert settings['source_metadata']['settings']['metric']=='logDice'
    assert settings['source_metadata']['population']==4
