import 'dart:collection';

/// Keep recent diagnostics without retaining arbitrarily large compiler lines.
class LogBuffer {
  static const maxLines = 5000;
  static const maxCodeUnits = 512 * 1024;
  static const maxLineCodeUnits = 16 * 1024;
  final _lines = <String>[];
  int _codeUnits = 0;
  late final List<String> lines = UnmodifiableListView(_lines);
  int get retainedCodeUnits => _codeUnits;

  void clear() {
    _lines.clear();
    _codeUnits = 0;
  }

  void add(String line) {
    if (line.length > maxLineCodeUnits) {
      const marker = ' …[显示内容已截断]… ';
      final half = (maxLineCodeUnits - marker.length) ~/ 2;
      line =
          '${line.substring(0, half)}$marker${line.substring(line.length - half)}';
    }
    _lines.add(line);
    _codeUnits += line.length;
    var remove = 0;
    while (_lines.length - remove > maxLines || _codeUnits > maxCodeUnits) {
      _codeUnits -= _lines[remove++].length;
    }
    if (remove > 0) _lines.removeRange(0, remove);
  }

  void addAll(Iterable<String> lines) {
    for (final line in lines) {
      add(line);
    }
  }
}
