import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:omg_neo/backend/neo_backend.dart';

void main() {
  test('portable default ignores LOCALAPPDATA and remains beside the app', () {
    final app = Directory('dist/OMG-Neo').absolute;
    expect(neoDataRoot(app.path, environment: {'LOCALAPPDATA': 'C:/old-data'}),
        Directory('${app.path}/AppData').absolute.path);
    expect(
        neoDataRoot(app.path, environment: {'OMGNEO_DATA_ROOT': 'test-data'}),
        Directory('test-data').absolute.path);
    expect(
        neoDataRoot(app.path,
            override: 'explicit-data',
            environment: {'OMGNEO_DATA_ROOT': 'test-data'}),
        Directory('explicit-data').absolute.path);
  });
}
