import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:omg_neo/backend/neo_backend.dart';

void main() {
  test('failed process startup still releases its communication isolate',
      () async {
    final backend = ProcessNeoBackend(executable: 'missing-omg-backend.exe');
    await expectLater(backend.start(), throwsStateError);
    await backend.close().timeout(const Duration(seconds: 3));
    await expectLater(backend.call('hello'), throwsStateError);
  });

  final executable = File(Platform.environment['OMGNEO_TEST_BACKEND'] ??
      'dist/OMG-Neo-v0.0.1/backend/omg_backend.exe');
  test('isolated process transport preserves replies and quiesces exit events',
      () async {
    final root = await Directory.systemTemp.createTemp('neo-transport-');
    final backend = ProcessNeoBackend(
        executable: executable.absolute.path, dataRoot: root.path);
    final events = <Map<String, dynamic>>[];
    final subscription = backend.events.listen(events.add);
    try {
      expect(await backend.resolveDataRoot(), root.path);
      await backend.start().timeout(const Duration(seconds: 20));
      final hello = await backend.call('hello', {'protocol': 1});
      expect(hello['snapshot']['settings']['game_folder'], '');
      backend.setClosing(true);
      final saved = await backend.call('config.patch', {
        'patch': {'theme': 'dark'},
        'revision': 0,
      });
      expect(saved['settings']['theme'], 'dark');
      expect(events.where((e) => e['event'] == 'config.changed'), isEmpty);
      await backend.call('settings.flush');
      backend.setClosing(false);
      // Reconnection never terminates a live service or replays an operation.
      await expectLater(backend.restart(), throwsStateError);
      final disconnected =
          backend.events.firstWhere((e) => e['event'] == 'backend.failed');
      await backend.call('shutdown');
      await disconnected.timeout(const Duration(seconds: 10));
      await backend.restart();
      final restored = await backend.call('hello', {'protocol': 1});
      expect(restored['snapshot']['settings']['theme'], 'dark');
      expect(restored['snapshot']['revision'], 1);
      final closing = backend.close();
      expect(identical(closing, backend.close()), isTrue);
      await closing.timeout(const Duration(seconds: 20));
      await expectLater(backend.call('hello'), throwsStateError);
    } finally {
      await backend.close();
      await subscription.cancel();
      await root.delete(recursive: true);
    }
  }, skip: !executable.existsSync());
}
