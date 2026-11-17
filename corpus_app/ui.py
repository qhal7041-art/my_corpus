from pathlib import Path
import os
from PyQt6.QtCore import Qt, QThread, QTimer
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QInputDialog, QMessageBox, QStackedWidget, QComboBox,
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem,
    QSplitter, QProgressBar, QPlainTextEdit, QHeaderView, QAbstractItemView,
    QFrame, QLineEdit, QTabWidget, QSizePolicy, QScrollArea,
)
from .presentation import apply_theme, label, primary, StatusLabel, DetailsPanel, finish_ui, table_item, result_name
from .project import Project
from .workers import CorpusWorker
from .json_corpus import display_path


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        apply_theme()
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
        self.resize(1280, 820)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.build_welcome()
        self.build_workspace()
        menu = self.menuBar().addMenu("프로젝트")
        self.new_action = menu.addAction("새 프로젝트…", self.new_project)
        self.new_action.setShortcut("Ctrl+N")
        self.open_action = menu.addAction("프로젝트 열기…", self.open_project)
        self.open_action.setShortcut("Ctrl+O")
        self.save_action = menu.addAction("저장", self.save_project)
        self.save_action.setShortcut("Ctrl+S")
        self.save_action.setEnabled(False)
        finish_ui(self)

    def build_welcome(self):
        page = QWidget(); page.setObjectName('page')
        outer = QVBoxLayout(page); outer.setContentsMargins(50, 40, 50, 40)
        outer.addStretch()
        card = QFrame(); card.setObjectName('card'); card.setMaximumWidth(760)
        layout = QVBoxLayout(card); layout.setContentsMargins(48, 40, 48, 40); layout.setSpacing(18)
        layout.addWidget(label('한국어 말뭉치 분석', 'section'))
        layout.addWidget(label('말뭉치 연구실', 'hero'))
        layout.addWidget(label('자료를 불러오고, 분석 결과를 연구 프로젝트에 모아 보세요.'))
        steps = QHBoxLayout()
        for title, description in [('01  자료 선택', 'JSON · TXT · Excel'), ('02  형태소 분석', '분석기 또는 사전 분석 자료'), ('03  통계·내보내기', '연어 · N-gram · 핵심도')]:
            box = QVBoxLayout(); box.addWidget(label(title, 'section')); box.addWidget(label(description)); steps.addLayout(box)
        layout.addLayout(steps)
        row = QHBoxLayout()
        self.welcome_new = primary(QPushButton('새 프로젝트 만들기'))
        self.welcome_new.clicked.connect(self.new_project)
        self.welcome_open = QPushButton('기존 프로젝트 열기')
        self.welcome_open.clicked.connect(self.open_project)
        for button in (self.welcome_new, self.welcome_open):
            button.setMinimumHeight(30); row.addWidget(button)
        layout.addLayout(row)
        layout.addWidget(label('이미 형태소·품사가 붙은 TXT도 재분석 없이 사용할 수 있습니다.'))
        outer.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch()
        self.stack.addWidget(page)

    def build_workspace(self):
        page = QWidget(); page.setObjectName('page')
        shell = QHBoxLayout(page); shell.setContentsMargins(0, 0, 0, 0); shell.setSpacing(0)
        sidebar = QFrame(); sidebar.setObjectName('sidebar'); sidebar.setFixedWidth(226)
        nav = QVBoxLayout(sidebar); nav.setContentsMargins(16, 20, 16, 16); nav.setSpacing(8)
        nav.addWidget(label('말뭉치 연구실', 'section'))
        nav.addWidget(label('연구 워크스페이스'))
        nav.addSpacing(12)
        self.data_button = QPushButton('01   자료·필드 선택')
        self.data_button.setProperty('role', 'nav'); self.data_button.setCheckable(True); self.data_button.setChecked(True)
        self.data_button.clicked.connect(lambda: (self.workspace_tabs.setCurrentIndex(0), self.data_button.setChecked(True)))
        self.morph_button = QPushButton('02   형태소 분석…'); self.morph_button.setProperty('role', 'nav')
        self.morph_button.clicked.connect(self.open_morphology)
        self.statistics_button = QPushButton('03   통계·핵심도…'); self.statistics_button.setProperty('role', 'nav')
        self.statistics_button.clicked.connect(self.open_statistics)
        for button in (self.data_button, self.morph_button, self.statistics_button): nav.addWidget(button)
        nav.addSpacing(12)
        nav.addWidget(label('사전 분석 자료', 'section'))
        self.import_button = QPushButton('분석된 파일 불러오기…'); self.import_button.clicked.connect(self.open_tagged_import)
        nav.addWidget(self.import_button)
        nav.addWidget(label('이미 분석된 TXT · JSON · Excel'))
        nav.addStretch()
        self.saved_count = label('저장 결과 0개', 'section'); nav.addWidget(self.saved_count)
        self.save_state = label('프로젝트 준비 중'); nav.addWidget(self.save_state)
        self.save_button = primary(QPushButton('프로젝트 저장'))
        self.save_button.clicked.connect(self.save_project); nav.addWidget(self.save_button)
        self.project_switch = QPushButton('다른 프로젝트 열기…'); self.project_switch.clicked.connect(self.open_project); nav.addWidget(self.project_switch)
        shell.addWidget(sidebar)
        content = QVBoxLayout(); content.setContentsMargins(24, 16, 24, 12); content.setSpacing(8)
        shell.addLayout(content, 1)
        self.heading = label('', 'title'); content.addWidget(self.heading)
        self.project_path = label(''); self.project_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.project_path.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); content.addWidget(self.project_path)
        self.workspace_tabs = QTabWidget(); content.addWidget(self.workspace_tabs, 1)
        self.workspace_tabs.currentChanged.connect(lambda index: self.data_button.setChecked(index == 0))
        data = QWidget(); data.setObjectName('page'); layout = QVBoxLayout(data); layout.setContentsMargins(0, 8, 0, 0); layout.setSpacing(8)
        self.data_scroll = QScrollArea(); self.data_scroll.setWidgetResizable(True); self.data_scroll.setWidget(data)
        self.workspace_tabs.addTab(self.data_scroll, '자료 탐색')
        row = QHBoxLayout()
        self.role = QComboBox(); self.role.addItem('대상 말뭉치', 'target'); self.role.addItem('참조 말뭉치', 'reference')
        self.role.currentIndexChanged.connect(self.source_changed); row.addWidget(self.role, 1)
        self.connect_button = primary(QPushButton('폴더 연결 / 재연결…')); self.connect_button.clicked.connect(self.connect_folder); row.addWidget(self.connect_button)
        self.scan_button = QPushButton('구조 다시 읽기'); self.scan_button.clicked.connect(self.scan); row.addWidget(self.scan_button)
        layout.addLayout(row)
        self.folder_label = label(''); self.folder_label.setWordWrap(False); self.folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.folder_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); layout.addWidget(self.folder_label)
        metrics = QHBoxLayout(); self.metric_values = {}
        for key, caption in [('files', '읽은 파일'), ('texts', '추출 문자열'), ('failed', '읽기 실패')]:
            card = QFrame(); card.setObjectName('card'); box = QHBoxLayout(card); box.setContentsMargins(14, 8, 14, 8)
            caption_label = label(caption); caption_label.setWordWrap(False); box.addWidget(caption_label, 1)
            value = label('—', 'metric'); value.setWordWrap(False); box.addWidget(value); metrics.addWidget(card)
            self.metric_values[key] = value
        layout.addLayout(metrics)
        self.selected_label = label(''); self.selected_label.setWordWrap(False); self.selected_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.selected_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); layout.addWidget(self.selected_label)
        self.schema_search = QLineEdit(); self.schema_search.setPlaceholderText('필드 경로 또는 자료형 검색'); self.schema_search.setClearButtonEnabled(True)
        self.search_timer = QTimer(self); self.search_timer.setSingleShot(True); self.search_timer.setInterval(150)
        self.schema_search.textChanged.connect(lambda: self.search_timer.start()); self.search_timer.timeout.connect(self.filter_tree)
        search_row = QHBoxLayout(); search_row.addWidget(self.schema_search, 1); layout.addLayout(search_row)
        split = QSplitter(Qt.Orientation.Vertical); split.setChildrenCollapsible(False)
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(['필드 / 경로', '자료형', '예시 값', '존재 파일 / 성공 파일'])
        self.tree.setAlternatingRowColors(True); self.tree.setColumnWidth(0, 310); self.tree.setColumnWidth(1, 110); self.tree.setColumnWidth(2, 240)
        self.tree.itemSelectionChanged.connect(self.selection_changed); split.addWidget(self.tree)
        self.preview = QTableWidget(0, 3); self.preview.setHorizontalHeaderLabels(['추출 텍스트 · 앞 100건 / 500자', '원본 파일', '발화 ID'])
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.preview.setColumnWidth(1, 260); self.preview.setColumnWidth(2, 90); split.addWidget(self.preview)
        split.setMinimumHeight(260); split.setSizes([150, 110]); layout.addWidget(split, 1)
        self.field_count = label('폴더를 연결해 필드를 확인하세요.'); self.field_count.setWordWrap(False); search_row.addWidget(self.field_count)
        self.preview_button = QPushButton('선택 필드 미리보기'); self.preview_button.clicked.connect(self.extract); self.preview_button.setEnabled(False); search_row.addWidget(self.preview_button)
        history_page = QWidget(); history = QVBoxLayout(history_page); history.setContentsMargins(0, 14, 0, 0); history.setSpacing(10)
        history.addWidget(label('저장된 분석을 다시 열거나 이어서 내보낼 수 있습니다.'))
        self.history_tree = QTreeWidget(); self.history_tree.setHeaderLabels(['분석', '말뭉치', '저장된 결과'])
        self.history_tree.setAlternatingRowColors(True); self.history_tree.setColumnWidth(0, 130); self.history_tree.setColumnWidth(1, 100)
        self.history_tree.itemDoubleClicked.connect(self.open_history_result)
        self.history_tree.itemSelectionChanged.connect(lambda: self.history_open.setEnabled(not self.thread and bool(self.history_tree.selectedItems())))
        history.addWidget(self.history_tree, 1)
        self.history_open = QPushButton('선택한 결과 열기…'); self.history_open.clicked.connect(self.open_history_result); history.addWidget(self.history_open)
        self.workspace_tabs.addTab(history_page, '저장된 결과')
        self.summary = StatusLabel('폴더를 연결하거나 사전 분석 자료를 불러오세요.'); content.addWidget(self.summary)
        row = QHBoxLayout(); self.progress = QProgressBar(); self.progress.setRange(0, 1); self.progress.setValue(0); self.progress.setTextVisible(False); row.addWidget(self.progress, 1)
        self.cancel_button = QPushButton('작업 취소'); self.cancel_button.setEnabled(False); self.cancel_button.clicked.connect(self.cancel_job); row.addWidget(self.cancel_button)
        content.addLayout(row)
        self.errors = QPlainTextEdit(); self.errors.setReadOnly(True)
        self.errors.setPlaceholderText('읽기 실패 이유를 여기에 표시합니다. 앞 100건까지 확인할 수 있습니다.')
        self.error_panel = DetailsPanel(self.errors, '오류 및 처리 기록', auto_errors=True); content.addWidget(self.error_panel)
        self.stack.addWidget(page)

    def update_project_header(self):
        if not self.project:
            return
        self.project_path.setText(str(self.project_file)); self.project_path.setToolTip(str(self.project_file))
        self.save_state.setText('저장하지 않은 변경 있음' if self.dirty else '모든 변경 저장됨')
        self.setWindowModified(self.dirty)
        self.saved_count.setText(f'저장 결과 {len(self.project.results):,}개')
        self.history_tree.clear()
        names = {'ngram':'N-gram', 'collocation':'연어', 'keyness':'핵심도'}
        for entry in self.project.results:
            kind = '형태소' if entry.get('type') == 'morphology' else names.get(entry.get('config', {}).get('kind'), '통계')
            role = {'target':'대상', 'reference':'참조'}.get(entry.get('role'), '')
            item = QTreeWidgetItem([kind, role, result_name(entry)])
            item.setData(0, Qt.ItemDataRole.UserRole, entry)
            item.setToolTip(2, str(self.project_file.parent / entry.get('path', '')))
            self.history_tree.addTopLevelItem(item)
        self.workspace_tabs.setTabText(1, f'저장된 결과 ({len(self.project.results):,})')
        self.history_open.setEnabled(not self.thread and bool(self.history_tree.selectedItems()))

    def filter_tree(self):
        query = self.schema_search.text().casefold().strip()
        matches = 0
        def visit(item):
            nonlocal matches
            matched = not query or query in (item.text(0) + ' ' + item.text(1)).casefold()
            child_match = False
            for index in range(item.childCount()):
                child_match = visit(item.child(index)) or child_match
            item.setHidden(not matched and not child_match)
            if query and child_match:
                item.setExpanded(True)
            if matched:
                matches += 1
            return matched or child_match
        for index in range(self.tree.topLevelItemCount()): visit(self.tree.topLevelItem(index))
        self.field_count.setText(f'{matches:,}개 필드' if not query else f'검색 일치 {matches:,}개 필드')

    def open_history_result(self, *args):
        if self.thread:
            return
        items = self.history_tree.selectedItems()
        if not items:
            return
        entry = items[0].data(0, Qt.ItemDataRole.UserRole)
        role = entry.get('role', 'target')
        if role not in ('target', 'reference'): role = 'target'
        if entry.get('type') == 'morphology':
            from .morph_ui import MorphDialog
            dialog = MorphDialog(self.project, self.project_file, role, self)
            dialog.settings_saved.connect(self.save_analyzer_settings)
            dialog.result_saved.connect(lambda result: self.save_morph_result(result, role))
            index = dialog.saved_results.findData(entry['path'])
            if index >= 0: dialog.saved_results.setCurrentIndex(index)
            QTimer.singleShot(0, dialog.open_result)
        else:
            from .analysis_ui import StatisticsDialog
            dialog = StatisticsDialog(self.project, self.project_file, role, self)
            dialog.result_saved.connect(self.save_statistics_result)
            dialog.settings_saved.connect(self.save_statistics_settings)
            QTimer.singleShot(0, lambda: dialog.load_path(self.project_file.parent / entry['path']))
        dialog.exec()

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
        self.setWindowTitle(f"{project.name}[*] — 말뭉치 연구실")
        self.update_project_header()
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

    def save_morph_result(self, result, role=None):
        relative = os.path.relpath(result.path, self.project_file.parent)
        role = role or self.role.currentData()
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
        self.schema_search.clear()
        self.field_count.setText('폴더를 연결해 필드를 확인하세요.')
        for value in self.metric_values.values(): value.setText('—')
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
        self.update_project_header()
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
            self.update_project_header()
            self.statusBar().showMessage("프로젝트를 저장했습니다.", 5000)
            return True
        except (OSError, ValueError) as error:
            self.update_project_header()
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
        for control in (self.role, self.connect_button, self.scan_button, self.preview_button, self.tree, self.save_button, self.morph_button, self.import_button, self.statistics_button, self.project_switch, self.history_open):
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
        self.metric_values['files'].setText(f'{succeeded:,}')
        self.metric_values['failed'].setText(f'{failed:,}')
        self.summary.setText(f"처리 {processed:,}건 · 성공 {succeeded:,}건 · 실패 {failed:,}건 (전체 개수는 탐색하며 집계)")

    def job_error(self, message):
        self.last_error = message
        self.summary.setText("작업 실패: " + message)
        self.errors.setPlainText(message)

    def job_result(self, report):
        self.last_report = report
        self.metric_values['files'].setText(f'{report.succeeded:,}')
        self.metric_values['failed'].setText(f'{report.failed:,}')
        if self.job_kind == 'extract': self.metric_values['texts'].setText(f'{report.texts:,}')
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
                    self.preview.setItem(index, column, table_item(row[key]))
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
        self.filter_tree()

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
