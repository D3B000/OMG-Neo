import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:isolate';

String neoErrorMessage(Object? error) =>
    '$error'.replaceFirst(RegExp(r'^(?:Bad state:\s*)+'), '');

abstract class NeoBackend {
  Stream<Map<String, dynamic>> get events;
  Future<void> start();
  Future<Map<String, dynamic>> call(String method,
      [Map<String, dynamic> params = const {}]);
  Future<void> close();
}

/// Quiesce unsolicited business events while persistence and shutdown finish.
abstract interface class QuiescentNeoBackend {
  void setClosing(bool closing);
}

abstract interface class RecoverableNeoBackend {
  Future<void> restart();
}

/// Application-owned data travels with the release directory. Explicit roots
/// remain available for isolated tests and deliberate user overrides.
String neoDataRoot(String applicationRoot,
    {String? override, Map<String, String> environment = const {}}) {
  return Directory(override ??
          environment['OMGNEO_DATA_ROOT'] ??
          '$applicationRoot/AppData')
      .absolute
      .path;
}

/// Shared by appearance preloading and process startup to select the same data.
Future<({File entrypoint, bool frozen, String dataRoot})>
    resolveNeoBackendLaunch({String? executable, String? dataRoot}) async {
  final executableRoot = File(Platform.resolvedExecutable).parent;
  final frozen =
      File(executable ?? '${executableRoot.path}/backend/omg_backend.exe');
  if (executable != null && !await frozen.exists()) {
    throw StateError('指定的后端不存在：$executable');
  }
  if (await frozen.exists()) {
    return (
      entrypoint: frozen.absolute,
      frozen: true,
      dataRoot: neoDataRoot(frozen.absolute.parent.parent.path,
          override: dataRoot, environment: Platform.environment)
    );
  }
  for (var current in [Directory.current, executableRoot]) {
    for (int depth = 0; depth < 9; depth++) {
      final source = File('${current.path}/backend/main.py');
      if (await source.exists()) {
        return (
          entrypoint: source.absolute,
          frozen: false,
          dataRoot: neoDataRoot(
              '${source.parent.parent.path}/omg_neo/dist/OMG-Neo',
              override: dataRoot,
              environment: Platform.environment)
        );
      }
      if (current.parent.path == current.path) break;
      current = current.parent;
    }
  }
  throw StateError('未找到 backend/omg_backend.exe，请完整分发后端目录。');
}

/// The process, pipe reads and JSON decoding live outside Flutter's UI isolate.
class ProcessNeoBackend
    implements NeoBackend, QuiescentNeoBackend, RecoverableNeoBackend {
  ProcessNeoBackend({this.executable, this.dataRoot});
  final String? executable, dataRoot;
  Future<String> resolveDataRoot() async => (await resolveNeoBackendLaunch(
          executable: executable, dataRoot: dataRoot))
      .dataRoot;
  final _events = StreamController<Map<String, dynamic>>.broadcast();
  final _pending = <int, Completer<Object?>>{};
  final _ready = Completer<SendPort>();
  ReceivePort? _messages;
  SendPort? _port;
  Object? _failure;
  Future<void>? _startFuture, _closeFuture;
  int _nextId = 0;
  bool _quiet = false, _closed = false;

  @override
  Stream<Map<String, dynamic>> get events => _events.stream;

  @override
  Future<void> start() => _startFuture ??= _start();

  Future<void> _start() async {
    _messages = ReceivePort();
    _messages!.listen((message) {
      if (message is List && message.isNotEmpty) {
        switch (message[0]) {
          case 'ready':
            _port = message[1] as SendPort;
            _port!.send(['quiet', _quiet]);
            _ready.complete(_port);
            return;
          case 'event':
            if (!_closed &&
                (!_quiet || (message[1] as Map)['event'] == 'cache.progress')) {
              _events.add(Map<String, dynamic>.from(message[1] as Map));
            }
            return;
          case 'reply':
            final pending = _pending.remove(message[1]);
            if (message[2] == null) {
              pending?.complete(message[3]);
            } else {
              pending?.completeError(StateError(message[2] as String));
            }
            return;
        }
      }
      if (_closed) return;
      final error = StateError('后端通信线程已退出：${message ?? "连接中断"}');
      _failure = error;
      if (!_ready.isCompleted) _ready.completeError(error);
      for (final pending in _pending.values) {
        pending.completeError(error);
      }
      _pending.clear();
      _events.add({
        'event': 'backend.failed',
        'data': {'message': '$error'}
      });
    });
    try {
      await Isolate.spawn(
          _processWorker, [_messages!.sendPort, executable, dataRoot],
          onError: _messages!.sendPort, onExit: _messages!.sendPort);
    } catch (error) {
      _failure = error;
      _messages!.close();
      rethrow;
    }
    await _request('start');
  }

  Future<Object?> _request(String method,
      [Map<String, dynamic> params = const {}]) async {
    if (_failure != null) throw _failure!;
    if (_closed) throw StateError('后端已关闭');
    final port = await _ready.future;
    if (_failure != null) throw _failure!;
    final id = ++_nextId;
    final pending = Completer<Object?>();
    _pending[id] = pending;
    port.send([id, method, params]);
    return pending.future;
  }

  @override
  Future<Map<String, dynamic>> call(String method,
          [Map<String, dynamic> params = const {}]) async =>
      Map<String, dynamic>.from(await _request(method, params) as Map);

  @override
  void setClosing(bool closing) {
    _quiet = closing;
    _port?.send(['quiet', closing]);
  }

  @override
  Future<void> restart() async {
    await _request('restart');
  }

  @override
  Future<void> close() => _closeFuture ??= _close();

  Future<void> _close() async {
    try {
      if (_startFuture != null) {
        try {
          await _startFuture;
        } catch (_) {
          // A failed process start must still release the communication isolate.
        }
        if (_failure == null) await _request('close');
      }
      _closed = true;
      _messages?.close();
      await _events.close();
    } catch (_) {
      _closeFuture = null;
      rethrow;
    }
  }
}

void _processWorker(List<Object?> args) {
  final host = args[0] as SendPort;
  final commands = ReceivePort();
  var backend = _ProcessConnection(
      executable: args[1] as String?, dataRoot: args[2] as String?);
  var quiet = false;
  void forwardEvents() => backend.events.listen((event) {
        if (!quiet || event['event'] == 'cache.progress') {
          host.send(['event', event]);
        }
      });
  forwardEvents();
  commands.listen((command) async {
    final values = command as List;
    if (values[0] == 'quiet') {
      quiet = values[1] as bool;
      return;
    }
    final id = values[0] as int;
    final method = values[1] as String;
    try {
      Object? result;
      if (method == 'start') {
        await backend.start();
      } else if (method == 'restart') {
        if (backend._process != null && !backend._ended) {
          throw StateError('后端仍在运行，请等待当前操作完成');
        }
        await backend.close();
        backend = _ProcessConnection(
            executable: args[1] as String?, dataRoot: args[2] as String?);
        forwardEvents();
        await backend.start();
      } else if (method == 'close') {
        await backend.close();
        Isolate.exit(host, ['reply', id, null, null]);
      } else {
        result = await backend.call(
            method, Map<String, dynamic>.from(values[2] as Map));
      }
      host.send(['reply', id, null, result]);
    } catch (error) {
      host.send(['reply', id, neoErrorMessage(error), null]);
    }
  });
  host.send(['ready', commands.sendPort]);
}

/// stdout contains protocol only; stderr is continuously drained independently.
class _ProcessConnection implements NeoBackend {
  _ProcessConnection({this.executable, this.dataRoot});
  final String? executable, dataRoot;
  final _events = StreamController<Map<String, dynamic>>.broadcast();
  final _pending = <String, Completer<Map<String, dynamic>>>{};
  Process? _process;
  int _nextId = 0;
  bool _closing = false;
  bool _ended = false;
  String _stderr = '';
  Future<void>? _exit;
  Future<void>? _closeFuture;

  @override
  Stream<Map<String, dynamic>> get events => _events.stream;

  @override
  Future<void> start() async {
    final environment = Platform.environment;
    final launch = await resolveNeoBackendLaunch(
        executable: executable, dataRoot: dataRoot);
    final temporary =
        await Directory('${launch.dataRoot}/temp').create(recursive: true);
    _process = await Process.start(
        launch.frozen
            ? launch.entrypoint.path
            : environment['OMGNEO_PYTHON'] ?? 'python',
        [
          if (!launch.frozen) ...['-u', launch.entrypoint.path],
          '--stdio',
          '--data-root',
          launch.dataRoot
        ],
        workingDirectory: launch.frozen
            ? launch.entrypoint.parent.parent.path
            : launch.entrypoint.parent.path,
        environment: {
          'PYTHONUTF8': '1',
          'TEMP': temporary.path,
          'TMP': temporary.path
        });
    _process!.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen((line) {
      try {
        final message = Map<String, dynamic>.from(jsonDecode(line) as Map);
        if (message.containsKey('event')) {
          _events.add(message);
        } else {
          final completer = _pending.remove(message['id']?.toString());
          if (completer == null) return;
          if (message['error'] != null) {
            completer.completeError(StateError(message['error']['message']));
          } else {
            completer
                .complete(Map<String, dynamic>.from(message['result'] as Map));
          }
        }
      } catch (error) {
        _fail(StateError('后端协议错误：$error'));
      }
    }, onError: _fail);
    _process!.stderr
        .transform(const Utf8Decoder(allowMalformed: true))
        .listen((text) {
      _stderr += text;
      if (_stderr.length > 3000) {
        _stderr = _stderr.substring(_stderr.length - 3000);
      }
    });
    _exit = _process!.exitCode.then((code) {
      _ended = true;
      final error = StateError('后端已退出（$code）。${_stderr.trim()}');
      _fail(error);
      if (!_closing) {
        _events.add({
          'event': 'backend.failed',
          'data': {'message': '$error'}
        });
      }
    });
  }

  void _fail(Object error) {
    for (final completer in _pending.values) {
      completer.completeError(error);
    }
    _pending.clear();
  }

  @override
  Future<Map<String, dynamic>> call(String method,
      [Map<String, dynamic> params = const {}]) async {
    if (_process == null || _ended) throw StateError('后端未运行。${_stderr.trim()}');
    final id = '${++_nextId}';
    final completer = Completer<Map<String, dynamic>>();
    _pending[id] = completer;
    try {
      _process!.stdin.writeln(
          jsonEncode({'v': 1, 'id': id, 'method': method, 'params': params}));
      return await completer.future.timeout(const Duration(seconds: 30));
    } finally {
      _pending.remove(id);
    }
  }

  @override
  Future<void> close() => _closeFuture ??= _close();

  Future<void> _close() async {
    _closing = true;
    try {
      if (_process != null && !_ended) {
        await call('shutdown');
        // Shutdown was acknowledged; don't wait for a pipe flush before exit.
        // The backend owns cancellation/rollback and exits when cleanup is safe.
        unawaited(_process!.stdin.close().catchError((Object _) {}));
        await _exit;
      }
      await _events.close();
    } catch (_) {
      _closing = false;
      _closeFuture = null;
      rethrow;
    }
  }
}
