# Validation-only wrapper: production neo_hosts.spec contains no executable probe.
from pathlib import Path
root = Path(SPECPATH).parent
_analysis = Analysis
def analysis_with_probe(*args, **kwargs):
    kwargs['runtime_hooks'] = [str(root / 'validation/size_probe_hook.py')]
    return _analysis(*args, **kwargs)
Analysis = analysis_with_probe
SPECPATH = str(root)
exec(compile((root / 'neo_hosts.spec').read_bytes(), str(root / 'neo_hosts.spec'), 'exec'))
