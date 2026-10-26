import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:omg_neo/main.dart';
import 'package:omg_neo/review.dart';

void main() {
  testWidgets('distribution omits review buttons, F8 and capture registration',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(960, 540));
    await tester.pumpWidget(const NeoApp());
    await tester.pumpAndSettle();
    expect(find.byTooltip('UI 调整工具 / F8'), findsNothing);
    expect(find.byType(ReviewRegion), findsNothing);
    await tester.sendKeyEvent(LogicalKeyboardKey.f8);
    await tester.pumpAndSettle();
    expect(find.byType(ReviewEditor), findsNothing);
    showDialog<void>(
        context: tester.element(find.byType(Workspace)),
        builder: (_) => const AlertDialog(title: Text('Release modal')));
    await tester.pumpAndSettle();
    await tester.sendKeyEvent(LogicalKeyboardKey.f8);
    await tester.pumpAndSettle();
    expect(find.byType(ReviewEditor), findsNothing);
    Navigator.of(tester.element(find.text('Release modal'))).pop();
    await tester.pumpAndSettle();
    await ReviewController()
        .open(tester.element(find.byType(Workspace)), GlobalKey(), 'home');
    await tester.pumpAndSettle();
    expect(find.byType(ReviewEditor), findsNothing);
    await tester.tap(find.text('设置 / CONFIG'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OMG'));
    await tester.pumpAndSettle();
    expect(find.text('打开 UI 调整工具'), findsNothing);
    await tester.sendKeyEvent(LogicalKeyboardKey.f8);
    await tester.pumpAndSettle();
    expect(find.byType(ReviewEditor), findsNothing);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    await tester.binding.setSurfaceSize(null);
  }, skip: uiReviewEnabled);
}
