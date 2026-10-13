"""Bounded CLI with collision-safe output ownership and cleanup."""
import argparse
from contextlib import contextmanager
import base64
import hashlib
from pathlib import Path
from importlib.resources import files
import os
import shutil
import signal
import sys
import tempfile

from . import __version__
from .core import InputError, canonical, load

MAX_OUTPUT_FILE = 8 * 1024 * 1024
MAX_OUTPUT_TOTAL = 20 * 1024 * 1024
RUNTIME_SECONDS = 60


@contextmanager
def defer_cancellation():
    """Protect tiny ownership transitions; deliver pending signals on exit."""
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGALRM})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def render(data):
    base = files('track_gap')
    script = (base / 'player.js').read_text(encoding='utf-8').rstrip()
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    payload = canonical(data).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    template = (base / 'player.html').read_text(encoding='utf-8')
    # Replace payload last: hostile aliases cannot be interpreted as template tokens.
    return template.replace('__SCRIPT_HASH__', digest).replace('__PLAYER__', script).replace('__TIMELINE__', payload)


def build(manifest, output, max_gap_ms=60000):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise InputError('output path already exists; choose a new directory')
    if not output.parent.is_dir():
        raise InputError('output parent must already exist')
    data = load(manifest, max_gap_ms)
    artifacts = {'timeline.json': canonical(data).encode('utf-8'), 'timelapse.html': render(data).encode('utf-8')}
    if any(len(v) > MAX_OUTPUT_FILE for v in artifacts.values()) or sum(map(len, artifacts.values())) > MAX_OUTPUT_TOTAL:
        raise InputError('output byte limit exceeded')
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in artifacts.items()}
    artifacts['SHA256SUMS'] = ''.join(f'{hashes[name]}  {name}\n' for name in sorted(hashes)).encode()
    owned = False
    stage = None
    try:
        # A cancellation between creating a directory and recording ownership
        # must not leave an untracked directory behind.
        with defer_cancellation():
            stage = Path(tempfile.mkdtemp(prefix='.track-gap-', dir=output.parent))
        for name, content in artifacts.items():
            with (stage / name).open('xb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        # Exclusive reservation avoids replacing even an empty competing directory.
        with defer_cancellation():
            output.mkdir(mode=0o700)
            owned = True
        for name in artifacts:
            os.replace(stage / name, output / name)
        with defer_cancellation():
            shutil.rmtree(stage)
            stage = None
    except BaseException:
        with defer_cancellation():
            if owned:
                shutil.rmtree(output)
            if stage is not None:
                shutil.rmtree(stage)
        raise
    return hashes


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build a self-contained synthetic GPX timelapse, offline.')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('output', type=Path, help='new output directory; never overwrites an existing path')
    parser.add_argument('--max-gap-ms', type=int, default=60000)
    args = parser.parse_args(argv)
    def cancelled(signum, frame):
        raise InputError('cancelled' if signum != getattr(signal, 'SIGALRM', None) else '60-second runtime limit exceeded')
    previous = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
            previous[sig] = signal.signal(sig, cancelled)
        signal.setitimer(signal.ITIMER_REAL, RUNTIME_SECONDS)
        hashes = build(args.manifest, args.output, args.max_gap_ms)
        print(canonical({'output': str(args.output), 'sha256': hashes}), end='')
        return 0
    except (InputError, OSError, ValueError, OverflowError, RecursionError) as exc:
        print(f'track-gap: {exc}', file=sys.stderr)
        return 2
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    sys.exit(main())
