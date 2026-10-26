import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Bound optional image/render caches while keeping hardware acceleration.
class FrontendMemoryPolicy with WidgetsBindingObserver {
  static const imageCacheBytes = 16 * 1024 * 1024;
  static const rasterCacheBytes = 16 * 1024 * 1024;

  Future<void> install() async {
    PaintingBinding.instance.imageCache
      ..maximumSize = 96
      ..maximumSizeBytes = imageCacheBytes;
    WidgetsBinding.instance.addObserver(this);
    try {
      await SystemChannels.skia.invokeMethod<void>(
          'Skia.setResourceCacheMaxBytes', rasterCacheBytes);
    } on MissingPluginException {
      // Some renderers do not expose Skia; the decoded-image budget still applies.
    } on PlatformException catch (error) {
      debugPrint('Unable to set render cache budget: $error');
    }
  }

  @override
  void didHaveMemoryPressure() {
    PaintingBinding.instance.imageCache
      ..clear()
      ..clearLiveImages();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.hidden ||
        state == AppLifecycleState.paused) {
      PaintingBinding.instance.imageCache.clear();
    }
  }

  void dispose() => WidgetsBinding.instance.removeObserver(this);
}

/// Keep a 3x sampling budget even at desktop 100% scaling. A fitted portrait
/// decoded at 1x becomes visibly pixelated when the square card crops it.
/// Both dimensions remain bounded; originals are never enlarged by the decoder.
ImageProvider boundedPreviewImage(String path,
    {required double width,
    required double height,
    required double pixelRatio}) {
  final scale = (pixelRatio * 3).clamp(1.0, 3.0);
  return ResizeImage(FileImage(File(path)),
      width: math.max(1, (width * scale).ceil()),
      height: math.max(1, (height * scale).ceil()),
      policy: ResizeImagePolicy.fit);
}
