import 'package:flutter/material.dart';
import 'ef/tokens.dart';
import 'ef/widgets.dart';

/// Exit status only: persistence and process shutdown remain owned by Workspace.
class NeoClosingDialog extends StatefulWidget {
  const NeoClosingDialog(
      {super.key, this.cleanupMessage, this.cleanupProgress});
  final String? cleanupMessage;
  final double? cleanupProgress;
  @override
  State<NeoClosingDialog> createState() => _NeoClosingDialogState();
}

class _NeoClosingDialogState extends State<NeoClosingDialog>
    with SingleTickerProviderStateMixin {
  late final AnimationController pulse = AnimationController(
      vsync: this, duration: const Duration(milliseconds: 1200));

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (MediaQuery.disableAnimationsOf(context)) {
      pulse.stop();
      pulse.value = 0;
    } else if (!pulse.isAnimating) {
      pulse.repeat();
    }
  }

  @override
  void dispose() {
    pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return PopScope(
      canPop: false,
      child: EfDialog(
        key: const ValueKey('app.closing'),
        width: 440,
        eyebrow: 'EXIT',
        title: const Text('正在关闭'),
        content: Semantics(
          liveRegion: true,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(widget.cleanupMessage ?? '正在保存设置并等待任务收尾。'),
              const SizedBox(height: 6),
              Text('完成后将自动退出，请稍候。', style: EfType.ui(12, color: c.ink2)),
              const SizedBox(height: 22),
              if (widget.cleanupMessage != null)
                LinearProgressIndicator(
                    key: const ValueKey('app.closing.cache.progress'),
                    value: widget.cleanupProgress,
                    color: c.signal,
                    backgroundColor: c.chip,
                    minHeight: 8)
              else
                Semantics(
                  label: '正在等待退出完成',
                  child: ExcludeSemantics(
                    child: AnimatedBuilder(
                      animation: pulse,
                      builder: (context, _) {
                        final head = (pulse.value * 24).floor();
                        return Row(
                          key: const ValueKey('app.closing.progress'),
                          children: [
                            for (var i = 0; i < 24; i++)
                              Expanded(
                                  child: Container(
                                height: 8,
                                margin: EdgeInsets.only(right: i == 23 ? 0 : 2),
                                color: (i - head + 24) % 24 < 4
                                    ? c.signal
                                    : c.chip,
                              )),
                          ],
                        );
                      },
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
