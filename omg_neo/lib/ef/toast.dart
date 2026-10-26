import 'dart:async';
import 'package:flutter/material.dart';
import 'marks.dart';
import 'tokens.dart';
import 'widgets.dart';

final _toastHosts = Expando<_ToastHost>();

/// Window-level notifications, newest first, without changing page layout.
void showEfToast(BuildContext context, String message) {
  if (message.trim().isEmpty) return;
  final overlay = Overlay.of(context, rootOverlay: true);
  final host = _toastHosts[overlay] ??= _ToastHost(overlay);
  host.show(message);
}

class _ToastMessage {
  _ToastMessage(this.text);
  final String text;
}

class _ToastHost {
  _ToastHost(this.overlay);
  final OverlayState overlay;
  final messages = <_ToastMessage>[];
  OverlayEntry? entry;

  void show(String text) {
    messages.insert(0, _ToastMessage(text));
    if (messages.length > 3) messages.removeLast();
    if (entry != null) {
      entry!.markNeedsBuild();
      overlay.rearrange([entry!], below: entry!);
      return;
    }
    entry = OverlayEntry(
        builder: (context) => Positioned(
              top: 50,
              left: 24,
              right: 24,
              child: Align(
                alignment: Alignment.topCenter,
                child: SizedBox(
                  width: 360,
                  height: messages.length * 50,
                  child: Stack(children: [
                    for (final (i, message) in messages.indexed)
                      AnimatedPositioned(
                        key: ObjectKey(message),
                        duration:
                            Ef.d(context, const Duration(milliseconds: 240)),
                        curve: Ef.mech,
                        top: i * 50,
                        left: 0,
                        right: 0,
                        height: 42,
                        child: _ToastBubble(
                          message: message.text,
                          onDone: () => remove(message),
                        ),
                      ),
                  ]),
                ),
              ),
            ));
    overlay.insert(entry!);
  }

  void remove(_ToastMessage message) {
    if (!messages.remove(message)) return;
    if (messages.isNotEmpty) {
      entry?.markNeedsBuild();
    } else {
      entry?.remove();
      entry?.dispose();
      entry = null;
      _toastHosts[overlay] = null;
    }
  }
}

class _ToastBubble extends StatefulWidget {
  const _ToastBubble({required this.message, required this.onDone});
  final String message;
  final VoidCallback onDone;
  @override
  State<_ToastBubble> createState() => _ToastBubbleState();
}

class _ToastBubbleState extends State<_ToastBubble>
    with SingleTickerProviderStateMixin {
  late final AnimationController animation = AnimationController(vsync: this);
  Timer? timer;
  bool started = false, closing = false;
  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    animation.duration = Ef.d(context, const Duration(milliseconds: 280));
    animation.reverseDuration =
        Ef.d(context, const Duration(milliseconds: 180));
    if (!started) {
      started = true;
      animation.forward();
    } else if (MediaQuery.disableAnimationsOf(context)) {
      animation.value = closing ? 0 : 1;
    }
  }

  Future<void> close() async {
    if (closing) return;
    closing = true;
    timer?.cancel();
    await animation.reverse();
    if (mounted) widget.onDone();
  }

  @override
  void dispose() {
    timer?.cancel();
    animation.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: animation,
        builder: (context, child) => ClipRect(
          clipper: _ToastReveal(Ef.mech.transform(animation.value)),
          child: child,
        ),
        child: Semantics(
          liveRegion: true,
          child: Material(
            type: MaterialType.transparency,
            child: ClipPath(
              clipper: ShapeBorderClipper(shape: efCut(br: 12)),
              child: EfToast(widget.message,
                  key: const ValueKey('app.toast'),
                  onClose: close, onRead: (overflow) {
                timer?.cancel();
                timer = Timer(Duration(seconds: overflow ? 2 : 4), close);
              }),
            ),
          ),
        ),
      );
}

class _ToastReveal extends CustomClipper<Rect> {
  const _ToastReveal(this.progress);
  final double progress;
  @override
  Rect getClip(Size size) =>
      Rect.fromLTWH(0, 0, size.width * progress, size.height);
  @override
  bool shouldReclip(_ToastReveal oldClipper) => oldClipper.progress != progress;
}
