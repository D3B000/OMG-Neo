import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:omg_neo/backend/neo_backend.dart';
import 'package:omg_neo/ef/tokens.dart';
import 'package:omg_neo/link_ui.dart';

class LinkBackend implements NeoBackend {
  String? method;
  Map<String, dynamic>? params;
  @override
  Stream<Map<String, dynamic>> get events => const Stream.empty();
  @override
  Future<void> start() async {}
  @override
  Future<void> close() async {}
  @override
  Future<Map<String, dynamic>> call(String method,
      [Map<String, dynamic> params = const {}]) async {
    this.method = method;
    this.params = params;
    if (params['name'] == 'duplicate') throw StateError('符号名称已存在');
    return {
      'message': '校验成功',
      'content':
          '[Include]\ninclude_recursive = ..\\..\\资源\nexclude_recursive = DISABLED*'
    };
  }
}

void main() {
  testWidgets('association fields, browser, validation and creation',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(960, 540));
    final latin = FontLoader('Saira')
      ..addFont(rootBundle.load('fonts/Saira.ttf'));
    await latin.load();
    final chinese = FontLoader('Noto Sans SC')
      ..addFont(Future.value(ByteData.sublistView(
          File('C:/Windows/Fonts/msyh.ttc').readAsBytesSync())));
    await chinese.load();
    final draft = LinkDraft();
    final backend = LinkBackend();
    await tester.pumpWidget(MaterialApp(
        theme: efTheme(Brightness.light),
        home: Scaffold(
            body: RepaintBoundary(
                child: Padding(
          padding: const EdgeInsets.fromLTRB(32, 62, 32, 0),
          child: NeoLinks(
              draft: draft,
              gimi: r'C:\GIMI',
              ready: true,
              backend: backend,
              onBack: () {},
              region: (_, child) => child,
              pickPath: ({required folder, initial = ''}) async => r'C:\资源'),
        )))));
    expect(draft.destination.text, r'C:\GIMI\Mods');
    expect(find.textContaining('JUNCTION'), findsWidgets);
    expect(find.textContaining('INCLUDE'), findsWidgets);
    await tester.tap(find.text('浏览').first);
    await tester.pumpAndSettle();
    expect(draft.resource.text, r'C:\资源');
    draft.name.text = 'duplicate';
    await tester.tap(find.text('检查').first);
    await tester.pumpAndSettle();
    expect(find.textContaining('符号名称已存在'), findsOneWidget);
    draft.name.text = '资源';
    await tester.tap(find.text('创建联接'));
    await tester.pumpAndSettle();
    expect(backend.method, 'links.create');
    expect(backend.params?['name'], '资源');
    await tester.tap(find.byKey(const ValueKey('links.tab.1')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('浏览').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('生成配置'));
    await tester.pumpAndSettle();
    expect(backend.params?['mode'], 'include');
    expect(backend.params?['resource'], r'C:\资源');
    await tester.tap(find.byKey(const ValueKey('links.tab.0')));
    await tester.pumpAndSettle();
    expect(draft.name.text, '资源');
    expect(draft.resource.text, r'C:\资源');
    expect(tester.takeException(), isNull);
    final boundary = tester.renderObject<RenderRepaintBoundary>(
        find.byType(RepaintBoundary).first);
    await tester.runAsync(() async {
      final image = await boundary.toImage();
      final data = await image.toByteData(format: ui.ImageByteFormat.png);
      await Directory('shots').create(recursive: true);
      await File('shots/links.png').writeAsBytes(data!.buffer.asUint8List());
      image.dispose();
    });
    await tester.pumpWidget(const SizedBox());
    draft.dispose();
  });
}
