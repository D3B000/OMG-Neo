"""Validation builds only: run a trusted local probe inside the frozen runtime.

Not referenced by the production build script. Keeping the probe external means
its imports cannot add dependencies to PyInstaller's analysis.
"""
import sys

if len(sys.argv) > 2 and sys.argv[1] == '--validation-probe':
    _probe = sys.argv[2]
    sys.argv = [_probe, *sys.argv[3:]]
    with open(_probe, 'rb') as _stream:
        _code = compile(_stream.read(), _probe, 'exec')
    exec(_code, {'__name__': '__main__', '__file__': _probe})
    raise SystemExit(0)
