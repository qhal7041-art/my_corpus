"""Local, beginner-friendly help. Opening help never reads input or runs analysis."""
from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QToolButton, QMessageBox, QTextEdit, QLabel, QSizePolicy

# Titles, short hover explanations, and optional extended click explanations.
HELP = {
    'exclude_punctuation': ('문장부호·가운뎃점 제외', '따옴표·물음표 등 문장부호와 ·, ㆍ, ⋅, ∙ 같은 가운뎃점 모양 문자로만 된 형태소를 통계에서 제외합니다. 원문과 형태소 분석 결과는 그대로 둡니다.',
        '품사 태그와 관계없이 Unicode P(문장부호) 또는 ·ㆍᆞ⋅∙・･ 문자만으로 구성된 형태소를 제외합니다. 예: 5 · 18 → 5 18. 단어 내부의 5·18이나 일반 수학기호 +, 이모지는 그대로 둡니다. 단독 아래아(ㆍ, ᆞ)도 제외하므로 이를 연구 대상으로 남기려면 이 체크를 끄고 추가 제외 목록을 사용하세요. 필요한 항목은 추가 제외 칸에 입력하세요.\nN-gram은 제외 후 남은 형태소를 이어 묶습니다. 예: “ 동일하 ㄴ 것 ” → 동일하 ㄴ 것. 연어는 후보에서 제외하되 원래 위치 간 탐색 거리를 유지합니다. 참조 핵심도는 양쪽에 같은 제외 기준을 적용합니다. 기존 결과는 바뀌지 않으므로 종류별 계산 버튼을 다시 누르세요. 결과 하단에서 저장 당시 필터의 켜짐/꺼짐과 이전 기준 여부를 확인할 수 있습니다.'),
    'excluded_forms': ('추가 제외 형태소', '제외할 형태소를 한 줄에 하나씩 입력합니다. 예: 것 또는 ?. 품사를 붙이지 않고 분석 결과에 나온 형태소 표기 그대로 적으세요.',
        '대소문자를 구분해 형태소 전체가 정확히 일치할 때만 제외합니다. 쉼표도 제외 항목이 될 수 있어 쉼표 구분은 사용하지 않습니다. 예: 것만 입력하면 그것은 제외되지 않습니다.\n통계 계산에만 적용하며 대상·참조에 동일하게 적용합니다. 품사 필터와 함께 사용하면 모든 조건을 통과한 형태소만 집계합니다. 제외 후에도 동일하·ㄴ처럼 형태소 사이의 표시 공백은 유지됩니다.'),
    'engine': ('형태소 분석기', '문장을 형태소(뜻이나 문법 기능을 가진 작은 단위)와 품사로 나눕니다. 예: 밥을 → 밥/NNG + 을/JKO.',
        'Kiwi는 로컬 모델, 바른 API는 서버 분석, 바른 로컬은 baropy 모델을 사용합니다. UTagger는 선택한 버전의 바이너리·모델이 필요합니다. 설치·인증 상태는 분석기 아래 안내를 확인하세요.\n분석기마다 분할 방법과 품사 체계가 다를 수 있습니다. 대상·참조 비교에는 같은 분석기와 설정을 사용하세요.'),
    'normalize_coda': ('Kiwi · 받침 정규화', '‘먹었엌ㅋㅋ’처럼 덧붙은 받침을 분리해 분석하도록 돕습니다. 일반적인 맞춤법 교정 기능과는 다릅니다.',
        '구어·채팅 자료에 쓸 수 있습니다. 방언 표기를 연구한다면 보정 전후 분석을 비교해 선택하세요. 원본 파일은 바꾸지 않지만 형태소 분석 결과는 달라질 수 있습니다.'),
    'split_complex': ('Kiwi · 복합 형태소 분리', '더 잘게 나눌 수 있는 형태소를 최대한 분리합니다. 예: 고마움/NNG → 고맙/VA-I + 음/ETN.',
        '예시는 Kiwi 문서의 분석 예입니다. 실제 결과는 문맥과 모델에 따라 달라질 수 있습니다. 더 잘게 나누면 형태소 수와 이후 연어·N-gram 빈도도 달라집니다.'),
    'compatible_jamo': ('Kiwi · 호환 자모 출력', '분석 결과의 자모 표기를 익숙한 모양으로 바꿉니다. 예: ᆫ다/EF → ㄴ다/EF, ᆯ/ETM → ㄹ/ETM.',
        '첫가끝 자모와 호환 자모는 비슷하게 보여도 서로 다른 문자입니다. 이 옵션에 따라 형태소 문자열이 달라지므로 대상·참조 말뭉치에 똑같이 적용하세요.'),
    'user_dictionary': ('Kiwi · 사용자 사전', '방언·고유명사 등 분석기에 알려 줄 단어를 적습니다. 한 줄에 ‘형태소 품사 [점수]’ 형식입니다. 예: 제주방언 NNP 5.',
        'NNP는 고유명사, NNG는 일반명사입니다. 점수는 생략할 수 있으며 기본값은 0입니다. 높은 점수는 해당 분석을 더 선호하게 합니다. #으로 시작하는 줄은 주석입니다.\n이 칸은 파일 경로가 아닌 사전 내용 입력란입니다. 내용은 프로젝트에 저장됩니다. 등록한 단어가 모든 문맥에서 반드시 선택되는 것은 아닙니다.'),
    'bareun_key': ('바른 · API 키', '바른에서 발급받은 키를 여기에 직접 입력합니다. env 파일은 필요하지 않으며 키는 프로젝트·분석 결과에 저장하지 않습니다.',
        '바른 API는 분석할 텍스트를 바른 서버로 전송합니다. 바른 로컬도 키가 필요하며 최초 모델 다운로드·등록에 네트워크를 사용합니다. 로컬 SDK의 임시 등록 정보는 작업 종료 시 정리합니다.\n설정 저장으로 키가 보관되지는 않으므로 다음에 분석할 때 다시 입력하세요.'),
    'auto_spacing': ('바른 API · 띄어쓰기 보정', '붙어 있는 표현의 띄어쓰기를 보정하며 분석합니다. 띄어쓰기가 적은 구어 전사 자료 등에서 결과를 비교해 보세요.',
        '서버의 auto_spacing 옵션입니다. 결과는 문맥과 서버 모델에 따라 달라집니다. 방언의 원래 표기·어절 구분이 중요하면 끈 경우와 비교하세요. 원본 파일은 수정하지 않습니다.'),
    'auto_jointing': ('바른 API · 붙여쓰기 보정', '불필요하게 떨어진 표현을 붙여 분석하도록 요청합니다. 띄어쓰기 보정과 함께 문맥에 맞는 단어 경계를 찾는 옵션입니다.',
        '서버의 auto_jointing 옵션입니다. 보정 여부에 따라 형태소와 빈도가 달라질 수 있으므로 비교하는 두 말뭉치에 같은 값을 적용하세요. 원본 파일은 수정하지 않습니다.'),
    'server_dicts': ('바른 API · 서버 사용자 사전', '바른 서버에 이미 등록한 사용자 사전의 이름을 입력합니다. 여러 개는 쉼표로 구분합니다. 예: 방언사전, 지명사전.',
        '여기에 단어를 쓰거나 로컬 사전 파일 경로를 넣는 방식이 아닙니다. 사전 등록은 바른 서비스에서 먼저 진행하세요. 사용하지 않으면 비워 두세요.'),
    'utagger_version': ('UTagger · 버전 선택', '설치한 모델에 맞춰 UTagger 3, UTagger 4 또는 옛한글용 UTagger 4를 선택합니다.',
        '버전마다 별도 바이너리·모델이 필요할 수 있습니다. 패키지 설치만으로 모든 모델이 준비되는 것은 아닙니다. 현재 사용 가능 여부와 필요한 설정은 위 분석기 안내에 표시됩니다. 이 화면에서는 UTagger 사용자 사전을 지원하지 않습니다.'),
    'threads': ('바른 로컬 · CPU 스레드 수', '분석에 사용할 CPU 작업 스레드 수입니다. 기본값은 2입니다. 컴퓨터가 느려지면 낮춰 보세요.',
        '1~32 사이에서 선택합니다. 수가 크다고 반드시 빨라지지는 않으며 CPU 사용량이 늘 수 있습니다. 이 값은 형태소 내용의 동일성을 비교할 때 제외합니다.'),
    'sense': ('바른 로컬 · 동형이의어 어깨번호', '같은 표기지만 뜻이 다른 단어를 구분하는 번호를 형태소에 포함합니다. 예: 배__01과 같은 표기입니다.',
        '번호를 포함하면 서로 다른 뜻의 형태소를 별개 문자열로 집계할 수 있습니다. 실제 번호·출력 여부는 모델 분석 결과에 따릅니다. 대상·참조 비교에는 같은 값을 적용하세요.'),
    'user_nouns': ('바른 로컬 · 고유명사 사전', '고유명사로 분석하도록 알려 줄 단어를 한 줄에 하나씩 입력합니다. 예: 제주방언.',
        'Kiwi 사전과 형식이 다릅니다. 품사나 점수를 붙이지 않고 단어만 적으세요. 사전 내용은 프로젝트에 저장되며 분석 실행 때 로컬 SDK에 적용합니다.'),
    'model_cache': ('바른 로컬 · 모델 캐시', '내려받은 모델을 보관할 폴더입니다. 말뭉치 자료가 없는 전용 폴더를 지정하세요.',
        '기본 위치는 운영체제의 임시 폴더입니다. 임시 폴더 정리로 모델이 삭제되면 다시 다운로드할 수 있습니다. 계속 보관하려면 전용 폴더로 바꾸세요. 경로 변경은 형태소 내용의 동일성 비교에서 제외합니다.'),
    'field': ('분석할 텍스트 필드', '문장이 들어 있는 항목을 트리에서 선택하세요. 예: $.utterances[*].text는 배열 안 각 발화의 text를 읽습니다.',
        '아래 미리보기에서 실제 추출 텍스트·원본 파일·발화 ID를 확인하세요. 누락 값과 문자열이 아닌 값은 별도로 집계합니다. TXT는 줄 텍스트, Excel은 분석할 열의 필드를 선택합니다. 원본은 수정하지 않습니다.'),
    'role': ('대상·참조 말뭉치', '대상은 연구할 자료, 참조는 비교할 자료입니다. 각 말뭉치에 폴더와 텍스트 필드를 따로 지정할 수 있습니다.',
        'N-gram 핵심도는 두 말뭉치에서 상대적으로 두드러지는 표현을 비교합니다. 참조 자료는 선택 사항이며 연어·N-gram 빈도 분석에는 필요하지 않습니다.'),
    'kind': ('통계 분석 종류', 'N-gram은 연속된 형태소 묶음의 빈도, 연어는 주변 형태소 쌍의 결합, 핵심도는 대상·참조 간 사용 비율의 차이를 봅니다.', ''),
    'source': ('저장된 형태소 결과', '통계 계산에 사용할 저장 결과를 선택하세요. 화면에 보이는 형태소 분석 설정이 아니라 이 결과를 만들 당시 설정이 적용됩니다.', ''),
    'reference': ('핵심도 비교 자료', '비교할 참조 말뭉치의 저장된 형태소 결과를 선택합니다. 대상과 같은 분석기·옵션·사전·전처리로 만든 자료가 필요합니다.', ''),
    'confirm': ('분석 조건의 동일성 확인', '외부에서 분석한 자료나 서버 모델은 생산 과정을 앱이 확인할 수 없습니다. 두 자료의 분석기·품사·사전·전처리가 같은지 직접 확인한 뒤 체크하세요.',
        '설정 불일치를 무시하는 옵션이 아닙니다. 결과 쌍을 바꾸면 확인이 해제됩니다.'),
    'pos': ('품사 필터', '남길 품사를 쉼표로 구분합니다. NN*는 NN으로 시작하는 명사 태그, VV는 VV로 시작하는 태그를 선택합니다. 비우면 전체 품사를 사용합니다.',
        'N-gram은 선택한 품사만 남긴 뒤 묶으므로 원문에서 떨어져 있던 단어가 이웃이 될 수 있습니다. 연어는 제외 품사를 건너뛰되 탐색 거리를 압축하지 않습니다. 예: 밥/NNG 을/JKO 먹/VV에서 NN,VV를 선택하면 2-gram은 ‘밥 먹’이지만 연어 범위 1에서는 두 단어가 공기하지 않습니다.'),
    'cross': ('발화 경계', '체크하지 않으면 한 발화 안에서만 집계합니다. 체크하면 같은 파일 안에서 이웃 발화도 이어 집계합니다. 파일 경계는 넘지 않습니다.', ''),
    'n': ('N-gram의 n', '연속된 형태소를 몇 개씩 묶을지 정합니다. n=2이면 ‘밥 먹 다’에서 ‘밥 먹’, ‘먹 다’를 셉니다.',
        '품사 필터와 발화 경계 설정을 적용한 뒤 묶습니다. 남은 형태소 수가 n보다 적은 구간에서는 N-gram이 생성되지 않습니다.'),
    'include_pos': ('형태소와 품사 함께 사용', '체크하면 형태소/품사를 함께 비교합니다. 같은 ‘눈’이라도 품사 태그가 다르면 다른 항목이 됩니다.', ''),
    'center': ('중심 형태소', '주변에서 함께 쓰이는 말을 찾을 중심어입니다. 예: 먹. 비우면 탐색 범위에서 관찰된 모든 형태소 쌍을 후보로 셉니다.', ''),
    'left': ('왼쪽 탐색 범위', '중심 형태소에서 왼쪽으로 몇 개의 형태소까지 살펴볼지 정합니다. 2이면 바로 앞과 그 앞의 형태소를 봅니다. 0이면 왼쪽은 제외합니다.', ''),
    'right': ('오른쪽 탐색 범위', '중심 형태소에서 오른쪽으로 몇 개의 형태소까지 살펴볼지 정합니다. 0이면 오른쪽은 제외합니다. 양쪽 범위 합은 1 이상이어야 합니다.', ''),
    'minimum': ('최소 공기 빈도', '두 형태소가 탐색 범위 안에서 함께 관찰된 횟수의 최솟값입니다. 2이면 한 번만 관찰된 쌍은 결과에서 제외합니다.', ''),
    'metric': ('연어 통계 지표', 'MI는 우연히 기대되는 결합보다 얼마나 강한지, t-score는 관찰 빈도와 기대값의 차이를, logDice는 두 단어 빈도 대비 결합 정도를 봅니다.',
        'MI = log₂(O/E)\nt-score = (O − E) / √O\nlogDice = 14 + log₂(2O / (M중심+M결합))\nE = M중심×M결합 / N\n\nO는 방향 있는 공기 슬롯 빈도, M은 각 형태소/품사의 중심·결합 슬롯 주변합, N은 전체 유효 슬롯 수입니다. 단순 토큰 빈도가 분모는 아닙니다. (가, 나)와 (나, 가)는 별도 후보이며 같은 중심 주변에 같은 결합어가 여러 번 있으면 각 위치를 셉니다. 중심어·최소 빈도는 전체 배경을 바꾸지 않고 표시 후보만 제한합니다. MI는 드문 쌍도 높게 나올 수 있으므로 빈도도 함께 확인하세요.'),
    'keyness': ('핵심도 통계 지표', 'G²(로그 우도비)와 χ²(피어슨 카이제곱)는 대상·참조의 N-gram 사용 비율 차이를 비교합니다. 값이 클수록 차이가 큰 경향이 있습니다.',
        '2×2 표: 대상 [a, T대상−a], 참조 [c, T참조−c]. a·c는 해당 N-gram 빈도, T는 같은 n의 전체 N-gram 수입니다. 기대빈도 E = 행 합계×열 합계 / 전체 합계.\nG² = 2Σ O ln(O/E) (O=0인 항은 0)\nχ² = Σ (O−E)²/E (Yates 보정 없음)\n\n방향은 상대 빈도로 판단하며 통계량은 음수가 아닙니다. 한쪽에만 있는 항목도 포함합니다. p값이나 자동 유의성 판정을 제공하지 않습니다. 한쪽 전체 N-gram 수가 0이면 이유를 표시합니다.'),
    'low': ('기대빈도 5 미만', '2×2 표의 기대빈도 중 하나라도 5보다 작은 항목만 보여줍니다. 특히 카이제곱 근사의 해석에 주의가 필요한 항목을 확인할 수 있습니다.',
        '전체 후보에서 먼저 필터링한 다음 정렬과 상위 행 제한을 적용합니다. 통계값을 다시 계산하거나 후보를 삭제하는 기능은 아닙니다.'),
}


class HelpButton(QToolButton):
    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.key = key
        title, brief, _ = HELP[key]
        self.setText('?')
        self.setProperty('role', 'help')
        self.setFixedSize(24, 24)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(title + ' 도움말')
        self.setToolTip(title + '\n' + brief + '\n클릭하면 자세한 설명을 볼 수 있습니다.')
        self.clicked.connect(self.show_help)
        self.popup = None

    def show_help(self):
        if self.popup is not None:
            self.popup.show(); self.popup.raise_(); self.popup.activateWindow()
            return
        title, brief, detail = HELP[self.key]
        popup = QMessageBox(self.window())
        help_width = min(400, max(200, self.screen().availableGeometry().width() - 100))
        popup.setStyleSheet(f'QLabel#qt_msgbox_label, QLabel#qt_msgbox_informativelabel {{ min-width: {help_width}px; }}')
        popup.setWindowTitle(title + ' 도움말')
        popup.setTextFormat(Qt.TextFormat.PlainText)
        popup.setText(title)
        popup.setInformativeText(brief)
        if detail:
            popup.setDetailedText(detail)
        popup.setStandardButtons(QMessageBox.StandardButton.Ok)
        popup.button(QMessageBox.StandardButton.Ok).setText('닫기')
        for button in popup.buttons():
            if popup.buttonRole(button) == QMessageBox.ButtonRole.ActionRole:
                button.setText('자세히 보기')
                def update_caption(current=button):
                    editor = popup.findChild(QTextEdit)
                    current.setText('자세한 설명 접기' if editor and editor.isVisible() else '자세히 보기')
                button.clicked.connect(lambda checked=False, update=update_caption: QTimer.singleShot(0, update))
        self.popup = popup
        popup.finished.connect(self.close_help)
        popup.open()

    def close_help(self, result):
        popup, self.popup = self.popup, None
        if popup:
            popup.deleteLater()


class HelpField(QWidget):
    """Keep help next to a control, following its engine/mode visibility."""
    def __init__(self, control, key):
        super().__init__()
        self.control = control
        if isinstance(control, QLabel):
            control.setWordWrap(True)
            control.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        control.setToolTip(HELP[key][1])
        control.setAccessibleDescription(HELP[key][1])
        self.help_button = HelpButton(key, self)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        hidden = control.isHidden()
        row.addWidget(control, 1)
        row.addWidget(self.help_button, 0, Qt.AlignmentFlag.AlignTop)
        control.installEventFilter(self)
        self.setVisible(not hidden)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.ShowToParent, QEvent.Type.HideToParent):
            self.setVisible(not self.control.isHidden())
        return super().eventFilter(watched, event)


def helped(control, key):
    return HelpField(control, key)
