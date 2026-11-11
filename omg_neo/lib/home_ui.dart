import 'package:flutter/material.dart';
import 'backend/neo_backend.dart';
import 'backend/neo_controller.dart';
import 'ef/marks.dart';
import 'ef/menus.dart';
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
      this.controller,
      this.versions,
      this.launchLabel = '启动游戏  ↗'});
  final UpdatePreviewController update;
  final HomeRegion region;
  final VoidCallback? onLaunch;
  final Map<String, dynamic>? versions;
  final NeoController? controller;
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
                child: versionCard(name)),
            if (name != 'TexFx') const SizedBox(width: 8),
          ],
        ],
      ));

  Widget versionCard(String name) {
    final version = widget.versions?[name] as String? ?? '';
    final label = Row(children: [
      Text(name, style: EfType.ui(12, weight: 600, color: c.ink)),
      const SizedBox(width: 8),
      Expanded(
          child: Text(version.isNotEmpty ? version : '未检测',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              textAlign: TextAlign.right,
              style: EfType.ui(12, color: c.ink2))),
    ]);
    final controller = widget.controller;
    if (name == 'GIMI' && controller != null) {
      return SizedBox(
          width: 112,
          height: 36,
          child: TextButton(
              key: const ValueKey('home.gimi-release-notes'),
              style: TextButton.styleFrom(
                  shape: efCut(br: 8),
                  foregroundColor: c.ink,
                  backgroundColor: c.chip,
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap),
              onPressed: () => showEfDialog<void>(
                  context: context,
                  builder: (_) => _GimiReleaseNotes(
                      controller: controller, version: version)),
              child: label));
    }
    return Container(
        width: 112,
        height: 36,
        padding: const EdgeInsets.symmetric(horizontal: 10),
        decoration: ShapeDecoration(color: c.chip, shape: efCut(br: 8)),
        child: label);
  }

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

class _GimiReleaseNotes extends StatefulWidget {
  const _GimiReleaseNotes({required this.controller, required this.version});
  final NeoController controller;
  final String version;

  @override
  State<_GimiReleaseNotes> createState() => _GimiReleaseNotesState();
}

class _GimiReleaseNotesState extends State<_GimiReleaseNotes> {
  String? body, error;
  bool loading = false;

  @override
  void initState() {
    super.initState();
    if (widget.version.isNotEmpty) load();
  }

  Future<void> load() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final cached = await widget.controller.releaseNotes(widget.version);
      if (!mounted) return;
      setState(() => body = cached['body'] as String? ?? body);
      if (body == null || cached['stale'] == true) {
        final notes =
            await widget.controller.refreshReleaseNotes(widget.version);
        if (mounted) setState(() => body = notes['body'] as String?);
      }
    } catch (exception) {
      if (mounted) setState(() => error = neoErrorMessage(exception));
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) => EfDialog(
          eyebrow: 'RELEASE NOTES',
          title: Text(widget.version.isEmpty
              ? 'GIMI 更新说明'
              : 'GIMI ${widget.version} 更新说明'),
          width: 640,
          content:
              Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            if (widget.version.isEmpty)
              const Text('未检测到 GIMI 版本，请先在设置中配置 GIMI 目录。'),
            if (loading) Text(body == null ? '正在获取更新说明…' : '正在刷新缓存中的更新说明…'),
            if (error != null)
              Text(body == null ? error! : '已显示缓存。刷新失败：$error'),
            if (body != null)
              SelectableText(body!.trim().isEmpty ? '此版本没有发布更新说明。' : body!,
                  contextMenuBuilder: efTextContextMenu),
          ]),
          actions: [
            if (error != null)
              EfButton('重试', small: true, onPressed: loading ? null : load),
            EfButton('关闭',
                small: true, onPressed: () => Navigator.pop(context)),
          ]);
}
