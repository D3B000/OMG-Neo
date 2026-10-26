import 'dart:async';
import 'dart:io';
import 'dart:convert';
import 'dart:ui' as ui;
import 'package:flutter/gestures.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:omg_neo/main.dart';
import 'package:omg_neo/closing_dialog.dart';
import 'package:omg_neo/build_ui.dart';
import 'package:omg_neo/resources_ui.dart';
import 'package:omg_neo/resource_keys_dialog.dart';
import 'package:omg_neo/review.dart';
import 'package:omg_neo/settings_ui.dart';
import 'package:omg_neo/ef/widgets.dart';
import 'package:omg_neo/ef/toast.dart';
import 'package:omg_neo/ef/menus.dart';
import 'package:omg_neo/ef/marks.dart';
import 'package:omg_neo/ef/tokens.dart';

void main() {
  final binding = TestWidgetsFlutterBinding.ensureInitialized();
  Future<void> prepare(WidgetTester tester) async {
    binding.platformDispatcher.textScaleFactorTestValue = 1;
    await binding.setSurfaceSize(const Size(960, 540));
    final loader = FontLoader('Saira')
      ..addFont(rootBundle.load('fonts/Saira.ttf'));
    await loader.load();
    if (File('C:/Windows/Fonts/msyh.ttc').existsSync()) {
      final chinese = FontLoader('Noto Sans SC')
        ..addFont(Future.value(ByteData.sublistView(
            File('C:/Windows/Fonts/msyh.ttc').readAsBytesSync())));
      await chinese.load();
    }
    final icons = FontLoader('MaterialIcons')
      ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
    await icons.load();
    final consoleFont = File('C:/Windows/Fonts/consola.ttf');
    if (consoleFont.existsSync()) {
      final console = FontLoader('Consolas')
        ..addFont(
            Future.value(ByteData.sublistView(consoleFont.readAsBytesSync())));
      await console.load();
    }
  }

  Future<void> shot(WidgetTester tester, String name,
      {bool settle = true}) async {
    if (settle) {
      await tester.pumpAndSettle();
    } else {
      await tester.pump();
    }
    expect(tester.takeException(), isNull);
    final boundary = tester.renderObject<RenderRepaintBoundary>(
        find.byType(RepaintBoundary).first);
    await tester.runAsync(() async {
      final image = await boundary.toImage(pixelRatio: 1);
      final data = await image.toByteData(format: ui.ImageByteFormat.png);
      await Directory('shots').create(recursive: true);
      await File('shots/$name.png').writeAsBytes(data!.buffer.asUint8List());
      image.dispose();
    });
  }

  testWidgets(
      'resource settings use checks and combine enabled priority with visible-name sorting',
      (tester) async {
    await prepare(tester);
    for (final brightness in [Brightness.light, Brightness.dark]) {
      final draft = ResourcesDraft()..path.add('角色');
      draft.items
        ..clear()
        ..addAll([
          ResourcePreview('folder', '0 Folder', '角色', '', '', isMod: false),
          ResourcePreview('bravo', 'Bravo', '角色', '', ''),
          ResourcePreview('alpha', 'DISABLED Alpha', '角色', '', '',
              enabled: false),
          ResourcePreview('charlie', 'DISABLED Charlie', '角色', '', '',
              enabled: false),
          ResourcePreview('zulu', 'Zulu', '角色', '', ''),
        ]);
      await tester.pumpWidget(RepaintBoundary(
          child: MaterialApp(
              debugShowCheckedModeBanner: false,
              theme: efTheme(brightness),
              home: Scaffold(
                  body: ResourceBrowser(
                      draft: draft,
                      region: (_, child) => child,
                      notice: (_) {},
                      onSettings: () {})))));
      await tester.pumpAndSettle();
      void order(List<String> ids) {
        double previous = -1;
        for (final id in ids) {
          final point =
              tester.getTopLeft(find.byKey(ValueKey('resources.card.$id')));
          final rank = point.dy * 10000 + point.dx;
          expect(rank, greaterThan(previous), reason: 'card $id');
          previous = rank;
        }
      }

      bool checked(String id) => (tester
              .widget<MenuItemButton>(
                  find.byKey(ValueKey('resources.settings.$id')))
              .leadingIcon as SizedBox)
          .child is Icon;
      Future<void> menu() async {
        await tester.tap(find.text('设置'));
        await tester.pumpAndSettle();
      }

      Future<void> choose(String id) async {
        await tester.tap(find.byKey(ValueKey('resources.settings.$id')));
        await tester.pumpAndSettle();
      }

      order(['bravo', 'zulu', 'folder', 'alpha', 'charlie']);
      expect(find.text('Alpha'), findsOneWidget);
      await menu();
      expect(checked('enabled-first'), isTrue);
      expect(checked('disabled-prefix'), isFalse);
      expect(checked('empty-folders'), isTrue);
      await shot(tester, 'resources-settings-checks-${brightness.name}');
      await choose('enabled-first');
      order(['folder', 'alpha', 'bravo', 'charlie', 'zulu']);
      await menu();
      expect(checked('enabled-first'), isFalse);
      await choose('disabled-prefix');
      order(['folder', 'bravo', 'alpha', 'charlie', 'zulu']);
      expect(find.text('DISABLED Alpha'), findsOneWidget);
      await menu();
      expect(checked('disabled-prefix'), isTrue);
      expect(find.text('显示 DISABLED 前缀'), findsOneWidget);
      await choose('enabled-first');
      order(['bravo', 'zulu', 'folder', 'alpha', 'charlie']);
      await menu();
      await choose('disabled-prefix');
      order(['bravo', 'zulu', 'folder', 'alpha', 'charlie']);
      expect(draft.items.map((e) => e.id).toList(),
          ['folder', 'bravo', 'alpha', 'charlie', 'zulu']);
      expect(draft.items[2].enabled, isFalse);
      await tester.pumpWidget(const SizedBox());
      draft.dispose();
    }
  });

  testWidgets(
      'disabled prefix is display-only and state tabs expand in both themes',
      (tester) async {
    await prepare(tester);
    for (final brightness in [Brightness.light, Brightness.dark]) {
      final draft = ResourcesDraft()..path.add('角色');
      draft.items
        ..clear()
        ..addAll([
          ResourcePreview('off', 'DISABLED 示例模组', '角色', '', '', enabled: false),
          ResourcePreview('literal', 'My DISABLED caption', '角色', '', ''),
          ResourcePreview('joined', 'DisabledFoo', '角色', '', ''),
        ]);
      await tester.pumpWidget(RepaintBoundary(
          child: MaterialApp(
              debugShowCheckedModeBanner: false,
              theme: efTheme(brightness),
              home: Scaffold(
                  body: ResourceBrowser(
                      draft: draft,
                      region: (_, child) => child,
                      notice: (_) {},
                      onSettings: () {})))));
      await tester.pumpAndSettle();
      final tab = find.byKey(const ValueKey('resources.status.off'));
      final fill =
          find.descendant(of: tab, matching: find.byType(AnimatedContainer));
      double width() =>
          tester.getSize(fill).width /
          tester
              .getSize(find.byKey(const ValueKey('resources.status-track.off')))
              .width;
      expect(find.text('示例模组'), findsOneWidget);
      expect(find.text('DISABLED 示例模组'), findsNothing);
      expect(find.text('My DISABLED caption'), findsOneWidget);
      expect(find.text('DisabledFoo'), findsOneWidget);
      expect(width(), closeTo(0, .001));
      await shot(tester, 'resources-prefix-hidden-${brightness.name}');
      await tester.tap(find.text('设置'));
      await tester.pumpAndSettle();
      expect(find.text('显示 DISABLED 前缀'), findsOneWidget);
      await tester.tap(
          find.byKey(const ValueKey('resources.settings.disabled-prefix')));
      await tester.pumpAndSettle();
      expect(find.text('DISABLED 示例模组'), findsOneWidget);
      expect(draft.items.first.enabled, isFalse);
      expect(width(), closeTo(0, .001));
      await shot(tester, 'resources-prefix-shown-${brightness.name}');
      await tester.tap(find.byKey(const ValueKey('resources.item.off')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 200));
      expect(width(), greaterThan(0));
      expect(width(), lessThan(1));
      await shot(tester, 'resources-enable-mid-${brightness.name}',
          settle: false);
      await tester.pumpAndSettle();
      expect(width(), closeTo(1, .001));
      await tester.tap(find.byKey(const ValueKey('resources.item.off')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 200));
      expect(width(), greaterThan(0));
      expect(width(), lessThan(1));
      await tester.pumpAndSettle();
      expect(width(), closeTo(0, .001));
      expect(draft.items.first.name, 'DISABLED 示例模组');
      binding.platformDispatcher.accessibilityFeaturesTestValue =
          const FakeAccessibilityFeatures(disableAnimations: true);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('resources.item.off')));
      await tester.pump();
      expect(width(), closeTo(1, .001));
      expect(tester.widget<AnimatedFractionallySizedBox>(tab).duration,
          Duration.zero);
      binding.platformDispatcher.clearAccessibilityFeaturesTestValue();
      await tester.pumpWidget(const SizedBox());
      draft.dispose();
    }
  });

  testWidgets('key binding records enter and scroll without hiding long keys',
      (tester) async {
    await prepare(tester);
    for (final dark in [false, true]) {
      await tester.pumpWidget(RepaintBoundary(
          child: NeoApp(key: ValueKey(dark), initialDark: dark)));
      await tester.pumpAndSettle();
      showEfDialog<void>(
          context: tester.element(find.byType(Workspace)),
          builder: (_) => ResourceKeysDialog(
              name: '资源切换键',
              bindings: Future.value([
                for (var i = 0; i < 18; i++)
                  (
                    'KeySwapLongSection$i / \$long_variable_name_$i',
                    'NO_SHIFT NO_ALT CTRL ${i + 1} / BACKSPACE'
                  ),
              ])));
      await tester.pump();
      await tester.pump();
      await tester.pump(Ef.dialogIn + const Duration(milliseconds: 1));
      await tester.pump();
      final first = find.byKey(const ValueKey('resources.keys.entrance.0'));
      final second = find.byKey(const ValueKey('resources.keys.entrance.1'));
      expect(tester.widget<Opacity>(first).opacity, 0);
      await tester.pump(const Duration(milliseconds: 80));
      expect(tester.widget<Opacity>(first).opacity,
          greaterThan(tester.widget<Opacity>(second).opacity));
      await tester.pumpAndSettle();
      expect(tester.widget<Opacity>(first).opacity, 1);
      final scrollbar = find.byKey(const ValueKey('resources.keys.scrollbar'));
      final raw = tester.widget<RawScrollbar>(scrollbar);
      expect(raw.radius, isNull);
      expect(raw.shape, isA<BeveledRectangleBorder>());
      expect(raw.controller!.position.maxScrollExtent, greaterThan(0));
      final bar = tester.getRect(scrollbar);
      final value =
          tester.getRect(find.byKey(const ValueKey('resources.keys.value.0')));
      expect(bar.right - value.right, greaterThanOrEqualTo(18));
      final keyText =
          tester.widget<Text>(find.text('NO_SHIFT NO_ALT CTRL 1 / BACKSPACE'));
      expect(keyText.maxLines, isNull);
      expect(keyText.overflow, isNot(TextOverflow.ellipsis));
      await shot(tester, 'key-bindings-${dark ? 'dark' : 'light'}');
      await tester.dragFrom(
          Offset(bar.right - 4, bar.top + 12), const Offset(0, 90));
      await tester.pumpAndSettle();
      expect(raw.controller!.offset, greaterThan(0));
      await tester.scrollUntilVisible(
          find.byKey(const ValueKey('resources.keys.row.17')), 150,
          scrollable: find.descendant(
              of: find.byKey(const ValueKey('resources.keys.list')),
              matching: find.byType(Scrollable)));
      await tester.pumpAndSettle();
      expect(find.text('NO_SHIFT NO_ALT CTRL 18 / BACKSPACE'), findsOneWidget);
      await shot(tester, 'key-bindings-end-${dark ? 'dark' : 'light'}');
      await tester.tap(find.text('关闭'));
      await tester.pumpAndSettle();
    }
  });

  testWidgets('key bindings respect reduced motion and retain async states',
      (tester) async {
    await prepare(tester);
    binding.platformDispatcher.accessibilityFeaturesTestValue =
        const FakeAccessibilityFeatures(disableAnimations: true);
    addTearDown(binding.platformDispatcher.clearAccessibilityFeaturesTestValue);
    await tester.pumpWidget(const NeoApp());
    await tester.pumpAndSettle();
    final pending = Completer<List<(String, String)>>();
    showEfDialog<void>(
        context: tester.element(find.byType(Workspace)),
        builder: (_) =>
            ResourceKeysDialog(name: '异步切换键', bindings: pending.future));
    await tester.pump();
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    pending.complete(
        [('KeyOutfit / \$swap', 'X'), ('KeyBack / \$back', 'SHIFT X')]);
    await tester.pump();
    await tester.pump();
    expect(
        tester
            .widget<Opacity>(
                find.byKey(const ValueKey('resources.keys.entrance.0')))
            .opacity,
        1);
    await tester.pumpAndSettle();
    expect(tester.binding.transientCallbackCount, 0);
    expect(find.text('SHIFT X'), findsOneWidget);
    await tester.tap(find.text('关闭'));
    await tester.pumpAndSettle();
    for (final fail in [false, true]) {
      final result = Completer<List<(String, String)>>();
      showEfDialog<void>(
          context: tester.element(find.byType(Workspace)),
          builder: (_) =>
              ResourceKeysDialog(name: '读取结果', bindings: result.future));
      await tester.pump();
      if (fail) {
        result.completeError(StateError('fixture read failure'));
      } else {
        result.complete([]);
      }
      await tester.pumpAndSettle();
      expect(find.textContaining(fail ? '读取失败：' : '未在 INI 中找到切换键。'),
          findsOneWidget);
      await tester.tap(find.text('关闭'));
      await tester.pumpAndSettle();
    }
  });

  testWidgets(
      'F8 reviews focused modal routes and preserves them in both themes',
      (tester) async {
    await prepare(tester);
    for (final dark in [false, true]) {
      await tester.pumpWidget(NeoApp(key: ValueKey(dark), initialDark: dark));
      await tester.pumpAndSettle();
      final context = tester.element(find.byType(Workspace));
      showEfDialog<void>(
          context: context,
          barrierDismissible: false,
          builder: (dialogContext) => EfDialog(
                  title: const Text('保留中的模态弹窗'),
                  content: Column(mainAxisSize: MainAxisSize.min, children: [
                    const SizedBox(
                        key: ValueKey('modal.marker'),
                        width: 200,
                        height: 24,
                        child: ColoredBox(color: Color(0xff123456))),
                    const TextField(
                        key: ValueKey('modal.input'), autofocus: true),
                  ]),
                  actions: [
                    EfButton('关闭测试弹窗',
                        onPressed: () => Navigator.pop(dialogContext))
                  ]));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const ValueKey('modal.input')), '保留输入');
      final marker =
          tester.getCenter(find.byKey(const ValueKey('modal.marker')));
      await tester.sendKeyEvent(LogicalKeyboardKey.f8);
      await tester.sendKeyEvent(LogicalKeyboardKey.f8);
      await tester.pumpAndSettle();
      await tester.runAsync(() async {
        await Future<void>.delayed(const Duration(milliseconds: 150));
      });
      await tester.pumpAndSettle();
      expect(find.byType(ReviewEditor), findsOneWidget);
      final editor = tester.widget<ReviewEditor>(find.byType(ReviewEditor));
      expect(editor.snapshot.width, 960);
      expect(editor.snapshot.height, 540);
      await tester.runAsync(() async {
        final pixels = await editor.snapshot.toByteData();
        final offset = (marker.dy.floor() * 960 + marker.dx.floor()) * 4;
        expect(pixels!.buffer.asUint8List(offset, 4), [0x12, 0x34, 0x56, 0xff]);
      });
      await tester.sendKeyEvent(LogicalKeyboardKey.f8);
      await tester.pumpAndSettle();
      expect(find.byType(ReviewEditor), findsOneWidget);
      await shot(tester, 'review-modal-${dark ? 'dark' : 'light'}');
      await tester.tap(find.byTooltip('关闭调整工具'));
      await tester.pumpAndSettle();
      expect(find.text('保留中的模态弹窗'), findsOneWidget);
      expect(find.text('保留输入'), findsOneWidget);
      await tester.tap(find.text('关闭测试弹窗'));
      await tester.pumpAndSettle();
    }
    await tester.pumpWidget(const SizedBox());
    await tester.sendKeyEvent(LogicalKeyboardKey.f8);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets('image preview actions retain Endfield styling in both themes',
      (tester) async {
    await prepare(tester);
    final draft = ResourcesDraft()..path.add('角色');
    for (final brightness in [Brightness.light, Brightness.dark]) {
      await tester.pumpWidget(RepaintBoundary(
          child: MaterialApp(
              debugShowCheckedModeBanner: false,
              theme: efTheme(brightness),
              home: Scaffold(
                  body: ResourceBrowser(
                      draft: draft,
                      region: (_, child) => child,
                      notice: (_) {},
                      onSettings: () {})))));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('resources.thumbnail.a1')));
      await shot(tester, 'image-preview-${brightness.name}');
      final open = find.byKey(const ValueKey('resources.preview.open'));
      expect(tester.widget<EfButton>(open).onPressed, isNull);
      expect(tester.getCenter(open).dx,
          lessThan(tester.getCenter(find.text('关闭')).dx));
      await tester.tap(find.text('关闭'));
      await tester.pumpAndSettle();
    }
    await tester.pumpWidget(const SizedBox());
    draft.dispose();
  });

  testWidgets('ritual target text stays inside compact field in both themes',
      (tester) async {
    await prepare(tester);
    final draft = BuildDraft();
    draft.target.text =
        r'G:\ObjNotFound\Tool4game\Landfill\OMG-RE\OMG-Neo\omg_neo\dist\OMG-Neo\AppData\build-work\artifact\d3d11.dll';
    for (final brightness in [Brightness.light, Brightness.dark]) {
      await tester.pumpWidget(RepaintBoundary(
          child: MaterialApp(
              debugShowCheckedModeBanner: false,
              theme: efTheme(brightness),
              home: Scaffold(
                  body: Padding(
                      padding: const EdgeInsets.all(32),
                      child: BuildConsole(
                          draft: draft,
                          onBack: () {},
                          region: (_, child) => child))))));
      final field = find.byKey(const ValueKey('build.target'));
      await tester.ensureVisible(field);
      await tester.pumpAndSettle();
      final editable =
          find.descendant(of: field, matching: find.byType(EditableText));
      final textBox = tester.getRect(editable);
      final fieldBox = tester.getRect(field);
      expect(textBox.top, greaterThanOrEqualTo(fieldBox.top));
      expect(textBox.bottom, lessThanOrEqualTo(fieldBox.bottom));
      expect(textBox.height, greaterThanOrEqualTo(10));
      await shot(tester, 'build-target-${brightness.name}');
    }
    await tester.pumpWidget(const SizedBox());
    draft.dispose();
  });

  testWidgets('terminal follows new output even after scrolling to older lines',
      (tester) async {
    await prepare(tester);
    final draft = BuildDraft();
    draft.logs.addAll(List.generate(60, (i) => '输出 ${i + 1}'));
    late StateSetter rebuild;
    await tester.pumpWidget(MaterialApp(
        theme: efTheme(Brightness.light),
        home: Scaffold(body: StatefulBuilder(builder: (context, setState) {
          rebuild = setState;
          return BuildConsole(
              draft: draft, onBack: () {}, region: (_, child) => child);
        }))));
    await tester.pumpAndSettle();
    final controller =
        tester.widget<ListView>(find.byType(ListView)).controller!;
    expect(controller.offset, controller.position.maxScrollExtent);
    controller.jumpTo(0);
    rebuild(() => draft.logs.add('最新输出\n最后一行'));
    await tester.pumpAndSettle();
    expect(controller.offset, controller.position.maxScrollExtent);
    expect(find.text('最后一行').hitTestable(), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    draft.dispose();
  });
  testWidgets('navigation, build stages, themes and review export',
      (tester) async {
    await prepare(tester);
    await tester.pumpWidget(const RepaintBoundary(child: NeoApp()));
    await shot(tester, 'home');
    expect(find.byType(EfTriStrip), findsNothing);
    expect(find.text('Ordinarily Manage GIMI'), findsOneWidget);
    expect(find.text('你的模组工作空间。'), findsNothing);
    expect(find.byType(Checkbox), findsNothing);
    expect(EfColors.of(tester.element(find.byType(Workspace))).signal,
        const Color(0xFF39C5BB));
    await tester.tap(find.text('工具 / TOOLS'));
    await shot(tester, 'tools');
    await tester.tap(find.text('便捷构建'));
    await shot(tester, 'build-download');
    final cardsScroll = find.byKey(const ValueKey('build.cards-scroll'));
    final terminalRegion = find.byKey(const ValueKey('region.build.terminal'));
    expect(tester.getTopLeft(terminalRegion).dx, greaterThan(500));
    expect(
        tester.getBottomRight(terminalRegion).dy,
        lessThanOrEqualTo(tester
                .getTopLeft(
                    find.byKey(const ValueKey('region.navigation.bottom')))
                .dy -
            8));
    expect(find.text('重新检测'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('build.download')));
    await tester.pumpAndSettle();
    expect(find.text('[预览] 下载源码：尚未连接业务。').hitTestable(), findsOneWidget);
    await shot(tester, 'build-terminal');
    final terminalHeader =
        tester.getRect(find.byKey(const ValueKey('build.terminal-header')));
    expect(terminalHeader.height, 32);
    expect(
        terminalHeader.contains(
            tester.getCenter(find.byKey(const ValueKey('build.export-log')))),
        isTrue);
    expect(
        terminalHeader.contains(
            tester.getCenter(find.byKey(const ValueKey('build.clear-log')))),
        isTrue);
    expect(find.text('>_'), findsOneWidget);
    expect(find.text('// TERMINAL'), findsNothing);
    await tester.runAsync(() async {
      await tester.tap(find.byKey(const ValueKey('build.export-log')));
    });
    for (var attempt = 0;
        attempt < 100 &&
            find.byKey(const ValueKey('build.export-path')).evaluate().isEmpty;
        attempt++) {
      await tester.runAsync(
          () => Future<void>.delayed(const Duration(milliseconds: 20)));
      await tester.pump();
    }
    await tester.pumpAndSettle();
    final exportedPath = tester
        .widget<SelectableText>(find.byKey(const ValueKey('build.export-path')))
        .data!;
    await tester.runAsync(() async {
      final contents = await File(exportedPath).readAsString();
      expect(contents, contains('[预览] 下载源码：尚未连接业务。'));
    });
    await tester.tap(find.text('关闭'));
    await tester.pumpAndSettle();
    await tester.drag(cardsScroll, const Offset(0, -1000));
    await tester.pumpAndSettle();
    final nav =
        tester.getRect(find.byKey(const ValueKey('region.navigation.bottom')));
    expect(
        tester
            .getBottomRight(
                find.byKey(const ValueKey('region.build.automation')))
            .dy,
        lessThanOrEqualTo(nav.top - 8));
    await tester.tap(find.byKey(const ValueKey('build.autoRitual')));
    await tester.pumpAndSettle();
    expect(
        tester
            .widget<EfSwitch>(find.byKey(const ValueKey('build.autoRitual')))
            .value,
        isTrue);
    await shot(tester, 'build-automation');
    expect(tester.getBottomRight(terminalRegion).dy,
        lessThanOrEqualTo(nav.top - 8));
    await tester.tap(find.text('设置 / CONFIG'));
    await shot(tester, 'settings');
    await tester.tap(find.text('OMG'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, '强调色'), '#7DE6FF');
    await tester.tap(find.text('应用颜色'));
    await tester.pumpAndSettle();
    expect(EfColors.of(tester.element(find.byType(Workspace))).signal,
        const Color(0xFF7DE6FF));
    await shot(tester, 'settings-accent');
    await tester.tap(find.text('恢复默认'));
    await tester.pumpAndSettle();
    expect(EfColors.of(tester.element(find.byType(Workspace))).signal,
        const Color(0xFF39C5BB));
    await tester.tap(find.byKey(const ValueKey('settings.dark')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('首页 / HOME'));
    await shot(tester, 'home-dark');
    await tester.tap(find.text('工具 / TOOLS'));
    await tester.pumpAndSettle();
    final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await mouse.addPointer(location: Offset.zero);
    await mouse.moveTo(tester.getCenter(find.text('便捷构建')));
    await tester.pumpAndSettle();
    final hovered = tester.widget<Text>(find.text('便捷构建'));
    expect(hovered.style!.color, const Color(0xFF161616));
    await shot(tester, 'tools-dark-hover');
    await mouse.removePointer();
    await tester.tap(find.text('便捷构建'));
    await shot(tester, 'build-dark');
    await tester.tap(find.byKey(const ValueKey('build.clear-log')));
    await tester.pumpAndSettle();
    expect(find.text('终端已清空，后续操作的输出将显示在这里。'), findsOneWidget);
    await shot(tester, 'build-terminal-empty-dark');
    await tester.drag(find.byKey(const ValueKey('build.cards-scroll')),
        const Offset(0, 1000));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('build.source.1')));
    await tester.pumpAndSettle();
    expect(find.text('已构建文件无需本地构建。\n可在文件优化卡片中选择目标文件并执行优化。'), findsOneWidget);
    await shot(tester, 'build-prebuilt');
    await tester.ensureVisible(find.byKey(const ValueKey('build.ritual')));
    await tester.tap(find.byKey(const ValueKey('build.ritual')));
    await tester.pumpAndSettle();
    expect(find.text('涂装(py)'), findsNothing);
    await tester.tap(find.text('清理'));
    await shot(tester, 'build-cleanup');
    await tester.tap(find.text('返回构建'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('首页 / HOME'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('UI 调整工具 / F8'));
    await tester.runAsync(() async {
      await Future<void>.delayed(const Duration(milliseconds: 150));
    });
    await tester.pumpAndSettle();
    expect(find.byType(ReviewEditor), findsOneWidget);
    final canvas = find.byType(RawImage).last;
    final rect = tester.getRect(canvas);
    final canvasScale = rect.width / 960;
    await tester.dragFrom(rect.topLeft + const Offset(350, 240) * canvasScale,
        const Offset(160, 40) * canvasScale);
    await tester.pumpAndSettle();
    expect(find.text('#1 未填写说明'), findsOneWidget);
    await tester.enterText(find.byType(TextField).first, '将此区域向右移动 12 像素');
    await shot(tester, 'review');
    await tester.runAsync(() async {
      await tester.tap(find.text('导出图片与 JSON'));
      await Future<void>.delayed(const Duration(milliseconds: 800));
    });
    await tester.pumpAndSettle();
    expect(
        find.byWidgetPredicate(
            (w) => w is SelectableText && (w.data?.contains('已导出原图') ?? false)),
        findsOneWidget);
    await tester.runAsync(() async {
      final exports = Directory('ui-reviews')
          .listSync()
          .whereType<File>()
          .where((f) => f.path.endsWith('.json'))
          .toList()
        ..sort((a, b) => b.path.compareTo(a.path));
      final data = jsonDecode(await exports.first.readAsString())
          as Map<String, dynamic>;
      expect(data['canvas'], {'width': 960.0, 'height': 540.0});
      expect(data['annotations'][0]['note'], '将此区域向右移动 12 像素');
      expect(data['annotations'][0]['components'], contains('home.launch'));
      expect(data['annotations'][0]['normalized']['width'], greaterThan(0));
      expect(
          await File(exports.first.path.replaceAll('.json', '-marked.png'))
              .length(),
          greaterThan(1000));
    });
  });
  testWidgets(
      'ported settings fields, whitelist and advanced form interactions',
      (tester) async {
    await prepare(tester);
    await tester.pumpWidget(const RepaintBoundary(child: NeoApp()));
    await tester.tap(find.text('设置 / CONFIG'));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byKey(const ValueKey('settings.path.game')), r'C:\Games\Game');
    await tester.enterText(
        find.byKey(const ValueKey('settings.path.gimi')), r'C:\Tools\GIMI');
    await tester.tap(find.byKey(const ValueKey('settings.help.游戏')));
    await tester.pumpAndSettle();
    expect(find.byType(EfDialog), findsOneWidget);
    await tester.tap(find.text('关闭'));
    await tester.pumpAndSettle();
    await shot(tester, 'settings-paths');
    await tester.tap(find.text('GIMI').first);
    await tester.pumpAndSettle();
    expect(
        find.byKey(const ValueKey('settings.card.D3DX.INI')), findsOneWidget);
    expect(find.byKey(const ValueKey('settings.card.UPDATES')), findsOneWidget);
    final hunting = find.byType(EfSegmented).first;
    await tester.tap(find.descendant(of: hunting, matching: find.text('1')));
    await tester.pumpAndSettle();
    expect(tester.widget<EfSegmented>(hunting).current, 1);
    await tester.tap(find.byKey(const ValueKey('settings.autoCheck')));
    await tester.pumpAndSettle();
    await shot(tester, 'settings-gimi');
    final form = find.descendant(
        of: find.byType(NeoSettings),
        matching: find.byType(SingleChildScrollView));
    await tester.drag(form, const Offset(0, -220));
    await tester.pumpAndSettle();
    expect(find.text('添加文件'), findsOneWidget);
    expect(find.text('添加文件夹'), findsOneWidget);
    expect(find.text('删除'), findsOneWidget);
    expect(find.text('示例配置.ini'), findsOneWidget);
    expect(find.text('示例日志.txt'), findsOneWidget);
    expect(find.text('示例目录/'), findsOneWidget);
    await shot(tester, 'settings-whitelist-examples');
    await tester.tap(find.byTooltip('添加白名单文件'));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.descendant(
            of: find.byType(EfDialog), matching: find.byType(TextField)),
        'd3dx.ini');
    await tester.tap(find.text('确定'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('添加白名单文件夹'));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.descendant(
            of: find.byType(EfDialog), matching: find.byType(TextField)),
        'Mods');
    await tester.tap(find.text('确定'));
    await tester.pumpAndSettle();
    expect(find.text('Mods/'), findsOneWidget);
    await shot(tester, 'settings-whitelist');
    await tester.drag(form, const Offset(0, -1000));
    await tester.pumpAndSettle();
    final settingsNav =
        tester.getRect(find.byKey(const ValueKey('region.navigation.bottom')));
    expect(
        tester
            .getBottomRight(find.byKey(const ValueKey('settings.card.UPDATES')))
            .dy,
        lessThanOrEqualTo(settingsNav.top - 8));
    await shot(tester, 'settings-cards-bottom');
    await tester.tap(find.byTooltip('删除选中的白名单条目'));
    await tester.pumpAndSettle();
    expect(find.text('Mods/'), findsNothing);
    await tester.tap(find.text('启动'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('settings.command')), findsNothing);
    await tester.tap(find.byKey(const ValueKey('settings.custom')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('settings.command')),
        r'C:\Tools\Launcher.exe -windowed');
    await tester.tap(find.text('Bypass'));
    await tester.pumpAndSettle();
    await shot(tester, 'settings-startup');
    await tester
        .ensureVisible(find.byKey(const ValueKey('settings.libraries')));
    await tester.tap(find.byKey(const ValueKey('settings.libraries')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const ValueKey('settings.dlls')));
    await tester.enterText(
        find.byKey(const ValueKey('settings.dlls')), r'C:\Tools\ReShade64.dll');
    await shot(tester, 'settings-libraries');
    await tester.tap(find.text('OMG'));
    await tester.pumpAndSettle();
    expect(find.text('窗口选项'), findsNothing);
    expect(find.byKey(const ValueKey('settings.pinned')), findsNothing);
    expect(find.byKey(const ValueKey('settings.opacity')), findsNothing);
    expect(find.byKey(const ValueKey('settings.hold')), findsNothing);
    expect(find.byKey(const ValueKey('settings.holdMs')), findsNothing);
    expect(find.text('打开 UI 调整工具'), findsOneWidget);
    await shot(tester, 'settings-omg');
    await tester.tap(find.text('路径'));
    await tester.pumpAndSettle();
    expect(
        tester
            .widget<TextField>(find.byKey(const ValueKey('settings.path.game')))
            .controller!
            .text,
        r'C:\Games\Game');
    await tester.tap(find.text('首页 / HOME'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('设置 / CONFIG'));
    await tester.pumpAndSettle();
    expect(
        tester
            .widget<TextField>(find.byKey(const ValueKey('settings.path.game')))
            .controller!
            .text,
        r'C:\Games\Game');
  });
  testWidgets('help dialog and association page render in both themes',
      (tester) async {
    await prepare(tester);
    await tester.pumpWidget(const RepaintBoundary(child: NeoApp()));
    for (final mode in ['light', 'dark']) {
      await tester.tap(find.text('设置 / CONFIG'));
      await tester.pumpAndSettle();
      if (mode == 'dark') {
        await tester.tap(find.text('OMG'));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('settings.dark')));
        await tester.pumpAndSettle();
        await tester.tap(find.text('路径'));
        await tester.pumpAndSettle();
      }
      await tester.tap(find.byKey(const ValueKey('settings.help.游戏')));
      await tester.pumpAndSettle();
      expect(find.text('// HELP'), findsOneWidget);
      await shot(tester, 'dialog-help-$mode');
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      await tester.pumpAndSettle();
      expect(find.byType(EfDialog), findsNothing);
      await tester.tap(find.text('工具 / TOOLS'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('region.tools.link')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('links.tab.0')));
      await tester.pumpAndSettle();
      expect(find.byType(TextField), findsNWidgets(3));
      expect(
          find.byKey(const ValueKey('region.links.junction')), findsOneWidget);
      await shot(tester, 'links-$mode');
      await tester.tap(find.byKey(const ValueKey('links.tab.1')));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('region.links.junction')), findsNothing);
      expect(
          find.byKey(const ValueKey('region.links.include')), findsOneWidget);
      expect(find.byType(TextField), findsOneWidget);
      await shot(tester, 'links-include-$mode');
      await tester.tap(find.text('返回工具'));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('region.tools.link')), findsOneWidget);
    }
  });
  testWidgets(
      'cache confirmation preserves cancel and confirm with reduced motion',
      (tester) async {
    await prepare(tester);
    final draft = SettingsDraft()..page = 3;
    var cleared = 0;
    var scanned = 0;
    for (final brightness in [Brightness.light, Brightness.dark]) {
      await tester.pumpWidget(RepaintBoundary(
          child: MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: efTheme(brightness, accent: const Color(0xFF39C5BB)),
        builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context).copyWith(disableAnimations: true),
            child: child!),
        home: Scaffold(
            body: Padding(
                padding: const EdgeInsets.all(32),
                child: NeoSettings(
                    draft: draft,
                    dark: brightness == Brightness.dark,
                    live: true,
                    onTheme: () {},
                    onAccent: (_) {},
                    openReview: () {},
                    cacheBytes: 1024,
                    onRefreshCache: () => scanned++,
                    cacheClearing: true,
                    cacheProgress: .5,
                    cacheMessage: '正在清理旧备份',
                    onClearCache: () => cleared++,
                    region: (_, child) => child))),
      )));
      await tester.pumpAndSettle();
      expect(scanned, greaterThanOrEqualTo(1));
      final beforeRefresh = scanned;
      await tester.tap(find.text('刷新用量'));
      await tester.pumpAndSettle();
      expect(scanned, beforeRefresh + 1);
      final progress = find.byKey(const ValueKey('settings.cache.progress'));
      expect(tester.widget<LinearProgressIndicator>(progress).value, .5);
      expect(tester.getTopLeft(progress).dy,
          greaterThan(tester.getBottomRight(find.text('清理缓存与备份')).dy));
      await tester.tap(find.byKey(const ValueKey('settings.cleanupOnExit')));
      await tester.pumpAndSettle();
      expect(draft.toSettings()['cleanup_on_exit'],
          brightness == Brightness.light);
      await tester.tap(find.text('清理缓存与备份'));
      await tester.pump();
      final route = ModalRoute.of(tester.element(find.byType(EfDialog)))!;
      expect(route.transitionDuration, Duration.zero);
      expect(route.animation!.status, AnimationStatus.completed);
      expect(find.text('// CONFIRM'), findsOneWidget);
      await shot(tester, 'dialog-confirm-${brightness.name}');
      await tester.sendKeyEvent(LogicalKeyboardKey.tab);
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pumpAndSettle();
      expect(find.byType(EfDialog), findsNothing);
      expect(cleared, brightness == Brightness.light ? 0 : 1);
      await tester.tap(find.text('清理缓存与备份'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('清理'));
      await tester.pumpAndSettle();
      expect(cleared, brightness == Brightness.light ? 1 : 2);
    }
    await tester.pumpWidget(const SizedBox.shrink());
    draft.dispose();
  });
  testWidgets(
      'resource scope loses focus outside without breaking menu selection',
      (tester) async {
    await prepare(tester);
    await tester.pumpWidget(const RepaintBoundary(child: NeoApp()));
    for (final mode in ['light', 'dark']) {
      if (mode == 'dark') {
        await tester.tap(find.text('设置 / CONFIG'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('OMG'));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('settings.dark')));
        await tester.pumpAndSettle();
      }
      await tester.tap(find.text('浏览 / BROWSE'));
      await tester.pumpAndSettle();
      final dropdown = find.byType(EfDropdown);
      final trigger =
          find.descendant(of: dropdown, matching: find.byType(TextButton));
      final focus = tester.widget<TextButton>(trigger).focusNode!;
      expect(focus.hasFocus, isFalse);
      await tester.tap(dropdown);
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(MenuItemButton, '全局'));
      await tester.pumpAndSettle();
      expect(tester.widget<EfDropdown>(dropdown).value, '全局');
      expect(focus.hasFocus, isFalse);
      showEfDialog<void>(
          context: tester.element(dropdown),
          builder: (context) => EfDialog(
                  title: const Text('焦点检查'),
                  content: const Text('关闭后不应默认选中下拉框。'),
                  actions: [
                    EfButton('关闭焦点检查',
                        small: true, onPressed: () => Navigator.pop(context))
                  ]));
      await tester.pumpAndSettle();
      await tester.tap(find.text('关闭焦点检查'));
      await tester.pumpAndSettle();
      expect(focus.hasFocus, isFalse);
      focus.requestFocus();
      await tester.pump();
      expect(focus.hasFocus, isTrue);
      await tester.tapAt(const Offset(480, 430));
      await tester.pumpAndSettle();
      expect(focus.hasFocus, isFalse);
      await tester.tap(dropdown);
      await tester.pumpAndSettle();
      await tester.tapAt(const Offset(480, 430));
      await tester.pumpAndSettle();
      expect(find.byType(MenuItemButton), findsNothing);
      expect(focus.hasFocus, isFalse);
      focus.requestFocus();
      await tester.pump();
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pumpAndSettle();
      expect(find.widgetWithText(MenuItemButton, '当前目录'), findsOneWidget);
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      await tester.pumpAndSettle();
      expect(focus.hasFocus, isTrue);
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(MenuItemButton, '当前目录'));
      await tester.pumpAndSettle();
      expect(focus.hasFocus, isFalse);
      await tester.tap(dropdown);
      await tester.pumpAndSettle();
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      await tester.pumpAndSettle();
      expect(focus.hasFocus, isTrue);
      await tester.sendKeyEvent(LogicalKeyboardKey.space);
      await tester.pumpAndSettle();
      await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pumpAndSettle();
      expect(tester.widget<EfDropdown>(dropdown).value, '全局');
      expect(focus.hasFocus, isTrue);
      await tester.tapAt(const Offset(480, 430));
      await tester.pumpAndSettle();
      expect(focus.hasFocus, isFalse);
      await tester.enterText(
          find.byKey(const ValueKey('resources.search')), '不存在');
      await tester.pumpAndSettle();
      expect(find.text('当前目录没有匹配的资源。'), findsOneWidget);
      expect(find.text('清空搜索'), findsNothing);
      expect(find.text('重新读取'), findsNothing);
      expect(find.text('刷新'), findsOneWidget);
      await tester.tapAt(const Offset(480, 430));
      await shot(tester, 'resources-clean-empty-$mode');
      await tester.tap(find.byTooltip('清空搜索'));
      await tester.pumpAndSettle();
    }
  });
  testWidgets('build dropdown selection and keyboard dismissal in both themes',
      (tester) async {
    await prepare(tester);
    await tester.pumpWidget(const RepaintBoundary(child: NeoApp()));
    for (final mode in ['light', 'dark']) {
      if (mode == 'dark') {
        await tester.tap(find.text('设置 / CONFIG'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('OMG'));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('settings.dark')));
        await tester.pumpAndSettle();
      }
      await tester.tap(find.text('工具 / TOOLS'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('便捷构建'));
      await tester.pumpAndSettle();
      final dropdown = find.byKey(const ValueKey('build.version'));
      await tester.tap(dropdown);
      await tester.pumpAndSettle();
      expect(find.byType(MenuItemButton), findsNWidgets(3));
      await shot(tester, 'menu-dropdown-$mode');
      await tester.tap(find.widgetWithText(MenuItemButton, '预览版本'));
      await tester.pumpAndSettle();
      expect(tester.widget<EfDropdown>(dropdown).value, '预览版本');
      await tester.tap(dropdown);
      await tester.pumpAndSettle();
      await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
      await tester.pump();
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      await tester.pumpAndSettle();
      expect(find.byType(MenuItemButton), findsNothing);
    }
  });
  testWidgets(
      'text context menus preserve clipboard actions and dismiss in both themes',
      (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.windows;
    addTearDown(() => debugDefaultTargetPlatformOverride = null);
    var clipboard = '粘贴内容';
    tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') {
        clipboard = call.arguments['text'] as String;
      }
      if (call.method == 'Clipboard.getData') return {'text': clipboard};
      if (call.method == 'Clipboard.hasStrings') {
        return {'value': clipboard.isNotEmpty};
      }
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));
    await prepare(tester);
    await tester.pumpWidget(const RepaintBoundary(child: NeoApp()));
    for (final mode in ['light', 'dark']) {
      await tester.tap(find.text('设置 / CONFIG'));
      await tester.pumpAndSettle();
      if (mode == 'dark') {
        await tester.tap(find.text('OMG'));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('settings.dark')));
        await tester.pumpAndSettle();
        await tester.tap(find.text('路径'));
        await tester.pumpAndSettle();
      }
      final field = find.byKey(const ValueKey('settings.path.game'));
      await tester.enterText(field, 'OMGNeo');
      final controller = tester.widget<TextField>(field).controller!;
      controller.selection =
          const TextSelection(baseOffset: 0, extentOffset: 6);
      await tester.pump();
      await tester.tapAt(tester.getTopLeft(field) + const Offset(30, 24),
          buttons: kSecondaryMouseButton);
      await tester.pumpAndSettle();
      final menu = find.byKey(const ValueKey('ef.context-menu'));
      expect(menu, findsOneWidget);
      await shot(tester, 'menu-context-$mode');
      await tester.tap(find.text('复制'));
      await tester.pumpAndSettle();
      expect(clipboard, 'OMGNeo');
      expect(menu, findsNothing);
      clipboard = '粘贴内容';
      controller.selection =
          const TextSelection(baseOffset: 0, extentOffset: 6);
      await tester.tapAt(tester.getTopLeft(field) + const Offset(30, 24),
          buttons: kSecondaryMouseButton);
      await tester.pumpAndSettle();
      await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
      await tester.sendKeyEvent(LogicalKeyboardKey.keyV);
      await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
      await tester.pumpAndSettle();
      expect(controller.text, '粘贴内容');
      await tester.tapAt(tester.getTopLeft(field) + const Offset(30, 24),
          buttons: kSecondaryMouseButton);
      await tester.pumpAndSettle();
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      await tester.pumpAndSettle();
      expect(menu, findsNothing);
    }
    await tester.tap(find.text('工具 / TOOLS'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('便捷构建'));
    await tester.pumpAndSettle();
    final log = find.byWidgetPredicate(
        (w) => w is SelectableText && (w.data?.startsWith('终端已就绪') ?? false));
    final logEditor = tester.widget<EditableText>(
        find.descendant(of: log, matching: find.byType(EditableText)));
    await tester.tap(log);
    await tester.pump();
    logEditor.controller.selection = TextSelection(
        baseOffset: 0, extentOffset: logEditor.controller.text.length);
    await tester.pump();
    await tester.tapAt(tester.getTopLeft(log) + const Offset(15, 6),
        buttons: kSecondaryMouseButton);
    await tester.pumpAndSettle();
    final logMenu = find.byKey(const ValueKey('ef.context-menu'));
    expect(logMenu, findsOneWidget);
    final copy = find.descendant(of: logMenu, matching: find.text('复制'));
    expect(copy, findsOneWidget);
    expect(find.text('剪切'), findsNothing);
    expect(find.text('粘贴'), findsNothing);
    await tester.tap(copy);
    await tester.pumpAndSettle();
    expect(clipboard, logEditor.controller.text);
    debugDefaultTargetPlatformOverride = null;
  });
  testWidgets(
      'exit status matches both themes, stays modal and respects reduced motion',
      (tester) async {
    await prepare(tester);
    await tester.pumpWidget(const RepaintBoundary(child: NeoApp()));
    await tester.pumpAndSettle();
    for (final mode in ['light', 'dark']) {
      if (mode == 'dark') {
        await tester.tap(find.text('设置 / CONFIG'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('OMG'));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('settings.dark')));
        await tester.tap(find.text('首页 / HOME'));
        await tester.pumpAndSettle();
      }
      final context = tester.element(find.byType(Workspace));
      final navigator = Navigator.of(context);
      final route = efDialogRoute<void>(
          context: context,
          barrierDismissible: false,
          builder: (_) => const NeoClosingDialog());
      navigator.push(route);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 320));
      expect(find.text('// EXIT'), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);
      await shot(tester, 'dialog-exit-$mode', settle: false);
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      await tester.tapAt(const Offset(24, 80));
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.byKey(const ValueKey('app.closing')), findsOneWidget);
      binding.platformDispatcher.accessibilityFeaturesTestValue =
          const FakeAccessibilityFeatures(disableAnimations: true);
      await tester.pumpAndSettle();
      expect(tester.binding.transientCallbackCount, 0);
      expect(
          find.byKey(const ValueKey('app.closing.progress')), findsOneWidget);
      navigator.removeRoute(route);
      await tester.pumpAndSettle();
      binding.platformDispatcher.clearAccessibilityFeaturesTestValue();
      await tester.pumpAndSettle();
    }
  });
  testWidgets('home update previews connecting and stepped syncing animations',
      (tester) async {
    await prepare(tester);
    await tester.pumpWidget(const RepaintBoundary(child: NeoApp()));
    await tester.pumpAndSettle();
    final navBefore =
        tester.getRect(find.byKey(const ValueKey('region.navigation.bottom')));
    final versions =
        tester.getRect(find.byKey(const ValueKey('region.home.versions')));
    final launch =
        tester.getRect(find.byKey(const ValueKey('region.home.launch')));
    expect(find.text('快捷操作'), findsNothing);
    expect(
        find.byKey(const ValueKey('region.home.quick-actions')), findsNothing);
    expect(launch.bottom, lessThan(versions.top));
    expect(launch.center.dx, 480);
    expect(versions.center.dx, 480);
    final update =
        tester.getRect(find.byKey(const ValueKey('region.home.update')));
    expect(update.top, lessThan(launch.top));
    expect(update.left, greaterThan(versions.right));
    expect(find.byKey(const ValueKey('home.bottom-progress')), findsNothing);
    await tester.tap(find.text('检查更新'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 600));
    expect(find.text('CONNECTING / 连接中'), findsOneWidget);
    expect(
        tester.getRect(find.byKey(const ValueKey('region.navigation.bottom'))),
        navBefore);
    final progress =
        tester.getRect(find.byKey(const ValueKey('home.progress-cells')));
    expect(progress, const Rect.fromLTWH(0, 530, 960, 10));
    await shot(tester, 'home-connecting', settle: false);
    await tester.pump(const Duration(seconds: 4));
    await tester.pumpAndSettle();
    await tester.tap(find.text('更新'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 600));
    expect(find.text('SYNCING / 同步中'), findsOneWidget);
    await shot(tester, 'home-syncing', settle: false);
    await tester.pump(const Duration(seconds: 4));
    await tester.pumpAndSettle();
    expect(find.text('检查更新'), findsOneWidget);
    expect(find.byKey(const ValueKey('home.bottom-progress')), findsNothing);
  });
  testWidgets(
      'top notifications stack, cap at three and close without moving home',
      (tester) async {
    await prepare(tester);
    await tester.pumpWidget(const RepaintBoundary(child: NeoApp()));
    await tester.pumpAndSettle();
    final launch = find.byKey(const ValueKey('region.home.launch'));
    final initial = tester.getRect(launch);
    void notify(String text) => showEfToast(tester.element(launch), text);
    // Notifications arriving before the first overlay frame must also be retained.
    notify('第一条通知');
    notify('第二条通知');
    await tester.pumpAndSettle();
    final secondTop = tester.getTopLeft(find.text('第二条通知')).dy;
    notify('第三条通知');
    await tester.pumpAndSettle();
    expect(tester.getTopLeft(find.text('第二条通知')).dy, secondTop + 50);
    notify('第四条通知');
    await tester.pumpAndSettle();
    final toast = find.byKey(const ValueKey('app.toast'));
    expect(toast, findsNWidgets(3));
    expect(find.text('第一条通知'), findsNothing);
    expect(tester.getRect(launch), initial);
    final newest = find.ancestor(of: find.text('第四条通知'), matching: toast);
    expect(tester.getRect(newest), const Rect.fromLTWH(300, 50, 360, 42));
    await shot(tester, 'home-toast');
    await tester
        .tap(find.descendant(of: newest, matching: find.byTooltip('关闭通知')));
    await tester.pumpAndSettle();
    expect(find.text('第四条通知'), findsNothing);
    expect(toast, findsNWidgets(2));
    expect(tester.getTopLeft(find.text('第三条通知')).dy, secondTop);
    await tester.pump(const Duration(seconds: 4));
    await tester.pumpAndSettle();
    expect(toast, findsNothing);
    await tester.tap(find.text('设置 / CONFIG'));
    await tester.pumpAndSettle();
    expect(find.text('保存'), findsNothing);
    await tester.tap(find.text('OMG'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings.dark')));
    await tester.tap(find.text('首页 / HOME'));
    await tester.pumpAndSettle();
    notify('深色主题下的通知');
    notify('通知可使用右侧按钮关闭');
    notify('新的通知显示在最上方');
    await tester.pumpAndSettle();
    await shot(tester, 'home-toast-dark');
    await tester.pump(const Duration(seconds: 4));
    await tester.pumpAndSettle();
    expect(toast, findsNothing);
    expect(tester.takeException(), isNull);
  });
  testWidgets('folder browser, animated status and retained preview state',
      (tester) async {
    await prepare(tester);
    await tester.pumpWidget(const RepaintBoundary(child: NeoApp()));
    await tester.tap(find.text('浏览 / BROWSE'));
    await shot(tester, 'resources');
    expect(find.text('自动分类'), findsNothing);
    expect(find.text('4 个文件夹'), findsNothing);
    final header =
        tester.getRect(find.byKey(const ValueKey('region.resources.header')));
    final search =
        tester.getRect(find.byKey(const ValueKey('resources.search')));
    expect(header.contains(search.center), isTrue);
    expect(
        tester
            .getSize(find.byKey(const ValueKey('region.resources.breadcrumb')))
            .height,
        28);
    expect(
        tester
            .getSize(find.byKey(const ValueKey('region.navigation.bottom')))
            .height,
        lessThan(56));
    await tester.tap(find.byKey(const ValueKey('resources.directory.角色')));
    await shot(tester, 'resources-folder');
    expect(find.text('3 项 / 2 项已启用'), findsNothing);
    expect(
        find.descendant(
            of: find.byType(ResourceBrowser), matching: find.byType(EfSwitch)),
        findsNothing);
    await tester.tap(find.byKey(const ValueKey('resources.item.a1')));
    await tester.pump(const Duration(milliseconds: 50));
    expect(tester.binding.hasScheduledFrame, isTrue);
    await tester.pumpAndSettle();
    expect(find.text('3 项 / 1 项已启用'), findsNothing);
    await tester.tap(find.byKey(const ValueKey('resources.keys.a1')));
    await tester.pumpAndSettle();
    expect(find.text('Shift + X'), findsOneWidget);
    await shot(tester, 'resources-keys');
    await tester.tap(find.text('关闭'));
    await tester.pumpAndSettle();
    expect(find.text('3 项 / 1 项已启用'), findsNothing);
    await tester.tap(find.byKey(const ValueKey('resources.thumbnail.a1')));
    await tester.pumpAndSettle();
    expect(find.byType(EfDialog), findsOneWidget);
    await tester.tap(find.text('关闭'));
    await tester.pumpAndSettle();
    expect(find.text('3 项 / 1 项已启用'), findsNothing);
    await tester.enterText(
        find.byKey(const ValueKey('resources.search')), '不存在');
    await shot(tester, 'resources-empty');
    expect(find.text('当前目录没有匹配的资源。'), findsOneWidget);
    expect(find.text('清空搜索'), findsNothing);
    expect(find.text('重新读取'), findsNothing);
    await tester.tap(find.byTooltip('清空搜索'));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byKey(const ValueKey('resources.search')), '配色');
    await tester.tap(find.text('工具 / TOOLS'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('浏览 / BROWSE'));
    await tester.pumpAndSettle();
    expect(find.text('1 项 / 0 项已启用'), findsNothing);
    await tester.tap(find.byKey(const ValueKey('resources.root')));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('清空搜索'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('写回'));
    await tester.pumpAndSettle();
    expect(find.text('写回预览：未修改资源或配置文件。'), findsOneWidget);
    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
    await tester.tap(find.text('设置 / CONFIG'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OMG'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings.dark')));
    await tester.tap(find.text('浏览 / BROWSE'));
    await shot(tester, 'resources-dark-folders');
    await tester.tap(find.byKey(const ValueKey('resources.directory.角色')));
    await shot(tester, 'resources-dark');
    await binding.setSurfaceSize(const Size(1280, 800));
    await shot(tester, 'resources-wide');
    await binding.setSurfaceSize(const Size(960, 540));
    await tester.pumpWidget(const SizedBox.shrink());
    await tester
        .pumpWidget(const RepaintBoundary(child: NeoApp(resources: true)));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('resources.folder-grid')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
      'square thumbnails, card menus, settings and directory scroll restore',
      (tester) async {
    await prepare(tester);
    final draft = ResourcesDraft();
    draft.items.addAll(List.generate(
        30, (i) => ResourcePreview('extra$i', '模组 $i', '角色', '', '')));
    await tester.pumpWidget(MaterialApp(
        theme: efTheme(Brightness.light),
        home: Scaffold(
            body: SizedBox(
                width: 960,
                height: 500,
                child: ResourceBrowser(
                    draft: draft,
                    region: (_, child) => child,
                    notice: (_) {},
                    onSettings: () {})))));
    await tester.tap(find.byKey(const ValueKey('resources.directory.角色')));
    await tester.pumpAndSettle();
    expect(tester.getSize(find.byKey(const ValueKey('resources.thumbnail.a1'))),
        const Size(84, 84));
    await tester.tap(find.byKey(const ValueKey('resources.item.a1')),
        buttons: kSecondaryMouseButton);
    await tester.pumpAndSettle();
    expect(find.text('配置文件'), findsOneWidget);
    expect(find.text('浏览子目录'), findsNothing);
    await tester.tap(find.text('开启缩略图遮罩'));
    await tester.pumpAndSettle();
    expect(draft.items.first.masked, isTrue);
    await tester.tap(find.byKey(const ValueKey('resources.item.a1')),
        buttons: kSecondaryMouseButton);
    await tester.pumpAndSettle();
    await tester.tap(find.text('转换为文件夹卡片'));
    await tester.pumpAndSettle();
    expect(draft.items.first.isMod, isFalse);
    // Non-mod folders now follow enabled mods when enabled-first is selected.
    await tester.scrollUntilVisible(
        find.byKey(const ValueKey('resources.thumbnail.a1')), 200,
        scrollable: find.descendant(
            of: find.byKey(const ValueKey('resources.folder-grid')),
            matching: find.byType(Scrollable)));
    expect(
        find.byKey(const ValueKey('resources.thumbnail.a1')), findsOneWidget);
    await tester.tap(
        find.byKey(const ValueKey('resources.directory.A / 角色外观示例')),
        buttons: kSecondaryMouseButton);
    await tester.pumpAndSettle();
    expect(find.text('配置文件'), findsNothing);
    await tester.tap(find.text('转换为模组卡片'));
    await tester.pumpAndSettle();
    draft.folderScroll.jumpTo(0);
    await tester.pumpAndSettle();
    await tester.drag(find.byKey(const ValueKey('resources.folder-grid')),
        const Offset(0, -450));
    await tester.pumpAndSettle();
    final offset = draft.folderScroll.offset;
    expect(offset, greaterThan(0));
    await tester.tap(find.byKey(const ValueKey('resources.root')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('resources.directory.角色')));
    await tester.pumpAndSettle();
    expect(draft.folderScroll.offset, closeTo(offset, 1));
    await tester.tap(find.text('设置'));
    await tester.pumpAndSettle();
    expect(find.text('显示空文件夹'), findsOneWidget);
    await tester.tap(find.text('显示空文件夹'));
    await tester.pumpAndSettle();
    expect(draft.showEmpty, isFalse);
    await tester.pumpWidget(const SizedBox.shrink());
    draft.dispose();
  });

  testWidgets('long notification scrolls fully before dismissal',
      (tester) async {
    await prepare(tester);
    await tester.pumpWidget(const RepaintBoundary(child: NeoApp()));
    await tester.pumpAndSettle();
    final launch =
        tester.element(find.byKey(const ValueKey('region.home.launch')));
    showEfToast(launch, List.filled(12, '需要完整阅读的通知内容 / 路径与操作结果').join(' │ '));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    await tester.pump(const Duration(seconds: 5));
    expect(find.byKey(const ValueKey('app.toast')), findsOneWidget);
    await tester.pumpAndSettle();
    final scroller = tester.widget<SingleChildScrollView>(find.descendant(
        of: find.byKey(const ValueKey('app.toast')),
        matching: find.byType(SingleChildScrollView)));
    expect(scroller.controller!.offset,
        scroller.controller!.position.maxScrollExtent);
    await tester.pump(const Duration(seconds: 2));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('app.toast')), findsNothing);
  });
}
