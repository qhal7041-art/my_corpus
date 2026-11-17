"""Morphology UI; no model initialization, corpus IO or SQLite IO on UI thread."""
from pathlib import Path
import json
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QProgressBar, QLineEdit, QSpinBox)
from .presentation import apply_theme, StatusLabel, DetailsPanel, primary, arrange_dialog, table_item, result_name
from .workers import FunctionWorker
from .analyzers.registry import status
from .morphology import analyze_corpus, load_result


class MorphDialog(QDialog):
    settings_saved = pyqtSignal(dict)
    result_saved = pyqtSignal(object)

    def __init__(self, project, project_file, role, parent=None):
        super().__init__(parent)
        apply_theme()
        self.project = project
        self.project_file = Path(project_file)
        self.role = role
        self.source = getattr(project, role)
        self.thread = None
        self.worker = None
        self.closing = False
        self.last_result = None
        self.export_path = None
        self.setWindowTitle('형태소 분석 — ' + ('대상 말뭉치' if role == 'target' else '참조 말뭉치'))
        self.resize(1000, 760)
        layout = QVBoxLayout(self)
        source_label = QLabel(f'원본: {self.source.folder}\n발화별로 분석합니다. 원문 전처리 없음 · 품사 필터 없음 · 발화 경계 유지')
        self.source_description = source_label
        source_label.setWordWrap(True)
        layout.addWidget(source_label)
        self.engine = QComboBox()
        for label, key in [('Kiwi (로컬)', 'kiwi'), ('바른 API', 'bareun'), ('UTagger', 'utagger'), ('바른 로컬 (baropy)', 'baropy')]:
            self.engine.addItem(label, key)
        layout.addWidget(self.engine)
        self.availability = QLabel()
        self.availability.setWordWrap(True)
        layout.addWidget(self.availability)
        self.options = []
        for key, label in [('normalize_coda', '받침 정규화 (normalize_coda)'),
                           ('split_complex', '복합 형태소 분리 (split_complex)'),
                           ('compatible_jamo', '호환 자모 출력 (compatible_jamo)')]:
            control = QCheckBox(label.split(' (')[0])
            control.setToolTip(key)
            self.options.append((key, control))
            layout.addWidget(control)
        self.dictionary_label = QLabel('사용자 사전: 한 줄에 형태소 품사 [점수]. 예: 제주방언 NNP 5. # 주석 허용. 내용은 프로젝트에 저장됩니다.')
        self.dictionary_label.setWordWrap(True)
        layout.addWidget(self.dictionary_label)
        self.dictionary = QPlainTextEdit()
        self.dictionary.setMaximumHeight(90)
        self.dictionary.setPlaceholderText('제주방언 NNP 5')
        layout.addWidget(self.dictionary)
        self.key_label = QLabel('바른 API 키 (이 창에서만 사용 · 프로젝트/결과에 저장하지 않음)')
        layout.addWidget(self.key_label)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText('API 키를 직접 입력하세요. env 설정 불필요')
        self.api_key.textChanged.connect(self.refresh)
        layout.addWidget(self.api_key)
        self.bareun_options = []
        for key, label in [('auto_spacing', '바른: 띄어쓰기 보정'), ('auto_jointing', '바른: 붙여쓰기 보정')]:
            control = QCheckBox(label)
            control.setChecked(True)
            self.bareun_options.append((key, control))
            layout.addWidget(control)
        self.server_dicts = QLineEdit()
        self.server_dicts.setPlaceholderText('바른 서버에 등록한 사전 이름 (쉼표로 구분, 선택 사항)')
        layout.addWidget(self.server_dicts)
        self.utagger_version = QComboBox()
        for variant in ('utagger4', 'utagger3', 'utagger4hj'):
            self.utagger_version.addItem({'utagger3':'UTagger 3', 'utagger4':'UTagger 4', 'utagger4hj':'UTagger 4 · 옛한글'}[variant], variant)
        self.utagger_version.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.utagger_version)
        from .analyzers.baropy_local import default_model_cache
        self.local_threads = QSpinBox()
        self.local_threads.setRange(1, 32)
        self.local_threads.setValue(2)
        self.local_threads.setPrefix('로컬 CPU 스레드: ')
        self.local_sense = QCheckBox('로컬: 동형이의어 어깨번호 포함 (sense)')
        self.local_nouns = QPlainTextEdit()
        self.local_nouns.setPlaceholderText('로컬 고유명사 사용자 사전: 한 줄에 한 단어. 예: 제주방언')
        self.local_nouns.setMaximumHeight(70)
        self.local_nouns_label = QLabel('바른 로컬 고유명사 사전: 한 줄에 한 단어')
        self.local_cache = QLineEdit(default_model_cache())
        self.local_cache_label = QLabel('바른 로컬 모델 캐시 폴더 (원본 말뭉치 폴더 밖)')
        self.local_cache.setPlaceholderText('모델만 보관할 캐시 폴더 (말뭉치 폴더 밖)')
        self.local_cache.setToolTip('기본값은 OS 임시 폴더입니다. 필요하면 전용 모델 폴더 경로로 바꾸세요.')
        for control in (self.local_threads, self.local_sense, self.local_nouns_label, self.local_nouns, self.local_cache_label, self.local_cache):
            layout.addWidget(control)
        row = QHBoxLayout()
        self.save_options = QPushButton('설정 저장')
        self.save_options.clicked.connect(self.persist_settings)
        row.addWidget(self.save_options)
        self.run_button = QPushButton('형태소 분석 / 같은 데이터·설정 결과 재사용')
        self.run_button.clicked.connect(self.run_analysis)
        row.addWidget(self.run_button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.saved_results = QComboBox()
        row.addWidget(self.saved_results, 1)
        self.load_button = QPushButton('저장한 결과 열기')
        self.load_button.clicked.connect(self.open_result)
        row.addWidget(self.load_button)
        layout.addLayout(row)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['원문 (최대 500자)', '형태소/품사 (앞 100개·1,500자)', '원본 파일', '발화 ID'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(2, 220)
        layout.addWidget(self.table, 1)
        self.export_button = QPushButton('저장된 전체 형태소 결과 내보내기…')
        self.export_button.clicked.connect(self.open_export)
        layout.addWidget(self.export_button)
        self.summary = StatusLabel('설정을 확인한 뒤 분석하세요. 모델 초기화는 시간이 걸릴 수 있습니다.')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        row.addWidget(self.progress)
        self.cancel_button = QPushButton('취소')
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(140)
        self.details_panel = DetailsPanel(self.details)
        layout.addWidget(self.details_panel)
        config = project.analyzer
        index = self.engine.findData(config.get('name', 'kiwi'))
        self.engine.setCurrentIndex(max(0, index))
        options = config.get('options', {})
        for key, control in self.options:
            control.setChecked(bool(options.get(key, False)))
        self.dictionary.setPlainText(options.get('user_dictionary', ''))
        for key, control in self.bareun_options:
            control.setChecked(bool(options.get(key, True)))
        self.server_dicts.setText(', '.join(options.get('custom_dicts', [])))
        variant = self.utagger_version.findData(options.get('version', 'utagger4'))
        self.utagger_version.setCurrentIndex(max(0, variant))
        self.local_threads.setValue(options.get('threads', 2))
        self.local_sense.setChecked(options.get('sense', False))
        self.local_nouns.setPlainText(options.get('user_nouns', ''))
        self.local_cache.setText(options.get('model_cache') or default_model_cache())
        self.engine.currentIndexChanged.connect(self.refresh)
        self.refresh_results()
        self.save_options.setText('설정 저장')
        self.load_button.setText('열기')
        self.export_button.setText('전체 형태소 결과 내보내기…')
        primary(self.run_button)
        arrange_dialog(self, '형태소 분석', '분석기를 선택하고 설정한 뒤, 발화별 형태소와 품사를 확인하세요.',
            ['분석 대상', self.source_description, '분석기', self.engine, self.availability,
             *[control for _, control in self.options], self.dictionary_label, self.dictionary,
             self.key_label, self.api_key, *[control for _, control in self.bareun_options], self.server_dicts,
             self.utagger_version, self.local_threads, self.local_sense, self.local_nouns_label, self.local_nouns,
             self.local_cache_label, self.local_cache, self.save_options, self.run_button],
            ['저장된 결과', [self.saved_results, self.load_button], self.table, self.export_button,
             self.summary, [self.progress, self.cancel_button], self.details_panel])
        self.refresh()

    def config(self):
        options = {key: control.isChecked() for key, control in self.options}
        options['user_dictionary'] = self.dictionary.toPlainText()
        name = self.engine.currentData()
        if name == 'bareun':
            options = {key: control.isChecked() for key, control in self.bareun_options}
            options['custom_dicts'] = [value.strip() for value in self.server_dicts.text().split(',') if value.strip()]
        elif name == 'utagger':
            options = {'version': self.utagger_version.currentData()}
        elif name == 'baropy':
            options = {'threads': self.local_threads.value(), 'sense': self.local_sense.isChecked(),
                       'user_nouns': self.local_nouns.toPlainText(), 'model_cache': self.local_cache.text().strip()}
        return {'name': name, 'options': options}

    def persist_settings(self):
        self.settings_saved.emit(self.config())

    def refresh(self):
        name = self.engine.currentData()
        info = status(name, self.config()['options'])
        self.availability.setText(info.instructions)
        kiwi = self.engine.currentData() == 'kiwi'
        for _, control in self.options:
            control.setVisible(kiwi)
        self.dictionary.setVisible(kiwi)
        self.dictionary_label.setVisible(kiwi)
        for control in [self.server_dicts] + [c for _, c in self.bareun_options]:
            control.setVisible(name == 'bareun')
        self.key_label.setVisible(name in ('bareun', 'baropy'))
        self.api_key.setVisible(name in ('bareun', 'baropy'))
        self.key_label.setText('바른 로컬 키: 프로젝트에 저장하지 않음 · SDK 임시 등록 DB는 종료 시 삭제' if name == 'baropy' else '바른 API 키 (이 창에서만 사용 · 프로젝트/결과에 저장하지 않음)')
        for control in (self.local_threads, self.local_sense, self.local_nouns_label, self.local_nouns, self.local_cache_label, self.local_cache):
            control.setVisible(name == 'baropy')
        self.utagger_version.setVisible(name == 'utagger')
        self.run_button.setText('바른 API 분석 실행' if name == 'bareun' else '바른 로컬 분석 실행' if name == 'baropy' else '형태소 분석 실행')
        self.run_button.setEnabled(not self.thread and info.available and (name not in ('bareun', 'baropy') or bool(self.api_key.text().strip())) and bool(self.source.folder) and self.source.field_path is not None)
        self.load_button.setEnabled(not self.thread and self.saved_results.count() > 0)
        self.export_button.setEnabled(not self.thread and self.export_path is not None)

    def refresh_results(self):
        self.saved_results.clear()
        for entry in self.project.results:
            if entry.get('type') == 'morphology' and entry.get('role') == self.role:
                self.saved_results.addItem(result_name(entry), entry['path'])

    def run_analysis(self):
        if self.thread:
            return
        config = self.config()
        self.persist_settings()
        folder, selected = self.source.folder, list(self.source.field_path)
        directory = self.project_file.with_suffix('.results')
        key = self.api_key.text() if config['name'] in ('bareun', 'baropy') else ''
        self.start(lambda cancel, progress: analyze_corpus(folder, selected, config, directory, cancel, progress, api_key=key), True)

    def open_result(self):
        relative = self.saved_results.currentData()
        if relative and not self.thread:
            path = self.project_file.parent / relative
            self.start(lambda cancel, progress: load_result(path), False)

    def start(self, function, save):
        self.last_result = None
        self.export_path = None
        self.should_save = save
        self.table.setRowCount(0)
        self.details.clear()
        self.summary.setText('입력 내용 확인 → 모델 초기화 → 발화별 분석. 같은 입력은 저장 결과를 재사용합니다.')
        self.thread = QThread(self)
        self.worker = FunctionWorker(function)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.result.connect(self.on_result)
        self.worker.error.connect(self.on_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.finished_job)
        self.thread.finished.connect(self.thread.deleteLater)
        for control in [self.engine, self.dictionary, self.api_key, self.server_dicts, self.utagger_version, self.run_button, self.save_options, self.saved_results, self.load_button, self.local_threads, self.local_sense, self.local_nouns, self.local_cache, self.export_button] + [c for _, c in self.options + self.bareun_options]:
            control.setEnabled(False)
        self.progress.setRange(0, 0)
        self.cancel_button.setEnabled(True)
        self.thread.start()

    def on_progress(self, processed, success, failed):
        self.summary.setText(f'입력 확인/분석 진행 {processed:,}파일 · 분석 성공 {success:,} · 실패 {failed:,} (분석 시작 시 건수 재설정)')

    def on_error(self, message):
        self.summary.setText('분석/결과 열기 실패. 미완료 결과는 저장하지 않았습니다.')
        self.details.setPlainText(message)
        self.details_panel.open()

    def on_result(self, result):
        self.last_result = result
        report = result.report
        if report.cancelled:
            self.summary.setText(f'취소됨: {report.processed:,}파일, {report.texts:,}발화 처리. 부분 결과는 저장하지 않았습니다.')
            return
        self.export_path = result.path
        self.summary.setText(f'{"재사용" if result.reused else "완료 / 저장 당시 결과"} · 성공 {report.succeeded:,}파일 · 실패 {report.failed:,} · '
                             f'발화 {report.texts:,} · 형태소 {result.tokens:,} · 누락 분기 {report.missing:,} · 비문자열 {report.non_string:,} · 빈 배열 {report.empty_arrays:,}')
        self.table.setRowCount(len(result.preview))
        for index, row in enumerate(result.preview):
            text, source, utterance_id, tokens = row
            for column, value in enumerate((text, tokens, source, utterance_id)):
                self.table.setItem(index, column, table_item(value))
        details = '저장된 결과의 설정 (위 편집 중인 설정과 다를 수 있음):\n' + json.dumps(result.config, ensure_ascii=False, indent=2)
        details += '\n결과 파일: ' + result.path
        details += '\n' + '\n'.join(f'{path}: {reason}' for path, reason in report.errors)
        self.details.setPlainText(details)
        if self.should_save:
            self.result_saved.emit(result)
            self.refresh_results()

    def cancel(self):
        if self.worker:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self.summary.setText('취소 요청됨. 현재 모델 초기화/발화 분석이 끝나면 중단합니다.')

    def open_export(self):
        if self.export_path and not self.thread:
            from .export_ui import ExportDialog
            ExportDialog(self.export_path, self, morphology=True).exec()

    def finished_job(self):
        self.thread = None
        self.worker = None
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.cancel_button.setEnabled(False)
        for control in [self.engine, self.dictionary, self.api_key, self.server_dicts, self.utagger_version, self.save_options, self.saved_results, self.local_threads, self.local_sense, self.local_nouns, self.local_cache] + [c for _, c in self.options + self.bareun_options]:
            control.setEnabled(True)
        self.refresh()
        if self.closing:
            self.api_key.clear()
            super().reject()

    def reject(self):
        if self.thread:
            self.closing = True
            self.cancel()
        else:
            self.api_key.clear()
            super().reject()

    def closeEvent(self, event):
        if self.thread:
            self.closing = True
            self.cancel()
            event.ignore()
        else:
            super().closeEvent(event)
