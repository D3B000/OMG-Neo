import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'ef/marks.dart';
import 'ef/tokens.dart';
import 'ef/widgets.dart';

class ResourceKeysDialog extends StatelessWidget {
  const ResourceKeysDialog(
      {super.key,
      required this.name,
      required this.bindings,
      this.preview = false});
  final String name;
  final Future<List<(String, String)>> bindings;
  final bool preview;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return EfDialog(
      title: const EfPair('KEY BINDINGS', '切换键', size: 22),
      scrollContent: false,
      content: SizedBox(
        height: 300,
        child: FutureBuilder<List<(String, String)>>(
          future: bindings,
          builder: (context, snapshot) => Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(
                    child: Tooltip(
                        message: name,
                        child: Text(name,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: EfType.ui(13, weight: 700, color: c.ink)))),
                if (snapshot.hasData) ...[
                  const SizedBox(width: 12),
                  Text('${snapshot.data!.length} 项',
                      style: EfType.ui(11, color: c.ink2)),
                ],
              ]),
              const SizedBox(height: 12),
              Expanded(
                  child: switch (snapshot) {
                AsyncSnapshot(
                  connectionState: ConnectionState.done,
                  hasError: true
                ) =>
                  SingleChildScrollView(
                      child: EfNotice('读取失败：${snapshot.error}')),
                AsyncSnapshot(
                  connectionState: ConnectionState.done,
                  data: final data?
                ) =>
                  data.isEmpty
                      ? Center(
                          child: Text('未在 INI 中找到切换键。',
                              style: EfType.ui(12, color: c.ink2)))
                      : _BindingList(bindings: data),
                _ => const Center(
                    child:
                        SizedBox(width: 160, child: LinearProgressIndicator())),
              }),
              const SizedBox(height: 10),
              Text(preview ? '仅预览 / 未读取实际模组配置' : '切换键来自当前资源的 INI 配置。',
                  style: EfType.ui(10, color: c.ink2)),
            ],
          ),
        ),
      ),
      actions: [
        EfButton('关闭', small: true, onPressed: () => Navigator.pop(context))
      ],
    );
  }
}

class _BindingList extends StatefulWidget {
  const _BindingList({required this.bindings});
  final List<(String, String)> bindings;
  @override
  State<_BindingList> createState() => _BindingListState();
}

class _BindingListState extends State<_BindingList>
    with SingleTickerProviderStateMixin {
  final scroll = ScrollController();
  late final entrance = AnimationController(vsync: this);
  Animation<double>? route;
  bool started = false;
  int visibleRows = 1;

  void start() {
    if (!mounted || started) return;
    started = true;
    entrance.duration = Duration(milliseconds: 320 + (visibleRows - 1) * 38);
    entrance.forward();
  }

  void routeStatus(AnimationStatus status) {
    if (status == AnimationStatus.completed) start();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (MediaQuery.disableAnimationsOf(context)) {
      started = true;
      entrance.value = 1;
    } else if (!started) {
      route?.removeStatusListener(routeStatus);
      route = ModalRoute.of(context)?.animation;
      if (route != null && route!.status != AnimationStatus.completed) {
        route!.addStatusListener(routeStatus);
      } else {
        WidgetsBinding.instance.addPostFrameCallback((_) => start());
      }
    }
  }

  @override
  void dispose() {
    route?.removeStatusListener(routeStatus);
    entrance.dispose();
    scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return LayoutBuilder(builder: (context, constraints) {
      if (!started) {
        visibleRows = math.min(widget.bindings.length,
            (constraints.maxHeight / 64).ceil().clamp(1, 10));
      }
      return ScrollConfiguration(
        behavior: ScrollConfiguration.of(context).copyWith(scrollbars: false),
        child: RawScrollbar(
          key: const ValueKey('resources.keys.scrollbar'),
          controller: scroll,
          thumbVisibility: true,
          trackVisibility: true,
          interactive: true,
          fadeDuration: Ef.d(context, const Duration(milliseconds: 150)),
          pressDuration: Ef.d(context, Ef.press),
          thickness: 4,
          minThumbLength: 32,
          crossAxisMargin: 2,
          mainAxisMargin: 4,
          shape: efCut(br: 2),
          trackRadius: Radius.zero,
          thumbColor: c.ink,
          trackColor: c.chip,
          trackBorderColor: c.rule,
          child: ListView.builder(
            key: const ValueKey('resources.keys.list'),
            controller: scroll,
            primary: false,
            padding: const EdgeInsets.only(right: 18),
            itemCount: widget.bindings.length,
            itemBuilder: (_, index) {
              final binding = widget.bindings[index];
              final row = Container(
                key: ValueKey('resources.keys.row.$index'),
                constraints: const BoxConstraints(minHeight: 64),
                decoration: BoxDecoration(
                    border: Border(
                        top: index == 0
                            ? BorderSide(color: c.rule)
                            : BorderSide.none,
                        bottom: BorderSide(color: c.rule))),
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Container(
                          width: 36,
                          color: c.ink,
                          padding: const EdgeInsets.symmetric(vertical: 4),
                          alignment: Alignment.center,
                          child: Text('${index + 1}'.padLeft(2, '0'),
                              style:
                                  EfType.ui(11, weight: 700, color: c.panel))),
                      const SizedBox(width: 12),
                      Expanded(
                          flex: 3,
                          child: Text(binding.$1,
                              style: EfType.ui(12, color: c.ink, height: 1.5))),
                      const SizedBox(width: 12),
                      Expanded(
                          flex: 2,
                          child: Container(
                              key: ValueKey('resources.keys.value.$index'),
                              color: c.chip,
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 10, vertical: 5),
                              child: Text(binding.$2,
                                  textAlign: TextAlign.right,
                                  style: EfType.ui(12,
                                      weight: 600,
                                      color: c.ink,
                                      height: 1.5)))),
                    ]),
              );
              // Only the initially visible rows enter; scrolling never restarts it.
              if (index >= visibleRows) return row;
              return AnimatedBuilder(
                  animation: entrance,
                  child: row,
                  builder: (_, child) {
                    final elapsed =
                        entrance.value * (320 + (visibleRows - 1) * 38);
                    final progress = Ef.snap.transform(
                        ((elapsed - index * 38) / 320).clamp(0.0, 1.0));
                    return Opacity(
                        key: ValueKey('resources.keys.entrance.$index'),
                        opacity: progress,
                        child: ClipRect(
                            clipper: _RowReveal(progress),
                            child: Transform.translate(
                                offset: Offset(-14 * (1 - progress), 0),
                                child: child)));
                  });
            },
          ),
        ),
      );
    });
  }
}

class _RowReveal extends CustomClipper<Rect> {
  const _RowReveal(this.progress);
  final double progress;
  @override
  Rect getClip(Size size) =>
      Rect.fromLTWH(0, 0, size.width * progress, size.height);
  @override
  bool shouldReclip(_RowReveal oldClipper) => oldClipper.progress != progress;
}
