"""Private runtime: no API key in argv/environment; never return raw SDK errors."""
import contextlib
import json
import signal
import sys


def reply(value):
    sys.__stdout__.write('CORPUS_BAROPY:' + json.dumps(value, ensure_ascii=False) + '\n')
    sys.__stdout__.flush()


def terminate(*args):
    # Unwind SDK calls and run its atexit handler, including during first startup.
    raise SystemExit()


def main():
    signal.signal(signal.SIGTERM, terminate)
    engine = None
    try:
        initial = json.loads(sys.stdin.readline())
        options = initial['options']
        with contextlib.redirect_stdout(sys.stderr):
            import baropy
            engine = baropy.Bareun(api_key=initial['api_key'], background=False,
                cache_dir=initial['runtime'], threads=options.get('threads', 2),
                idle_timeout=None, start_timeout=1800)
        initial.clear()
        reply({'ok': True})
        registered = False
        for line in sys.stdin:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                if not registered:
                    nouns = [v.strip() for v in options.get('user_nouns', '').splitlines() if v.strip()]
                    if nouns:
                        engine.dicts.put('corpus_app', np=nouns)
                    registered = True
                result = engine.analyze(request['text'], split_sentences=False,
                    sense=options.get('sense', False), dicts=['corpus_app'] if options.get('user_nouns', '').strip() else [])
                tokens = []
                for morph in result.morphemes:
                    form = morph.text
                    if options.get('sense') and morph.sense is not None and morph.sense.sense_no:
                        form += '__' + morph.sense.sense_no
                    tokens.append([form, morph.tag])
            reply({'ok': True, 'tokens': tokens})
    except Exception as error:
        code = type(error).__name__
        reply({'ok': False, 'code': code if code in ('AuthError', 'ModelFetchError', 'ServerStartError') else 'RuntimeError'})
    except SystemExit:
        pass
    finally:
        if engine is not None:
            with contextlib.redirect_stdout(sys.stderr):
                engine.release()


if __name__ == '__main__':
    main()
