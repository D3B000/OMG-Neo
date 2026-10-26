import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:omg_neo/main.dart';
import 'package:omg_neo/startup_appearance.dart';
import 'package:omg_neo/ef/tokens.dart';

void main() {
  late Directory root;
  setUp(() async =>
      root = await Directory.systemTemp.createTemp('neo-appearance-'));
  tearDown(() async => root.delete(recursive: true));
  Future<StartupAppearance> load() =>
      StartupAppearance.load(() async => root.path);
  Future<void> save(String name, String theme, [String accent = '#39C5BB']) =>
      File('${root.path}/$name').writeAsString(jsonEncode({
        'schemaVersion': 1,
        'revision': 1,
        'settings': {'theme': theme, 'accent_color': accent}
      }));

  test('saved appearance is read without modifying configuration', () async {
    await save('config.json', 'dark', '#AABBCC');
    final config = File('${root.path}/config.json');
    final before = await config.readAsString();
    final appearance = await load();
    expect(appearance.dark, isTrue);
    expect(appearance.accent, const Color(0xFFAABBCC));
    expect(await config.readAsString(), before);
    expect(await root.list().length, 1);
  });
  test('primary theme wins over backup; corrupt primary uses backup', () async {
    await save('config.json', 'light');
    await save('config.json.bak', 'dark');
    expect((await load()).dark, isFalse);
    await File('${root.path}/config.json').writeAsString('broken');
    expect((await load()).dark, isTrue);
    await save('config.json', 'invalid');
    expect((await load()).dark, isTrue);
  });
  test('fresh installs ignore orphan backup and invalid files use defaults',
      () async {
    await save('config.json.bak', 'dark');
    expect((await load()).dark, isFalse);
    await File('${root.path}/config.json').writeAsString('broken');
    await File('${root.path}/config.json.bak').writeAsString('broken');
    final appearance = await load();
    expect(appearance.dark, isFalse);
    expect(appearance.accent, Ef.signal);
    expect(
        (await StartupAppearance.load(() async => throw StateError('missing')))
            .dark,
        isFalse);
  });
  testWidgets('saved dark appearance is applied on the very first frame',
      (tester) async {
    final appearance = (await tester.runAsync(() async {
      await save('config.json', 'dark', '#AABBCC');
      return load();
    }))!;
    await tester.binding.setSurfaceSize(const Size(960, 540));
    await tester.pumpWidget(
        NeoApp(initialDark: appearance.dark, initialAccent: appearance.accent));
    expect(tester.widget<MaterialApp>(find.byType(MaterialApp)).themeMode,
        ThemeMode.dark);
    final context = tester.element(find.byType(Workspace));
    expect(Theme.of(context).brightness, Brightness.dark);
    expect(EfColors.of(context).paper, EfColors.dark.paper);
    expect(EfColors.of(context).signal, const Color(0xFFAABBCC));
    await tester.pump(const Duration(milliseconds: 250));
    expect(Theme.of(context).brightness, Brightness.dark);
    await tester.pumpWidget(const SizedBox());
    await tester.binding.setSurfaceSize(null);
  });
}
