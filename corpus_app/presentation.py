"""Shared visual language and layouts, independent of analysis settings/storage."""
import csv
import io
import re
import sys
from pathlib import Path
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QFont, QFontDatabase, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QToolButton, QFrame, QScrollArea, QSplitter, QPlainTextEdit,
    QTableWidget, QAbstractItemView, QComboBox, QSizePolicy)

STYLE = '''
QWidget { color: #243247; }
QMainWindow, QDialog, QWidget#page { background: #f5f7fa; }
QFrame#card, QWidget#card { background: white; border: 1px solid #e0e6ee; border-radius: 10px; }
QFrame#sidebar { background: #edf1f6; border: none; border-right: 1px solid #dce3ed; }
QLabel { background: transparent; border: none; }
QLabel[role="title"] { font-size: 17pt; font-weight: 700; color: #172f50; }
QLabel[role="hero"] { font-size: 24pt; font-weight: 700; color: #172f50; }
QLabel[role="section"] { font-size: 10pt; font-weight: 600; color: #283f60; }
QLabel[role="muted"] { color: #637187; }
QLabel[role="metric"] { font-size: 17pt; font-weight: 600; color: #172f50; }
QLabel[role="empty"] { color: #77869b; padding: 20px; }
QPushButton { background: white; border: 1px solid #cfd8e5; border-radius: 6px; padding: 8px 12px; min-height: 18px; }
QPushButton:hover { background: #edf3fb; border-color: #9eb3cf; }
QPushButton:pressed { background: #dbe7f6; }
QPushButton:focus, QToolButton:focus { border: 2px solid #5c83b8; }
QPushButton[role="primary"] { background: #254c7a; color: white; border-color: #254c7a; font-weight: 600; }
QPushButton[role="primary"]:hover { background: #1b3e68; }
QPushButton[role="nav"] { background: transparent; border: none; text-align: left; padding: 12px; }
QPushButton[role="nav"]:hover { background: #dfe7f2; }
QPushButton[role="nav"]:checked { background: #dae5f4; color: #183e6b; font-weight: 600; }
QPushButton:disabled { background: #edf0f4; border-color: #e1e6ed; color: #8b98a9; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox { background: white; border: 1px solid #cfd8e5; border-radius: 5px; padding: 7px 9px; selection-background-color: #d9e7f7; selection-color: #193655; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border: 2px solid #5c83b8; }
QComboBox::drop-down { border: none; width: 23px; }
QComboBox::down-arrow { image: url("@ASSETS@/chevron-down.svg"); width: 12px; height: 12px; }
QSpinBox::up-button, QSpinBox::down-button { width: 23px; border: none; }
QSpinBox::up-arrow { image: url("@ASSETS@/chevron-up.svg"); width: 12px; height: 12px; }
QSpinBox::down-arrow { image: url("@ASSETS@/chevron-down.svg"); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #dce8f8; selection-color: #173958; border: 1px solid #cfd8e5; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { background: #eff2f6; color: #8b98a9; }
QCheckBox { spacing: 7px; padding: 3px 0px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QTreeWidget, QTableWidget { background: white; alternate-background-color: #f5f8fc; border: 1px solid #dfe5ee; border-radius: 6px; selection-background-color: #dfeafa; selection-color: #183858; }
QTreeWidget::item { min-height: 29px; }
QHeaderView::section { background: #eef2f7; color: #4a5e78; border: none; border-bottom: 1px solid #dce4ef; padding: 9px 8px; font-weight: 600; }
QTableCornerButton::section { background: #eef2f7; border: none; }
QTabWidget::pane { border: none; }
QTabBar::tab { color: #65768d; background: transparent; padding: 10px 18px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #234c7a; border-bottom: 2px solid #234c7a; font-weight: 600; }
QProgressBar { background: #e6ecf4; border: none; border-radius: 3px; min-height: 6px; max-height: 6px; }
QProgressBar::chunk { background: #527cad; border-radius: 3px; }
QLabel[role="status"] { background: #eef2f7; color: #536880; border-radius: 6px; padding: 9px 12px; }
QLabel[state="success"] { background: #eaf5f0; color: #22634c; }
QLabel[state="warning"] { background: #fff5df; color: #89601d; }
QLabel[state="error"] { background: #fceeee; color: #a03737; }
QLabel[state="busy"] { background: #eaf1fb; color: #305a8c; }
QToolButton { border: none; background: transparent; padding: 7px 0px; color: #506580; }
QToolButton[role="help"] { border: 1px solid #9caec4; border-radius: 12px; padding: 0px; color: #385b83; background: #f3f7fc; font-weight: 600; }
QToolButton[role="help"]:hover { background: #dfeafa; border-color: #527cad; }
QToolButton[role="help"]:focus { border: 2px solid #527cad; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 11px; background: #f0f3f7; }
QScrollBar::handle:vertical { background: #bbc7d7; min-height: 30px; border-radius: 5px; margin: 2px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QSplitter::handle { background: #e2e8f0; }
QMenuBar { background: white; border-bottom: 1px solid #e3e8f0; }
QMenuBar::item { padding: 6px 10px; }
QStatusBar { background: #f5f7fa; color: #65768d; }
QToolTip { background: #243b59; color: white; padding: 6px; border: none; }
'''


def preferred_font_family(available, platform_name):
    """Choose an installed Korean UI font instead of a Latin-first fallback list."""
    common = ['Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic']
    preferred = (['Malgun Gothic', '맑은 고딕'] + common if platform_name == 'win32'
                 else ['Apple SD Gothic Neo'] + common if platform_name == 'darwin'
                 else common + ['Malgun Gothic', 'Apple SD Gothic Neo'])
    installed = {family.casefold(): family for family in available}
    return next((installed[name.casefold()] for name in preferred if name.casefold() in installed), None)


def apply_theme():
    app = QApplication.instance()
    if not app or app.property('corpus_theme_applied'):
        return
    app.setStyle('Fusion')
    font = QFont(app.font())
    family = preferred_font_family(QFontDatabase.families(), sys.platform)
    if family:
        font.setFamily(family)
    font.setPointSizeF(max(10, font.pointSizeF()))
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(STYLE.replace('@ASSETS@', (Path(__file__).parent / 'assets').as_posix()))
    app.setProperty('corpus_theme_applied', True)


def label(text, role='muted'):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    widget.setProperty('role', role)
    return widget


def primary(button):
    button.setProperty('role', 'primary')
    return button


class StatusLabel(QLabel):
    def __init__(self, text='준비됨'):
        super().__init__()
        self.setProperty('role', 'status')
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setText(text)

    def setText(self, text):
        super().setText(text)
        state = 'idle'
        if text.startswith(('실패', '작업 실패', '분석/결과 열기 실패')):
            state = 'error'
        elif '취소' in text:
            state = 'warning'
        elif '완료' in text or text.startswith('재사용'):
            state = 'warning' if re.search(r'실패\s*[1-9]', text) else 'success'
        elif '중' in text or '진행' in text or '집계' in text:
            state = 'busy'
        if self.property('state') != state:
            self.setProperty('state', state)
            self.style().unpolish(self)
            self.style().polish(self)


class DetailsPanel(QWidget):
    def __init__(self, editor, title='자세히 보기 · 설정 및 처리 기록', auto_errors=False):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.editor = editor
        editor.setMaximumHeight(180)
        editor.setMinimumHeight(100)
        layout.addWidget(self.toggle)
        layout.addWidget(editor)
        editor.hide()
        self.toggle.toggled.connect(self.expand)
        if auto_errors:
            editor.textChanged.connect(lambda: self.toggle.setChecked(bool(editor.toPlainText())))

    def expand(self, expanded):
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.editor.setVisible(expanded)

    def open(self):
        self.toggle.setChecked(True)


class EmptyTable(QLabel):
    def __init__(self, table, text):
        super().__init__(text, table.viewport())
        self.table = table
        self.setProperty('role', 'empty')
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        table.viewport().installEventFilter(self)
        for signal in (table.model().rowsInserted, table.model().rowsRemoved, table.model().modelReset):
            signal.connect(self.refresh)
        self.refresh()

    def refresh(self, *args):
        self.setGeometry(self.table.viewport().rect())
        self.setVisible(self.table.rowCount() == 0)
        self.raise_()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.refresh()
        return False


def copy_selection(table):
    indexes = table.selectedIndexes()
    if not indexes:
        return
    rows = sorted({index.row() for index in indexes})
    columns = sorted({index.column() for index in indexes})
    selected = {(index.row(), index.column()) for index in indexes}
    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter='\t', lineterminator='\n')
    for row in rows:
        writer.writerow([table.item(row, col).text() if (row, col) in selected and table.item(row, col) else '' for col in columns])
    QApplication.clipboard().setText(output.getvalue())


def table_item(value):
    from PyQt6.QtWidgets import QTableWidgetItem
    item = QTableWidgetItem()
    item.setData(Qt.ItemDataRole.DisplayRole, value)
    item.setToolTip(str(value))
    return item


def finish_ui(widget):
    for combo in widget.findChildren(QComboBox):
        combo.setMinimumContentsLength(12)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    for button in widget.findChildren(QPushButton):
        button.setAutoDefault(False)
    for text in widget.findChildren(QLabel):
        text.setTextFormat(Qt.TextFormat.PlainText)
    for table in widget.findChildren(QTableWidget):
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setDefaultSectionSize(32)
        table.horizontalHeader().setMaximumSectionSize(440)
        if not getattr(table, '_copy_shortcut', None):
            table._copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, table)
            table._copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            table._copy_shortcut.activated.connect(lambda current=table: copy_selection(current))
            table._empty_label = EmptyTable(table, '표시할 결과가 없습니다.\n자료나 저장 결과를 선택한 뒤 작업을 실행하세요.')
    app = QApplication.instance()
    if app and app.platformName() != 'offscreen' and widget.screen():
        available = widget.screen().availableGeometry()
        widget.resize(min(widget.width(), int(available.width() * .94)),
                      min(widget.height(), int(available.height() * .9)))


def _drain(layout):
    """Take layout items without deleting the analysis controls or their signals."""
    widgets = []
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            widgets.append(item.widget())
        elif item.layout():
            widgets.extend(_drain(item.layout()))
            item.layout().deleteLater()
    return widgets


def arrange_dialog(dialog, title, subtitle, settings, results):
    """Place existing controls into a scrolling settings pane and a wide result pane.

    Each entry is a QWidget, text section label, or a list of widgets for one row.
    Visibility is retained so analyzer-specific options still follow refresh().
    """
    root = dialog.layout()
    old = _drain(root)
    keep = set()
    for entries in (settings, results):
        for entry in entries:
            if isinstance(entry, QWidget):
                keep.add(entry)
            elif isinstance(entry, (tuple, list)):
                keep.update(entry)
    for widget in old:
        if widget not in keep:
            widget.hide()
            # Retain fields parented to a DetailsPanel, which is itself kept.
            if not any(widget.isAncestorOf(k) or k.isAncestorOf(widget) for k in keep):
                widget.deleteLater()
    root.setContentsMargins(22, 20, 22, 18)
    root.setSpacing(14)
    root.addWidget(label(title, 'title'))
    root.addWidget(label(subtitle))
    split = QSplitter(Qt.Orientation.Horizontal)
    split.setChildrenCollapsible(False)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setMinimumWidth(270)
    pane = QFrame(); pane.setObjectName('card')
    left = QVBoxLayout(pane); left.setContentsMargins(16, 16, 16, 16); left.setSpacing(10)
    scroll.setWidget(pane)
    right_pane = QWidget()
    right = QVBoxLayout(right_pane); right.setContentsMargins(14, 0, 0, 0); right.setSpacing(10)
    def add(layout, entries):
        for entry in entries:
            if isinstance(entry, str):
                layout.addWidget(label(entry, 'section'))
            elif isinstance(entry, (tuple, list)):
                row = QHBoxLayout(); row.setSpacing(8)
                for child in entry:
                    row.addWidget(child)
                layout.addLayout(row)
            else:
                layout.addWidget(entry, 1 if isinstance(entry, QTableWidget) else 0)
                if isinstance(entry, QLabel):
                    entry.setWordWrap(True)
                    entry.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    add(left, settings); left.addStretch()
    add(right, results)
    split.addWidget(scroll); split.addWidget(right_pane)
    split.setStretchFactor(0, 0); split.setStretchFactor(1, 1)
    split.setSizes([330, 830])
    root.addWidget(split, 1)
    dialog.resize(1240, 800)
    dialog.settings_scroll = scroll
    dialog.workspace_splitter = split
    finish_ui(dialog)


def result_name(entry):
    text = entry.get('label', entry.get('path', ''))
    names = {'imported': '사전 분석 자료', 'kiwi': 'Kiwi', 'bareun': '바른 API', 'baropy': '바른 로컬', 'utagger': 'UTagger', 'target': '대상', 'reference': '참조', 'keyness': '핵심도', 'ngram': 'N-gram', 'collocation': '연어'}
    return ' · '.join(names.get(part, part) for part in text.split(' · '))
