// Shapes and drawn marks: cut corners, hatch, three-colour strip, contours.
import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'tokens.dart';
import 'contour_data.dart';

/// A cut corner means "you can press this". Flutter's BeveledRectangleBorder
/// cuts at 45° with the radius as the cut length.
BeveledRectangleBorder efCut({
  double tl = 0,
  double tr = 0,
  double br = 0,
  double bl = 0,
  BorderSide side = BorderSide.none,
}) =>
    BeveledRectangleBorder(
      side: side,
      borderRadius: BorderRadius.only(
        topLeft: Radius.circular(tl),
        topRight: Radius.circular(tr),
        bottomRight: Radius.circular(br),
        bottomLeft: Radius.circular(bl),
      ),
    );

/// Magenta / yellow / mint, 3px. Only at the very top of a screen and under a
/// document title. Never as a divider elsewhere.
class EfTriStrip extends StatelessWidget {
  const EfTriStrip({super.key, this.height = Ef.strip});
  final double height;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: height,
        child: Row(children: [
          const Expanded(
              child: ColoredBox(color: Ef.triA, child: SizedBox.expand())),
          Expanded(
              child: ColoredBox(
                  color: EfColors.of(context).signal,
                  child: const SizedBox.expand())),
          const Expanded(
              child: ColoredBox(color: Ef.triC, child: SizedBox.expand())),
        ]),
      );
}

/// 45° hatch lines. For empty states, title bands, disabled or "nothing here" areas.
class EfHatch extends StatelessWidget {
  const EfHatch({super.key, this.child, this.spacing = Ef.hatchStep});
  final Widget? child;
  final double spacing;

  @override
  Widget build(BuildContext context) => CustomPaint(
        painter: _HatchPainter(
            EfColors.of(context).ink.withValues(alpha: Ef.hatchAlpha), spacing),
        child: child,
      );
}

class _HatchPainter extends CustomPainter {
  _HatchPainter(this.color, this.spacing);
  final Color color;
  final double spacing;

  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..color = color
      ..strokeWidth = Ef.hatchLine;
    canvas.save();
    canvas.clipRect(Offset.zero & size);
    for (var x = -size.height; x < size.width; x += spacing) {
      canvas.drawLine(Offset(x, size.height), Offset(x + size.height, 0), p);
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(_HatchPainter old) =>
      old.color != color || old.spacing != spacing;
}

/// Faint open contour lines in two opposite corners of a screen background.
/// Open, flowing, never closed rings; 9% ink; behind everything.
class EfContours extends StatelessWidget {
  const EfContours({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) => CustomPaint(
        painter: _ContourPainter(
            EfColors.of(context).ink.withValues(alpha: Ef.contourAlpha)),
        child: child,
      );
}

class _ContourPainter extends CustomPainter {
  _ContourPainter(this.color);
  final Color color;
  static final patches = [
    [_readPath(contourA0), _readPath(contourA1)],
    [_readPath(contourB0), _readPath(contourB1)],
  ];

  // The bundled source contains only M, Q and L commands, with no closed rings.
  static Path _readPath(String data) {
    final tokens = RegExp(r'[MQL]|-?\d+(?:\.\d+)?')
        .allMatches(data)
        .map((m) => m.group(0)!)
        .toList();
    final path = Path();
    int i = 0;
    double number() => double.parse(tokens[i++]);
    while (i < tokens.length) {
      switch (tokens[i++]) {
        case 'M':
          path.moveTo(number(), number());
        case 'L':
          path.lineTo(number(), number());
        case 'Q':
          path.quadraticBezierTo(number(), number(), number(), number());
      }
    }
    return path;
  }

  @override
  void paint(Canvas canvas, Size size) {
    final scale = math.min(size.width / 960, 1.5);
    canvas.save();
    canvas.clipRect(Offset.zero & size);
    _patch(
        canvas,
        0,
        Rect.fromLTWH(
            size.width - 550 * scale, -100 * scale, 680 * scale, 510 * scale),
        const Size(960, 720));
    _patch(
        canvas,
        1,
        Rect.fromLTWH(
            -95 * scale, size.height - 350 * scale, 520 * scale, 520 * scale),
        const Size(800, 800));
    canvas.restore();
  }

  void _patch(Canvas canvas, int index, Rect rect, Size source) {
    canvas.save();
    canvas.translate(rect.left, rect.top);
    final scale = rect.width / source.width;
    canvas.scale(scale);
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..shader = RadialGradient(
        colors: [color, color, color.withValues(alpha: 0)],
        stops: const [0, .35, 1],
        radius: .5,
      ).createShader(Offset.zero & source);
    for (int i = 0; i < 2; i++) {
      paint.strokeWidth = (i == 0 ? 1 : 1.6) / scale;
      canvas.drawPath(patches[index][i], paint);
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(_ContourPainter old) => old.color != color;
}
