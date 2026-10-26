import 'dart:io';
import 'package:omg_neo/backend/neo_backend.dart';

/// No dataRoot override: exercise the actual portable default without changing
/// the user's settings. All backend scratch files must stay beside this app.
Future<void> main(List<String> args) async {
  final executable = File(args.single).absolute;
  final expected =
      Directory('${executable.parent.parent.path}/AppData').absolute;
  final backend = ProcessNeoBackend(executable: executable.path);
  String normalize(String path) =>
      Directory(path).absolute.path.replaceAll('\\', '/').toLowerCase();
  try {
    await backend.start();
    final hello = await backend.call('hello');
    final actual = hello['snapshot']['dataRoot'] as String;
    if (normalize(actual) != normalize(expected.path)) {
      throw StateError('Wrong data root: $actual; expected ${expected.path}');
    }
    final build = await backend.call('build.get');
    if (normalize(build['workspace'] as String) !=
        normalize('${expected.path}/build-work')) {
      throw StateError('Build workspace escaped AppData');
    }
    if (!await Directory('${expected.path}/temp').exists()) {
      throw StateError('Missing portable temporary directory');
    }
    stdout.writeln('Portable default: $actual');
    stdout.writeln('Build workspace: ${build['workspace']}');
    stdout.writeln('Configuration and temporary paths: OK');
  } finally {
    await backend.close();
  }
}
