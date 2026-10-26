import 'dart:async';
import 'package:flutter/material.dart';
import 'ef/tokens.dart';
import 'ef/widgets.dart';

/// Self-contained UI preview, without update services or file operations.
class UpdatePreviewController extends ChangeNotifier {
  Timer? _timer;
  bool ready = false;
  bool? syncing;
  int step = 0;
  bool get active => syncing != null;
  VoidCallback? onAction;
  bool enabled = true;
  String? message;

  /// The timer animates unknown progress only; completion comes from the backend.
  void live(
      {required bool active,
      required bool syncing,
      required bool ready,
      double? progress,
      String? message}) {
    _timer?.cancel();
    if (active && syncing && this.syncing != true) step = 0;
    this.ready = ready;
    this.syncing = active ? syncing : null;
    this.message = message;
    if (progress != null) step = (progress.clamp(0, 1) * 24).floor();
    if (active && !syncing) {
      _timer = Timer.periodic(const Duration(milliseconds: 100), (_) {
        step = (step + 2) % 24;
        notifyListeners();
      });
    }
    notifyListeners();
  }

  void start({bool reduceMotion = false}) {
    if (onAction != null) {
      onAction!();
      return;
    }
    _timer?.cancel();
    if (active) {
      syncing = null;
      notifyListeners();
      return;
    }
    final sync = ready;
    syncing = sync;
    step = reduceMotion ? 12 : 0;
    notifyListeners();
    int tick = 0;
    _timer = Timer.periodic(const Duration(milliseconds: 100), (timer) {
      tick++;
      if (tick >= 26) {
        timer.cancel();
        ready = !sync;
        syncing = null;
      } else if (!reduceMotion) {
        step = sync ? tick.clamp(0, 24) : tick % 12 * 2;
      }
      notifyListeners();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}

class UpdatePreview extends StatelessWidget {
  const UpdatePreview(
      {super.key, required this.controller, this.compact = false});
  final UpdatePreviewController controller;
  final bool compact;
  @override
  Widget build(BuildContext context) => ListenableBuilder(
      listenable: controller,
      builder: (context, _) {
        final button = EfButton(
            controller.active
                ? '取消'
                : controller.ready
                    ? '更新'
                    : '检查更新',
            small: true,
            expand: compact,
            onPressed: !controller.enabled
                ? null
                : () => controller.start(
                    reduceMotion: MediaQuery.disableAnimationsOf(context)));
        if (compact) return button;
        return Row(children: [
          Expanded(
              child: Text('版本信息',
                  style: EfType.ui(17,
                      weight: 700, color: EfColors.of(context).ink))),
          button,
        ]);
      });
}

/// Adapts a task's real progress to the same bottom strip used by updates.
class BottomTaskProgress extends StatefulWidget {
  const BottomTaskProgress(
      {super.key,
      required this.active,
      required this.progress,
      required this.message});
  final bool active;
  final double? progress;
  final String message;
  @override
  State<BottomTaskProgress> createState() => _BottomTaskProgressState();
}

class _BottomTaskProgressState extends State<BottomTaskProgress> {
  final progress = UpdatePreviewController();
  void sync() => progress.live(
      active: widget.active,
      syncing: widget.progress != null,
      ready: false,
      progress: widget.progress,
      message: widget.message);
  @override
  void initState() {
    super.initState();
    sync();
  }

  @override
  void didUpdateWidget(BottomTaskProgress oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.active != widget.active ||
        oldWidget.progress != widget.progress ||
        oldWidget.message != widget.message) {
      sync();
    }
  }

  @override
  void dispose() {
    progress.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) =>
      BottomUpdateProgress(controller: progress);
}

/// Bottom overlay; its visibility never moves the navigation or page content.
class BottomUpdateProgress extends StatelessWidget {
  const BottomUpdateProgress({super.key, required this.controller});
  final UpdatePreviewController controller;
  @override
  Widget build(BuildContext context) => ListenableBuilder(
      listenable: controller,
      builder: (context, _) {
        if (!controller.active) return const SizedBox.shrink();
        final c = EfColors.of(context);
        final sync = controller.syncing!;
        final step = !sync && MediaQuery.disableAnimationsOf(context)
            ? 12
            : controller.step;
        final head = (step * 1.25).floor() - 6;
        final percentage = (step / 24 * 100).round();
        return IgnorePointer(
            child: Semantics(
          label: controller.message ?? (sync ? '同步进度' : '连接进度'),
          value: sync ? '$percentage%' : '未知进度',
          child: SizedBox(
              key: const ValueKey('home.bottom-progress'),
              height: 28,
              child: Column(children: [
                Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    child: Row(children: [
                      Expanded(
                          child: Text(
                              controller.message ??
                                  (sync ? 'SYNCING / 同步中' : 'CONNECTING / 连接中'),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: EfType.ui(10,
                                  weight: 600, color: c.ink2, spacing: .10))),
                      const SizedBox(width: 8),
                      Text(
                          sync
                              ? '${percentage.toString().padLeft(3, '0')}%'
                              : '——',
                          style: EfType.ui(11, color: c.ink)),
                    ])),
                const Spacer(),
                SizedBox(
                    key: const ValueKey('home.progress-cells'),
                    height: 10,
                    child: Row(children: [
                      for (int i = 0; i < 24; i++)
                        Expanded(
                            child: Container(
                                margin: EdgeInsets.only(right: i == 23 ? 0 : 2),
                                color: (sync
                                        ? i < step
                                        : i >= head && i < head + 6)
                                    ? c.signal
                                    : c.chip)),
                    ])),
              ])),
        ));
      });
}
