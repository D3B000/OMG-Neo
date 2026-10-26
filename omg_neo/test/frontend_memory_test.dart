import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:omg_neo/frontend_memory.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('image and GPU budgets apply without disabling rendering', () async {
    final cache = PaintingBinding.instance.imageCache;
    final originalCount = cache.maximumSize;
    final originalBytes = cache.maximumSizeBytes;
    final calls = <MethodCall>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.skia, (call) async {
      calls.add(call);
      return null;
    });
    final policy = FrontendMemoryPolicy();
    try {
      await policy.install();
      expect(cache.maximumSizeBytes, 16 * 1024 * 1024);
      expect(cache.maximumSize, 96);
      expect(calls.single.method, 'Skia.setResourceCacheMaxBytes');
      expect(calls.single.arguments, FrontendMemoryPolicy.rasterCacheBytes);
      policy.didHaveMemoryPressure();
      expect(cache.currentSizeBytes, 0);
      policy.didChangeAppLifecycleState(AppLifecycleState.hidden);
    } finally {
      policy.dispose();
      cache.maximumSize = originalCount;
      cache.maximumSizeBytes = originalBytes;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.skia, null);
    }
  });

  for (final dimensions in [const Size(100, 5000), const Size(1000, 1500)]) {
    test('preview $dimensions retains detail within the display budget',
        () async {
      final directory = await Directory.systemTemp.createTemp('neo-preview-');
      final file = File('${directory.path}/tall.png');
      final recorder = ui.PictureRecorder();
      Canvas(recorder).drawColor(const Color(0xff123456), BlendMode.src);
      final picture = recorder.endRecording();
      final source = await picture.toImage(
          dimensions.width.toInt(), dimensions.height.toInt());
      final encoded = await source.toByteData(format: ui.ImageByteFormat.png);
      await file.writeAsBytes(encoded!.buffer.asUint8List());
      source.dispose();
      picture.dispose();
      final provider = boundedPreviewImage(file.path,
          width: 84, height: 84, pixelRatio: dimensions.width == 100 ? 4 : 1);
      final stream = provider.resolve(ImageConfiguration.empty);
      final decoded = Completer<Size>();
      final listener = ImageStreamListener((info, _) {
        decoded.complete(
            Size(info.image.width.toDouble(), info.image.height.toDouble()));
        info.dispose();
      },
          onError: (Object error, StackTrace? stack) =>
              decoded.completeError(error, stack));
      try {
        stream.addListener(listener);
        final size = await decoded.future;
        expect(size.height, lessThanOrEqualTo(252));
        if (dimensions.width == 100) {
          expect(size.width, lessThan(size.height / 10));
        } else {
          expect(size, const Size(168, 252));
        }
        expect(size.width * size.height * 4, lessThan(256 * 1024));
      } finally {
        stream.removeListener(listener);
        await provider.evict();
        await directory.delete(recursive: true);
      }
    });
  }
}
