"""Availability metadata without loading native models on the UI thread."""
from importlib.metadata import version, PackageNotFoundError
from . import AnalyzerStatus


def engine_version():
    try:
        return version('kiwipiepy') + '/model-' + version('kiwipiepy_model')
    except PackageNotFoundError:
        return None


def status(name):
    if name == 'kiwi':
        installed = engine_version()
        return AnalyzerStatus('Kiwi', installed is not None,
            f'설치됨: {installed}. 모델 초기화·실행 확인은 분석 시 수행합니다. 로컬 분석, 인증 불필요.' if installed else
            '미설치: python -m pip install -e ".[morphology]" 실행 후 다시 여세요.')
    if name == 'bareun':
        return AnalyzerStatus('바른', False,
            '현재 어댑터 미구현. 바른 SDK, 접근 가능한 분석 서버와 API 인증 설정이 필요합니다. '
            '이번 버전에서는 실행할 수 없습니다. https://bareun.ai 문서를 참고하세요. 인증 키를 프로젝트에 저장하지 마세요.')
    return AnalyzerStatus('UTagger', False,
        '현재 어댑터 미구현. 공식 배포처에서 OS에 맞는 UTagger 라이브러리·모델과 사용 허가를 준비해야 합니다. '
        '이번 버전에서는 실행할 수 없습니다.')


def create(name, options):
    if name != 'kiwi':
        raise ValueError(status(name).instructions)
    from .kiwi import KiwiAnalyzer
    return KiwiAnalyzer(options)
