import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:desktop_drop/desktop_drop.dart';
import 'package:omg_neo/backend/neo_backend.dart';
import 'package:omg_neo/backend/neo_controller.dart';
import 'package:omg_neo/ef/tokens.dart';
import 'package:omg_neo/ef/widgets.dart';
import 'package:omg_neo/server_switch_ui.dart';
import 'package:omg_neo/main.dart';
import 'package:omg_neo/update_preview.dart';
import 'backend_test.dart' show FixtureBackend;

class SwitchBackend implements NeoBackend {
  bool failPreview = false;
  final calls = <String>[];
  @override
  Stream<Map<String, dynamic>> get events => const Stream.empty();
  @override
  Future<void> start() async {}
  @override
  Future<void> close() async {}
  @override
  Future<Map<String, dynamic>> call(String method,
      [Map<String, dynamic> params = const {}]) async {
    calls.add(method);
    if (method == 'serverSwitch.versions') {
      return {
        'sources': [
          {
            'id': 'local.cn',
            'label': '本地游戏 / 国服',
            'version': '7.1.0',
            'build': '7.1.0_48052158_48145775',
            'path': r'C:\Game\YuanShen_Data\globalgamemanagers',
            'declaredVersion': '7.0.0',
            'mismatch': true,
            'error': '',
            'note': ''
          },
          {
            'id': 'package.cn',
            'label': '替换包 / 国服',
            'version': '7.1.0',
            'build': '7.1.0_48052158_48145775',
            'path': r'C:\Package\YuanShen_Data\globalgamemanagers',
            'declaredVersion': '7.1.0',
            'mismatch': false,
            'error': '',
            'note': ''
          },
          {
            'id': 'package.global',
            'label': '替换包 / 国际服',
            'version': '',
            'build': '',
            'path': r'C:\Package\GenshinImpact_Data\globalgamemanagers',
            'declaredVersion': '7.1.0',
            'mismatch': false,
            'error': '文件不存在',
            'note': ''
          }
        ],
        'errors': [],
        'backupRoot': r'C:\AppData\server-switch\备份包'
      };
    }
    if (method == 'serverSwitch.preview') {
      if (failPreview) throw StateError('替换包版本与游戏版本不一致');
      return {
        'current': 'cn',
        'version': '7.1.0',
        'resourceRoot': r'C:\AppData\server-switch',
        'rename': '',
        'copy': [],
        'remove': []
      };
    }
    return {'taskId': 'switch-test'};
  }
}

void main() {
  testWidgets(
      'segmented server row and mechanical progress disappear on completion in both themes',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(960, 540));
    await tester.runAsync(() async {
      await (FontLoader('Saira')..addFont(rootBundle.load('fonts/Saira.ttf')))
          .load();
      await (FontLoader('MaterialIcons')
            ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf')))
          .load();
      await (FontLoader('Noto Sans SC')
            ..addFont(Future.value(ByteData.sublistView(
                File('C:/Windows/Fonts/msyh.ttc').readAsBytesSync()))))
          .load();
    });
    for (final brightness in [Brightness.light, Brightness.dark]) {
      final backend = FixtureBackend()
        ..replies['serverSwitch.versions'] =
            await SwitchBackend().call('serverSwitch.versions')
        ..replies['serverSwitch.backup'] = {'taskId': 'backup1'}
        ..replies['serverSwitch.apply'] = {'taskId': 'switch1'}
        ..replies['serverSwitch.preview'] = {
          'current': 'cn',
          'version': '7.1.0',
          'resourceRoot': r'C:\AppData\server-switch',
          'rename': '',
          'copy': [],
          'remove': []
        };
      final controller = NeoController(backend);
      backend.settings['theme'] = brightness.name;
      backend.settings['game_folder'] = r'C:\Game';
      backend.settings['gimi_folder'] = r'C:\GIMI';
      await controller.start();
      const window = MethodChannel('window_manager');
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(window, (_) async => null);
      await tester.pumpWidget(NeoApp(
          key: ValueKey(brightness),
          controller: controller,
          initialDark: brightness == Brightness.dark));
      await tester.pumpAndSettle();
      await tester.tap(find.text('工具 / TOOLS'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('服务器切换'));
      await tester.pumpAndSettle();
      final navigation = tester
          .getRect(find.byKey(const ValueKey('region.navigation.bottom')));
      final actions = tester
          .getRect(find.byKey(const ValueKey('region.serverSwitch.actions')));
      final versions = tester
          .getRect(find.byKey(const ValueKey('region.serverSwitch.versions')));
      expect(actions.right, lessThan(versions.left));
      final restore =
          tester.getRect(find.byKey(const ValueKey('serverSwitch.restore')));
      final check =
          tester.getRect(find.byKey(const ValueKey('serverSwitch.check')));
      expect(restore.left, greaterThan(actions.center.dx));
      expect(restore.right, lessThan(check.left));
      expect(check.top, lessThan(actions.top + 24));
      expect(find.byTooltip('恢复上一次未完成的服务器切换。'), findsOneWidget);
      expect(find.byTooltip('检查当前游戏与目标服务器的替换资源。'), findsOneWidget);
      expect(find.text('检查替换资源'), findsNothing);
      expect(find.text('恢复未完成的切换'), findsNothing);
      expect(actions.width / versions.width, closeTo(2, .05));
      for (final id in ['local.cn', 'package.cn', 'package.global']) {
        final block = find.byKey(ValueKey('serverSwitch.version-source.$id'));
        final decoration =
            tester.widget<Container>(block).decoration as ShapeDecoration;
        expect(decoration.shape, isA<BeveledRectangleBorder>());
        expect(
            find.ancestor(
                of: find.byKey(ValueKey('serverSwitch.version-record.$id')),
                matching: find.byType(Tooltip)),
            findsNothing);
      }
      const localPath = r'C:\Game\YuanShen_Data\globalgamemanagers';
      final record = tester.getRect(
          find.byKey(const ValueKey('serverSwitch.version-record.local.cn')));
      final mouse =
          await tester.createGesture(kind: ui.PointerDeviceKind.mouse);
      await mouse.addPointer(location: const Offset(0, 0));
      await mouse.moveTo(record.topRight + const Offset(-10, 20));
      await tester.pump(const Duration(milliseconds: 800));
      expect(find.text(localPath), findsNothing);
      await mouse.moveTo(tester.getCenter(
          find.byKey(const ValueKey('serverSwitch.version-source.local.cn'))));
      await tester.pump(const Duration(milliseconds: 800));
      await tester.pumpAndSettle();
      expect(find.text(localPath), findsOneWidget);
      await mouse.moveTo(const Offset(0, 0));
      await mouse.removePointer();
      await tester.pump(const Duration(milliseconds: 500));
      await tester.pumpAndSettle();
      await tester
          .tap(find.byKey(const ValueKey('serverSwitch.open-directory')));
      await tester.pumpAndSettle();
      expect(backend.calls, contains('serverSwitch.openDirectory'));
      expect(find.byType(EfSegmented), findsOneWidget);
      expect(find.byType(ChoiceChip), findsNothing);
      await tester.tap(find.text('开始切换'));
      await tester.pump();
      backend.stream.add({
        'event': 'task.progress',
        'data': {
          'taskId': 'switch1',
          'kind': 'serverSwitch.apply',
          'progress': .5,
          'message': '正在替换客户端文件'
        }
      });
      await tester.pumpAndSettle();
      expect(find.byType(EfProgress), findsNothing);
      expect(find.byType(BottomUpdateProgress), findsOneWidget);
      final progress =
          tester.getRect(find.byKey(const ValueKey('home.bottom-progress')));
      expect(progress.bottom, 540);
      expect(progress.left, 0);
      expect(progress.width, 960);
      expect(
          tester
              .getRect(find.byKey(const ValueKey('region.navigation.bottom'))),
          navigation);
      expect(
          find.ancestor(
              of: find.byType(EfSegmented), matching: find.byType(Opacity)),
          findsNothing);
      final selected = tester.widget<AnimatedContainer>(find
          .descendant(
              of: find.byType(EfSegmented),
              matching: find.byType(AnimatedContainer))
          .first);
      final colors = EfColors.of(tester.element(find.byType(EfSegmented)));
      expect((selected.decoration as BoxDecoration).color, colors.ink);
      expect(
          tester
              .widget<AbsorbPointer>(find
                  .ancestor(
                      of: find.byType(EfSegmented),
                      matching: find.byType(AbsorbPointer))
                  .first)
              .absorbing,
          isTrue);
      expect(find.byType(LinearProgressIndicator), findsNothing);
      expect(controller.launchEnabled, isFalse);
      await tester.runAsync(() async {
        final image = await tester
            .renderObject<RenderRepaintBoundary>(
                find.byType(RepaintBoundary).first)
            .toImage();
        final png = await image.toByteData(format: ui.ImageByteFormat.png);
        final file =
            File('validation/server-switch-progress-${brightness.name}.png');
        file.parent.createSync(recursive: true);
        file.writeAsBytesSync(png!.buffer.asUint8List());
        image.dispose();
      });
      backend.stream.add({
        'event': 'task.finished',
        'data': {
          'taskId': 'switch1',
          'kind': 'serverSwitch.apply',
          'state': 'succeeded',
          'message': '切换完成',
          'result': {}
        }
      });
      await tester.pumpAndSettle();
      expect(find.byType(EfProgress), findsNothing);
      expect(find.byKey(const ValueKey('home.bottom-progress')), findsNothing);
      expect(controller.update.active, isFalse);
      expect(controller.launchEnabled, isTrue);
      await tester.pump(const Duration(milliseconds: 2800));
      await tester.pumpAndSettle();
      await tester.tap(find.text('制作备份 / BACKUP'));
      await tester.pumpAndSettle();
      final backup = tester
          .getRect(find.byKey(const ValueKey('region.serverSwitch.actions')));
      final guide = tester
          .getRect(find.byKey(const ValueKey('region.serverSwitch.guide')));
      expect(backup.width / guide.width, closeTo(2, .05));
      expect(tester.getSize(find.widgetWithText(EfButton, '备份国服 / B 服')).height,
          36);
      expect(
          tester
              .getRect(
                  find.byKey(const ValueKey('serverSwitch.backup-actions')))
              .bottom,
          lessThan(navigation.top));
      await tester.runAsync(() async {
        final image = await tester
            .renderObject<RenderRepaintBoundary>(
                find.byType(RepaintBoundary).first)
            .toImage();
        final png = await image.toByteData(format: ui.ImageByteFormat.png);
        File('validation/server-backup-redesign-${brightness.name}.png')
            .writeAsBytesSync(png!.buffer.asUint8List());
        image.dispose();
      });
      await tester.tap(find.text('备份国服 / B 服'));
      await tester.pump();
      backend.stream.add({
        'event': 'task.progress',
        'data': {
          'taskId': 'backup1',
          'kind': 'serverSwitch.backup',
          'progress': .25,
          'message': '正在备份文件'
        }
      });
      await tester.pumpAndSettle();
      expect(
          tester
              .getRect(find.byKey(const ValueKey('home.bottom-progress')))
              .bottom,
          540);
      backend.stream.add({
        'event': 'task.finished',
        'data': {
          'taskId': 'backup1',
          'kind': 'serverSwitch.backup',
          'state': 'cancelled',
          'message': '备份已取消',
          'result': {}
        }
      });
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('home.bottom-progress')), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
      await backend.close();
    }
  });

  testWidgets(
      'page navigation, automatic preview and start without manual check',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(960, 540));
    await tester.runAsync(() async {
      await (FontLoader('Saira')..addFont(rootBundle.load('fonts/Saira.ttf')))
          .load();
      await (FontLoader('Noto Sans SC')
            ..addFont(Future.value(ByteData.sublistView(
                File('C:/Windows/Fonts/msyh.ttc').readAsBytesSync()))))
          .load();
    });
    final backend = SwitchBackend();
    final controller = NeoController(backend)..ready = true;
    bool returned = false;
    await tester.pumpWidget(MaterialApp(
        theme: efTheme(Brightness.light),
        home: Scaffold(
            body: RepaintBoundary(
                child: Padding(
                    padding: const EdgeInsets.all(32),
                    child: NeoServerSwitch(
                        controller: controller,
                        onBack: () => returned = true))))));
    await tester.pumpAndSettle();
    expect(find.byType(AlertDialog), findsNothing);
    expect(backend.calls, contains('serverSwitch.preview'));
    expect(
        tester
            .widget<EfButton>(find.widgetWithText(EfButton, '开始切换'))
            .onPressed,
        isNotNull);
    await tester.tap(find.text('制作备份 / BACKUP'));
    await tester.pumpAndSettle();
    expect(find.text('备份输出目录'), findsOneWidget);
    expect(
        tester
            .widgetList<TextField>(find.byType(TextField))
            .last
            .controller!
            .text,
        r'C:\AppData\server-switch\备份包');
    await tester.runAsync(() async {
      final image = await tester
          .renderObject<RenderRepaintBoundary>(
              find.byType(RepaintBoundary).first)
          .toImage();
      final png = await image.toByteData(format: ui.ImageByteFormat.png);
      File('validation/server-backup-default.png')
          .writeAsBytesSync(png!.buffer.asUint8List());
      image.dispose();
    });
    await tester.tap(find.text('服务器切换 / SERVER'));
    await tester.pumpAndSettle();
    await tester.runAsync(() async {
      final image = await tester
          .renderObject<RenderRepaintBoundary>(
              find.byType(RepaintBoundary).first)
          .toImage();
      final png = await image.toByteData(format: ui.ImageByteFormat.png);
      final file = File('validation/server-switch-page.png');
      file.parent.createSync(recursive: true);
      file.writeAsBytesSync(png!.buffer.asUint8List());
      image.dispose();
    });
    await tester.tap(find.text('开始切换'));
    await tester.pump(const Duration(milliseconds: 200));
    expect(backend.calls, contains('serverSwitch.apply'));
    await tester.tap(find.text('返回工具'));
    expect(returned, isTrue);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });

  testWidgets(
      'folder drops import packages, show recognition progress and report rejection',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(960, 540));
    final backend = FixtureBackend()
      ..replies['serverSwitch.import'] = {'taskId': 'import1'};
    backend.settings['game_folder'] = r'C:\Game';
    backend.settings['gimi_folder'] = r'C:\GIMI';
    final controller = NeoController(backend);
    await controller.start();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            const MethodChannel('window_manager'), (_) async => null);
    await tester.pumpWidget(NeoApp(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.text('工具 / TOOLS'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('服务器切换'));
    await tester.pumpAndSettle();
    final drop = find.byKey(const ValueKey('serverSwitch.drop'));
    expect(tester.widget<DropTarget>(drop).enable, isTrue);
    tester.widget<DropTarget>(drop).onDragEntered!(DropEventDetails(
        localPosition: const Offset(60, 60),
        globalPosition: const Offset(92, 122)));
    await tester.pumpAndSettle();
    expect(
        find.byKey(const ValueKey('serverSwitch.drop-hint')), findsOneWidget);
    final details = DropDoneDetails(
        files: [DropItemDirectory(r'C:\Incoming\package', [])],
        localPosition: const Offset(60, 60),
        globalPosition: const Offset(92, 122));
    tester.widget<DropTarget>(drop).onDragDone!(details);
    await tester.pump();
    expect(backend.parameters['serverSwitch.import'],
        {'source': r'C:\Incoming\package'});
    expect(tester.widget<DropTarget>(drop).enable, isFalse);
    expect(find.text('识别中…'), findsWidgets);
    expect(
        tester
            .getRect(find.byKey(const ValueKey('home.bottom-progress')))
            .bottom,
        540);
    expect(find.byKey(const ValueKey('serverSwitch.drop-hint')), findsNothing);
    tester.widget<DropTarget>(drop).onDragDone!(details);
    expect(
        backend.calls.where((m) => m == 'serverSwitch.import'), hasLength(1));
    backend.stream.add({
      'event': 'task.finished',
      'data': {
        'taskId': 'import1',
        'kind': 'serverSwitch.import',
        'state': 'succeeded',
        'message': '替换包已导入（9 个文件）',
        'result': {}
      }
    });
    await tester.pumpAndSettle();
    expect(find.text('替换包已导入（9 个文件）'), findsWidgets);
    expect(find.byKey(const ValueKey('home.bottom-progress')), findsNothing);
    expect(tester.widget<DropTarget>(drop).enable, isTrue);
    backend.replies['serverSwitch.import'] = {'taskId': 'import2'};
    tester.widget<DropTarget>(drop).onDragDone!(details);
    await tester.pump();
    backend.stream.add({
      'event': 'task.finished',
      'data': {
        'taskId': 'import2',
        'kind': 'serverSwitch.import',
        'state': 'failed',
        'message': '不是一个替换包',
        'result': {}
      }
    });
    await tester.pumpAndSettle();
    expect(find.text('不是一个替换包'), findsWidgets);
    expect(find.byKey(const ValueKey('home.bottom-progress')), findsNothing);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
    await backend.close();
  });

  testWidgets('failed preview explains why and never switches game',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(960, 540));
    final backend = SwitchBackend()..failPreview = true;
    final controller = NeoController(backend)..ready = true;
    await tester.pumpWidget(MaterialApp(
        theme: efTheme(Brightness.light),
        home: Scaffold(
            body: NeoServerSwitch(controller: controller, onBack: () {}))));
    await tester.pumpAndSettle();
    expect(find.textContaining('版本不一致'), findsWidgets);
    expect(find.text('本地游戏 / 国服'), findsOneWidget);
    expect(find.text('替换包 / 国服'), findsOneWidget);
    expect(find.text('替换包 / 国际服'), findsOneWidget);
    expect(find.text('未识别'), findsOneWidget);
    expect(find.text('文件不存在'), findsOneWidget);
    await tester.tap(find.text('开始切换'));
    await tester.pumpAndSettle();
    expect(backend.calls.where((call) => call == 'serverSwitch.preview').length,
        2);
    expect(backend.calls, isNot(contains('serverSwitch.apply')));
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });
}
