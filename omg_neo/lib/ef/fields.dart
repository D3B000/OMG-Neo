import 'package:flutter/material.dart';
import 'tokens.dart';

/// Shared path and configuration field appearance in both themes.
InputDecoration efInputDecoration(BuildContext context, String label,
    {String? hint, String? error}) {
  final c = EfColors.of(context);
  return InputDecoration(
      labelText: label,
      hintText: hint,
      isDense: true,
      filled: true,
      fillColor: c.panel,
      labelStyle: EfType.ui(12, color: c.ink2),
      hintStyle: EfType.ui(12, color: c.ink2),
      contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
      border: OutlineInputBorder(
          borderRadius: BorderRadius.zero,
          borderSide: BorderSide(color: c.rule)),
      enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.zero,
          borderSide: BorderSide(color: c.rule)),
      focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.zero,
          borderSide: BorderSide(color: c.ink, width: 2)),
      errorText: error,
      errorStyle: EfType.ui(10, color: c.ink),
      errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.zero,
          borderSide: BorderSide(color: c.ink)),
      focusedErrorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.zero,
          borderSide: BorderSide(color: c.ink, width: 2)));
}
