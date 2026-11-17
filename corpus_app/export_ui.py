"""A cancellable export window for immutable morphology/statistics snapshots."""
from pathlib import Path
from PyQt6.QtWidgets import (QVBoxLayout, QLabel, QComboBox, QCheckBox, QPushButton, QFileDialog, QMessageBox)
from .analysis_ui import JobDialog
from .presentation import label, primary, finish_ui
from .exporting import export_result


class ExportDialog(JobDialog):
    def __init__(self, source, parent=None, *, sort='frequency', morphology=False):
        super().__init__(parent)
        self.source, self.sort = str(source), sort
        self.destination, self.overwrite = None, False
        self.setWindowTitle('전체 분석 결과 내보내기')
        self.resize(820, 500)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(label('전체 결과 내보내기', 'title'))
        info = QLabel('미리보기 행 수와 관계없이 저장된 전체 결과와 당시 설정을 내보냅니다. 형태소는 토큰별 한 행, 통계는 후보별 한 행입니다.')
        info.setWordWrap(True)
        layout.addWidget(info)
        self.format = QComboBox()
        self.format.addItem('CSV (UTF-8 BOM) + 분석 설정 JSON', '.csv')
        self.format.addItem('Excel (.xlsx): 결과 + 분석 설정 시트', '.xlsx')
        self.format.currentIndexChanged.connect(self.format_changed)
        layout.addWidget(self.format)
        self.include_text = QCheckBox('형태소 내보내기에 원문/재구성 텍스트 포함 (Excel 셀은 32,767자까지)')
        self.include_text.setChecked(True)
        self.include_text.setVisible(morphology)
        layout.addWidget(self.include_text)
        self.safe_csv = QCheckBox("CSV: 수식 시작 문자열과 16자리 이상 정수를 텍스트로 보호 (앞에 ' 추가)")
        self.safe_csv.setChecked(True)
        layout.addWidget(self.safe_csv)
        self.choose = QPushButton('저장 파일 선택…')
        self.choose.clicked.connect(self.choose_file)
        layout.addWidget(self.choose)
        self.path_label = QLabel('저장할 파일을 선택하세요.')
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)
        self.run_button = QPushButton('전체 결과 내보내기')
        self.run_button.clicked.connect(self.run_export)
        layout.addWidget(self.run_button)
        primary(self.run_button)
        self.job_footer(layout)
        self.inputs = [self.format, self.include_text, self.safe_csv, self.choose, self.run_button]
        finish_ui(self)
        self.refresh()

    def format_changed(self):
        self.destination = None
        self.overwrite = False
        self.path_label.setText('형식이 바뀌었습니다. 저장 파일을 선택하세요.')
        self.refresh()

    def refresh(self):
        self.safe_csv.setVisible(self.format.currentData() == '.csv')
        self.run_button.setEnabled(not self.thread and self.destination is not None)

    def choose_file(self):
        suffix = self.format.currentData()
        filename, _ = QFileDialog.getSaveFileName(self, '전체 분석 결과 저장', Path(self.source).stem + suffix,
            'CSV (*.csv)' if suffix == '.csv' else 'Excel (*.xlsx)', options=QFileDialog.Option.DontConfirmOverwrite)
        if not filename:
            return
        path = Path(filename)
        if not path.suffix:
            path = path.with_suffix(suffix)
        if path.suffix.lower() != suffix:
            self.on_error('선택한 출력 형식과 파일 확장자가 다릅니다.')
            return
        outputs = [path, path.with_suffix(path.suffix + '.settings.json')] if suffix == '.csv' else [path]
        existing = [str(p) for p in outputs if p.exists()]
        overwrite = False
        if existing:
            answer = QMessageBox.question(self, '출력 파일 덮어쓰기', '아래 파일을 덮어쓸까요?\n' + '\n'.join(existing),
                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        self.destination, self.overwrite = path, overwrite
        self.path_label.setText('\n'.join(str(p) for p in outputs))
        self.refresh()

    def run_export(self):
        if self.thread or self.destination is None:
            return
        source, destination, sort = self.source, str(self.destination), self.sort
        include, safe, overwrite = self.include_text.isChecked(), self.safe_csv.isChecked(), self.overwrite
        self.background(lambda cancel, progress: export_result(source, destination, cancel=cancel, progress=progress,
            sort=sort, include_text=include, csv_safe=safe, overwrite=overwrite), self.show_export)

    def on_progress(self, done, total, unused):
        self.summary.setText(f'전체 결과 저장 중 · 내보낸 행 {done:,}')

    def show_export(self, result):
        if result.cancelled:
            self.summary.setText('취소됨 — 기존 출력 파일은 유지했습니다.')
        else:
            self.summary.setText(f'완료 · 전체 {result.rows:,}행 저장')
            self.overwrite = True  # The same chosen destination now belongs to this export.
        self.details.setPlainText('\n'.join(result.files + result.warnings))
