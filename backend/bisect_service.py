"""Manual recursive mod groups; resource-browser snapshot; exact reversible renames."""
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
from bisect_fs import identity, is_link, rename_exact, supported

CLOSED = {'closed', 'idle'}
CONTROL_NAMES = {'modfolder.ini', 'd3dx.ini', 'd3dx_user.ini'}
MAX_ENTRIES = 100000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def normalized(path):
    return os.path.normcase(str(Path(path).absolute()))


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


class ResourceLease:
    """OS locks shared by cooperating Neo instances, including portable copies."""
    def __init__(self, keys):
        self.files = []
        # Backend TEMP may be redirected to a portable AppData. Use the same
        # per-user OS location across portable copies for cooperative locks.
        common = Path(os.environ['LOCALAPPDATA']) / 'Temp' if os.name == 'nt' and os.environ.get('LOCALAPPDATA') else Path(tempfile.gettempdir())
        directory = common / 'OMGNeo-bisect-locks'
        directory.mkdir(exist_ok=True)
        try:
            for key in sorted(set(keys)):
                stream = (directory / (digest(key.encode()) + '.lock')).open('a+b')
                self.files.append(stream)
                stream.seek(0)
                if stream.read(1) == b'':
                    stream.write(b'0')
                    stream.flush()
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.close()
            raise ValueError('另一个 OMG-Neo 会话正在使用这些模组目录') from exc

    def close(self):
        for stream in reversed(self.files):
            stream.close()
        self.files.clear()


class BisectService:
    def __init__(self, data_root, config, game_stopped=None):
        self.directory = Path(data_root) / 'mod-bisect'
        self.path = self.directory / 'session.json'
        self.key_path = self.directory / 'integrity.key'
        self.config = config
        self.session, self.lease, self.load_error = None, None, None
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                self._load()
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.load_error = f'恢复记录无法验证，未执行文件操作：{exc}'

    def close(self):
        if self.lease:
            self.lease.close()
            self.lease = None

    @property
    def active(self):
        return bool(self.load_error or self.session and self.session['status'] not in CLOSED)

    def _key(self):
        if not self.key_path.exists():
            if self.path.exists():
                raise ValueError('完整性密钥缺失')
            with self.key_path.open('xb') as stream:
                stream.write(os.urandom(32))
                stream.flush()
                os.fsync(stream.fileno())
        key = self.key_path.read_bytes()
        if len(key) != 32:
            raise ValueError('完整性密钥无效')
        return key

    def _save(self):
        payload = json.dumps(self.session, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')).encode('utf-8')
        signature = hmac.new(self._key(), payload, hashlib.sha256).hexdigest()
        try:
            atomic(self.path, json.dumps({'payload': payload.decode('utf-8'), 'hmac': signature},
                                        ensure_ascii=False).encode('utf-8'))
        except OSError:
            self.session.update(status='recovery', message='恢复日志写入失败；已停止新操作，请核对并恢复。')
            raise

    def _load(self):
        envelope = json.loads(self.path.read_text('utf-8'))
        payload = envelope['payload'].encode('utf-8')
        if not hmac.compare_digest(envelope['hmac'], hmac.new(self._key(), payload, hashlib.sha256).hexdigest()):
            raise ValueError('记录完整性校验失败')
        session = json.loads(payload)
        if session.get('schema') not in (1, 2):
            raise ValueError('不支持的会话版本')
        self.session = session
        if self.active:
            session['resumeStatus'] = session['status']
            session['status'] = 'recovery'
            session['message'] = '发现未结束的记录；可核对状态后继续使用分组，或恢复初始状态。'

    def state(self):
        if self.load_error:
            return {'status': 'blocked', 'message': self.load_error, 'units': [], 'inis': [], 'errors': [self.load_error]}
        if not self.session:
            return {'status': 'idle', 'message': '扫描设置中的 GIMI\\Mods，核对模组与 INI 后开始。', 'units': [], 'inis': []}
        value = copy.deepcopy(self.session)
        value.pop('transactions', None)
        value['reportPath'] = str(self.directory / (value['sessionId'] + '-report.json'))
        value['logPath'] = str(self.path)
        value['groupCount'] = sum(not n.get('children') for n in value.get('nodes', []))
        entries = {e['id']: e for e in value['entries']}
        for ini in value['inis']:
            e = entries[ini['entryId']]
            base = Path(e['parent']) / e['currentName']
            target = Path(e['originalTarget']) if e['link'] else Path(e['originalTarget']).parent / e['currentName']
            ini['currentPath'] = str(base if ini['inside'] == '.' else base / ini['inside'])
            ini['currentTargetPath'] = str(target if ini['inside'] == '.' else target / ini['inside'])
        for key in ('history', 'discardedHistory'):
            for record in value.get(key, []):
                record.pop('before', None)
        by_unit = {}
        for e in value['entries']:
            by_unit.setdefault(e['unitId'], []).append(e['enabled'])
        for n in value.get('nodes', []):
            ids = n.get('unitIds', n.get('candidates', []))
            n['enabledCount'] = sum(all(by_unit.get(u, [False])) for u in ids)
            n['disabledCount'] = sum(not any(by_unit.get(u, [False])) for u in ids)
            n['count'] = len(ids)
            n['state'] = ('enabled' if ids and n['enabledCount'] == len(ids) else
                          'disabled' if ids and n['disabledCount'] == len(ids) else 'mixed')
        value['operationCount'] = len(value.get('history', []))
        return value

    def _require(self, params, statuses=None):
        if self.load_error or not self.session:
            raise ValueError(self.load_error or '没有二分排查会话')
        s = self.session
        if params.get('sessionId') != s['sessionId'] or params.get('generation') != s['generation']:
            raise ValueError('会话已变化，请刷新后重试')
        if statuses and s['status'] not in statuses:
            raise ValueError('当前阶段不能执行此操作')
        return s

    def _root(self, custom=None):
        if custom is not None:
            if not isinstance(custom, str) or not Path(custom).is_absolute():
                raise ValueError('请选择有效的绝对目录路径')
            root = Path(os.path.abspath(custom))
            if not root.is_dir():
                raise ValueError('所选排查目录不存在')
            supported(root)
            return root
        value = self.config.get_gimi_dir()
        if not value:
            raise ValueError('请先在设置中配置 GIMI 目录')
        root = Path(os.path.abspath(Path(value) / 'Mods'))
        if not root.is_dir():
            raise ValueError('设置中的 GIMI\\Mods 不存在')
        supported(root)
        return root

    def _acquire(self):
        if self.lease:
            return
        # Resource locks exclude drive/root ancestors: otherwise unrelated
        # libraries on the same volume would unnecessarily block each other.
        keys = ['root:' + json.dumps(self.session['rootIdentity'])]
        keys += ['parent:' + json.dumps(identity(e['parent'])) for e in self.session['entries']]
        keys += ['target:' + json.dumps(e['targetIdentity']) for e in self.session['entries']]
        self.lease = ResourceLease(keys)

    def _check_root(self):
        s = self.session
        root = self._root(s['root'] if s.get('customRoot') else None)
        if normalized(root) != normalized(s['root']) or identity(root) != s['rootIdentity']:
            raise ValueError('GIMI／Mods 根目录已更换；请恢复原路径后处理')

    @staticmethod
    def _chain(parent):
        paths = {normalized(p): p for base in [parent, parent.resolve(strict=True)]
                 for p in [base, *base.parents]}
        return [{'path': str(p), 'entry': identity(p, False), 'target': identity(p),
                 'resolved': normalized(p.resolve(strict=True)), 'link': is_link(p)}
                for p in paths.values()]

    @staticmethod
    def _check_chain(e):
        for p in e['chain']:
            path = Path(p['path'])
            if identity(path, False) != p['entry'] or identity(path) != p['target'] or normalized(path.resolve(strict=True)) != p['resolved']:
                raise ValueError(f'父目录或 Junction 目标已变化：{path}')

    @staticmethod
    def _check_entry(e, path):
        if identity(path, False) != e['identity'] or identity(path) != e['targetIdentity']:
            raise ValueError(f'入口或目标身份已变化：{path}')
        if e['link'] and normalized(path.resolve(strict=True)) != e['linkTarget']:
            raise ValueError(f'Junction 目标已变化：{path}')

    def _validate(self, e, path):
        self._check_root()
        self._check_chain(e)
        self._check_entry(e, path)

    @staticmethod
    def _cancel(worker):
        if worker and worker.cancel.is_set():
            raise ValueError('已取消，未提交新的排查结果')

    def _ini_records(self, path, worker, counter):
        records, stack, seen = [], [path], set()
        while stack:
            self._cancel(worker)
            current = stack.pop()
            key = tuple(identity(current))
            if current.is_dir():
                if key in seen:
                    raise ValueError(f'模组内部出现重复／循环目录：{current}')
                seen.add(key)
                for child in sorted(current.iterdir()):
                    counter[0] += 1
                    if counter[0] > MAX_ENTRIES:
                        raise ValueError('超过扫描条目上限，不能使用不完整的结果')
                    if is_link(child):
                        raise ValueError(f'模组内部含链接，需先核对加载边界：{child}')
                    if child.is_dir() or child.suffix.lower() == '.ini':
                        stack.append(child)
            elif current.suffix.lower() == '.ini':
                if current.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError(f'INI 超过 8 MiB，需手动核对：{current}')
                raw = current.read_bytes()
                rel = current.relative_to(path).as_posix() if path.is_dir() else '.'
                # Evidence inherits the browser resource's status; INI names do
                # not define a competing enable/disable model.
                records.append({'id': uuid.uuid4().hex, 'inside': rel, 'name': current.name,
                                'originalPath': str(current), 'targetPath': str(current.resolve(strict=True)),
                                'identity': identity(current), 'sha256': digest(raw), 'size': len(raw),
                                'initialEnabled': True, 'stateSource': 'resources.list', 'operations': []})
        return sorted(records, key=lambda r: r['inside'].casefold())

    def scan(self, params, worker=None):
        if self.active:
            raise ValueError('请先恢复或结束当前会话；扫描不会覆盖恢复依据')
        root = self._root(params.get('root'))
        if worker:
            worker.progress.emit({'progress': None, 'message': '正在记录已启用模组…'})
        lease = ResourceLease(['root:' + json.dumps(identity(root))])
        try:
            from resource_browser import ResourceService
            browser = ResourceService(self.directory.parent, self.config)
            browser.root = lambda: root
            s = {'schema': 2, 'mode': 'manual', 'sessionId': uuid.uuid4().hex, 'generation': 0, 'status': 'ready',
                 'root': str(root), 'customRoot': params.get('root') is not None,
                 'rootIdentity': identity(root), 'createdAt': time.time(),
                 'units': [], 'entries': [], 'inis': [], 'initialDisabled': [], 'errors': [],
                 'stateSource': 'resources.list', 'resourceSnapshot': [],
                 'warnings': ['分组仅控制已记录的模组，不移动文件夹，不判断游戏中的问题。'],
                 'history': [], 'nodes': [], 'transaction': None, 'events': [],
                 'message': '已记录初始启用模组；可独立启停每组，或继续二分。'}
            target_units, entry_keys = {}, {}
            stack, counter = [(root, set(), 0)], [0]
            while stack:
                self._cancel(worker)
                folder, ancestors, depth = stack.pop()
                if worker:
                    worker.progress.emit({'progress': None, 'message': f'正在记录 / 已发现 {len(s["units"])} 个启用模组'})
                if depth > 64:
                    s['errors'].append(f'目录层级过深：{folder}')
                    continue
                try:
                    key = tuple(identity(folder))
                    if key in ancestors:
                        raise ValueError(f'循环目录：{folder}')
                    children = sorted(folder.iterdir(), key=lambda p: p.name.casefold())
                    listing = browser.listing(folder.relative_to(root).as_posix(), worker=worker)
                    browser_items = {i['name']: i for i in listing['items']}
                    s['resourceSnapshot'].extend({k: item.get(k) for k in
                        ('name', 'relativePath', 'enabled', 'isMod', 'isDirectory', 'isLink', 'blockedReason')}
                        for item in listing['items'])
                except (OSError, ValueError) as exc:
                    s['errors'].append(str(exc))
                    continue
                for child in children:
                    self._cancel(worker)
                    counter[0] += 1
                    if counter[0] > MAX_ENTRIES:
                        raise ValueError('超过扫描条目上限，未生成可应用的会话')
                    try:
                        self._cancel(worker)
                        if child.name.startswith(('.omg-move-', '.omg-recovery-')):
                            continue
                        item = browser_items.get(child.name)
                        if item is None:
                            if child.is_dir() or child.suffix.lower() == '.ini':
                                s['errors'].append(f'资源浏览页未返回该条目，不能记录为已启用：{child}')
                            continue
                        if item.get('blockedReason'):
                            raise ValueError(item['blockedReason'])
                        if item['enabled'] is not True:
                            s['initialDisabled'].append(str(child))
                            continue
                        supported(child)
                        if child.is_dir() and not item['isMod']:
                            stack.append((child, ancestors | {key}, depth + 1))
                            continue
                        if not child.is_dir() and child.suffix.lower() != '.ini':
                            continue
                        if child.name.lower() in CONTROL_NAMES:
                            s['warnings'].append(f'加载控制配置不参与二分：{child}')
                            continue
                        entry_key = (tuple(identity(child.parent)), child.name.casefold())
                        if entry_key in entry_keys:
                            s['entries'][entry_keys[entry_key]]['aliases'].append(str(child))
                            continue
                        try:
                            records = self._ini_records(child, worker, counter)
                        except (OSError, ValueError, RuntimeError) as exc:
                            self._cancel(worker)
                            records = []
                            s['warnings'].append(f'INI 明细不完整，模组仍按资源浏览页状态记录：{child} / {exc}')
                        if not records:
                            s['warnings'].append(f'无 INI，仍按资源浏览页的模组状态参与分组：{child}')
                        target_key = tuple(identity(child))
                        unit = target_units.get(target_key)
                        if unit is None:
                            unit = {'id': uuid.uuid4().hex, 'name': child.name, 'entryIds': [], 'iniIds': [],
                                    'members': [child.name], 'external': False}
                            target_units[target_key] = unit
                            s['units'].append(unit)
                        e = {'id': uuid.uuid4().hex, 'unitId': unit['id'], 'parent': str(child.parent),
                             'initialName': child.name, 'currentName': child.name, 'disabledName': 'DISABLED ' + child.name,
                             'identity': identity(child, False), 'targetIdentity': identity(child),
                             'link': is_link(child), 'linkTarget': normalized(child.resolve()) if is_link(child) else None,
                             'chain': self._chain(child.parent), 'aliases': [str(child)],
                             'relative': child.relative_to(root).as_posix(), 'originalTarget': str(child.resolve()), 'enabled': True}
                        entry_keys[entry_key] = len(s['entries'])
                        if os.path.lexists(child.parent / e['disabledName']):
                            s['errors'].append(f'停用目标已存在，不能安全启停：{child.parent / e["disabledName"]}')
                        s['entries'].append(e)
                        unit['entryIds'].append(e['id'])
                        unit['external'] |= not Path(child.resolve()).is_relative_to(root.resolve())
                        for r in records:
                            r.update(unitId=unit['id'], entryId=e['id'], modName=child.name, resourceRelative=e['relative'])
                            unit['iniIds'].append(r['id'])
                            s['inis'].append(r)
                    except (OSError, ValueError, RuntimeError) as exc:
                        s['errors'].append(f'{child}：{exc}')
            self._cancel(worker)
            if not s['units']:
                s['errors'].append('未找到可参与排查的已启用模组')
            self.close()
            self.session, self.lease, lease = s, lease, None
            ids = [u['id'] for u in s['units']]
            s['nodes'] = [{'id': 'root', 'label': '已记录模组', 'parent': None,
                           'unitIds': ids, 'children': []}]
            if len(ids) > 1:
                self._split_node(s['nodes'][0])
            if not s['errors']:
                self.close()
                self._acquire()
                self._check_root()
            self._save()
            if worker:
                worker.progress.emit({'progress': 1., 'message': f'记录完成 / {len(s["units"])} 个启用模组'})
            return self.state()
        finally:
            if lease:
                lease.close()

    def _locate(self, e):
        self._check_chain(e)
        parent = Path(e['parent'])
        original, disabled = parent / e['initialName'], parent / e['disabledName']
        a, b = os.path.lexists(original), os.path.lexists(disabled)
        if a == b:
            raise ValueError(f'恢复冲突：原名和停用名{"同时存在" if a else "均不存在"}，未覆盖或删除：{original}')
        p = original if a else disabled
        self._check_entry(e, p)
        return p, a

    def _transaction(self, enabled, worker=None):
        s = self.session
        if worker:
            worker.progress.emit({'progress': None, 'message': '正在核对模组启停状态…'})
        self._acquire()
        self._check_root()
        expected, operations = set(enabled), []
        for e in s['entries']:
            self._cancel(worker)
            p, actual = self._locate(e)
            e['currentName'], e['enabled'] = p.name, actual
            wanted = e['unitId'] in expected
            name = e['initialName'] if wanted else e['disabledName']
            if actual != wanted:
                operations.append({'entryId': e['id'], 'from': p.name, 'to': name, 'stage': 'pending'})
        tx = {'id': uuid.uuid4().hex, 'operations': operations, 'stage': 'applying', 'createdAt': time.time()}
        s['transaction'], s['status'] = tx, 'applying'
        s.setdefault('transactions', []).append(tx)
        self._save()
        entries = {e['id']: e for e in s['entries']}
        try:
            for index, op in enumerate(operations):
                self._cancel(worker)
                e = entries[op['entryId']]
                source, target = Path(e['parent']) / op['from'], Path(e['parent']) / op['to']
                op['stage'] = 'intent'
                self._save()
                rename_exact(source, target, lambda e=e, p=source: self._validate(e, p))
                self._check_entry(e, target)
                if os.path.lexists(source):
                    raise ValueError(f'改名核验失败：{source}')
                e['currentName'], e['enabled'] = target.name, e['unitId'] in expected
                op['stage'] = 'verified'
                self._save()
                if worker:
                    worker.progress.emit({'progress': (index + 1) / (len(operations) + 1),
                                          'message': f'正在切换启停 / {index + 1} / {len(operations)}'})
            for e in s['entries']:
                p, actual = self._locate(e)
                if actual != (e['unitId'] in expected):
                    raise ValueError(f'最终方案核验不一致：{p}')
            tx['stage'] = 'committed'
            s['appliedEnabled'] = sorted(expected)
            self._save()
            if worker:
                worker.progress.emit({'progress': 1., 'message': '模组启停状态已核验'})
        except Exception as exc:
            if worker:
                worker.progress.emit({'progress': None, 'message': '切换未完成，正在回退…'})
            failures = []
            for op in reversed(operations):
                if op['stage'] == 'pending':
                    continue
                e = entries[op['entryId']]
                try:
                    p, actual = self._locate(e)
                    if p.name != op['from']:
                        dest = p.parent / op['from']
                        rename_exact(p, dest, lambda e=e, p=p: self._validate(e, p))
                        self._check_entry(e, dest)
                    e['currentName'], e['enabled'] = op['from'], op['from'] == e['initialName']
                    op['stage'] = 'rolled_back'
                except Exception as rollback:
                    failures.append(str(rollback))
            tx['stage'] = 'conflict' if failures else 'rolled_back'
            s['status'] = 'recovery'
            s['message'] = str(exc) + ('；回退未完成：' + '；'.join(failures) if failures else '；已回退本批，需核对恢复')
            try:
                self._save()
            except OSError:
                pass
            raise ValueError(s['message']) from exc

    def _split_node(self, node):
        if node['children']:
            return
        ids = node['unitIds']
        if len(ids) < 2:
            raise ValueError('组内不足两个模组，无法继续二分')
        mid = (len(ids) + 1) // 2
        for i, members in enumerate((ids[:mid], ids[mid:])):
            label = ('A', 'B')[i] if node['id'] == 'root' else node['label'] + str(i + 1)
            child = {'id': node['id'] + '.' + str(i + 1), 'label': label,
                     'parent': node['id'], 'unitIds': members[:], 'children': []}
            self.session['nodes'].append(child)
            node['children'].append(child['id'])

    def split(self, params):
        s = self._require(params, {'ready'})
        node = self._group(params.get('groupId'))
        if node['children']:
            return self.state()
        self._split_node(node)
        s['generation'] += 1
        s['events'].append({'type': 'split', 'groupId': node['id'], 'time': time.time()})
        s['message'] = f'{node["label"]} 组已分成两组；启停状态保持不变。'
        self._save()
        return self.state()

    def split_leaves(self, params):
        s = self._require(params, {'ready'})
        leaves = [n for n in s['nodes'] if not n['children'] and len(n['unitIds']) > 1]
        if not leaves:
            raise ValueError('所有末级组均无法继续二分')
        for node in leaves:
            self._split_node(node)
        s['generation'] += 1
        s['events'].append({'type': 'splitLeaves', 'groups': [n['id'] for n in leaves], 'time': time.time()})
        s['message'] = '所有可拆分的末级组已各分成两组；启停状态保持不变。'
        self._save()
        return self.state()

    def _group(self, group_id):
        node = next((n for n in self.session.get('nodes', []) if n['id'] == group_id), None)
        if node is None or 'unitIds' not in node:
            raise ValueError('分组不存在或属于旧版引导流程，请恢复后重新记录')
        return node

    def _sync_entries(self):
        self._check_root()
        for e in self.session['entries']:
            path, enabled = self._locate(e)
            e['currentName'], e['enabled'] = path.name, enabled

    def _enabled_units(self):
        groups = {}
        for e in self.session['entries']:
            groups.setdefault(e['unitId'], []).append(e['enabled'])
        if any(any(v) != all(v) for v in groups.values()):
            raise ValueError('同一模组的多个入口启停不一致，请先恢复初始状态')
        return {u for u, states in groups.items() if all(states)}

    def _record_operation(self, action, group_id, before, after, **extra):
        s = self.session
        record = {'id': uuid.uuid4().hex, 'type': action, 'groupId': group_id,
                  'beforeEnabled': sorted(before), 'afterEnabled': sorted(after),
                  'time': time.time(), **extra}
        s['history'].append(record)
        locations = {i['id']: i for i in self.state()['inis']}
        for ini in s['inis']:
            if (ini['unitId'] in before) != (ini['unitId'] in after):
                ini.setdefault('operations', []).append({
                    'operationId': record['id'], 'type': action, 'groupId': group_id,
                    'resourceEnabled': ini['unitId'] in after, 'time': record['time'],
                    'logicalPath': locations[ini['id']]['currentPath'],
                    'targetPath': locations[ini['id']]['currentTargetPath']})
        s['generation'] += 1
        s['status'] = 'ready'
        self._save()
        return record

    def toggle(self, params, worker=None):
        s = self._require(params, {'ready'})
        if s['errors']:
            raise ValueError('初始记录有异常，请处理后重新记录；未执行启停')
        node = self._group(params.get('groupId'))
        enabled = params.get('enabled')
        if type(enabled) is not bool:
            raise ValueError('enabled 必须为布尔值')
        self._sync_entries()
        before = self._enabled_units()
        affected = set(node['unitIds'])
        after = before | affected if enabled else before - affected
        s['pendingAction'] = {'type': 'toggle', 'groupId': node['id'], 'enabled': enabled}
        self._transaction(after, worker)
        s['message'] = f'{node["label"]} 组已{"启用" if enabled else "停用"}；其他分组保持原状。'
        self._record_operation('enable' if enabled else 'disable', node['id'], before, after)
        s.pop('pendingAction', None)
        self._save()
        return self.state()

    def refresh(self, params):
        s = self._require(params, {'ready'})
        self._sync_entries()
        s['generation'] += 1
        s['message'] = '已刷新实际启停状态；初始快照与分组结构保持不变。'
        self._save()
        return self.state()

    def resume(self, params):
        s = self._require(params, {'recovery'})
        if s.get('mode') != 'manual':
            raise ValueError('旧版引导流程只能恢复初始状态后重新记录')
        self._acquire()
        self._sync_entries()
        s['generation'] += 1
        s['status'] = 'ready'
        s['message'] = '已核对磁盘状态，可继续独立启停和拆分。'
        s.pop('pendingAction', None)
        self._save()
        return self.state()

    def undo(self, params, worker=None):
        s = self._require(params, {'ready'})
        record = next((r for r in reversed(s['history']) if r.get('type') in ('enable', 'disable') and not r.get('undone')), None)
        if record is None:
            raise ValueError('没有可撤销的启停操作')
        self._sync_entries()
        before = self._enabled_units()
        if before != set(record['afterEnabled']):
            raise ValueError('启停状态已被外部改变，不能自动撤销；可刷新后手动控制分组')
        after = set(record['beforeEnabled'])
        self._transaction(after, worker)
        record['undone'] = True
        s['message'] = '已撤销上次启停；分组结构保持不变。'
        self._record_operation('undo', record['groupId'], before, after, reverses=record['id'])
        return self.state()

    def restore(self, params, worker=None):
        s = self._require(params)
        if s['status'] in CLOSED:
            return self.state()
        # Restore only owned names, never old INI contents. Schema 1 sessions
        # remain recoverable without reviving their old question/answer flow.
        if not s.get('transactions') and not s.get('transaction'):
            s.update(status='closed', message='已结束记录；未发生启停改名。')
        else:
            self._transaction([u['id'] for u in s['units']], worker)
            s.update(status='closed', message='已恢复本次记录的初始启用状态；INI 内容未覆盖。')
        s['generation'] += 1
        self._save()
        self.close()
        self.export()
        return self.state()

    def finish(self, params):
        s = self._require(params, {'ready'})
        self._sync_entries()
        s.update(status='closed', message='已结束记录并保留当前启停状态。')
        s['generation'] += 1
        self._save()
        self.close()
        self.export()
        return self.state()

    def export(self):
        if not self.session or self.load_error:
            raise ValueError('没有可导出的有效记录')
        report = copy.deepcopy(self.session)
        path = self.directory / (self.session['sessionId'] + '-report.json')
        atomic(path, json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8'))
        atomic(self.directory / 'report.json', path.read_bytes())
        return {'path': str(path), 'message': '已导出初始快照、分组树、启停操作和 INI 明细'}

    def dispatch(self, action, params, worker=None):
        if action == 'state':
            return self.state()
        if action == 'scan':
            return self.scan(params, worker)
        if action == 'export':
            return self.export()
        functions = {'split': self.split, 'splitLeaves': self.split_leaves, 'toggle': lambda p: self.toggle(p, worker),
                     'refresh': self.refresh, 'resume': self.resume,
                     'undo': lambda p: self.undo(p, worker), 'restore': lambda p: self.restore(p, worker),
                     'finish': self.finish}
        if action not in functions:
            raise ValueError('未知分组操作')
        return functions[action](params)
