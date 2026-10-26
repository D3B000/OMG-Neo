import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:omg_neo/backend/neo_backend.dart';
import 'package:omg_neo/backend/neo_controller.dart';
import 'package:omg_neo/main.dart';
import 'package:omg_neo/ef/widgets.dart';
import 'package:omg_neo/build_ui.dart';
import 'package:omg_neo/ef/tokens.dart';

class FixtureBackend
    implements NeoBackend, QuiescentNeoBackend, RecoverableNeoBackend {
  final stream = StreamController<Map<String, dynamic>>.broadcast(sync: true);
  final calls = <String>[];
  final parameters = <String, Map<String, dynamic>>{};
  final replies = <String, Map<String, dynamic>>{};
  final settings = <String, dynamic>{
    'game_folder': '',
    'gimi_folder': '',
    'hunting': 2,
    'warning': 0,
    'auto_check_update': false,
    'gimi_update_whitelist': <String>[],
    'launch_method': 'native',
    'custom_launch_enabled': false,
    'custom_launch_cmd': '',
    'custom_launch_inject_mode': 'hook',
    'extra_libraries_enabled': false,
    'extra_libraries': '',
    'theme': 'light',
    'accent_color': '#39C5BB',
  };
  int revision = 0;
  bool rejectSave = false;
  bool rejectClose = false;
  int closeCount = 0;
  Completer<void>? saveGate, closeGate;
  bool quiet = false;
  int restartCount = 0;
  bool rejectRestart = false;
  bool rejectStart = false;
  @override
  Future<void> restart() async {
    restartCount++;
    if (rejectRestart) throw StateError('restart failed');
  }

  @override
  void setClosing(bool closing) => quiet = closing;
  Map<String, dynamic> get snapshot => {
        'settings': Map<String, dynamic>.from(settings),
        'revision': revision,
        'versions': {'GIMI': '9.1.0', 'ORFix': '2.0', 'TexFx': ''},
        'launchState': 'idle',
      };
  @override
  Stream<Map<String, dynamic>> get events => stream.stream;
  @override
  Future<void> start() async {
    if (rejectStart) throw StateError('startup failed');
  }

  @override
  Future<Map<String, dynamic>> call(String method,
      [Map<String, dynamic> params = const {}]) async {
    calls.add(method);
    parameters[method] = Map<String, dynamic>.from(params);
    if (replies.containsKey(method)) return replies[method]!;
    switch (method) {
      case 'hello':
        return {'snapshot': snapshot};
      case 'config.patch':
        await saveGate?.future;
        if (rejectSave) throw StateError('disk locked');
        expect(params['revision'], revision);
        settings.addAll(Map<String, dynamic>.from(params['patch']));
        revision++;
        return snapshot;
      case 'cache.info':
        return {'bytes': 1024};
      case 'updates.check':
        return {'taskId': 'check1'};
      case 'launch.start':
        return {'taskId': 'launch1'};
      default:
        return {};
    }
  }

  @override
  Future<void> close() async {
    closeCount++;
    await closeGate?.future;
    if (rejectClose) throw StateError('shutdown rejected');
    await stream.close();
  }
}

void main() {
  test('cache cleanup reports progress without changing update state',
      () async {
    final backend = FixtureBackend()
      ..replies['cache.clear'] = {'taskId': 'cache1'};
    final controller = NeoController(backend);
    await controller.start();
    await controller.refreshCache(clear: true);
    expect(controller.busy, isTrue);
    backend.stream.add({
      'event': 'task.progress',
      'data': {'taskId': 'cache1', 'progress': .5, 'message': '正在清理旧备份'}
    });
    expect(controller.taskProgress, .5);
    expect(controller.update.active, isFalse);
    backend.stream.add({
      'event': 'task.finished',
      'data': {
        'taskId': 'cache1',
        'kind': 'cache.clear',
        'state': 'succeeded',
        'message': '释放 1 MB',
        'result': {'bytes': 7, 'errors': []}
      }
    });
    expect(controller.busy, isFalse);
    expect(controller.cacheBytes, 7);
    expect(controller.cacheMessage, '释放 1 MB');
    controller.closing = true;
    backend.stream.add({
      'event': 'cache.progress',
      'data': {'progress': .75, 'message': '正在清理退出缓存'}
    });
    expect(controller.cacheProgress, .75);
    expect(controller.cacheCleaning, isTrue);
    await controller.close();
    controller.dispose();
  });
  test('server switch refreshes newly created backup usage', () async {
    final backend = FixtureBackend()
      ..replies['serverSwitch.apply'] = {'taskId': 'new-backup'};
    final controller = NeoController(backend);
    await controller.start();
    expect(controller.cacheBytes, 1024);
    await controller.switchServer('global');
    backend.replies['cache.info'] = {'bytes': 195281026};
    backend.stream.add({
      'event': 'task.finished',
      'data': {
        'taskId': 'new-backup',
        'kind': 'serverSwitch.apply',
        'state': 'succeeded',
        'message': '已切服',
        'result': {}
      }
    });
    await Future<void>.delayed(Duration.zero);
    expect(controller.cacheBytes, 195281026);
    await controller.close();
    controller.dispose();
  });
  test('error presentation removes repeated isolate StateError prefixes', () {
    expect(neoErrorMessage(StateError('Bad state: Bad state: 无法识别')), '无法识别');
  });
  for (final terminal in ['succeeded', 'failed', 'cancelled']) {
    test(
        'server switch $terminal isolates progress and locks launch until finished',
        () async {
      final backend = FixtureBackend()
        ..replies['serverSwitch.apply'] = {'taskId': 'switch1'};
      final controller = NeoController(backend);
      await controller.start();
      controller.update.ready = true;
      final starting = controller.switchServer('global');
      expect(controller.launchEnabled, isFalse);
      await starting;
      expect(controller.taskKind, 'serverSwitch.apply');
      await controller.launch();
      expect(backend.calls, isNot(contains('launch.start')));
      backend.stream.add({
        'event': 'task.progress',
        'data': {
          'taskId': 'switch1',
          'kind': 'serverSwitch.apply',
          'progress': .75,
          'message': '正在替换'
        }
      });
      expect(controller.update.active, isFalse);
      expect(controller.update.ready, isTrue);
      expect(controller.taskProgress, .75);
      expect(controller.launchEnabled, isFalse);
      // An obsolete completion must not unlock launch while replacement is active.
      backend.stream.add({
        'event': 'task.finished',
        'data': {
          'taskId': 'obsolete',
          'kind': 'check',
          'state': 'succeeded',
          'message': 'old',
          'result': {}
        }
      });
      expect(controller.busy, isTrue);
      backend.stream.add({
        'event': 'task.finished',
        'data': {
          'taskId': 'switch1',
          'kind': 'serverSwitch.apply',
          'state': terminal,
          'message': terminal,
          'result': {}
        }
      });
      expect(controller.busy, isFalse);
      expect(controller.launchEnabled, isTrue);
      expect(controller.taskProgress, isNull);
      expect(controller.update.active, isFalse);
      backend.stream.add({
        'event': 'task.progress',
        'data': {
          'taskId': 'switch1',
          'kind': 'serverSwitch.apply',
          'progress': .9,
          'message': 'late'
        }
      });
      expect(controller.taskProgress, isNull);
      expect(controller.update.active, isFalse);
      controller.dispose();
      await backend.close();
    });
  }

  test('home startup defers build capabilities until the tool is opened',
      () async {
    final backend = FixtureBackend()
      ..replies['build.get'] = {
        'options': {'optimize': true},
        'capabilities': {'build': true}
      };
    final controller = NeoController(backend);
    await controller.start();
    expect(controller.ready, isTrue);
    expect(backend.calls, isNot(contains('build.get')));
    expect(controller.buildState, isEmpty);
    await controller.loadBuild();
    expect(controller.buildState['capabilities']['build'], isTrue);
    expect(
        backend.calls.where((method) => method == 'build.get'), hasLength(1));
    controller.dispose();
    await backend.close();
  });

  test('reconnect after startup failure also restores event delivery',
      () async {
    final backend = FixtureBackend()..rejectStart = true;
    final controller = NeoController(backend);
    await controller.start();
    expect(controller.canReconnect, isTrue);
    backend.rejectStart = false;
    await controller.reconnect();
    backend.stream.add({
      'event': 'launch.state',
      'data': {'state': 'error', 'message': 'verification failed'}
    });
    expect(controller.ready, isTrue);
    expect(controller.launchState, 'error');
    expect(controller.status, 'verification failed');
    controller.dispose();
    await backend.close();
  });
  testWidgets(
      'resource disconnect remains recoverable without dumping raw logs',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(960, 540));
    const window = MethodChannel('window_manager');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(window, (_) async => null);
    final backend = FixtureBackend()
      ..replies['resources.list'] = {'taskId': 'reload1'};
    final controller = NeoController(backend);
    await controller.start();
    const diagnostic =
        'backend exited (0)\nVerification Failed: Invalid Handle: 5\nprivate/path';
    controller.busy = true;
    controller.taskId = 'old-launch';
    backend.stream.add({
      'event': 'backend.failed',
      'data': {'message': diagnostic}
    });
    await tester.pumpWidget(NeoApp(controller: controller, resources: true));
    await tester.pumpAndSettle();
    expect(controller.taskId, isNull);
    expect(find.text(diagnostic), findsNothing);
    expect(find.text('后端连接已断开'), findsOneWidget);
    expect(find.text('重新连接'), findsOneWidget);
    expect(
        tester.widget<EfButton>(find.widgetWithText(EfButton, '设置')).onPressed,
        isNotNull);
    await tester.tap(find.text('重新连接'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(backend.restartCount, 1);
    expect(backend.calls, isNot(contains('launch.start')));
    expect(backend.calls, contains('resources.list'));
    backend.stream.add({
      'event': 'task.finished',
      'data': {
        'taskId': 'reload1',
        'kind': 'resources.list',
        'state': 'succeeded',
        'message': 'loaded',
        'result': {
          'resources': {'relativePath': '', 'revision': 1, 'items': []}
        }
      }
    });
    await tester.pumpAndSettle();
    expect(controller.ready, isTrue);
    expect(
        tester.widget<EfButton>(find.widgetWithText(EfButton, '写回')).onPressed,
        isNotNull);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
    await backend.close();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(window, null);
    await tester.binding.setSurfaceSize(null);
  });

  test('closing is immediate, shared, and preserves pending settings',
      () async {
    final backend = FixtureBackend()..saveGate = Completer<void>();
    final controller = NeoController(backend);
    await controller.start();
    controller.stage({'game_folder': 'C:/Game'});
    final first = controller.close();
    expect(controller.closing, isTrue);
    expect(controller.launchEnabled, isFalse);
    expect(controller.update.enabled, isFalse);
    expect(backend.quiet, isTrue);
    expect(identical(first, controller.close()), isTrue);
    controller.stage({'game_folder': 'C:/Unexpected'});
    expect(backend.closeCount, 0);
    backend.saveGate!.complete();
    await first;
    expect(backend.settings['game_folder'], 'C:/Game');
    expect(backend.calls, contains('settings.flush'));
    expect(backend.closeCount, 1);
    controller.dispose();
  });

  test('save and shutdown failures restore actions and allow close retry',
      () async {
    final backend = FixtureBackend();
    final controller = NeoController(backend);
    await controller.start();
    backend.rejectSave = true;
    controller.stage({'game_folder': 'C:/Game'});
    await expectLater(controller.close(), throwsStateError);
    expect(controller.closing, isFalse);
    expect(backend.quiet, isFalse);
    expect(controller.launchEnabled, isTrue);
    expect(backend.closeCount, 0);
    backend.rejectSave = false;
    backend.rejectClose = true;
    await expectLater(controller.close(), throwsStateError);
    expect(controller.closing, isFalse);
    expect(controller.update.enabled, isTrue);
    backend.rejectClose = false;
    await controller.close();
    expect(backend.closeCount, 2);
    controller.dispose();
  });

  testWidgets('resource page always shows closing feedback until cleanup ends',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(960, 540));
    const window = MethodChannel('window_manager');
    const lifecycle = MethodChannel('omg_neo/lifecycle');
    final windowCalls = <String>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(window, (call) async {
      windowCalls.add(call.method);
      return null;
    });
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(lifecycle, (call) async {
      windowCalls.add(call.method);
      return null;
    });
    final backend = FixtureBackend()..closeGate = Completer<void>();
    final controller = NeoController(backend);
    await controller.start();
    await tester.pumpWidget(NeoApp(controller: controller, resources: true));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('关闭'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byKey(const ValueKey('app.closing')), findsOneWidget);
    expect(windowCalls, isNot(contains('finishExit')));
    expect(controller.closing, isTrue);
    await tester.pump(const Duration(seconds: 6));
    expect(find.byKey(const ValueKey('app.closing')), findsOneWidget);
    final progress = find.byKey(const ValueKey('app.closing.progress'));
    final beforeFrame = tester.binding.transientCallbackCount;
    backend.stream.add({
      'event': 'task.progress',
      'data': {'message': 'ignored during exit', 'progress': 0.5}
    });
    await tester.pump(const Duration(milliseconds: 16));
    expect(progress, findsOneWidget);
    expect(beforeFrame, greaterThan(0));
    expect(tester.binding.transientCallbackCount, greaterThan(0));
    expect(controller.status, isNot('ignored during exit'));
    backend.closeGate!.complete();
    // Drain the asynchronous stream shutdown before checking native teardown.
    await tester.runAsync(() => controller.close());
    await tester.pump();
    expect(windowCalls.where((call) => call == 'finishExit'), hasLength(1));
    expect(windowCalls, isNot(contains('destroy')));
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(window, null);
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(lifecycle, null);
    await tester.binding.setSurfaceSize(null);
  });

  testWidgets('failed close dismisses feedback and a second click retries',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(960, 540));
    const window = MethodChannel('window_manager');
    const lifecycle = MethodChannel('omg_neo/lifecycle');
    var destroyed = 0;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(window, (call) async {
      return null;
    });
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(lifecycle, (call) async {
      if (call.method == 'finishExit') destroyed++;
      return null;
    });
    final backend = FixtureBackend()..rejectClose = true;
    final controller = NeoController(backend);
    await controller.start();
    await tester.pumpWidget(NeoApp(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('关闭'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('app.closing')), findsNothing);
    expect(find.textContaining('关闭失败：'), findsOneWidget);
    expect(controller.closing, isFalse);
    expect(destroyed, 0);
    backend.rejectClose = false;
    await tester.tap(find.byTooltip('关闭'));
    await tester.pump();
    await tester.runAsync(() => controller.close());
    await tester.pump();
    expect(destroyed, 1);
    expect(backend.closeCount, 2);
    await tester.pumpWidget(const SizedBox());
    await tester.pump(const Duration(seconds: 1));
    controller.dispose();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(window, null);
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(lifecycle, null);
    await tester.binding.setSurfaceSize(null);
  });

  test('build success notices are short while terminal keeps the details',
      () async {
    final backend = FixtureBackend();
    final controller = NeoController(backend);
    await controller.start();
    for (final (action, message) in [
      ('ritual', '执行完毕'),
      ('copy', '复制完毕'),
      ('compile', '构建完毕')
    ]) {
      backend.replies['build.$action'] = {'taskId': action};
      await controller.businessTask('build.$action');
      backend.stream.add({
        'event': 'task.finished',
        'data': {
          'taskId': action,
          'kind': 'build.$action',
          'state': 'succeeded',
          'message': '包含产物路径、备份路径的完整输出',
          'result': {},
        }
      });
      expect(controller.status, message);
      expect(controller.buildLogs.last, '包含产物路径、备份路径的完整输出');
    }
    backend.replies['build.ritual'] = {'taskId': 'failed'};
    await controller.businessTask('build.ritual');
    backend.stream.add({
      'event': 'task.finished',
      'data': {
        'taskId': 'failed',
        'kind': 'build.ritual',
        'state': 'failed',
        'message': '原始失败原因',
        'result': {},
      }
    });
    expect(controller.status, '原始失败原因');
    expect(controller.error, '原始失败原因');
    controller.dispose();
    await backend.close();
  });

  testWidgets('work directory remains available during a build task',
      (tester) async {
    final backend = FixtureBackend();
    final controller = NeoController(backend);
    await controller.start();
    controller.busy = true;
    controller.taskKind = 'build.compile';
    final draft = BuildDraft();
    await tester.pumpWidget(MaterialApp(
        theme: efTheme(Brightness.light),
        home: Scaffold(
            body: BuildConsole(
                draft: draft,
                controller: controller,
                onBack: () {},
                region: (_, child) => child))));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('build.open-workspace')));
    await tester.pumpAndSettle();
    expect(backend.calls, contains('build.openWorkspace'));
    await tester.pumpWidget(const SizedBox.shrink());
    draft.dispose();
    controller.dispose();
    await backend.close();
  });

  testWidgets(
      'directory menus open INI files and navigate folders from the current breadcrumb',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(960, 540));
    const window = MethodChannel('window_manager');
    tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(window, (_) async => null);
    final backend = FixtureBackend()
      ..replies['resources.list'] = {'taskId': 'list-menu'}
      ..replies['resources.directory'] = {
        'folders': [
          {'name': '子目录', 'path': '分组/当前/子目录'}
        ],
        'files': [
          {'name': 'config.ini', 'path': '分组/当前/config.ini'}
        ],
      };
    final controller = NeoController(backend);
    await controller.start();
    controller.resources = {
      'relativePath': '分组/当前',
      'revision': 1,
      'items': []
    };
    controller.resourcesLoaded = true;
    await tester.pumpWidget(NeoApp(controller: controller, resources: true));
    await tester.pumpAndSettle();
    expect(find.byTooltip('显示此目录的文件夹'), findsNothing);
    await tester.tap(find.byKey(const ValueKey('resources.menu.ini')));
    await tester.pumpAndSettle();
    expect(backend.parameters['resources.directory'], {'path': '分组/当前'});
    expect(tester.getTopLeft(find.text('config.ini')).dx, greaterThan(600));
    await tester.tap(find.text('config.ini'));
    await tester.pumpAndSettle();
    expect(backend.parameters['resources.open'],
        {'path': '分组/当前/config.ini', 'config': true});
    await tester.tap(find.byKey(const ValueKey('resources.menu.folders')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('子目录'));
    await tester.pumpAndSettle();
    expect(backend.parameters['resources.list']?['path'], '分组/当前/子目录');
    expect(backend.calls, isNot(contains('resources.toggle')));
    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
    await backend.close();
    tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(window, null);
    await tester.binding.setSurfaceSize(null);
  });

  test('build tasks retain logs and results without starting home update',
      () async {
    final backend = FixtureBackend()
      ..replies['build.compile'] = {'taskId': 'build1'};
    final controller = NeoController(backend);
    await controller.start();
    final starting = controller.businessTask('build.compile');
    expect(controller.status, '正在执行…');
    expect(controller.buildLogs.last, '> build.compile');
    await starting;
    expect(controller.busy, isTrue);
    expect(controller.update.active, isFalse);
    backend.stream.add({
      'event': 'task.progress',
      'data': {
        'taskId': 'build1',
        'kind': 'build.compile',
        'message': 'MSBuild output',
        'progress': 0.5
      }
    });
    expect(controller.buildLogs, contains('MSBuild output'));
    expect(controller.update.active, isFalse);
    await controller.cancelTask();
    expect(controller.busy, isTrue);
    expect(backend.calls.last, 'tasks.cancel');
    backend.stream.add({
      'event': 'task.finished',
      'data': {
        'taskId': 'build1',
        'kind': 'build.compile',
        'state': 'cancelled',
        'message': '后续步骤已取消',
        'result': {
          'build': {
            'products': {
              'artifact': {'sha256': 'digest'}
            }
          }
        }
      }
    });
    expect(controller.busy, isFalse);
    expect(controller.buildState['products']['artifact']['sha256'], 'digest');
    expect(controller.buildLogs.last, '后续步骤已取消');
    controller.dispose();
    await backend.close();
  });

  testWidgets(
      'live resource keys and thumbnails never toggle; rename refreshes actual ID',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(960, 540));
    const window = MethodChannel('window_manager');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(window, (_) async => null);
    final backend = FixtureBackend()
      ..replies['resources.toggle'] = {'taskId': 'toggle1'}
      ..replies['resources.keys'] = {'taskId': 'keys1'};
    final controller = NeoController(backend);
    await controller.start();
    final item = <String, dynamic>{
      'id': 'real1',
      'uiKey': 'stable-real1',
      'name': '真实模组',
      'relativePath': '真实分组/真实模组',
      'isDirectory': true,
      'isMod': true,
      'enabled': true,
      'thumbnailPath': null,
      'keys': []
    };
    controller.resources = {
      'relativePath': '真实分组',
      'revision': 1,
      'items': [item]
    };
    controller.resourcesLoaded = true;
    await tester.pumpWidget(NeoApp(controller: controller, resources: true));
    await tester.pumpAndSettle();
    expect(find.text('角色'), findsNothing);
    expect(find.text('真实模组'), findsOneWidget);
    backend.replies['resources.configs'] = {
      'files': [
        {'name': 'outfit.ini', 'path': '真实分组/真实模组/outfit.ini'}
      ]
    };
    await tester.tap(find.byKey(const ValueKey('resources.item.real1')),
        buttons: kSecondaryMouseButton);
    await tester.pumpAndSettle();
    await tester.tap(find.text('配置文件'));
    await tester.pumpAndSettle();
    expect(find.text('outfit.ini'), findsOneWidget);
    await tester.tap(find.text('outfit.ini'));
    await tester.pumpAndSettle();
    expect(backend.parameters['resources.open'],
        {'path': '真实分组/真实模组/outfit.ini', 'config': true});

    await tester.tap(find.byKey(const ValueKey('resources.keys.real1')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    expect(backend.calls, contains('resources.keys'));
    backend.stream.add({
      'event': 'task.finished',
      'data': {
        'taskId': 'keys1',
        'kind': 'resources.keys',
        'state': 'succeeded',
        'message': '切换键已读取',
        'result': {
          'resourceKeys': {
            'id': 'real1',
            'keys': [
              {'section_name': 'KeyOutfit', 'variable': r'$swap', 'key': 'X'}
            ]
          }
        }
      }
    });
    await tester.pumpAndSettle();
    expect(find.text('X'), findsOneWidget);
    await tester.tap(find.text('关闭'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('resources.thumbnail.real1')));
    await tester.pumpAndSettle();
    expect(find.byType(EfDialog), findsOneWidget);
    final open = find.byKey(const ValueKey('resources.preview.open'));
    expect(tester.widget<EfButton>(open).onPressed, isNull);
    expect(tester.getCenter(open).dx,
        lessThan(tester.getCenter(find.text('关闭')).dx));
    expect(backend.calls, isNot(contains('resources.toggle')));
    await tester.tap(find.text('关闭'));
    await tester.pumpAndSettle();
    item['thumbnailPath'] = 'missing-preview-fixture.png';
    controller.resources = {
      ...controller.resources,
      'items': [item]
    };
    controller.notifyListeners();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('resources.thumbnail.real1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('resources.preview.open')));
    await tester.pumpAndSettle();
    expect(backend.parameters['resources.openImage'],
        {'id': 'real1', 'revision': 1});
    expect(find.byType(EfDialog), findsOneWidget);
    await tester.tap(find.text('关闭'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('resources.item.real1')));
    await tester.pumpAndSettle();
    expect(backend.calls.where((m) => m == 'resources.toggle'), hasLength(1));
    final stateTab =
        find.byKey(const ValueKey('resources.status.stable-real1'));
    final previousState = tester.state(stateTab);
    backend.stream.add({
      'event': 'task.finished',
      'data': {
        'taskId': 'toggle1',
        'kind': 'resources.toggle',
        'state': 'succeeded',
        'message': '已停用',
        'result': {
          'resources': {
            'relativePath': '真实分组',
            'revision': 2,
            'items': [
              {
                'id': 'new-first',
                'uiKey': 'another-file',
                'name': 'A 新条目',
                'relativePath': '真实分组/A 新条目',
                'isDirectory': true,
                'isMod': true,
                'enabled': true,
                'keys': [],
                'thumbnailPath': null
              },
              {
                ...item,
                'id': 'real2',
                'name': 'DISABLED 真实模组',
                'relativePath': '真实分组/DISABLED 真实模组',
                'enabled': false
              }
            ]
          }
        }
      }
    });
    await tester.pump();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
    final fill =
        find.descendant(of: stateTab, matching: find.byType(AnimatedContainer));
    final fraction = tester.getSize(fill).width /
        tester
            .getSize(find
                .byKey(const ValueKey('resources.status-track.stable-real1')))
            .width;
    expect(fraction, greaterThan(0));
    expect(fraction, lessThan(1));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('resources.item.real2')), findsOneWidget);
    expect(identical(tester.state(stateTab), previousState), isTrue);
    expect(find.text('1 项 / 0 项已启用'), findsNothing);
    await tester.tap(find.text('工具 / TOOLS'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('浏览 / BROWSE'));
    await tester.pumpAndSettle();
    expect(find.text('DISABLED 真实模组'), findsNothing);
    expect(find.text('真实模组'), findsOneWidget);
    final callsBeforeDisplayChange = backend.calls.length;
    await tester.tap(find.text('设置'));
    await tester.pumpAndSettle();
    await tester
        .tap(find.byKey(const ValueKey('resources.settings.disabled-prefix')));
    await tester.pumpAndSettle();
    expect(find.text('DISABLED 真实模组'), findsOneWidget);
    expect(backend.calls.length, callsBeforeDisplayChange);
    expect(controller.resources['items'][1]['enabled'], isFalse);
    await tester.tap(find.text('设置'));
    await tester.pumpAndSettle();
    await tester
        .tap(find.byKey(const ValueKey('resources.settings.enabled-first')));
    await tester.pumpAndSettle();
    expect(backend.calls.length, callsBeforeDisplayChange);
    expect(find.byKey(const ValueKey('app.toast')), findsNothing);
    backend.replies['resources.move'] = {'taskId': 'drop1'};
    final point =
        tester.getCenter(find.byKey(const ValueKey('region.resources.cards')));
    final ratio = tester.view.devicePixelRatio;
    Future<void> dropEvent(String method, Object arguments) async {
      await tester.binding.defaultBinaryMessenger.handlePlatformMessage(
          'desktop_drop',
          const StandardMethodCodec()
              .encodeMethodCall(MethodCall(method, arguments)),
          (_) {});
    }

    await dropEvent('entered', [point.dx * ratio, point.dy * ratio]);
    await dropEvent(
        'performOperation', [r'C:\incoming\中文文件.ini', r'C:\incoming\folder']);
    await tester.pumpAndSettle();
    expect(backend.calls, contains('resources.move'));
    expect(backend.parameters['resources.move']!['path'], '真实分组');
    expect(backend.parameters['resources.move']!['sources'],
        [r'C:\incoming\中文文件.ini', r'C:\incoming\folder']);
    expect(find.byKey(const ValueKey('app.toast')), findsNothing);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
    await backend.close();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(window, null);
    await tester.binding.setSurfaceSize(null);
  });

  test('unverified running game blocks duplicate launch until exit', () async {
    final backend = FixtureBackend();
    final controller = NeoController(backend);
    await controller.start();
    backend.stream.add({
      'event': 'launch.state',
      'data': {
        'state': 'unverified',
        'message': '游戏已启动，但模块表不可读取',
      }
    });
    expect(controller.launchEnabled, isFalse);
    expect(controller.status, contains('模块表不可读取'));
    backend.stream.add({
      'event': 'launch.state',
      'data': {
        'state': 'idle',
        'message': '游戏已退出',
      }
    });
    expect(controller.launchEnabled, isTrue);
    controller.dispose();
    await backend.close();
  });
  test(
      'save failures block launch; retry uses queued edits and latest revision',
      () async {
    final backend = FixtureBackend();
    final controller = NeoController(backend);
    await controller.start();
    backend.rejectSave = true;
    controller.stage({'game_folder': 'C:/Game'});
    await controller.launch();
    expect(backend.calls, isNot(contains('launch.start')));
    expect(controller.error, contains('disk locked'));
    backend.rejectSave = false;
    await controller.launch();
    expect(backend.settings['game_folder'], 'C:/Game');
    expect(backend.calls.where((m) => m == 'launch.start'), hasLength(1));
    expect(controller.busy, isTrue);
    controller.dispose();
    await backend.close();
  });

  test(
      'update completion is driven by backend; cancel retains task until finished',
      () async {
    final backend = FixtureBackend();
    final controller = NeoController(backend);
    await controller.start();
    await controller.check();
    expect(controller.update.active, isTrue);
    expect(controller.update.ready, isFalse);
    await controller.updateAction();
    expect(backend.calls.last, 'tasks.cancel');
    expect(controller.busy, isTrue);
    backend.stream.add({
      'event': 'task.finished',
      'data': {
        'taskId': 'check1',
        'kind': 'check',
        'state': 'cancelled',
        'message': '已取消',
        'snapshot': backend.snapshot,
      }
    });
    expect(controller.update.active, isFalse);
    expect(controller.update.ready, isFalse);
    expect(controller.busy, isFalse);
    controller.dispose();
    await backend.close();
  });

  testWidgets(
      'live home versions and settings edit persist across page switches',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(960, 540));
    const window = MethodChannel('window_manager');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(window, (_) async => null);
    final backend = FixtureBackend();
    final controller = NeoController(backend);
    await tester.pumpWidget(NeoApp(controller: controller));
    await controller.start();
    await tester.pumpAndSettle();
    expect(find.text('9.1.0'), findsOneWidget);
    expect(find.text('2.0'), findsOneWidget);
    await tester.tap(find.text('设置 / CONFIG'));
    await tester.pumpAndSettle();
    expect(find.text('仅界面预览 / 不写入配置'), findsNothing);
    await tester.enterText(
        find.byKey(const ValueKey('settings.path.game')), 'C:/RealGame');
    await controller.flush();
    await tester.pumpAndSettle();
    expect(backend.settings['game_folder'], 'C:/RealGame');
    await tester.tap(find.text('首页 / HOME'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('设置 / CONFIG'));
    await tester.pumpAndSettle();
    expect(find.text('C:/RealGame'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
    await backend.close();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(window, null);
    await tester.binding.setSurfaceSize(null);
  });
}
