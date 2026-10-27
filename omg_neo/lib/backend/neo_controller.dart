import 'dart:async';
import 'package:flutter/foundation.dart';
import '../update_preview.dart';
import 'neo_backend.dart';
import 'log_buffer.dart';

class NeoController extends ChangeNotifier {
  NeoController(this.backend) {
    update.onAction = updateAction;
    update.enabled = false;
  }
  final NeoBackend backend;
  final update = UpdatePreviewController();
  StreamSubscription<Map<String, dynamic>>? _subscription;
  Map<String, dynamic> settings = {}, versions = {};
  Map<String, dynamic> buildState = {}, resources = {}, cleanup = {};
  Map<String, dynamic> bisectState = {};
  bool bisectActive = false;
  final _buildLogs = LogBuffer()..add('终端已就绪。');
  List<String> get buildLogs => _buildLogs.lines;
  int buildLogRevision = 0;
  final _writebackLogs = LogBuffer();
  List<String> get writebackLogs => _writebackLogs.lines;
  String taskKind = '', noticeKind = '';
  Map<String, dynamic> resourceView = {};
  bool resourcesLoaded = false;
  double? taskProgress;
  int resourceEpoch = 0;
  Completer<List<Map<String, dynamic>>>? _keysRequest;
  Map<String, dynamic> _pending = {};
  final _finished = <String>{};
  @visibleForTesting
  int get retainedCompletionCount => _finished.length;
  Timer? _debounce, _maxDelay;
  Future<void> _saving = Future.value();
  Future<void>? _starting, _closeFuture, _reconnecting;
  bool _disconnected = false, _disposed = false;
  bool get canReconnect =>
      _disconnected &&
      !ready &&
      !busy &&
      !closing &&
      backend is RecoverableNeoBackend;

  Future<void> reconnect() =>
      _reconnecting ??= _reconnect().whenComplete(() => _reconnecting = null);

  Future<void> _reconnect() async {
    if (!canReconnect) return;
    busy = true;
    error = null;
    status = '正在重新连接…';
    noticeKind = 'resources.reconnect';
    notifyListeners();
    try {
      _subscription ??= backend.events.listen(_event);
      await (backend as RecoverableNeoBackend).restart();
      _snapshot(Map<String, dynamic>.from(
          (await backend.call('hello', {'protocol': 1}))['snapshot']));
      if (bisectActive) bisectState = await backend.call('bisect.state');
      // Reconcile queued settings against the new process's current revision.
      ready = true;
      await save();
      _disconnected = false;
      settingsEpoch++;
      status = error ?? '已重新连接';
    } catch (exception) {
      ready = false;
      fail(exception);
    } finally {
      busy = false;
      update.enabled = ready && !closing;
      notifyListeners();
    }
  }

  bool ready = false, saving = false, busy = false, closing = false;
  String? error, taskId;
  String status = '正在连接后端…', launchState = 'idle', launchDetail = '';
  int revision = 0, settingsEpoch = 0, cacheBytes = 0;
  bool get launchEnabled =>
      ready &&
      !busy &&
      !['done', 'unverified'].contains(launchState) &&
      !closing;

  Future<void> start() => _starting ??= _start();

  Future<void> _start() async {
    try {
      await backend.start();
      _subscription = backend.events.listen(_event);
      final hello = await backend.call('hello', {'protocol': 1});
      _snapshot(Map<String, dynamic>.from(hello['snapshot']));
      ready = true;
      settingsEpoch++;
      status = bisectActive
          ? '存在未结束的二分排查，请进入工具核对恢复'
          : settings['gimi_folder'] == ''
              ? '请配置游戏与 GIMI 目录'
              : '配置已加载';
      update.enabled = !closing;
      notifyListeners();
      if (closing) return;
      await refreshCache();
      // BuildConsole loads its own state when opened. Probing native build
      // capabilities here keeps the entire toolchain resident on the home page.
      if (settings['auto_check_update'] == true) await check(auto: true);
    } catch (exception) {
      if (!ready) _disconnected = true;
      fail(exception);
    }
  }

  void _snapshot(Map<String, dynamic> snapshot) {
    final previousGimi = settings['gimi_folder'];
    settings = Map<String, dynamic>.from(snapshot['settings'] as Map);
    if (previousGimi != settings['gimi_folder']) {
      resources = {};
      resourcesLoaded = false;
      resourceEpoch++;
      update.live(active: false, syncing: false, ready: false);
    }
    versions = Map<String, dynamic>.from(snapshot['versions'] as Map);
    revision = snapshot['revision'] as int;
    bisectActive = snapshot['bisectActive'] == true;
    launchState = snapshot['launchState'] as String? ?? launchState;
    launchDetail = snapshot['launchDetail'] as String? ?? launchDetail;
  }

  void _event(Map<String, dynamic> event) {
    // Do not rebuild resource/build pages for results arriving during exit.
    if (closing &&
        event['event'] != 'backend.failed' &&
        event['event'] != 'cache.progress') {
      return;
    }
    final data = Map<String, dynamic>.from(event['data'] as Map);
    switch (event['event']) {
      case 'cache.progress':
        cacheCleaning = true;
        cacheProgress = (data['progress'] as num?)?.toDouble();
        cacheMessage = data['message'] as String? ?? '';
      case 'config.changed':
        _snapshot(data);
      case 'launch.state':
        launchState = data['state'] as String;
        launchDetail = data['message'] as String;
        status = launchDetail;
      case 'settings.ini':
        status = data['message'] as String? ?? status;
        if (data['status'] == 'error') error = '配置已保存，INI 同步失败：$status';
      case 'task.progress':
        if (data['taskId'] != null &&
            (!busy || (taskId != null && taskId != data['taskId']))) {
          break;
        }
        if (data['message'] != null) status = data['message'] as String;
        taskProgress = (data['progress'] as num?)?.toDouble();
        if (taskKind.startsWith('build.')) {
          if (data['message'] != null) _buildLog(status);
          break;
        }
        if (taskKind.startsWith('bisect.') ||
            taskKind.startsWith('resources.') ||
            taskKind.startsWith('serverSwitch.') ||
            taskKind == 'cache.clear') {
          break;
        }
        update.live(
            active: true,
            syncing: update.syncing == true,
            ready: update.ready,
            progress: (data['progress'] as num?)?.toDouble(),
            message: status);
      case 'task.finished':
        final completedId = data['taskId'] as String;
        if ((taskId != null && taskId != completedId) ||
            (busy && taskKind.isNotEmpty && data['kind'] != taskKind)) {
          break;
        }
        // Only retain a completion until its accepted reply has been consumed.
        if (taskId != completedId) {
          _finished.add(completedId);
          if (_finished.length > 64) _finished.remove(_finished.first);
        }
        taskId = null;
        busy = false;
        status = data['message'] as String;
        if (data['snapshot'] != null) {
          _snapshot(Map<String, dynamic>.from(data['snapshot']));
        }
        final result = Map<String, dynamic>.from(data['result'] as Map? ?? {});
        if (data['kind'] == 'resources.keys' && _keysRequest != null) {
          final waiter = _keysRequest!;
          _keysRequest = null;
          if (data['state'] == 'succeeded') {
            waiter.complete((result['resourceKeys']?['keys'] as List? ?? [])
                .map((key) => Map<String, dynamic>.from(key as Map))
                .toList());
          } else {
            waiter.completeError(StateError(status));
          }
        }
        if (data['kind'] == 'cache.clear') {
          cacheBytes = result['bytes'] as int? ?? cacheBytes;
          cacheMessage = status;
          cacheProgress = data['state'] == 'succeeded' ? 1 : null;
          if ((result['errors'] as List? ?? []).isNotEmpty) error = status;
        }
        if (result['bisect'] != null) {
          bisectState = Map<String, dynamic>.from(result['bisect']);
          bisectActive = !['idle', 'closed'].contains(bisectState['status']);
          resourcesLoaded = false;
          resourceEpoch++;
        }
        if (result['build'] != null) {
          buildState = Map<String, dynamic>.from(result['build']);
        }
        if (result['cleanup'] != null) {
          cleanup = Map<String, dynamic>.from(result['cleanup']);
        }
        if (result['resources'] != null) {
          resources = Map<String, dynamic>.from(result['resources']);
          resourcesLoaded = true;
          resourceEpoch++;
          status = resources['message'] as String? ?? status;
        }
        if (data['kind'] == 'resources.writeback') {
          _writebackLogs
            ..clear()
            ..addAll((result['logs'] as List? ?? []).cast<String>())
            ..add(status);
          if (result['partial'] == true || result['ok'] == false) {
            error = status;
          }
          resourcesLoaded = false;
        }
        if ('${data['kind']}'.startsWith('build.')) {
          _buildLog(status);
          for (final line in result['errors'] as List? ?? []) {
            _buildLog('$line');
          }
        }
        if (data['state'] == 'failed') error = status;
        if (data['state'] == 'succeeded') {
          status = switch (data['kind']) {
            'build.ritual' => '执行完毕',
            'build.copy' => '复制完毕',
            'build.compile' => '构建完毕',
            _ => status,
          };
        }
        if (data['kind'] == 'check' || data['kind'] == 'update') {
          final available =
              data['kind'] == 'check' && data['state'] == 'succeeded'
                  ? result['available'] == true
                  : data['kind'] == 'update' && data['state'] == 'succeeded'
                      ? false
                      : update.ready;
          update.live(
              active: false, syncing: false, ready: available, message: status);
        }
        taskKind = '';
        taskProgress = null;
        if (ready &&
            !closing &&
            data['kind'] != 'cache.clear' &&
            (data['kind'] == 'update' ||
                data['kind'] == 'launch' ||
                '${data['kind']}'.startsWith('serverSwitch.') ||
                '${data['kind']}'.startsWith('build.') ||
                data['kind'] == 'resources.writeback')) {
          unawaited(refreshCache());
        }
      case 'backend.failed':
        _disconnected = true;
        _keysRequest?.completeError(StateError('${data['message']}'));
        _keysRequest = null;
        ready = false;
        busy = false;
        taskId = null;
        taskKind = '';
        taskProgress = null;
        fail(data['message']);
        update.enabled = false;
        update.live(
            active: false, syncing: false, ready: false, message: error);
    }
    update.enabled = ready && !closing && (!busy || update.active);
    notifyListeners();
  }

  void fail(Object? exception) {
    error = neoErrorMessage(exception);
    status = error!;
    notifyListeners();
  }

  void _buildLog(String line) {
    buildLogRevision++;
    _buildLogs.add(line);
  }

  Future<void> loadBisect() async {
    if (!ready || busy) return;
    try {
      bisectState = await backend.call('bisect.state');
      bisectActive = !['idle', 'closed'].contains(bisectState['status']);
      notifyListeners();
    } catch (exception) {
      fail(exception);
    }
  }

  Future<void> loadBuild() async {
    if (!ready) return;
    try {
      buildState = await backend.call('build.get');
      notifyListeners();
    } catch (exception) {
      fail(exception);
    }
  }

  Future<void> selectBuild(Map<String, dynamic> patch) async {
    if (!ready || busy) return;
    try {
      buildState = await backend.call('build.select', {'patch': patch});
      notifyListeners();
    } catch (exception) {
      fail(exception);
    }
  }

  Future<void> businessTask(String method,
      [Map<String, dynamic> params = const {}]) async {
    if (!ready || busy || closing) return;
    busy = true;
    taskKind = method;
    noticeKind = method;
    taskProgress = null;
    error = null;
    update.enabled = false;
    status = method == 'serverSwitch.import' ? '识别中…' : '正在执行…';
    if (method.startsWith('build.')) _buildLog('> $method');
    notifyListeners();
    try {
      // Recovery must remain available even when an unrelated settings draft
      // was rejected while scanning. The backend owns the frozen config.
      if (!(method.startsWith('bisect.') && bisectActive)) await flush();
      final result = await backend.call(method, params);
      if (!_finished.remove(result['taskId'])) {
        taskId = result['taskId'] as String;
      }
    } catch (exception) {
      if (method.startsWith('build.')) _buildLog('$exception');
      busy = false;
      taskKind = '';
      fail(exception);
    }
    update.enabled = ready && !busy;
    notifyListeners();
  }

  Future<void> browseResources(
      [String path = '', Map<String, dynamic> options = const {}]) {
    resourceView = {'path': path, ...options};
    return businessTask('resources.list', resourceView);
  }

  Future<Map<String, dynamic>> resourceCall(
          String method, Map<String, dynamic> params) =>
      backend.call(method, params);

  Future<List<Map<String, dynamic>>> resourceKeys(
      String id, int revision) async {
    if (!ready || busy || closing) throw StateError('请等待当前任务完成');
    final waiter = Completer<List<Map<String, dynamic>>>();
    _keysRequest = waiter;
    // Attach the error handler before accepting a task: a very small INI may
    // finish before the accepted reply arrives over the pipe.
    final result = waiter.future;
    unawaited(() async {
      await businessTask('resources.keys', {'id': id, 'revision': revision});
      if (!busy && identical(_keysRequest, waiter)) {
        _keysRequest = null;
        waiter.completeError(StateError(error ?? '切换键读取失败'));
      }
    }());
    return result;
  }

  Future<void> cancelTask() async {
    if (taskId == null) return;
    try {
      await backend.call('tasks.cancel', {'taskId': taskId});
      status = '正在取消；不可中断的阶段将等待收尾，后续步骤不再执行';
      if (taskKind.startsWith('build.')) _buildLog(status);
      notifyListeners();
    } catch (exception) {
      fail(exception);
    }
  }

  void stage(Map<String, dynamic> patch) {
    if (closing) return;
    if (bisectActive) {
      const appearance = {'theme', 'accent_color'};
      bool same(Object? a, Object? b) =>
          a is List && b is List ? listEquals(a, b) : a == b;
      if (patch.entries.any((e) =>
          !appearance.contains(e.key) && !same(settings[e.key], e.value))) {
        fail(StateError('二分排查期间不能修改业务设置，请先恢复或结束会话'));
        return;
      }
      patch = Map.fromEntries(
          patch.entries.where((e) => appearance.contains(e.key)));
      if (patch.isEmpty) return;
    }
    noticeKind = 'settings';
    _pending.addAll(patch);
    saving = true;
    error = null;
    status = '等待保存…';
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 400), save);
    _maxDelay ??= Timer(const Duration(milliseconds: 1500), save);
    notifyListeners();
  }

  Future<void> save() {
    _debounce?.cancel();
    _maxDelay?.cancel();
    _maxDelay = null;
    _saving = _saving.then((_) async {
      if (_pending.isEmpty) return;
      final patch = Map<String, dynamic>.from(_pending);
      _pending.clear();
      try {
        final snapshot = await backend
            .call('config.patch', {'patch': patch, 'revision': revision});
        _snapshot(snapshot);
        status = '已保存';
        error = null;
      } catch (exception) {
        _pending = {...patch, ..._pending};
        fail(exception);
      }
      saving = _pending.isNotEmpty;
      notifyListeners();
    });
    return _saving;
  }

  Future<void> flush() async {
    await save();
    if (_pending.isNotEmpty) throw StateError(error ?? '设置未保存');
    await backend.call('settings.flush');
  }

  Future<void> importLite(String path) async {
    try {
      await flush();
      _snapshot(await backend.call('config.importLite', {'path': path}));
      settingsEpoch++;
      update.live(active: false, syncing: false, ready: false);
      error = null;
      status = '已导入 OMGLite 配置';
      notifyListeners();
    } catch (exception) {
      fail(exception);
    }
  }

  Future<void> _task(String method,
      [Map<String, dynamic> params = const {}]) async {
    if (!ready || busy || closing) return;
    busy = true;
    noticeKind = method;
    notifyListeners();
    try {
      await flush();
      error = null;
      status = method == 'launch.start' ? '正在准备启动…' : '正在连接…';
      update.enabled = method != 'launch.start';
      if (method != 'launch.start' && !method.startsWith('serverSwitch.')) {
        update.live(
            active: true,
            syncing: method == 'updates.apply',
            ready: update.ready);
      }
      notifyListeners();
      final result = await backend.call(method, params);
      if (result['throttled'] == true) {
        busy = false;
        update.live(active: false, syncing: false, ready: update.ready);
      } else if (!_finished.remove(result['taskId'])) {
        taskId = result['taskId'] as String;
      }
    } catch (exception) {
      busy = false;
      update.live(active: false, syncing: false, ready: update.ready);
      fail(exception);
    }
    update.enabled = ready && (!busy || update.active);
    notifyListeners();
  }

  Future<void> check({bool auto = false}) =>
      _task('updates.check', {'auto': auto});
  Future<void> backupServer(
          String channel, String source, String destination) =>
      businessTask('serverSwitch.backup',
          {'channel': channel, 'source': source, 'destination': destination});
  Future<void> switchServer(String target) =>
      businessTask('serverSwitch.apply', {'target': target});
  Future<void> restoreServer() => businessTask('serverSwitch.restore');
  Future<void> launch() => _task('launch.start');
  Future<void> updateAction() async {
    if (busy) {
      if (taskId != null && update.active) {
        try {
          await backend.call('tasks.cancel', {'taskId': taskId});
          status = '正在取消并等待任务收尾…';
          update.live(
              active: true,
              syncing: update.syncing == true,
              ready: update.ready,
              message: status);
          notifyListeners();
        } catch (exception) {
          fail(exception);
        }
      }
    } else {
      await _task(update.ready ? 'updates.apply' : 'updates.check');
    }
  }

  bool cacheCleaning = false;
  double? cacheProgress;
  String cacheMessage = '';

  Future<void> refreshCache({bool clear = false}) async {
    if (clear) {
      if (!ready || busy || closing) return;
      cacheMessage = '正在统计缓存与备份…';
      await businessTask('cache.clear');
      return;
    }
    if (!ready || busy || closing || _disposed) return;
    try {
      final result = await backend.call('cache.info');
      if (_disposed || closing) return;
      cacheBytes = result['bytes'] as int;
      notifyListeners();
    } catch (exception) {
      if (!_disposed && !closing) fail(exception);
    }
  }

  Future<void> close() => _closeFuture ??= _close();

  Future<void> _close() async {
    closing = true;
    final transport =
        backend is QuiescentNeoBackend ? backend as QuiescentNeoBackend : null;
    transport?.setClosing(true);
    _keysRequest?.completeError(StateError('应用正在关闭'));
    _keysRequest = null;
    status = '正在收尾，请稍候…';
    update.enabled = false;
    notifyListeners();
    try {
      // A close during startup must still wait for the owned process to exist.
      await _starting;
      if (ready) await flush();
      await backend.close();
      await _subscription?.cancel();
    } catch (exception) {
      closing = false;
      transport?.setClosing(false);
      _closeFuture = null;
      update.enabled = ready && (!busy || update.active);
      fail(exception);
      rethrow;
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _debounce?.cancel();
    _maxDelay?.cancel();
    _subscription?.cancel();
    update.dispose();
    super.dispose();
  }
}
