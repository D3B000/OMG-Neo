import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'ef/tokens.dart';

/// Read appearance before creating any visible frame, without starting Python.
class StartupAppearance {
  const StartupAppearance({this.dark = false, this.accent = Ef.signal});
  final bool dark;
  final Color accent;

  static Future<StartupAppearance> load(
      Future<String> Function() dataRoot) async {
    try {
      final root = await dataRoot();
      final primary = File('$root/config.json');
      // Match SettingsStore: an orphaned backup is not used on a fresh install.
      if (!await primary.exists()) return const StartupAppearance();
      try {
        return await _read(primary);
      } catch (_) {
        return await _read(File('$root/config.json.bak'));
      }
    } catch (_) {
      // Backend initialization will report configuration errors normally.
      return const StartupAppearance();
    }
  }

  static Future<StartupAppearance> _read(File file) async {
    final data = jsonDecode(await file.readAsString()) as Map;
    if (data['schemaVersion'] != 1 ||
        data['settings'] is! Map ||
        int.tryParse('${data['revision']}') == null) {
      throw const FormatException('Invalid configuration');
    }
    final settings = data['settings'] as Map;
    final theme = (settings['theme'] as String? ?? 'light').toLowerCase();
    final accent = settings['accent_color'] as String? ?? '#39C5BB';
    if (!['light', 'dark'].contains(theme) ||
        !RegExp(r'^#[0-9a-fA-F]{6}$').hasMatch(accent)) {
      throw const FormatException('Invalid appearance');
    }
    return StartupAppearance(
        dark: theme == 'dark',
        accent: Color(int.parse('FF${accent.substring(1)}', radix: 16)));
  }
}
