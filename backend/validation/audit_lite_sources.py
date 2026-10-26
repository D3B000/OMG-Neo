"""Conservative source dependency closure for Neo's vendored OMGLite subset.

No imports are executed. Every top-level backend module is a root (including
lazy features), and package initializers and relative imports are traversed.
The report is advisory: dynamic loaders and non-code assets need manual review.
"""
import argparse
import ast
import importlib.util
import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
LITE = BACKEND.parent / 'OMGLite/src'


def audit():
    modules = {}
    for path in LITE.rglob('*.py'):
        parts = path.relative_to(LITE).with_suffix('').parts
        name = '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)
        modules[name] = path
    roots = list(BACKEND.glob('*.py'))
    pending = [(path.stem, path) for path in roots]
    reached, visited, edges, dynamic = set(), set(), {}, []
    while pending:
        name, path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        package = name if path.name == '__init__.py' else name.rpartition('.')[0]
        dependencies = set()
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            if isinstance(node, ast.Import):
                dependencies.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ''
                if node.level:
                    base = importlib.util.resolve_name('.' * node.level + base, package)
                dependencies.add(base)
                dependencies.update(base + '.' + alias.name for alias in node.names)
            elif isinstance(node, ast.Call):
                func = ast.unparse(node.func)
                if func.endswith(('import_module', '__import__', 'spec_from_file_location')):
                    dynamic.append({'file': str(path.relative_to(BACKEND.parent)),
                                    'line': node.lineno, 'call': ast.unparse(node)})
                    if func.endswith(('import_module', '__import__')) and node.args:
                        arg = node.args[0]
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            dependencies.add(arg.value)
        local = set()
        for dependency in dependencies:
            parts = dependency.split('.')
            for index in range(1, len(parts) + 1):
                candidate = '.'.join(parts[:index])
                if candidate in modules:
                    local.add(candidate)
                    reached.add(candidate)
                    pending.append((candidate, modules[candidate]))
        edges[str(path.relative_to(BACKEND.parent))] = sorted(local)
    unused = sorted(set(modules) - reached)
    return {'rootPolicy': 'all backend/*.py, including lazy feature imports',
            'totalModules': len(modules), 'reachableModules': sorted(reached),
            'unusedFiles': [{'module': name,
                             'file': str(modules[name].relative_to(BACKEND.parent)),
                             'bytes': modules[name].stat().st_size,
                             'lines': len(modules[name].read_text(encoding='utf-8-sig').splitlines())}
                            for name in unused],
            'dynamicCallsToReview': dynamic, 'edges': edges}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = audit()
    if args.output:
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in
                      ('totalModules', 'unusedFiles', 'dynamicCallsToReview')}, indent=2))
