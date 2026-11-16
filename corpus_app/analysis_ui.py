"""Shared cancellable Qt jobs for pretagged import and disk-backed statistics."""
from pathlib import Path
import json
from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QProgressBar, QFileDialog, QSpinBox, QCheckBox)
from .workers import FunctionWorker
from .tagged_import import import_tagged, import_database
from .statistics.analysis import analyze_statistics, load_statistics


class JobDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = self.worker = None
        self.closing = False
        self.inputs = []
        self.last_result = None

    def job_footer(self, layout):
        self.summary = QLabel('준비됨')
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
        layout.addWidget(self.details)

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
        self.job_footer(layout)
        self.inputs = [self.mode, self.plus_delimited, self.choose, self.path, self.form, self.pos, self.id, self.run_button]
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
                self.table.setItem(index, column, QTableWidgetItem(value))
        prefix = '기존 결과 복사 완료 (저장 당시 집계)' if self.mode.currentData() == 'sqlite' else '완료'
        self.summary.setText(f'{prefix} · 성공 {report.succeeded:,}파일 · 실패 {report.failed:,} · 발화 {report.texts:,} · 형태소 {result.tokens:,} · 누락 분기 {report.missing:,}')
        self.details.setPlainText(json.dumps(result.config, ensure_ascii=False, indent=2) + '\n' +
                                  '\n'.join(f'{path}: {reason}' for path, reason in report.errors))
        self.result_saved.emit(result)


class StatisticsDialog(JobDialog):
    result_saved = pyqtSignal(object)
    settings_saved = pyqtSignal(dict)

    def __init__(self, project, project_file, role, parent=None):
        super().__init__(parent)
        self.project, self.project_file, self.role = project, Path(project_file), role
        self.current_result_path = None
        self.setWindowTitle('연어 · N-gram 분석')
        self.resize(1200, 800)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('저장된 형태소 결과 또는 이미 분석된 파일을 불러온 결과를 선택하세요. 분석기는 다시 실행하지 않습니다.'))
        self.source = QComboBox()
        preferred = 0
        for entry in project.results:
            if entry.get('type') == 'morphology':
                if entry.get('role') == role:
                    preferred = self.source.count()
                self.source.addItem(f"[{entry.get('role', '')}] {entry.get('label', entry['path'])}", entry['path'])
        self.source.setCurrentIndex(preferred)
        layout.addWidget(self.source)
        row = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItem('N-gram 빈도', 'ngram')
        self.kind.addItem('연어 (중심어 지정 / 전체 쌍)', 'collocation')
        self.kind.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.kind)
        self.pos = QLineEdit()
        self.pos.setPlaceholderText('품사 접두어 필터 (예: NN*,VV · 비우면 전체)')
        row.addWidget(self.pos, 1)
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
        layout.addWidget(self.table, 1)
        self.job_footer(layout)
        self.inputs = [self.source, self.kind, self.pos, self.cross, self.n, self.include_pos, self.center,
                       self.left, self.right, self.minimum, self.metric, self.run_button, self.saved, self.open_button,
                       self.sort, self.limit, self.view_button]
        settings = project.analysis_settings.get('statistics', {})
        self.kind.setCurrentIndex(max(0, self.kind.findData(settings.get('kind', 'ngram'))))
        self.pos.setText(settings.get('pos', ''))
        self.cross.setChecked(settings.get('cross_utterances', False))
        self.n.setValue(settings.get('n', 2))
        self.include_pos.setChecked(settings.get('include_pos', False))
        self.center.setText(settings.get('center', ''))
        self.left.setValue(settings.get('left', 2))
        self.right.setValue(settings.get('right', 2))
        self.minimum.setValue(settings.get('minimum', 2))
        self.metric.setCurrentText(settings.get('metric', 'MI'))
        self.refresh_saved()
        self.refresh()

    def refresh(self):
        ngram = self.kind.currentData() == 'ngram'
        self.n.setVisible(ngram)
        self.include_pos.setVisible(ngram)
        for control in (self.center, self.left, self.right, self.minimum, self.metric):
            control.setVisible(not ngram)
        self.run_button.setEnabled(not self.thread and self.source.count() > 0)
        self.open_button.setEnabled(not self.thread and self.saved.count() > 0)
        self.view_button.setEnabled(not self.thread and self.current_result_path is not None)
        if not self.source.count() and not self.thread:
            self.summary.setText('먼저 형태소 분석을 실행하거나 이미 분석된 파일을 불러오세요.')

    def refresh_saved(self):
        self.saved.clear()
        for entry in self.project.results:
            if entry.get('type') == 'statistics':
                self.saved.addItem(entry.get('label', entry['path']), entry['path'])
                if self.current_result_path and (self.project_file.parent / entry['path']).resolve() == Path(self.current_result_path).resolve():
                    self.saved.setCurrentIndex(self.saved.count() - 1)

    def settings(self):
        result = {'kind': self.kind.currentData(), 'pos': self.pos.text(), 'cross_utterances': self.cross.isChecked()}
        if result['kind'] == 'ngram':
            result.update(n=self.n.value(), include_pos=self.include_pos.isChecked())
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
        self.background(lambda cancel, progress: analyze_statistics(source, settings, directory, cancel, progress, sort=sort, limit=limit), self.new_result)

    def new_result(self, result):
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
                item = QTableWidgetItem()
                item.setData(Qt.ItemDataRole.DisplayRole, value)
                self.table.setItem(index, column, item)
        self.table.setSortingEnabled(True)
        meta = result.metadata
        column = 1 if meta['kind'] == 'ngram' else 9 if self.sort.currentData() == 'score' else 6
        self.table.sortItems(column, Qt.SortOrder.DescendingOrder)
        self.summary.setText(f"완료 · {meta['utterances']:,}발화 · 대상 형태소 {meta['eligible_tokens']:,} · 전체 N-gram/공기 슬롯 {meta['population']:,} · 후보 {meta['result_count']:,} · 표시 {len(result.rows):,}행\n" + meta['note'])
        ordered = {'kind': meta['kind'], 'settings': meta['settings'], 'population': meta['population'], **meta}
        self.details.setPlainText('저장된 결과의 설정과 빈도 기준 (위 편집 중인 설정과 다를 수 있음):\n' + json.dumps(ordered, ensure_ascii=False, indent=2))

    def on_progress(self, units, tokens, items):
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
        self.background(lambda cancel, progress: load_statistics(path, sort, limit, cancel), self.show_result)
