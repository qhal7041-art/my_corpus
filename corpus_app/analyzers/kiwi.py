"""Kiwi adapter, initialized only inside an analysis worker."""
import math
from . import Morpheme


def user_words(text):
    words = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        parts = line.split()
        if len(parts) not in (2, 3):
            raise ValueError(f'사용자 사전 {number}행: 형태소 품사 [점수] 형식이 필요합니다.')
        score = float(parts[2]) if len(parts) == 3 else 0.0
        if not math.isfinite(score):
            raise ValueError(f'사용자 사전 {number}행: 유한한 점수가 필요합니다.')
        words.append((parts[0], parts[1], score))
    return words


class KiwiAnalyzer:
    def status(self):
        from .registry import status
        return status('kiwi')

    def supported_options(self):
        return {'normalize_coda': bool, 'split_complex': bool,
                'compatible_jamo': bool, 'user_dictionary': str}

    def __init__(self, options):
        from kiwipiepy import Kiwi
        allowed = {'normalize_coda', 'split_complex', 'compatible_jamo', 'user_dictionary'}
        if set(options) - allowed:
            raise ValueError('지원하지 않는 Kiwi 옵션입니다.')
        for key in allowed - {'user_dictionary'}:
            if key in options and type(options[key]) is not bool:
                raise ValueError(f'{key}는 참/거짓 값이어야 합니다.')
        self.options = {key: options.get(key, False) for key in allowed - {'user_dictionary'}}
        words = user_words(options.get('user_dictionary', ''))
        self.engine = Kiwi(num_workers=1, model_type='cong')
        for word, tag, score in words:
            self.engine.add_user_word(word, tag, score)

    def analyze(self, text):
        return [Morpheme(token.form, token.tag) for token in self.engine.tokenize(text, **self.options)]
