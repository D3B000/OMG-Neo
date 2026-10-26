import 'package:flutter/material.dart';
import 'backend/neo_backend.dart';
import 'ef/marks.dart';
import 'ef/menus.dart';
import 'ef/fields.dart';
import 'ef/tokens.dart';
import 'ef/widgets.dart';

class LinkDraft {
  int page = 0;
  final resource = TextEditingController();
  final destination = TextEditingController();
  final name = TextEditingController();
  final includeResource = TextEditingController();
  void dispose() {
    for (final field in [resource, destination, name, includeResource]) {
      field.dispose();
    }
  }
}

class NeoLinks extends StatefulWidget {
  const NeoLinks(
      {super.key,
      required this.draft,
      required this.gimi,
      required this.onBack,
      required this.pickPath,
      required this.region,
      this.backend,
      this.ready = false});
  final LinkDraft draft;
  final String gimi;
  final VoidCallback onBack;
  final Future<String?> Function({required bool folder, String initial})
      pickPath;
  final Widget Function(String, Widget) region;
  final NeoBackend? backend;
  final bool ready;
  @override
  State<NeoLinks> createState() => _NeoLinksState();
}

class _NeoLinksState extends State<NeoLinks> {
  bool working = false;
  String junctionStatus = '', includeStatus = '';
  bool junctionError = false, includeError = false;
  LinkDraft get d => widget.draft;
  EfColors get c => EfColors.of(context);

  @override
  void initState() {
    super.initState();
    if (d.destination.text.isEmpty && widget.gimi.trim().isNotEmpty) {
      d.destination.text =
          '${widget.gimi.replaceAll(RegExp(r'[/\\]+$'), '')}\\Mods';
    }
  }

  void changed(String mode) => setState(() {
        if (mode == 'junction') {
          junctionStatus = '';
        } else {
          includeStatus = '';
        }
      });

  Future<void> run(String mode, bool create) async {
    setState(() {
      working = true;
    });
    String message;
    bool error = false;
    try {
      if (!widget.ready || widget.backend == null) {
        throw StateError('后端尚未就绪，请等待连接完成');
      }
      final result = await widget.backend!
          .call(create ? 'links.create' : 'links.validate', {
        'mode': mode,
        'resource':
            mode == 'junction' ? d.resource.text : d.includeResource.text,
        'destination': d.destination.text,
        'name': d.name.text,
      });
      message = '${result['message']}';
      if (!create && result['content'] != null) {
        message += '\n${result['content']}';
      }
    } catch (exception) {
      message = '$exception';
      error = true;
    }
    if (!mounted) return;
    setState(() {
      working = false;
      if (mode == 'junction') {
        junctionStatus = message;
        junctionError = error;
      } else {
        includeStatus = message;
        includeError = error;
      }
    });
  }

  Widget field(String label, TextEditingController controller, String mode,
          {bool browse = true, String? hint}) =>
      Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Row(children: [
            Expanded(
                child: TextField(
                    controller: controller,
                    enabled: !working,
                    contextMenuBuilder: efTextContextMenu,
                    onChanged: (_) => changed(mode),
                    style: EfType.ui(12, color: c.ink),
                    decoration: efInputDecoration(context, label, hint: hint))),
            if (browse) ...[
              const SizedBox(width: 8),
              EfButton('浏览',
                  small: true,
                  onPressed: working
                      ? null
                      : () async {
                          final path = await widget.pickPath(
                              folder: true, initial: controller.text);
                          if (!mounted || path == null) return;
                          controller.text = path;
                          changed(mode);
                        }),
            ],
          ]));

  Widget card(String mode, String title, String detail, List<Widget> fields,
      {List<Widget> details = const []}) {
    final status = mode == 'junction' ? junctionStatus : includeStatus;
    final error = mode == 'junction' ? junctionError : includeError;
    return widget.region(
        'links.$mode',
        Container(
            padding: const EdgeInsets.all(24),
            decoration: ShapeDecoration(color: c.panel, shape: efCut(tl: 18)),
            child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  EfPair(mode.toUpperCase(), title, size: 20),
                  const SizedBox(height: 22),
                  Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Expanded(
                        flex: 3,
                        child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              ...fields,
                              const SizedBox(height: 8),
                              Row(children: [
                                EfButton('检查',
                                    small: true,
                                    onPressed: working || !widget.ready
                                        ? null
                                        : () => run(mode, false)),
                                const SizedBox(width: 8),
                                EfButton(mode == 'junction' ? '创建联接' : '生成配置',
                                    small: true,
                                    kind: EfButtonKind.go,
                                    onPressed: working || !widget.ready
                                        ? null
                                        : () => run(mode, true)),
                              ]),
                            ])),
                    const SizedBox(width: 28),
                    Expanded(
                        flex: 2,
                        child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              Text(detail,
                                  style: EfType.ui(12,
                                      color: c.ink2, height: 1.7)),
                              ...details,
                            ])),
                  ]),
                  if (status.isNotEmpty)
                    Container(
                        margin: const EdgeInsets.only(top: 20),
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                            color: c.paper,
                            border: error
                                ? Border(
                                    left: BorderSide(color: c.signal, width: 4))
                                : null),
                        child: SelectableText(status,
                            contextMenuBuilder: efTextContextMenu,
                            style: EfType.ui(12, color: c.ink, height: 1.6))),
                ])));
  }

  @override
  Widget build(BuildContext context) => Column(children: [
        Row(children: [
          for (final (index, label)
              in ['目录联接 / JUNCTION', '递归包含 / INCLUDE'].indexed) ...[
            if (index > 0) const SizedBox(width: 8),
            Semantics(
                selected: d.page == index,
                child: EfButton(label,
                    key: ValueKey('links.tab.$index'),
                    small: true,
                    kind:
                        d.page == index ? EfButtonKind.go : EfButtonKind.normal,
                    onPressed:
                        working ? null : () => setState(() => d.page = index))),
          ],
          const Spacer(),
          EfButton('返回工具',
              small: true, onPressed: working ? null : widget.onBack),
        ]),
        const SizedBox(height: 16),
        Expanded(
            child: SingleChildScrollView(
          key: ValueKey('links.page.${d.page}'),
          padding: const EdgeInsets.only(bottom: 96),
          child: d.page == 0
              ? card('junction', '目录联接',
                  '将资源目录关联到 GIMI 的 Mods 目录。创建前检查磁盘能力与符号名称，原资源仍保存在资源目录中。', [
                  field('资源目录', d.resource, 'junction'),
                  field('符号目录', d.destination, 'junction', hint: 'GIMI\\Mods'),
                  field('符号名称', d.name, 'junction', browse: false),
                ])
              : card('include', '递归包含',
                  '资源目录须与 GIMI 位于同一父目录。已有配置时，在 DISABLED* 排除规则上方追加相对路径。', [
                  field('资源目录', d.includeResource, 'include'),
                ],
                  details: [
                      const SizedBox(height: 18),
                      Text(
                          '写入：${widget.gimi.isEmpty ? 'GIMI' : widget.gimi}\\Mods\\modFolder.ini',
                          style: EfType.ui(12, color: c.ink2, height: 1.7)),
                      const SizedBox(height: 16),
                      SelectableText(
                          '[Include]\ninclude_recursive = <资源目录的相对路径>\nexclude_recursive = DISABLED*',
                          contextMenuBuilder: efTextContextMenu,
                          style: EfType.ui(12, color: c.ink2, height: 1.7)),
                    ]),
        )),
      ]);
}
