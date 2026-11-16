"""Bareun hosted HTTPS adapter. API keys exist only in this runtime object."""
from . import Morpheme


class BareunAnalyzer:
    def status(self):
        from .registry import status
        return status('bareun')

    def supported_options(self):
        return {'auto_spacing': bool, 'auto_jointing': bool, 'custom_dicts': list}

    def __init__(self, options, api_key):
        if not api_key or not api_key.strip():
            raise ValueError('바른 API 키를 분석 창에 입력하세요.')
        from bareunpy.bareun.language_service_connect import LanguageServiceClientSync
        self.options = options
        self._key = api_key.strip()
        self.client = LanguageServiceClientSync('https://api.bareun.ai:443', timeout_ms=30000)

    def analyze(self, text):
        if not text.strip():
            return []
        from bareunpy import Tagged
        from bareunpy.bareun import language_service_pb2 as pb, lang_common_pb2 as lpb
        request = pb.AnalyzeSyntaxRequest()
        request.document.content = text
        request.document.language = 'ko_KR'
        request.encoding_type = lpb.EncodingType.UTF32
        request.auto_split_sentence = False
        request.auto_spacing = self.options.get('auto_spacing', True)
        request.auto_jointing = self.options.get('auto_jointing', True)
        request.custom_dict_names.extend(self.options.get('custom_dicts', []))
        try:
            response = self.client.analyze_syntax(request, headers={'api-key': self._key})
            return [Morpheme(form, pos) for form, pos in Tagged(text, response).pos()]
        except Exception:
            # SDK/server exceptions may include authentication headers or raw text.
            raise RuntimeError('바른 요청 실패: API 키·이용 한도·네트워크·서버 사전 이름을 확인하세요. 요청 제한 시간은 30초입니다.') from None

    def close(self):
        try:
            self.client.close()
        finally:
            self._key = ''
