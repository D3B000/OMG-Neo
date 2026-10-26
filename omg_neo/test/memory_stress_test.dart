import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:omg_neo/backend/log_buffer.dart';
import 'package:omg_neo/backend/neo_controller.dart';
import 'package:omg_neo/build_ui.dart';
import 'package:omg_neo/main.dart';
import 'package:omg_neo/resources_ui.dart';
import 'backend_test.dart' show FixtureBackend;

class InstantBackend extends FixtureBackend {
  int sequence = 0;
  bool early = true;
  void finish(String id) => stream.add({
        'event': 'task.finished',
        'data': {
          'taskId': id,
          'kind': 'resources.list',
          'state': 'succeeded',
          'message': 'done',
          'result': {}
        }
      });
  @override
  Future<Map<String, dynamic>> call(String method,
      [Map<String, dynamic> params = const {}]) async {
    if (method == 'resources.list') {
      final id = 'stress-${++sequence}';
      if (early) finish(id);
      return {'taskId': id};
    }
    return super.call(method, params);
  }
}

void main() {
  test('4000 tasks retain no consumed completion IDs in either reply order',
      () async {
    final backend = InstantBackend();
    final controller = NeoController(backend);
    await controller.start();
    for (final early in [true, false]) {
      backend.early = early;
      for (var i = 0; i < 2000; i++) {
        await controller.browseResources();
        if (!early) backend.finish('stress-${backend.sequence}');
        expect(controller.busy, isFalse);
        expect(controller.taskId, isNull);
      }
      expect(controller.retainedCompletionCount, 0);
    }
    controller.dispose();
    await backend.close();
  });

  test('long compiler lines and large writeback logs retain a bounded tail',
      () async {
    final logs = LogBuffer();
    for (var i = 0; i < 10000; i++) {
      logs.add('$i:${'x' * 1024}');
    }
    expect(logs.retainedCodeUnits, lessThanOrEqualTo(LogBuffer.maxCodeUnits));
    expect(logs.lines.last, startsWith('9999:'));
    logs.add('HEAD${'x' * (4 * 1024 * 1024)}TAIL');
    expect(logs.lines.last, startsWith('HEAD'));
    expect(logs.lines.last, endsWith('TAIL'));
    expect(
        logs.lines.last.length, lessThanOrEqualTo(LogBuffer.maxLineCodeUnits));

    final backend = FixtureBackend();
    final controller = NeoController(backend);
    await controller.start();
    backend.stream.add({
      'event': 'task.finished',
      'data': {
        'taskId': 'writeback',
        'kind': 'resources.writeback',
        'state': 'succeeded',
        'message': 'backup complete',
        'result': {'logs': List.generate(10000, (i) => '$i:${'z' * 1024}')}
      }
    });
    expect(controller.writebackLogs.fold<int>(0, (n, s) => n + s.length),
        lessThanOrEqualTo(LogBuffer.maxCodeUnits));
    expect(controller.writebackLogs.last, 'backup complete');
    controller.dispose();
    await backend.close();
  });

  test(
      'visiting 10000 folders bounds scroll history and keeps recent positions',
      () {
    final draft = ResourcesDraft();
    for (var i = 0; i < 10000; i++) {
      draft.rememberScroll('folder-$i', i.toDouble());
    }
    expect(draft.scrollPositions.length, 128);
    expect(draft.scrollPositions['folder-9999'], 9999);
    expect(draft.scrollPositions.containsKey('folder-0'), isFalse);
    draft.dispose();
  });

  testWidgets('20 page and preview cycles dispose browsers and build views',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(960, 540));
    const window = MethodChannel('window_manager');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(window, (_) async => null);
    final backend = FixtureBackend();
    final controller = NeoController(backend);
    await controller.start();
    controller.resources = {
      'items': [
        {
          'id': 'memory-fixture',
          'name': '内存测试模组',
          'relativePath': 'fixture',
          'isDirectory': true,
          'isMod': true,
          'enabled': true
        }
      ],
      'relativePath': '',
      'revision': 1
    };
    controller.resourcesLoaded = true;
    await tester.pumpWidget(NeoApp(controller: controller));
    await tester.pumpAndSettle();
    for (var i = 0; i < 20; i++) {
      await tester.tap(find.text('浏览 / BROWSE'));
      await tester.pumpAndSettle();
      expect(find.byType(ResourceBrowser), findsOneWidget);
      await tester.tap(
          find.byKey(const ValueKey('resources.thumbnail.memory-fixture')));
      await tester.pumpAndSettle();
      expect(find.text('该资源未提供预览图。'), findsOneWidget);
      await tester.tap(find.text('关闭'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('工具 / TOOLS'));
      await tester.pumpAndSettle();
      expect(find.byType(ResourceBrowser), findsNothing);
      await tester.tap(find.text('便捷构建'));
      await tester.pumpAndSettle();
      expect(find.byType(BuildConsole), findsOneWidget);
      await tester.tap(find.text('设置 / CONFIG'));
      await tester.pumpAndSettle();
      expect(find.byType(BuildConsole), findsNothing);
      await tester.tap(find.text('首页 / HOME'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    }
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
    await backend.close();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(window, null);
    await tester.binding.setSurfaceSize(null);
  });
}
