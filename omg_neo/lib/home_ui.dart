import 'package:flutter/material.dart';
import 'ef/marks.dart';
import 'ef/tokens.dart';
import 'ef/widgets.dart';
import 'update_preview.dart';

typedef HomeRegion = Widget Function(String id, Widget child);

class NeoHome extends StatefulWidget {
  const NeoHome(
      {super.key,
      required this.update,
      required this.region,
      required this.onLaunch,
      this.versions,
      this.launchLabel = '启动游戏  ↗'});
  final UpdatePreviewController update;
  final HomeRegion region;
  final VoidCallback? onLaunch;
  final Map<String, dynamic>? versions;
  final String launchLabel;
  @override
  State<NeoHome> createState() => _NeoHomeState();
}

class _NeoHomeState extends State<NeoHome> {
  EfColors get c => EfColors.of(context);
  Widget versions() => widget.region(
      'home.versions',
      Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          for (final name in ['GIMI', 'ORFix', 'TexFx']) ...[
            Tooltip(
                message: '$name / ${widget.versions?[name] ?? '未检测'}',
                child: Container(
                  width: 112,
                  height: 36,
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  decoration:
                      ShapeDecoration(color: c.chip, shape: efCut(br: 8)),
                  child: Row(children: [
                    Text(name, style: EfType.ui(12, weight: 600, color: c.ink)),
                    const SizedBox(width: 8),
                    Expanded(
                        child: Text(
                            (widget.versions?[name] as String?)?.isNotEmpty ==
                                    true
                                ? widget.versions![name] as String
                                : '未检测',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            textAlign: TextAlign.right,
                            style: EfType.ui(12, color: c.ink2))),
                  ]),
                )),
            if (name != 'TexFx') const SizedBox(width: 8),
          ],
        ],
      ));

  Widget launch() => widget.region(
      'home.launch',
      SizedBox(
          width: 280,
          height: 48,
          child: EfButton(widget.launchLabel,
              expand: true,
              kind: EfButtonKind.go,
              onPressed: widget.onLaunch)));

  @override
  Widget build(BuildContext context) => Stack(children: [
        Positioned(
            top: 0,
            right: 0,
            child: widget.region(
                'home.update',
                SizedBox(
                    width: 104,
                    child: UpdatePreview(
                        controller: widget.update, compact: true)))),
        Center(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
          widget.region(
              'home.hero',
              Text.rich(TextSpan(children: [
                TextSpan(
                    text: 'OMG ',
                    style: EfType.ui(42, weight: 800, color: c.ink, height: 1)),
                TextSpan(
                    text: 'NEO',
                    style:
                        EfType.ui(42, weight: 500, color: c.ink2, height: 1)),
              ]))),
          const SizedBox(height: 20),
          launch(),
          const SizedBox(height: 20),
          versions(),
        ])),
      ]);
}
