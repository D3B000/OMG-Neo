import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:omg_neo/backend/neo_controller.dart';
import 'package:omg_neo/bisect_ui.dart';
import 'package:omg_neo/ef/tokens.dart';
import 'package:omg_neo/main.dart';
import 'backend_test.dart' show FixtureBackend;

Map<String, dynamic> fixture(
    {bool fourGroups = false, bool mixed = false, String status = 'ready'}) {
  Map<String, dynamic> node(String id, String label, List<int> ids,
          List<String> children, String? parent) =>
      {
        'id': id,
        'label': label,
        'unitIds': ids.map((i) => 'u$i').toList(),
        'parent': parent,
        'children': children,
        'count': ids.length,
        'enabledCount': ids.where((i) => !mixed || i != 3).length,
        'disabledCount': ids.where((i) => mixed && i == 3).length,
        'state': ids.every((i) => !mixed || i != 3)
            ? 'enabled'
            : ids.every((i) => mixed && i == 3)
                ? 'disabled'
                : 'mixed',
      };
  return {
    'mode': 'manual',
    'status': status,
    'sessionId': 's1',
    'generation': 4,
    'root': r'G:\GIMI\Mods',
    'groupCount': fourGroups ? 4 : 2,
    'stateSource': 'resources.list',
    'message': '可独立启停和继续二分。',
    'units': [
      for (var i = 1; i <= 8; i++)
        {
          'id': 'u$i',
          'name': '测试模组 $i',
          'iniIds': ['i$i'],
          'entryIds': ['e$i'],
          'external': i == 1
        }
    ],
    'entries': [
      for (var i = 1; i <= 8; i++)
        {
          'id': 'e$i',
          'unitId': 'u$i',
          'enabled': !mixed || i != 3,
          'currentName': '测试模组 $i',
          'initialName': '测试模组 $i',
          'parent': r'G:\GIMI\Mods\Hub',
          'aliases': [],
          'originalTarget': 'G:\\ModLibrary\\测试模组 $i'
        }
    ],
    'inis': [
      for (var i = 1; i <= 8; i++)
        {
          'id': 'i$i',
          'unitId': 'u$i',
          'name': 'main.ini',
          'modName': '测试模组 $i',
          'inside': 'main.ini',
          'size': 32,
          'sha256': 'abc123',
          'initialEnabled': true,
          'originalPath': 'G:\\GIMI\\Mods\\Hub\\测试模组 $i\\main.ini',
          'targetPath': 'G:\\ModLibrary\\测试模组 $i\\main.ini',
          'operations': []
        }
    ],
    'nodes': [
      node('root', '已记录模组', [1, 2, 3, 4, 5, 6, 7, 8], ['root.1', 'root.2'],
          null),
      node('root.1', 'A', [1, 2, 3, 4],
          fourGroups ? ['root.1.1', 'root.1.2'] : [], 'root'),
      if (fourGroups) ...[
        node('root.1.1', 'A1', [1, 2], [], 'root.1'),
        node('root.1.2', 'A2', [3, 4], [], 'root.1')
      ],
      node('root.2', 'B', [5, 6, 7, 8],
          fourGroups ? ['root.2.1', 'root.2.2'] : [], 'root'),
      if (fourGroups) ...[
        node('root.2.1', 'B1', [5, 6], [], 'root.2'),
        node('root.2.2', 'B2', [7, 8], [], 'root.2')
      ],
    ],
    'history': [],
    'errors': [],
    'warnings': [],
    'initialDisabled': [],
  };
}

Map<String, dynamic> largeFixture(int count) {
  final state = fixture();
  final nodes = <Map<String, dynamic>>[];
  void add(String id, String label, List<String> ids, String? parent) {
    final children = ids.length > 1 ? ['$id.1', '$id.2'] : <String>[];
    nodes.add({
      'id': id,
      'label': label,
      'parent': parent,
      'unitIds': ids,
      'children': children,
      'count': ids.length,
      'enabledCount': ids.length,
      'disabledCount': 0,
      'state': 'enabled'
    });
    if (ids.length > 1) {
      final mid = (ids.length + 1) ~/ 2;
      add('$id.1', id == 'root' ? 'A' : '${label}1', ids.sublist(0, mid), id);
      add('$id.2', id == 'root' ? 'B' : '${label}2', ids.sublist(mid), id);
    }
  }

  add('root', '全部模组', [for (var i = 1; i <= count; i++) 'u$i'], null);
  state['nodes'] = nodes;
  state['groupCount'] = count;
  state['units'] = [
    for (var i = 1; i <= count; i++)
      {'id': 'u$i', 'name': '长名称模组_${i}_角色服装与贴图替换'}
  ];
  state['entries'] = [
    for (var i = 1; i <= count; i++)
      {
        'id': 'e$i',
        'unitId': 'u$i',
        'enabled': true,
        'relative': 'Hub/Junction/Mod_$i'
      }
  ];
  state['inis'] = [];
  return state;
}

void main() {
  final binding = TestWidgetsFlutterBinding.ensureInitialized();
  Future<void> fonts() async {
    await (FontLoader('MaterialIcons')
          ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf')))
        .load();
    await (FontLoader('Saira')..addFont(rootBundle.load('fonts/Saira.ttf')))
        .load();
    final chinese = File('C:/Windows/Fonts/msyh.ttc');
    if (chinese.existsSync()) {
      await (FontLoader('Noto Sans SC')
            ..addFont(
                Future.value(ByteData.sublistView(chinese.readAsBytesSync()))))
          .load();
    }
  }

  Future<(NeoController, FixtureBackend)> prepare(
      WidgetTester tester, Map<String, dynamic> state,
      {Brightness theme = Brightness.light,
      bool reducedMotion = false,
      Size size = const Size(960, 540),
      Future<String?> Function({required bool folder, String initial})?
          pickPath}) async {
    await binding.setSurfaceSize(size);
    await fonts();
    final backend = FixtureBackend()..replies['bisect.state'] = state;
    final controller = NeoController(backend)
      ..ready = true
      ..bisectState = state;
    addTearDown(controller.dispose);
    await tester.pumpWidget(MaterialApp(
        theme: efTheme(theme),
        builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context)
                .copyWith(disableAnimations: reducedMotion),
            child: child!),
        home: Scaffold(
            body: Padding(
                padding: const EdgeInsets.only(top: 40),
                child: NeoBisect(
                    controller: controller,
                    onBack: () {},
                    pickPath: pickPath,
                    region: (id, child) => KeyedSubtree(
                        key: ValueKey('test.$id'), child: child))))));
    await tester.pumpAndSettle();
    return (controller, backend);
  }

  testWidgets('fixed graph fits two and four groups in both themes',
      (tester) async {
    for (final theme in [Brightness.light, Brightness.dark]) {
      for (final four in [false, true]) {
        await prepare(tester, fixture(fourGroups: four, mixed: four),
            theme: theme);
        expect(
            find.byKey(const ValueKey('graph.current.root.1')), findsOneWidget);
        expect(find.byKey(const ValueKey('test.bisect.child.1')),
            four ? findsOneWidget : findsNothing);
        expect(find.byType(InteractiveViewer), findsNothing);
        expect(find.text('归位'), findsNothing);
        expect(find.textContaining('重载'), findsNothing);
        expect(find.textContaining('基线'), findsNothing);
        final before =
            tester.getRect(find.byKey(const ValueKey('test.bisect.current')));
        await tester.drag(find.byKey(const ValueKey('test.bisect.current')),
            const Offset(50, 40));
        await tester.pumpAndSettle();
        expect(
            tester.getRect(find.byKey(const ValueKey('test.bisect.current'))),
            before);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      }
    }
  });

  testWidgets('operation panel and child toggles target exact groups',
      (tester) async {
    final (controller, backend) =
        await prepare(tester, fixture(fourGroups: true));
    backend.replies['bisect.toggle'] = {'taskId': 'toggle-a'};
    await tester.tap(find.byKey(const ValueKey('group.toggle.root.1')));
    await tester.pump();
    expect(backend.parameters['bisect.toggle']?['groupId'], 'root.1');
    expect(backend.parameters['bisect.toggle']?['enabled'], false);
    expect(backend.parameters['bisect.toggle']?['generation'], 4);
    controller.busy = false;
    controller.notifyListeners();
    await tester.pumpAndSettle();
    controller.bisectState = fixture(fourGroups: true, mixed: true);
    controller.notifyListeners();
    await tester.pumpAndSettle();
    backend.replies['bisect.toggle'] = {'taskId': 'toggle-a2'};
    await tester.tap(find.byKey(const ValueKey('child.toggle.root.1.2')));
    await tester.pump();
    expect(backend.parameters['bisect.toggle']?['groupId'], 'root.1.2');
    expect(backend.parameters['bisect.toggle']?['enabled'], true);
    expect(
        backend.calls
            .where((s) => s.contains('Reload') || s == 'bisect.result'),
        isEmpty);
  });

  testWidgets(
      'navigation is local and splitting leaves the chosen group centered',
      (tester) async {
    final (controller, backend) =
        await prepare(tester, fixture(fourGroups: true));
    await tester.tap(find.byKey(const ValueKey('group.enter.root.1.1')));
    await tester.pumpAndSettle();
    expect(
        find.byKey(const ValueKey('graph.current.root.1.1')), findsOneWidget);
    expect(find.byKey(const ValueKey('group.sibling')), findsOneWidget);
    backend.replies['bisect.split'] = {'taskId': 'split'};
    await tester.tap(find.byKey(const ValueKey('group.split.root.1.1')));
    await tester.pump();
    expect(backend.parameters['bisect.split']?['groupId'], 'root.1.1');
    controller.busy = false;
    controller.notifyListeners();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('bisect.up')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('graph.current.root.1')), findsOneWidget);
    expect(backend.calls.where((s) => s == 'bisect.toggle'), isEmpty);
  });

  testWidgets('reviewed buttons wipe in from left and wipe out from right',
      (tester) async {
    await prepare(tester, fixture(fourGroups: true));
    final toggle = find.byKey(const ValueKey('group.toggle.root.1'));
    expect(tester.getSize(toggle).width, greaterThan(225));
    expect(
        tester
            .getCenter(find.descendant(of: toggle, matching: find.text('停用本组')))
            .dx,
        tester.getCenter(toggle).dx);
    expect(find.byKey(const ValueKey('group.enable.root.1')), findsNothing);
    expect(find.byKey(const ValueKey('group.disable.root.1')), findsNothing);
    expect(find.text('下一级 ↗'), findsNothing);
    expect(find.text('前往 ↗'), findsNWidgets(2));
    final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await mouse.addPointer(location: const Offset(4, 530));
    for (final id in [
      'bisect.restore',
      'child.toggle.root.1.1',
      'child.toggle.root.1.2',
      'group.mods.root.1'
    ]) {
      final button = find.byKey(ValueKey(id));
      final fill = find.descendant(
          of: button, matching: find.byType(FractionallySizedBox));
      expect(tester.widget<FractionallySizedBox>(fill).widthFactor, 0);
      await mouse.moveTo(tester.getCenter(button));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 140));
      final midway = tester.widget<FractionallySizedBox>(fill).widthFactor!;
      expect(midway, greaterThan(0));
      expect(midway, lessThan(1));
      await tester.pumpAndSettle();
      expect(tester.widget<FractionallySizedBox>(fill).widthFactor, 1);
      await mouse.moveTo(const Offset(4, 530));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 140));
      final retreat = tester.widget<FractionallySizedBox>(fill);
      expect(retreat.alignment, Alignment.centerLeft);
      expect(retreat.widthFactor, greaterThan(0));
      expect(retreat.widthFactor, lessThan(1));
      await tester.pumpAndSettle();
      expect(tester.widget<FractionallySizedBox>(fill).widthFactor, 0);
    }
    await mouse.removePointer();
    expect(tester.takeException(), isNull);
  });

  testWidgets('reduced motion disables hover wipe transitions', (tester) async {
    await prepare(tester, fixture(fourGroups: true), reducedMotion: true);
    final action = find.byKey(const ValueKey('bisect.restore'));
    final animation = find.descendant(
        of: action, matching: find.byType(AnimatedFractionallySizedBox));
    expect(tester.widget<AnimatedFractionallySizedBox>(animation).duration,
        Duration.zero);
    final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await mouse.addPointer(location: const Offset(4, 530));
    await mouse.moveTo(tester.getCenter(action));
    await tester.pump();
    await tester.pump();
    final fill = find.descendant(
        of: action, matching: find.byType(FractionallySizedBox));
    expect(tester.widget<FractionallySizedBox>(fill).widthFactor, 1);
    await mouse.moveTo(const Offset(4, 530));
    await tester.pump();
    await tester.pump();
    expect(tester.widget<FractionallySizedBox>(fill).widthFactor, 0);
    await mouse.removePointer();
  });

  testWidgets(
      'group mods and INI details are lazy and scoped to selected group',
      (tester) async {
    await prepare(tester, fixture(fourGroups: true));
    await tester.tap(find.byKey(const ValueKey('group.enter.root.1.1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('group.mods.root.1.1')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('mod.open.u1')), findsOneWidget);
    expect(find.text('测试模组 3'), findsNothing);
    await tester.tap(find.byKey(const ValueKey('mod.open.u1')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('INI / main.ini ↗'));
    await tester.pumpAndSettle();
    expect(find.text('关联启停记录'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('selected directory affects only the next recording',
      (tester) async {
    final (_, backend) = await prepare(tester, {'status': 'idle'},
        pickPath: ({required bool folder, String initial = ''}) async {
      expect(folder, isTrue);
      return r'G:\Other Mods';
    });
    await tester.tap(find.byKey(const ValueKey('bisect.changeDirectory')));
    await tester.pumpAndSettle();
    backend.replies['bisect.scan'] = {'taskId': 'scan'};
    await tester.tap(find.byKey(const ValueKey('bisect.scan')));
    await tester.pump();
    expect(backend.parameters['bisect.scan']?['root'], r'G:\Other Mods');
    expect(backend.calls, isNot(contains('config.patch')));
  });

  testWidgets('restore clears graph and new session starts at A',
      (tester) async {
    final (controller, _) = await prepare(tester, fixture(fourGroups: true));
    await tester.tap(find.byKey(const ValueKey('group.enter.root.1.2')));
    await tester.pumpAndSettle();
    controller.bisectState = fixture(status: 'closed');
    controller.notifyListeners();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('test.bisect.current')), findsNothing);
    expect(find.byKey(const ValueKey('bisect.scan')), findsOneWidget);
    controller.bisectState = fixture()..['sessionId'] = 's2';
    controller.notifyListeners();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('graph.current.root.1')), findsOneWidget);
  });

  testWidgets('1024 mods and deep groups stay in a five node local graph',
      (tester) async {
    final state = largeFixture(1024);
    await prepare(tester, state, theme: Brightness.dark);
    await tester.tap(find.text('分组目录'));
    await tester.pumpAndSettle();
    const target = 'root.1.2.1.2.1.2.1.2';
    final values = (state['nodes'] as List).cast<Map<String, dynamic>>();
    final index = values.indexWhere((n) => n['id'] == target);
    final scroll = tester.state<ScrollableState>(find
        .descendant(
            of: find.byKey(const ValueKey('bisect.catalog.list')),
            matching: find.byType(Scrollable))
        .first);
    scroll.position.jumpTo(index * 46.0);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('catalog.select.$target')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('graph.current.$target')), findsOneWidget);
    expect(find.byKey(const ValueKey('test.bisect.parent')), findsOneWidget);
    expect(find.byKey(const ValueKey('test.bisect.sibling')), findsOneWidget);
    expect(find.byKey(const ValueKey('test.bisect.child.1')), findsOneWidget);
    expect(find.byKey(const ValueKey('test.bisect.child.2')), findsOneWidget);
    expect(find.byKey(const ValueKey('bisect.ancestors')), findsOneWidget);
    expect(find.byType(ListView), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('odd, single, empty, recovery and large windows remain usable',
      (tester) async {
    for (final state in [
      largeFixture(129),
      largeFixture(1),
      {'status': 'idle'},
      fixture(status: 'recovery', fourGroups: true)
    ]) {
      for (final size in [const Size(960, 540), const Size(1280, 720)]) {
        await prepare(tester, state, size: size);
        if (state['status'] == 'recovery') {
          expect(find.byKey(const ValueKey('bisect.resume')), findsOneWidget);
          final child = tester.widget<InkWell>(find
                  .byKey(const ValueKey('child.toggle.root.1.1'))
                  .evaluate()
                  .isEmpty
              ? find.byKey(const ValueKey('group.toggle.root.1'))
              : find.byKey(const ValueKey('child.toggle.root.1.1')));
          expect(child.onTap, isNull);
        }
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      }
    }
  });

  testWidgets(
      'native window matches graph geometry with full width task progress',
      (tester) async {
    for (final theme in [Brightness.light, Brightness.dark]) {
      await binding.setSurfaceSize(const Size(960, 540));
      await fonts();
      const window = MethodChannel('window_manager');
      binding.defaultBinaryMessenger
          .setMockMethodCallHandler(window, (_) async => null);
      final backend = FixtureBackend()
        ..replies['bisect.state'] = fixture(fourGroups: true);
      backend.settings['theme'] = theme.name;
      final controller = NeoController(backend);
      await controller.start();
      controller.status = '';
      await tester.pumpWidget(NeoApp(
          controller: controller, initialDark: theme == Brightness.dark));
      await tester.pumpAndSettle();
      await tester.tap(find.text('工具 / TOOLS'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('二分排查'));
      await tester.pumpAndSettle();
      final canvas =
          tester.getRect(find.byKey(const ValueKey('region.bisect.canvas')));
      final controls =
          tester.getRect(find.byKey(const ValueKey('region.bisect.controls')));
      final focus =
          tester.getRect(find.byKey(const ValueKey('region.bisect.current')));
      expect(canvas.left, 0);
      expect(canvas.width, 960);
      expect(canvas.top, 118);
      expect(controls.left, 28);
      expect(controls.width, 260);
      expect(focus.left, 370);
      expect(focus.top, closeTo(255.44, 1));
      final up = tester.getRect(find.byKey(const ValueKey('bisect.up')));
      final splitAll =
          tester.getRect(find.byKey(const ValueKey('group.splitLeaves')));
      expect(up.size, splitAll.size);
      expect(up.top, splitAll.top);
      final directory =
          tester.getRect(find.byKey(const ValueKey('bisect.directory')));
      final choose =
          tester.getRect(find.byKey(const ValueKey('bisect.changeDirectory')));
      expect(choose.right, 938);
      expect(directory.right, choose.left - 8);
      final trace = tester.widget<Container>(
          find.byKey(const ValueKey('bisect.current.trace')));
      expect(((trace.decoration as BoxDecoration).border as Border).top.color,
          EfColors.of(tester.element(find.byType(NeoBisect))).signal);

      expect(find.byType(InteractiveViewer), findsNothing);
      final boundary = tester.renderObject<RenderRepaintBoundary>(
          find.byType(RepaintBoundary).first);
      await tester.runAsync(() async {
        final image = await boundary.toImage();
        final png = await image.toByteData(format: ui.ImageByteFormat.png);
        await File('shots/bisect-graph-window-${theme.name}.png')
            .writeAsBytes(png!.buffer.asUint8List());
        image.dispose();
      });
      for (final kind in ['bisect.scan', 'bisect.toggle']) {
        controller.busy = true;
        controller.taskKind = kind;
        controller.taskProgress = .5;
        controller.notifyListeners();
        await tester.pump();
        final progress =
            tester.getRect(find.byKey(const ValueKey('home.progress-cells')));
        expect(progress.left, 0);
        expect(progress.right, 960);
        expect(progress.bottom, 540);
      }
      controller.busy = false;
      controller.notifyListeners();
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
      await backend.close();
      binding.defaultBinaryMessenger.setMockMethodCallHandler(window, null);
    }
  });

  test('recovery bypasses rejected unrelated setting drafts', () async {
    final backend = FixtureBackend()
      ..replies['bisect.restore'] = {'taskId': 'restore'};
    final controller = NeoController(backend)..ready = true;
    addTearDown(controller.dispose);
    controller.stage({'gimi_folder': 'draft'});
    controller.bisectActive = true;
    await controller
        .businessTask('bisect.restore', {'sessionId': 's1', 'generation': 1});
    expect(backend.calls, contains('bisect.restore'));
    expect(backend.calls, isNot(contains('settings.flush')));
  });
}
