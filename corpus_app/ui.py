from pathlib import Path
import os
from PyQt6.QtCore import Qt, QThread, QTimer
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QInputDialog, QMessageBox, QStackedWidget, QComboBox,
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem,
    QSplitter, QProgressBar, QPlainTextEdit, QHeaderView, QAbstractItemView,
)
from .project import Project
from .workers import CorpusWorker
from .json_corpus import display_path


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project = None
        self.project_file = None
        self.thread = None
        self.worker = None
        self.dirty = False
        self.closing = False
        self.job_kind = None
        self.job_role = None
        self.last_report = None
        self.last_error = None
        self.setWindowTitle("말뭉치 연구실")
        self.resize(1200, 800)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.build_welcome()
        self.build_workspace()
        menu = self.menuBar().addMenu("프로젝트")
        self.new_action = menu.addAction("새 프로젝트…", self.new_project)
        self.open_action = menu.addAction("프로젝트 열기…", self.open_project)
        self.save_action = menu.addAction("저장", self.save_project)
        self.save_action.setShortcut("Ctrl+S")
        self.save_action.setEnabled(False)

    def build_welcome(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch()
        title = QLabel("말뭉치 연구실\n한국어 JSON 말뭉치 프로젝트")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 26px; font-weight: 600; padding: 30px")
        layout.addWidget(title)
        for label, callback in (("새 연구 프로젝트 만들기", self.new_project), ("기존 프로젝트 열기", self.open_project)):
            button = QPushButton(label)
            button.setMinimumHeight(48)
            button.clicked.connect(callback)
            layout.addWidget(button)
        hint = QLabel("JSON · TXT · Excel 말뭉치 탐색 · 형태소 분석\n원본 파일은 수정하지 않습니다.")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        layout.addStretch()
        self.stack.addWidget(page)

    def build_workspace(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.heading = QLabel()
        self.heading.setStyleSheet("font-size: 20px; font-weight: 600")
        layout.addWidget(self.heading)
        row = QHBoxLayout()
        self.role = QComboBox()
        self.role.addItem("대상 말뭉치", "target")
        self.role.addItem("참조 말뭉치 (선택 사항)", "reference")
        self.role.currentIndexChanged.connect(self.source_changed)
        row.addWidget(self.role)
        self.connect_button = QPushButton("폴더 연결 / 재연결…")
        self.connect_button.clicked.connect(self.connect_folder)
        row.addWidget(self.connect_button)
        self.scan_button = QPushButton("구조 다시 읽기")
        self.scan_button.clicked.connect(self.scan)
        row.addWidget(self.scan_button)
        self.save_button = QPushButton("프로젝트 저장")
        self.save_button.clicked.connect(self.save_project)
        row.addWidget(self.save_button)
        self.morph_button = QPushButton("형태소 분석…")
        self.morph_button.clicked.connect(self.open_morphology)
        row.addWidget(self.morph_button)
        layout.addLayout(row)
        analysis_row = QHBoxLayout()
        self.import_button = QPushButton('이미 분석된 형태소·품사 파일 불러오기…')
        self.import_button.clicked.connect(self.open_tagged_import)
        analysis_row.addWidget(self.import_button)
        self.statistics_button = QPushButton('연어 · N-gram · 핵심도 분석…')
        self.statistics_button.clicked.connect(self.open_statistics)
        analysis_row.addWidget(self.statistics_button)
        layout.addLayout(analysis_row)
        self.folder_label = QLabel()
        self.folder_label.setWordWrap(True)
        layout.addWidget(self.folder_label)
        self.selected_label = QLabel()
        self.selected_label.setWordWrap(True)
        layout.addWidget(self.selected_label)
        split = QSplitter(Qt.Orientation.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["필드 / 경로", "자료형", "예시 값 (최대 160자)", "존재 파일 / 성공 파일"])
        self.tree.setColumnWidth(0, 400)
        self.tree.setColumnWidth(1, 150)
        self.tree.setColumnWidth(2, 280)
        self.tree.itemSelectionChanged.connect(self.selection_changed)
        split.addWidget(self.tree)
        self.preview = QTableWidget(0, 3)
        self.preview.setHorizontalHeaderLabels(["추출 텍스트 (최대 500자)", "원본 파일", "발화 ID"])
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.preview.setColumnWidth(1, 350)
        split.addWidget(self.preview)
        split.setSizes([350, 200])
        layout.addWidget(split, 1)
        self.preview_button = QPushButton("선택한 필드로 전체 추출 건수 확인 / 미리보기")
        self.preview_button.clicked.connect(self.extract)
        self.preview_button.setEnabled(False)
        layout.addWidget(self.preview_button)
        self.summary = QLabel("폴더를 연결하면 JSON · TXT · Excel을 파일별로 탐색합니다.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        row.addWidget(self.progress)
        self.cancel_button = QPushButton("작업 취소")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_job)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.errors = QPlainTextEdit()
        self.errors.setReadOnly(True)
        self.errors.setMaximumHeight(110)
        self.errors.setPlaceholderText("읽기 실패 이유가 여기에 표시됩니다 (최대 100건).")
        layout.addWidget(self.errors)
        future = QLabel("형태소 · 연어 · N-gram · 참조 핵심도(G²/χ²) · 전체 결과 Excel/CSV 내보내기")
        future.setStyleSheet("color: #666; padding: 6px")
        layout.addWidget(future)
        self.stack.addWidget(page)

    def confirm_discard(self):
        if not self.dirty:
            return True
        answer = QMessageBox.question(self, "프로젝트 변경", "현재 프로젝트의 변경 내용을 저장할까요?",
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QMessageBox.StandardButton.Discard

    def new_project(self):
        if self.thread or not self.confirm_discard():
            return
        name, ok = QInputDialog.getText(self, "새 프로젝트", "연구 프로젝트 이름")
        if not ok or not name.strip():
            return
        filename, _ = QFileDialog.getSaveFileName(self, "프로젝트 저장 위치", "연구.corpusproj", "말뭉치 프로젝트 (*.corpusproj)")
        if not filename:
            return
        if not filename.endswith(".corpusproj"):
            filename += ".corpusproj"
        project = Project(name.strip())
        try:
            project.save(filename)
        except (OSError, ValueError) as error:
            self.show_error(str(error))
            return
        self.activate(project, filename)

    def open_project(self):
        if self.thread or not self.confirm_discard():
            return
        filename, _ = QFileDialog.getOpenFileName(self, "프로젝트 열기", "", "말뭉치 프로젝트 (*.corpusproj);;모든 파일 (*)")
        if filename:
            self.load_project(filename)

    def load_project(self, filename):
        try:
            project = Project.load(filename)
        except (OSError, ValueError, TypeError, RecursionError) as error:
            self.show_error(str(error))
            return False
        self.activate(project, filename)
        return True

    def activate(self, project, filename):
        self.project = project
        self.project_file = Path(filename).resolve()
        self.dirty = False
        self.role.blockSignals(True)
        self.role.setCurrentIndex(0)
        self.role.blockSignals(False)
        self.heading.setText(project.name)
        self.setWindowTitle(f"{project.name} — 말뭉치 연구실")
        self.stack.setCurrentIndex(1)
        self.save_action.setEnabled(True)
        self.source_changed()

    def current_source(self):
        return getattr(self.project, self.role.currentData())

    def open_morphology(self):
        if self.thread or not self.project:
            return
        from .morph_ui import MorphDialog
        dialog = MorphDialog(self.project, self.project_file, self.role.currentData(), self)
        dialog.settings_saved.connect(self.save_analyzer_settings)
        dialog.result_saved.connect(self.save_morph_result)
        dialog.exec()

    def save_analyzer_settings(self, config):
        self.project.analyzer = config
        self.dirty = True
        self.save_project()

    def save_morph_result(self, result):
        relative = os.path.relpath(result.path, self.project_file.parent)
        role = self.role.currentData()
        self.project.results = [entry for entry in self.project.results
                                if not (entry.get('type') == 'morphology' and entry.get('path') == relative and entry.get('role') == role)]
        self.project.results.append({'type': 'morphology', 'role': role, 'path': relative,
            'label': f"{result.config['name']} · {result.report.texts:,}발화 · {Path(result.path).stem[-10:]}", 'config': result.config})
        self.dirty = True
        self.save_project()

    def open_tagged_import(self):
        if self.thread or not self.project:
            return
        from .analysis_ui import TaggedImportDialog
        dialog = TaggedImportDialog(self.project, self.project_file, self.role.currentData(), self)
        dialog.result_saved.connect(self.save_morph_result)
        dialog.exec()

    def open_statistics(self):
        if self.thread or not self.project:
            return
        from .analysis_ui import StatisticsDialog
        dialog = StatisticsDialog(self.project, self.project_file, self.role.currentData(), self)
        dialog.result_saved.connect(self.save_statistics_result)
        dialog.settings_saved.connect(self.save_statistics_settings)
        dialog.exec()

    def save_statistics_settings(self, settings):
        self.project.analysis_settings['statistics'] = settings
        self.dirty = True
        self.save_project()

    def save_statistics_result(self, result):
        relative = os.path.relpath(result.path, self.project_file.parent)
        role = self.role.currentData()
        source = Path(result.metadata['source']).resolve()
        for entry in self.project.results:
            if entry.get('type') == 'morphology' and (self.project_file.parent / entry['path']).resolve() == source:
                role = entry.get('role', role)
                break
        self.project.results = [entry for entry in self.project.results
                                if not (entry.get('type') == 'statistics' and entry.get('path') == relative)]
        self.project.results.append({'type': 'statistics', 'role': role, 'path': relative,
                                    'label': f"{role} · {result.metadata['kind']} · {result.metadata['result_count']:,}후보 · {Path(result.path).stem[-10:]}",
                                    'config': result.metadata})
        self.dirty = True
        self.save_project()

    def source_changed(self):
        if not self.project:
            return
        self.tree.clear()
        self.preview.setRowCount(0)
        self.errors.clear()
        self.summary.setText("폴더를 연결하거나 구조를 다시 읽으세요.")
        self.refresh_source()
        source = self.current_source()
        if source.folder and Path(source.folder).is_dir():
            self.scan()
        elif source.folder:
            self.summary.setText("연결된 폴더가 이동했거나 없습니다. ‘폴더 연결 / 재연결’에서 새 경로를 지정하세요. 선택 필드는 유지됩니다.")

    def refresh_source(self):
        source = self.current_source()
        self.folder_label.setText("폴더: " + (source.folder or "연결되지 않음"))
        self.selected_label.setText("저장할 분석 필드: " + (display_path(source.field_path) if source.field_path is not None else "선택하지 않음"))
        self.preview_button.setEnabled(not self.thread and source.field_path is not None and bool(source.folder))
        self.scan_button.setEnabled(not self.thread and bool(source.folder))

    def connect_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "말뭉치 폴더 (JSON / TXT / XLSX / XLS)", self.current_source().folder)
        if folder:
            self.current_source().folder = str(Path(folder).resolve())
            self.dirty = True
            self.source_changed()

    def save_project(self):
        if not self.project:
            return False
        try:
            self.project.save(self.project_file)
            self.dirty = False
            self.statusBar().showMessage("프로젝트를 저장했습니다.", 5000)
            return True
        except (OSError, ValueError) as error:
            self.show_error(str(error))
            return False

    def scan(self):
        self.start_job("scan")

    def extract(self):
        if self.current_source().field_path is not None:
            self.start_job("extract")

    def start_job(self, kind):
        if self.thread or not self.project:
            return
        source = self.current_source()
        if not source.folder:
            return
        self.job_kind = kind
        self.job_role = self.role.currentData()
        self.last_error = None
        self.last_report = None
        self.errors.clear()
        self.preview.setRowCount(0)
        if kind == "scan":
            self.tree.clear()
        self.summary.setText("구조 탐색 중…" if kind == "scan" else "텍스트 추출 중…")
        self.thread = QThread(self)
        self.worker = CorpusWorker(source.folder, tuple(source.field_path) if kind == "extract" else None)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.update_progress)
        self.worker.result.connect(self.job_result)
        self.worker.error.connect(self.job_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.job_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.set_busy(True)
        self.thread.start()

    def set_busy(self, busy):
        for control in (self.role, self.connect_button, self.scan_button, self.preview_button, self.tree, self.save_button, self.morph_button, self.import_button, self.statistics_button):
            control.setEnabled(not busy)
        for action in (self.new_action, self.open_action, self.save_action):
            action.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.progress.setRange(0, 0 if busy else 1)
        if not busy:
            self.progress.setValue(1)
            self.refresh_source()

    def cancel_job(self):
        if self.worker:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self.summary.setText("취소 요청됨 — 현재 파일 읽기가 끝나면 중단합니다.")

    def update_progress(self, processed, succeeded, failed):
        self.summary.setText(f"처리 {processed:,}건 · 성공 {succeeded:,}건 · 실패 {failed:,}건 (전체 개수는 탐색하며 집계)")

    def job_error(self, message):
        self.last_error = message
        self.summary.setText("작업 실패: " + message)
        self.errors.setPlainText(message)

    def job_result(self, report):
        self.last_report = report
        status = "취소됨 · 부분 결과" if report.cancelled else "완료"
        summary = f"{status} | 발견 {report.discovered:,} · 처리 {report.processed:,} · 성공 {report.succeeded:,} · 실패 {report.failed:,}"
        self.errors.setPlainText("\n".join(f"{path}\n  {reason}" for path, reason in report.errors))
        if report.failed > len(report.errors):
            self.errors.appendPlainText(f"실패 이유는 앞 {len(report.errors)}건만 표시합니다.")
        if self.job_kind == "scan":
            self.populate_tree(report)
            if report.schema_limited:
                summary += " | 필드 10,000개 제한 도달: 일부 구조 생략"
            if not report.discovered:
                summary += " | 지원하는 JSON / TXT / XLSX / XLS 파일이 없습니다."
        else:
            summary += (f"\n문자열 {report.texts:,}건 · 누락 분기 {report.missing:,}건 ({report.missing_files:,}개 파일)"
                        f" · 비문자열 {report.non_string:,}건 · 빈 배열 {report.empty_arrays:,}개"
                        f" | 미리보기 {len(report.preview)}건 / 최대 100건")
            self.preview.setRowCount(len(report.preview))
            for index, row in enumerate(report.preview):
                for column, key in enumerate(("text", "source", "utterance_id")):
                    self.preview.setItem(index, column, QTableWidgetItem(row[key]))
        self.summary.setText(summary)

    def populate_tree(self, report):
        items = {}
        restored_item = None
        self.tree.blockSignals(True)
        try:
            for path, info in sorted(report.fields.items(), key=lambda pair: (len(pair[0]), display_path(pair[0]))):
                item = QTreeWidgetItem([display_path(path), ", ".join(sorted(info.types)),
                                        " | ".join(f"{kind}: {value}" for kind, value in info.examples.items()),
                                        f"{info.files:,} / {report.succeeded:,}"])
                item.setData(0, Qt.ItemDataRole.UserRole, path)
                item.setToolTip(0, display_path(path))
                if path and path[:-1] in items:
                    items[path[:-1]].addChild(item)
                else:
                    self.tree.addTopLevelItem(item)
                items[path] = item
                if self.current_source().field_path is not None and tuple(self.current_source().field_path) == path:
                    item.setSelected(True)
                    restored_item = item
            self.tree.expandToDepth(1)
            if restored_item is not None:
                ancestor = restored_item.parent()
                while ancestor is not None:
                    ancestor.setExpanded(True)
                    ancestor = ancestor.parent()
                self.tree.scrollToItem(restored_item)
        finally:
            self.tree.blockSignals(False)

    def selection_changed(self):
        items = self.tree.selectedItems()
        if not items or not self.project or self.thread:
            return
        path = list(items[0].data(0, Qt.ItemDataRole.UserRole))
        if self.current_source().field_path != path:
            self.current_source().field_path = path
            self.dirty = True
        self.refresh_source()
        # Selecting a field immediately starts an actual, bounded preview.
        self.extract()

    def job_finished(self):
        kind = self.job_kind
        report = self.last_report
        self.thread = None
        self.worker = None
        self.set_busy(False)
        if self.closing:
            self.close()
        elif kind == "scan" and report and not report.cancelled and self.current_source().field_path is not None:
            QTimer.singleShot(0, self.extract)

    def show_error(self, message):
        QMessageBox.warning(self, "작업을 완료할 수 없습니다", message)

    def closeEvent(self, event):
        if self.thread:
            self.closing = True
            self.cancel_job()
            event.ignore()
        elif self.confirm_discard():
            event.accept()
        else:
            self.closing = False
            event.ignore()
