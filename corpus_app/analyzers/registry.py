"""Public configuration excludes runtime credentials. Native models load in workers."""
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
import hashlib
import json
import platform
from . import AnalyzerStatus


def package_version(name):
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def engine_version(name='kiwi'):
    if name == 'kiwi':
        engine, model = package_version('kiwipiepy'), package_version('kiwipiepy_model')
        return engine + '/model-' + model if engine and model else None
    return package_version({'bareun': 'bareunpy', 'utagger': 'pyutagger'}.get(name, name))


def public_config(config):
    if set(config) - {'name', 'options'}:
        raise ValueError('분석기 설정에는 이름과 옵션만 저장할 수 있습니다. API 키는 전용 입력 칸에 입력하세요.')
    name = config.get('name', 'kiwi')
    allowed = {'kiwi': {'normalize_coda', 'split_complex', 'compatible_jamo', 'user_dictionary'},
               'bareun': {'auto_spacing', 'auto_jointing', 'custom_dicts'}, 'utagger': {'version'}}
    options = config.get('options', {})
    if name not in allowed or not isinstance(options, dict) or set(options) - allowed[name]:
        raise ValueError('지원하지 않는 분석기 설정입니다. API 키는 전용 입력 칸에 입력하세요.')
    for key in ('normalize_coda', 'split_complex', 'compatible_jamo', 'auto_spacing', 'auto_jointing'):
        if key in options and type(options[key]) is not bool:
            raise ValueError('분석 옵션은 참/거짓이어야 합니다.')
    if 'user_dictionary' in options and not isinstance(options['user_dictionary'], str):
        raise ValueError('사용자 사전은 문자열이어야 합니다.')
    if 'custom_dicts' in options and (not isinstance(options['custom_dicts'], list) or any(not isinstance(v, str) for v in options['custom_dicts'])):
        raise ValueError('바른 사전 이름은 문자열 목록이어야 합니다.')
    if name == 'utagger' and options.get('version', 'utagger4') not in ('utagger3', 'utagger4', 'utagger4hj'):
        raise ValueError('지원하지 않는 UTagger 버전입니다.')
    return {'name': name, 'options': dict(options)}


def utagger_root(variant='utagger4'):
    path = Path.home() / 'pyutagger_path.json'
    try:
        if path.stat().st_size > 1024 * 1024:
            return None
        config = json.loads(path.read_text(encoding='utf-8'))
        value = config.get(variant)
        return Path(value).expanduser().resolve() if isinstance(value, str) and value else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def status(name, options=None):
    options = options or {}
    installed = engine_version(name)
    if name == 'kiwi':
        return AnalyzerStatus('Kiwi', bool(installed),
            f'설치됨: {installed}. 모델 초기화·실행 확인은 분석 시 수행합니다. 로컬 분석, 인증 불필요.' if installed else
            '미설치: python -m pip install -e ".[morphology]" 실행 후 다시 여세요.')
    if name == 'bareun':
        return AnalyzerStatus('바른', bool(installed),
            ('SDK 설치됨. API 키를 아래에 직접 입력하세요. 원문이 https://api.bareun.ai 로 전송되며 API 이용 한도/요금이 적용될 수 있습니다. '
             '서버 사용자 사전은 등록된 이름만 적용합니다. 키·연결 유효성은 분석 시 확인합니다.') if installed else
            'bareunpy 미설치: python -m pip install -e ".[bareun]". API 키 발급: https://bareun.ai/analyze')
    if name != 'utagger':
        return AnalyzerStatus(name, False, '알 수 없는 분석기입니다.')
    root = utagger_root(options.get('version', 'utagger4'))
    lib = ('LibUMA4.dll' if options.get('version', 'utagger4') != 'utagger3' else 'UTaggerR64.dll') if platform.system() == 'Windows' else ('UTagger4.so' if options.get('version', 'utagger4') != 'utagger3' else 'UTagger.so')
    available = bool(installed and platform.system() in ('Linux', 'Windows') and root and (root / 'bin' / lib).is_file())
    return AnalyzerStatus('UTagger', available,
        f'pyutagger {installed or "미설치"}. ' + ('등록된 라이브러리 발견. 실제 로드·모델 확인은 분석 시 수행합니다. API 키 불필요.' if available else
        '라이브러리/모델 미등록 또는 OS 미지원. pyutagger 설치 후 공식 다운로드 방법으로 바이너리·데이터를 설치하고 다시 여세요. '
        'pyutagger.downloader.install_utagger("utagger4") · https://pypi.org/project/pyutagger/'))


def model_identity(name, options, cancel):
    if name != 'utagger':
        return 'cong' if name == 'kiwi' else 'hosted-api/model-version-not-exposed'
    from ..json_corpus import checkpoint
    root = utagger_root(options.get('version', 'utagger4'))
    if root is None or not root.is_dir():
        raise ValueError('UTagger 설치 경로가 등록되지 않았습니다.')
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        checkpoint(cancel)
        if path.is_file():
            digest.update(json.dumps(str(path.relative_to(root))).encode())
            with path.open('rb') as stream:
                while chunk := stream.read(1024 * 1024):
                    checkpoint(cancel)
                    digest.update(chunk)
    return options.get('version', 'utagger4') + '/' + digest.hexdigest()


def create(name, options, *, api_key=''):
    if name == 'kiwi':
        from .kiwi import KiwiAnalyzer
        return KiwiAnalyzer(options)
    if name == 'bareun':
        from .bareun import BareunAnalyzer
        return BareunAnalyzer(options, api_key)
    if name == 'utagger':
        from .utagger import UTaggerAnalyzer
        return UTaggerAnalyzer(options)
    raise ValueError('지원하지 않는 분석기입니다.')
