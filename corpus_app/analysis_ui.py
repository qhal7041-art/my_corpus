"""Shared cancellable Qt jobs for pretagged import and disk-backed statistics."""
from pathlib import Path
import json
from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QProgressBar, QFileDialog, QSpinBox, QCheckBox, QSizePolicy)
from .presentation import apply_theme, StatusLabel, DetailsPanel, primary, arrange_dialog, table_item, result_name, label
from .help_ui import helped
from .workers import FunctionWorker
from .tagged_import import import_tagged, import_database
from .statistics.analysis import analyze_statistics, load_statistics, PUNCTUATION_FILTER_VERSION
from .statistics.keyness import analyze_keyness


class JobDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        apply_theme()
        self.thread = self.worker = None
        self.closing = False
        self.inputs = []
        self.last_result = None

    def job_footer(self, layout):
        self.summary = StatusLabel('준비됨')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        row.addWidget(self.progress)
        self.cancel_button = QPushButton('취소')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(150)
        self.details_panel = DetailsPanel(self.details)
        layout.addWidget(self.details_panel)

    def background(self, function, callback):
        if self.thread:
            return
        self.last_result = None
        self.details.clear()
        self.summary.setText('처리 중…')
        self.callback = callback
        self.thread = QThread(self)
        self.worker = FunctionWorker(function)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.result.connect(self.completed)
        self.worker.error.connect(self.on_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.finished_job)
        self.thread.finished.connect(self.thread.deleteLater)
        for control in self.inputs:
            control.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        self.thread.start()

    def completed(self, result):
        self.last_result = result
        self.callback(result)

    def on_error(self, message):
        self.summary.setText('실패 — 기존 완료 결과는 유지됩니다.')
        self.details.setPlainText(message)
        self.details_panel.open()

    def finished_job(self):
        self.thread = self.worker = None
        for control in self.inputs:
            control.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.refresh()
        if self.closing:
            super().reject()

    def cancel(self):
        if self.worker:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self.summary.setText('취소 요청됨… 완료되지 않은 결과는 저장하지 않습니다.')

    def reject(self):
        if self.thread:
            self.closing = True
            self.cancel()
        else:
            super().reject()

    def closeEvent(self, event):
        if self.thread:
            self.closing = True
            self.cancel()
            event.ignore()
        else:
            super().closeEvent(event)


def result_table(columns):
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    return table


class TaggedImportDialog(JobDialog):
    result_saved = pyqtSignal(object)

    def __init__(self, project, project_file, role, parent=None):
        super().__init__(parent)
        self.project, self.project_file, self.role = project, Path(project_file), role
        self.files = []
        self.setWindowTitle('이미 분석된 형태소·품사 파일 불러오기')
        self.resize(1050, 750)
        layout = QVBoxLayout(self)
        info = QLabel('분석기를 실행하지 않고 입력된 형태소·품사를 그대로 저장합니다. TXT 기본: 한 줄=한 발화, 공백으로 토큰 구분, 마지막 /가 품사 구분자입니다.')
        info.setWordWrap(True)
        layout.addWidget(info)
        self.mode = QComboBox()
        for label, value in [('TXT: 형태소/품사 (한 줄=발화)', 'slash'), ('JSON: 발화별 형태소 배열', 'json'),
                             ('Excel: 형태소·품사 열', 'excel'), ('TSV: 형태소<TAB>품사, 빈 행=발화', 'tsv'),
                             ('앱에서 저장한 형태소 SQLite 결과', 'sqlite')]:
            self.mode.addItem(label, value)
        self.mode.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.mode)
        self.plus_delimited = QCheckBox('TXT: 형태소/품사+형태소/품사 형식의 + 연결도 분리')
        layout.addWidget(self.plus_delimited)
        self.choose = QPushButton('파일 선택… (여러 파일 가능)')
        self.choose.clicked.connect(self.choose_files)
        layout.addWidget(self.choose)
        self.file_label = QLabel('선택한 파일 없음')
        self.file_label.setWordWrap(True)
        layout.addWidget(self.file_label)
        self.path = QLineEdit('$.utterances[*].tokens')
        self.path_label = QLabel('JSON 경로: 발화별 토큰 배열까지 선택 (예: $.utterances[*].tokens, $.tokens, $)')
        layout.addWidget(self.path_label)
        layout.addWidget(self.path)
        self.form = QLineEdit('form')
        self.pos = QLineEdit('pos')
        self.id = QLineEdit('id')
        self.mapping_labels = []
        for label, widget in [('형태소 필드/열 (중복 Excel 헤더는 A, B 등 열 문자)', self.form), ('품사 필드/열', self.pos),
                              ('Excel 발화 ID 열 (비우면 시트 전체가 한 발화, 동일 ID의 연속 행끼리 묶음)', self.id)]:
            text = QLabel(label)
            self.mapping_labels.append(text)
            layout.addWidget(text)
            layout.addWidget(widget)
        self.run_button = QPushButton('불러오기 · 프로젝트에 결과 등록')
        self.run_button.clicked.connect(self.run_import)
        layout.addWidget(self.run_button)
        self.table = result_table(['재구성 텍스트 / 저장된 원문', '형태소/품사', '원본 파일', '발화 ID'])
        layout.addWidget(self.table, 1)
        self.export_button = QPushButton('불러온 전체 형태소 결과 내보내기…')
        self.export_button.clicked.connect(self.open_export)
        self.export_path = None
        layout.addWidget(self.export_button)
        self.job_footer(layout)
        self.inputs = [self.mode, self.plus_delimited, self.choose, self.path, self.form, self.pos, self.id, self.run_button, self.export_button]
        self.plus_delimited.setText('TXT의 + 연결도 분리')
        self.plus_delimited.setToolTip('형태소/품사+형태소/품사 형식의 + 연결을 분리합니다.')
        self.run_button.setText('파일 불러오기')
        primary(self.run_button)
        self.export_button.setText('전체 형태소 결과 내보내기…')
        arrange_dialog(self, '분석된 파일 불러오기', '형태소·품사를 그대로 가져옵니다. TXT는 한 줄을 한 발화로 읽습니다.',
            ['입력 형식', self.mode, self.plus_delimited, self.choose, self.file_label,
             self.path_label, self.path, self.mapping_labels[0], self.form, self.mapping_labels[1], self.pos,
             self.mapping_labels[2], self.id, self.run_button],
            ['가져온 결과', self.table, self.export_button, self.summary, [self.progress, self.cancel_button], self.details_panel])
        self.refresh()

    def refresh(self):
        mode = self.mode.currentData()
        self.plus_delimited.setVisible(mode == 'slash')
        self.path.setVisible(mode == 'json')
        self.path_label.setVisible(mode == 'json')
        for index, widget in enumerate((self.form, self.pos, self.id)):
            visible = mode in ('json', 'excel') and (index != 2 or mode == 'excel')
            widget.setVisible(visible)
            self.mapping_labels[index].setVisible(visible)
        self.run_button.setEnabled(not self.thread and bool(self.files))
        self.export_button.setEnabled(not self.thread and self.export_path is not None)

    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, '이미 분석된 파일 선택', '',
            '형태소 자료 (*.txt *.tsv *.json *.xlsx *.xls *.sqlite);;모든 파일 (*)')
        if files:
            self.files = list(dict.fromkeys(files))
            self.file_label.setText(f'{len(self.files):,}개 파일: ' + ', '.join(Path(v).name for v in self.files[:5]))
            self.refresh()

    def run_import(self):
        if self.thread or not self.files:
            return
        directory = self.project_file.with_suffix('.results')
        config = {'mode': self.mode.currentData(), 'path': self.path.text().strip(),
                  'form_key': self.form.text().strip(), 'pos_key': self.pos.text().strip(), 'id_key': self.id.text().strip(),
                  'plus_delimited': self.plus_delimited.isChecked()}
        if config['mode'] == 'sqlite':
            if len(self.files) != 1:
                self.on_error('앱 SQLite 결과는 한 번에 하나씩 선택하세요.')
                return
            source = self.files[0]
            function = lambda cancel, progress: import_database(source, directory, cancel, progress)
        else:
            files = list(self.files)
            function = lambda cancel, progress: import_tagged(files, config, directory, cancel, progress)
        self.background(function, self.show_import)

    def on_progress(self, done, success, failure):
        if self.mode.currentData() == 'sqlite':
            self.summary.setText(f'형태소 결과 복사 중 · {done:,} MiB')
        else:
            self.summary.setText(f'읽은 발화 {done:,}건 · 완료 파일 {success + failure:,}/{len(self.files):,} · 성공 {success:,} · 실패 {failure:,}')

    def show_import(self, result):
        report = result.report
        if report.cancelled:
            self.summary.setText('취소됨 — 부분 결과는 저장하지 않았습니다.')
            return
        self.table.setRowCount(len(result.preview))
        for index, (text, source, identifier, tokens) in enumerate(result.preview):
            for column, value in enumerate((text, tokens, source, identifier)):
                self.table.setItem(index, column, table_item(value))
        prefix = '기존 결과 복사 완료 (저장 당시 집계)' if self.mode.currentData() == 'sqlite' else '완료'
        self.summary.setText(f'{prefix} · 성공 {report.succeeded:,}파일 · 실패 {report.failed:,} · 발화 {report.texts:,} · 형태소 {result.tokens:,} · 누락 분기 {report.missing:,}')
        self.details.setPlainText(json.dumps(result.config, ensure_ascii=False, indent=2) + '\n' +
                                  '\n'.join(f'{path}: {reason}' for path, reason in report.errors))
        self.result_saved.emit(result)
        self.export_path = result.path

    def open_export(self):
        if self.export_path and not self.thread:
            from .export_ui import ExportDialog
            ExportDialog(self.export_path, self, morphology=True).exec()


class StatisticsDialog(JobDialog):
    result_saved = pyqtSignal(object)
    settings_saved = pyqtSignal(dict)

    def __init__(self, project, project_file, role, parent=None):
        super().__init__(parent)
        self.project, self.project_file, self.role = project, Path(project_file), role
        self.current_result_path = None
        self.displayed_kind = None
        self.setWindowTitle('연어 · N-gram · 참조 핵심도 분석')
        self.resize(1200, 800)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('저장된 형태소 결과 또는 이미 분석된 파일을 불러온 결과를 선택하세요. 분석기는 다시 실행하지 않습니다.'))
        self.source = QComboBox()
        preferred = 0
        for entry in project.results:
            if entry.get('type') == 'morphology':
                if entry.get('role') == role:
                    preferred = self.source.count()
                self.source.addItem(f"[{ {'target':'대상', 'reference':'참조'}.get(entry.get('role'), '자료')}] {result_name(entry)}", entry['path'])
        self.source.setCurrentIndex(preferred)
        self.source_label = QLabel('형태소 분석 결과')
        layout.addWidget(self.source_label)
        layout.addWidget(self.source)
        self.reference_label = QLabel('참조 말뭉치 형태소 결과 (대상과 같은 분석기·사전·전처리 필요)')
        self.reference = QComboBox()
        self.reference.addItem('참조 결과를 선택하세요', None)
        reference_preferred = 0
        for entry in project.results:
            if entry.get('type') == 'morphology':
                self.reference.addItem(f"[{ {'target':'대상', 'reference':'참조'}.get(entry.get('role'), '자료')}] {result_name(entry)}", entry['path'])
                if entry.get('role') == 'reference':
                    reference_preferred = self.reference.count() - 1
        self.reference.setCurrentIndex(reference_preferred)
        layout.addWidget(self.reference_label)
        layout.addWidget(self.reference)
        self.confirm_external = QCheckBox('사전 분석/버전 미고정 모델의 분석 방식·품사 체계·전처리·사전이 같음을 확인')
        layout.addWidget(self.confirm_external)
        row = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItem('N-gram 빈도 · 단일 말뭉치', 'ngram')
        self.kind.addItem('연어 · 단일 말뭉치', 'collocation')
        self.kind.addItem('참조 말뭉치 N-gram 핵심도', 'keyness')
        self.kind.currentIndexChanged.connect(self.kind_changed)
        row.addWidget(self.kind)
        self.pos = QLineEdit()
        self.pos.setPlaceholderText('품사 접두어 필터 (예: NN*,VV · 비우면 전체)')
        row.addWidget(self.pos, 1)
        self.exclude_punctuation = QCheckBox('문장부호·가운뎃점 제외')
        layout.addWidget(self.exclude_punctuation)
        self.excluded_forms = QPlainTextEdit()
        self.excluded_forms.setPlaceholderText('추가로 제외할 형태소: 한 줄에 하나\n예: 것')
        self.excluded_forms.setMaximumHeight(80)
        layout.addWidget(self.excluded_forms)
        self.cross = QCheckBox('발화 경계 넘기 (파일 경계는 유지)')
        row.addWidget(self.cross)
        layout.addLayout(row)
        self.n = QSpinBox()
        self.n.setRange(1, 10)
        self.n.setValue(2)
        self.n.setPrefix('n = ')
        self.include_pos = QCheckBox('N-gram에 품사 포함')
        layout.addWidget(self.n)
        layout.addWidget(self.include_pos)
        self.keyness_metric = QComboBox()
        self.keyness_metric.addItem('로그 우도비 (G²)', 'G²')
        self.keyness_metric.addItem('피어슨 카이제곱 (χ²)', 'χ²')
        layout.addWidget(self.keyness_metric)
        self.center = QLineEdit()
        self.center.setPlaceholderText('중심 형태소 (비우면 관찰된 전체 형태소 쌍)')
        layout.addWidget(self.center)
        self.left, self.right, self.minimum = QSpinBox(), QSpinBox(), QSpinBox()
        for prefix, widget, low, high, default in [('왼쪽 범위 ', self.left, 0, 50, 2), ('오른쪽 범위 ', self.right, 0, 50, 2),
                                                  ('최소 공기 빈도 ', self.minimum, 1, 100000000, 2)]:
            widget.setRange(low, high)
            widget.setValue(default)
            widget.setPrefix(prefix)
            layout.addWidget(widget)
        self.metric = QComboBox()
        self.metric.addItems(['MI', 't-score', 'logDice'])
        layout.addWidget(self.metric)
        self.run_button = QPushButton('통계 계산 · 프로젝트에 결과 저장')
        self.run_button.clicked.connect(self.run_statistics)
        layout.addWidget(self.run_button)
        row = QHBoxLayout()
        self.saved = QComboBox()
        row.addWidget(self.saved, 1)
        self.open_button = QPushButton('저장 통계 열기')
        self.open_button.clicked.connect(self.open_saved)
        row.addWidget(self.open_button)
        self.sort = QComboBox()
        self.sort.addItem('전체 결과: 빈도순', 'frequency')
        self.sort.addItem('전체 결과: 점수순', 'score')
        row.addWidget(self.sort)
        self.limit = QComboBox()
        for value in (10, 100, 1000):
            self.limit.addItem(f'상위 {value:,}행', value)
        row.addWidget(self.limit)
        self.view_button = QPushButton('정렬/표시 적용')
        self.view_button.clicked.connect(self.reload_result)
        row.addWidget(self.view_button)
        layout.addLayout(row)
        self.table = result_table([])
        self.low_only = QCheckBox('핵심도: 기대빈도 5 미만 항목만 조회 (정렬/표시 적용)')
        self.low_only.setVisible(False)
        layout.addWidget(self.low_only)
        layout.addWidget(self.table, 1)
        self.export_button = QPushButton('표시 행 제한 없이 전체 통계 내보내기…')
        self.export_button.clicked.connect(self.open_export)
        layout.addWidget(self.export_button)
        self.job_footer(layout)
        self.inputs = [self.source, self.kind, self.pos, self.exclude_punctuation, self.excluded_forms, self.cross, self.n, self.include_pos, self.center,
                       self.left, self.right, self.minimum, self.metric, self.run_button, self.saved, self.open_button,
                       self.sort, self.limit, self.view_button, self.reference, self.confirm_external, self.keyness_metric, self.export_button, self.low_only]
        self.confirm_external.setToolTip(self.confirm_external.text())
        self.confirm_external.setText('분석 방식·품사·사전의 동일성 확인')
        self.cross.setText('발화 연결 (파일 경계 유지)')
        self.include_pos.setText('형태소와 품사 함께 사용')
        self.run_button.setText('통계 계산')
        self.mode_hint = label('')
        self.view_button.setText('조회 적용')
        self.open_button.setText('열기')
        self.export_button.setText('전체 통계 결과 내보내기…')
        self.low_only.setText('기대빈도 5 미만만 조회')
        primary(self.run_button)
        arrange_dialog(self, '통계 분석', '저장된 형태소 결과로 연어·N-gram·참조 핵심도를 계산합니다.',
            ['분석 종류', helped(self.kind, 'kind'), self.mode_hint, self.source_label, helped(self.source, 'source'), self.reference_label, helped(self.reference, 'reference'),
             helped(self.confirm_external, 'confirm'), '분석 조건', helped(self.pos, 'pos'), helped(self.exclude_punctuation, 'exclude_punctuation'), '추가 제외 형태소', helped(self.excluded_forms, 'excluded_forms'), helped(self.cross, 'cross'), helped(self.n, 'n'), helped(self.include_pos, 'include_pos'),
             helped(self.keyness_metric, 'keyness'), helped(self.center, 'center'), helped(self.left, 'left'), helped(self.right, 'right'), helped(self.minimum, 'minimum'), helped(self.metric, 'metric'), self.run_button],
            ['분석 결과', [self.saved, self.open_button], [self.sort, self.limit, self.view_button], helped(self.low_only, 'low'),
             self.table, self.export_button, self.summary, [self.progress, self.cancel_button], self.details_panel])
        for selector in (self.source, self.reference):
            selector.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        settings = project.analysis_settings.get('statistics', {})
        initial_kind = settings.get('kind', 'ngram')
        if initial_kind == 'keyness' and not any(entry.get('type') == 'morphology' and (entry.get('role') == 'reference' or entry.get('path') == settings.get('reference_result')) for entry in project.results):
            initial_kind = 'ngram'
        self.kind.setCurrentIndex(max(0, self.kind.findData(initial_kind)))
        self.pos.setText(settings.get('pos', ''))
        self.exclude_punctuation.setChecked(settings.get('exclude_punctuation', False))
        self.excluded_forms.setPlainText('\n'.join(settings.get('excluded_forms', [])))
        self.cross.setChecked(settings.get('cross_utterances', False))
        self.n.setValue(settings.get('n', 2))
        self.include_pos.setChecked(settings.get('include_pos', False))
        self.center.setText(settings.get('center', ''))
        self.left.setValue(settings.get('left', 2))
        self.right.setValue(settings.get('right', 2))
        self.minimum.setValue(settings.get('minimum', 2))
        self.metric.setCurrentText(settings.get('metric', 'MI'))
        self.keyness_metric.setCurrentIndex(max(0, self.keyness_metric.findData(settings.get('metric', 'G²'))))
        target_index = self.source.findData(settings.get('target_result'))
        reference_index = self.reference.findData(settings.get('reference_result'))
        if target_index >= 0:
            self.source.setCurrentIndex(target_index)
        if reference_index > 0:
            self.reference.setCurrentIndex(reference_index)
        self.confirm_external.setChecked(settings.get('confirm_external', False) and target_index >= 0 and reference_index > 0)
        self.source.currentIndexChanged.connect(self.pair_changed)
        self.reference.currentIndexChanged.connect(self.pair_changed)
        self.refresh_saved()
        self.refresh()

    def refresh(self):
        kind = self.kind.currentData()
        ngram, keyness = kind in ('ngram', 'keyness'), kind == 'keyness'
        self.n.setVisible(ngram)
        self.include_pos.setVisible(ngram)
        for control in (self.center, self.left, self.right, self.minimum, self.metric):
            control.setVisible(not ngram)
        self.source_label.setText('대상 말뭉치 형태소 결과' if keyness else '분석할 말뭉치의 형태소 결과')
        self.mode_hint.setText('대상·참조 결과를 비교합니다. 두 결과에 같은 분석 조건이 필요합니다.' if keyness else '선택한 말뭉치만 분석합니다. 참조 말뭉치는 필요하지 않습니다.')
        self.run_button.setText('핵심도 비교 계산' if keyness else 'N-gram 빈도 계산' if ngram else '연어 계산')
        for widget in (self.reference, self.reference_label, self.confirm_external, self.keyness_metric):
            widget.setVisible(keyness)
        self.sort.setItemText(0, '전체 결과: 대상 빈도순' if keyness else '전체 결과: 빈도순')
        self.run_button.setEnabled(not self.thread and self.source.count() > 0 and (not keyness or self.reference.currentData() is not None))
        self.open_button.setEnabled(not self.thread and self.saved.count() > 0)
        self.view_button.setEnabled(not self.thread and self.current_result_path is not None)
        self.export_button.setEnabled(not self.thread and self.current_result_path is not None)
        self.low_only.setVisible(self.displayed_kind == 'keyness')
        if not self.source.count() and not self.thread:
            self.summary.setText('먼저 형태소 분석을 실행하거나 이미 분석된 파일을 불러오세요.')

    def kind_changed(self):
        if self.kind.currentData() == 'keyness':
            self.sort.setCurrentIndex(self.sort.findData('score'))
        self.refresh()

    def pair_changed(self):
        self.confirm_external.setChecked(False)
        self.refresh()

    def refresh_saved(self):
        self.saved.clear()
        for entry in self.project.results:
            if entry.get('type') == 'statistics':
                self.saved.addItem(entry.get('label', entry['path']), entry['path'])
                if self.current_result_path and (self.project_file.parent / entry['path']).resolve() == Path(self.current_result_path).resolve():
                    self.saved.setCurrentIndex(self.saved.count() - 1)

    def settings(self):
        result = {'kind': self.kind.currentData(), 'pos': self.pos.text(), 'cross_utterances': self.cross.isChecked(),
                  'exclude_punctuation': self.exclude_punctuation.isChecked(),
                  'excluded_forms': sorted({line.strip() for line in self.excluded_forms.toPlainText().splitlines() if line.strip()})}
        if result['kind'] in ('ngram', 'keyness'):
            result.update(n=self.n.value(), include_pos=self.include_pos.isChecked())
            if result['kind'] == 'keyness':
                result.update(metric=self.keyness_metric.currentData(), confirm_external=self.confirm_external.isChecked(),
                              target_result=self.source.currentData(), reference_result=self.reference.currentData())
        else:
            result.update(center=self.center.text().strip(), left=self.left.value(), right=self.right.value(),
                          minimum=self.minimum.value(), metric=self.metric.currentText())
        return result

    def run_statistics(self):
        relative = self.source.currentData()
        if self.thread or not relative:
            return
        settings = self.settings()
        self.settings_saved.emit(settings)
        source = self.project_file.parent / relative
        directory = self.project_file.with_suffix('.results')
        sort, limit = self.sort.currentData(), self.limit.currentData()
        if settings['kind'] == 'keyness':
            relative_reference = self.reference.currentData()
            if not relative_reference:
                self.on_error('참조 말뭉치 결과를 선택하세요.')
                return
            reference = self.project_file.parent / relative_reference
            self.background(lambda cancel, progress: analyze_keyness(source, reference, settings, directory, cancel, progress, sort=sort, limit=limit), self.new_result)
        else:
            self.background(lambda cancel, progress: analyze_statistics(source, settings, directory, cancel, progress, sort=sort, limit=limit), self.new_result)

    def new_result(self, result):
        if not result.cancelled:
            self.low_only.setChecked(False)
        self.show_result(result)
        if not result.cancelled:
            self.result_saved.emit(result)
            self.refresh_saved()

    def show_result(self, result):
        if result.cancelled:
            self.summary.setText('취소됨 — 완료되지 않은 통계는 저장하지 않았습니다.')
            return
        self.current_result_path = result.path
        self.table.setSortingEnabled(False)
        self.table.setColumnCount(len(result.columns))
        self.table.setHorizontalHeaderLabels(result.columns)
        self.table.setRowCount(len(result.rows))
        for index, row in enumerate(result.rows):
            for column, value in enumerate(row):
                item = table_item(value)
                self.table.setItem(index, column, item)
        self.table.setSortingEnabled(True)
        meta = result.metadata
        self.displayed_kind = meta['kind']
        if self.displayed_kind != 'keyness':
            self.low_only.setChecked(False)
        column = (5 if self.sort.currentData() == 'score' else 1) if meta['kind'] == 'keyness' else 1 if meta['kind'] == 'ngram' else 9 if self.sort.currentData() == 'score' else 6
        self.table.sortItems(column, Qt.SortOrder.DescendingOrder)
        self.summary.setText(f"완료 · {meta['utterances']:,}발화 · 대상 형태소 {meta['eligible_tokens']:,} · 전체 N-gram/공기 슬롯 {meta['population']:,} · 후보 {meta['result_count']:,} · 표시 {len(result.rows):,}행\n" + meta['note'])
        if meta['kind'] == 'keyness':
            self.summary.setText(f"핵심도 완료 · 전체 N-gram 대상 {meta['target_ngrams']:,} / 참조 {meta['reference_ngrams']:,} · 합집합 {meta['result_count']:,}종 · 기대빈도<5 {meta['low_expected_count']:,}종 · 표시 {len(result.rows):,}행\n" + meta['note'])
        saved_filter = meta['settings'].get('exclude_punctuation', False)
        filter_state = '켜짐' if saved_filter else '꺼짐'
        if saved_filter and meta['settings'].get('punctuation_filter_version', 1) < PUNCTUATION_FILTER_VERSION:
            filter_state += ' (이전 제외 기준 · 새 기준 적용은 다시 계산)'
        self.summary.setText(self.summary.text().rstrip() + '\n저장 결과의 문장부호·가운뎃점 제외: ' + filter_state)
        ordered = {'kind': meta['kind'], 'settings': meta['settings'], 'population': meta['population'], **meta}
        self.details.setPlainText('저장된 결과의 설정과 빈도 기준 (위 편집 중인 설정과 다를 수 있음):\n' + json.dumps(ordered, ensure_ascii=False, indent=2))

    def on_progress(self, units, tokens, items):
        if self.kind.currentData() == 'keyness':
            label = f'{"대상" if units == -1 else "참조"} 준비/집계 · 발화 {tokens:,} · N-gram {items:,}' if units < 0 else f'핵심도 비교 후보 {units:,}종'
            self.summary.setText(label)
            return
        self.summary.setText(f'처리 {units:,}발화 · 형태소 {tokens:,} · 생성 N-gram/공기 슬롯 {items:,}')

    def open_saved(self):
        relative = self.saved.currentData()
        if relative and not self.thread:
            self.load_path(self.project_file.parent / relative)

    def reload_result(self):
        if self.current_result_path and not self.thread:
            self.load_path(self.current_result_path)

    def load_path(self, path):
        sort, limit = self.sort.currentData(), self.limit.currentData()
        low = self.low_only.isChecked()
        self.background(lambda cancel, progress: load_statistics(path, sort, limit, cancel, low_expected_only=low), self.show_result)

    def open_export(self):
        if self.current_result_path and not self.thread:
            from .export_ui import ExportDialog
            ExportDialog(self.current_result_path, self, sort=self.sort.currentData()).exec()
