import 'dart:io';
import 'package:omg_neo/backend/neo_backend.dart';

/// Exercise the production Dart transport against the frozen Python executable.
Future<void> main(List<String> args) async {
  final temporary = await Directory.systemTemp.createTemp('omg-neo-stdio-');
  final backend = ProcessNeoBackend(
      executable: File(args.first).absolute.path, dataRoot: temporary.path);
  try {
    await backend.start();
    final hello = await backend.call('hello', {'protocol': 1});
    if (hello['protocol'] != 1) throw StateError('Protocol mismatch');
    await backend.call('config.patch', {
      'revision': 0,
      'patch': {'theme': 'dark', 'accent_color': '#123456'}
    });
    final snapshot = await backend.call('config.get');
    if (snapshot['settings']['theme'] != 'dark' ||
        snapshot['settings']['accent_color'] != '#123456') {
      throw StateError('Configuration roundtrip failed');
    }
    stdout.writeln('Dart → frozen Python: handshake, save, readback OK');
  } finally {
    await backend.close();
    final parent = Directory.systemTemp.absolute.path;
    if (temporary.absolute.path
        .startsWith('$parent${Platform.pathSeparator}')) {
      await temporary.delete(recursive: true);
    }
  }
}
