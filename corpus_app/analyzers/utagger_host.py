"""Private child-process protocol for the official pyutagger API."""
import contextlib
import json
import sys


def reply(value):
    sys.__stdout__.write('CORPUS_UTAGGER:' + json.dumps(value, ensure_ascii=False) + '\n')
    sys.__stdout__.flush()


def main():
    engine = None
    try:
        initial = json.loads(sys.stdin.readline())
        if initial.get('version') not in ('utagger3', 'utagger4', 'utagger4hj'):
            raise ValueError('unsupported version')
        with contextlib.redirect_stdout(sys.stderr):
            import pyutagger.utagger as ut
            engine = ut.utagger_loader(initial['version'])
            engine.load()
        reply({'ok': True})
        for line in sys.stdin:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                result = engine.pos(request['text'])
            if not isinstance(result, list) or any(not isinstance(p, (tuple, list)) or len(p) != 2 or not all(isinstance(v, str) for v in p) for p in result):
                raise ValueError('invalid output')
            reply({'ok': True, 'tokens': result})
    except (Exception, SystemExit):
        reply({'ok': False})
    finally:
        if engine is not None:
            with contextlib.redirect_stdout(sys.stderr):
                engine.release()


if __name__ == '__main__':
    main()
