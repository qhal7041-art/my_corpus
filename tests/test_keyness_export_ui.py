import csv
import json
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from corpus_app.project import Project
from corpus_app.ui import MainWindow
from corpus_app.analysis_ui import StatisticsDialog
from corpus_app.morph_ui import MorphDialog
from corpus_app.export_ui import ExportDialog
from corpus_app.tagged_import import import_tagged
from test_ui import wait


def test_reference_keyness_export_and_project_restore(tmp_path):
    app=QApplication.instance()
    filename=tmp_path/'study.corpusproj';Project('핵심도').save(filename)
    window=MainWindow();assert window.load_project(filename)
    for role,content in [('target','밥/NNG 밥/NNG 먹/VV\n'),('reference','국/NNG 먹/VV 먹/VV\n')]:
        source=tmp_path/(role+'.txt');source.write_text(content,encoding='utf-8')
        result=import_tagged([source],{'mode':'slash'},filename.with_suffix('.results'))
        window.role.setCurrentIndex(window.role.findData(role))
        window.save_morph_result(result)
    window.role.setCurrentIndex(0)
    dialog=StatisticsDialog(window.project,filename,'target',window)
    dialog.settings_saved.connect(window.save_statistics_settings)
    dialog.result_saved.connect(window.save_statistics_result)
    dialog.show()
    dialog.kind.setCurrentIndex(dialog.kind.findData('keyness'))
    dialog.n.setValue(1)
    assert dialog.reference.currentData() is not None and dialog.reference.isVisible()
    assert dialog.keyness_metric.isVisible() and not dialog.left.isVisible()
    # External producer records require an explicit methodological confirmation.
    dialog.run_button.click();wait(app,lambda:dialog.thread is None)
    assert dialog.last_result is None and '확인' in dialog.details.toPlainText()
    dialog.confirm_external.setChecked(True)
    dialog.run_button.click();wait(app,lambda:dialog.thread is None)
    assert dialog.last_result.metadata['kind']=='keyness'
    assert dialog.last_result.metadata['target_ngrams']==dialog.last_result.metadata['reference_ngrams']==3
    assert dialog.table.columnCount()==9 and dialog.table.rowCount()==3
    assert dialog.table.item(0,0).text()=='밥'
    assert '참조' in dialog.summary.text()
    assert dialog.export_button.isEnabled()
    exported=ExportDialog(dialog.current_result_path,dialog,sort='score')
    output=tmp_path/'핵심도.csv'
    with patch('corpus_app.export_ui.QFileDialog.getSaveFileName',return_value=(str(output),'')):
        exported.choose.click()
    exported.run_button.click();wait(app,lambda:exported.thread is None)
    assert exported.last_result.rows==3
    with output.open(encoding='utf-8-sig',newline='') as stream:
        rows=list(csv.reader(stream))
    assert rows[0][5]=='G²' and rows[1][0]=='밥'
    meta=json.loads((tmp_path/'핵심도.csv.settings.json').read_text(encoding='utf-8'))
    assert meta['source_metadata']['target_ngrams']==3 and meta['source_metadata']['reference_ngrams']==3
    exported.close();dialog.close()
    saved=Project.load(filename)
    reopened=StatisticsDialog(saved,filename,'target')
    assert reopened.kind.currentData()=='keyness'
    assert reopened.n.value()==1 and reopened.confirm_external.isChecked()
    assert reopened.reference.currentData()==saved.analysis_settings['statistics']['reference_result']
    reopened.source.setCurrentIndex(1)
    assert not reopened.confirm_external.isChecked()
    reopened.saved.setCurrentIndex(reopened.saved.count()-1)
    reopened.open_button.click();wait(app,lambda:reopened.thread is None)
    assert reopened.last_result.metadata['kind']=='keyness'
    reopened.close();window.close()


def test_morphology_exports_saved_snapshot_not_edited_options_or_key(tmp_path):
    app=QApplication.instance()
    filename=tmp_path/'morph.corpusproj'
    project=Project('형태소 내보내기');project.save(filename)
    text=tmp_path/'one.txt';text.write_text('밥/NNG 먹/VV',encoding='utf-8')
    result=import_tagged([text],{'mode':'slash'},filename.with_suffix('.results'))
    project.results.append({'type':'morphology','role':'target','path':str(Path(result.path).relative_to(tmp_path)),'config':result.config})
    dialog=MorphDialog(project,filename,'target')
    dialog.api_key.setText('fixture-session-secret')
    dialog.dictionary.setPlainText('아직 적용하지 않은 사전 NNP 10')
    dialog.load_button.click();wait(app,lambda:dialog.thread is None)
    assert dialog.export_button.isEnabled()
    exported=ExportDialog(dialog.export_path,dialog,morphology=True)
    output=tmp_path/'morph.xlsx'
    exported.format.setCurrentIndex(exported.format.findData('.xlsx'))
    with patch('corpus_app.export_ui.QFileDialog.getSaveFileName',return_value=(str(output),'')):
        exported.choose.click()
    exported.run_button.click();wait(app,lambda:exported.thread is None)
    assert exported.last_result.rows==2
    from openpyxl import load_workbook
    workbook=load_workbook(output,read_only=True)
    settings='\n'.join(str(row) for row in workbook['분석 설정'].values)
    assert 'fixture-session-secret' not in settings and '아직 적용하지 않은 사전' not in settings
    assert 'imported' in settings
    workbook.close();exported.close();dialog.close()
