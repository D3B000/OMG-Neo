import 'package:flutter/material.dart';
import 'package:desktop_drop/desktop_drop.dart';
import 'ef/toast.dart';
import 'backend/neo_controller.dart';
import 'backend/neo_backend.dart';
import 'ef/widgets.dart';
import 'ef/tokens.dart';
import 'ef/marks.dart';

class NeoServerSwitch extends StatefulWidget {
  const NeoServerSwitch(
      {super.key,
      this.controller,
      this.pickPath,
      required this.onBack,
      this.region});
  final NeoController? controller;
  final Widget Function(String, Widget)? region;
  final VoidCallback onBack;
  final Future<String?> Function({required bool folder, String initial})?
      pickPath;
  @override
  State<NeoServerSwitch> createState() => _NeoServerSwitchState();
}

class _NeoServerSwitchState extends State<NeoServerSwitch> {
  final actionScroll = ScrollController();
  final detailsScroll = ScrollController();
  Widget mark(String id, Widget child) =>
      widget.region?.call(id, child) ?? child;

  String target = 'cn', message = '';
  int tab = 0;
  bool dragging = false;
  Map<String, dynamic> versions = {};
  bool readingVersions = false, wasBusy = false;
  String? gamePath;

  void backendChanged() {
    final c = widget.controller;
    if (c == null) return;
    final refresh =
        !c.busy && (wasBusy || gamePath != c.settings['game_folder']);
    wasBusy = c.busy;
    gamePath = c.settings['game_folder'] as String?;
    if (refresh && c.ready) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && !c.busy) refreshVersions();
      });
    }
  }

  Future<void> refreshVersions() async {
    final c = widget.controller;
    if (readingVersions || c == null || !c.ready || c.busy) {
      return;
    }
    setState(() => readingVersions = true);
    try {
      final value = await c.backend.call('serverSwitch.versions');
      if (mounted) {
        setState(() {
          versions = value;
          if (destination.text.trim().isEmpty &&
              value['backupRoot'] is String) {
            destination.text = value['backupRoot'] as String;
          }
        });
      }
    } catch (error) {
      if (mounted) {
        setState(() => versions = {
              'errors': [neoErrorMessage(error)]
            });
      }
    } finally {
      if (mounted) setState(() => readingVersions = false);
    }
  }

  Widget versionPanel(bool enabled, EfColors colors) {
    final rows = (versions['sources'] as List? ?? []).whereType<Map>();
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(children: [
        Expanded(child: EfPair('VERSIONS', '本地与替换包版本', size: 16)),
        const SizedBox(width: 8),
        EfButton(readingVersions ? '读取中…' : '刷新版本',
            small: true,
            onPressed: enabled && !readingVersions ? refreshVersions : null),
      ]),
      const SizedBox(height: 12),
      if (rows.isEmpty && !readingVersions)
        Text('配置游戏目录后，可在这里查看游戏与替换包的版本。',
            style: EfType.ui(12, color: colors.ink2, height: 1.6)),
      for (final row in rows)
        Container(
          key: ValueKey('serverSwitch.version-record.${row['id']}'),
          padding: const EdgeInsets.symmetric(vertical: 12),
          decoration: BoxDecoration(
              border: Border(bottom: BorderSide(color: colors.rule))),
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(
                  child: Align(
                      alignment: Alignment.centerLeft,
                      child: Tooltip(
                          message: '${row['path'] ?? ''}',
                          triggerMode: TooltipTriggerMode.tap,
                          constraints: const BoxConstraints(maxWidth: 420),
                          decoration: BoxDecoration(
                              color: colors.ink,
                              border: Border.all(color: colors.rule)),
                          textStyle:
                              EfType.ui(11, color: colors.panel, height: 1.5),
                          padding: const EdgeInsets.symmetric(
                              horizontal: 10, vertical: 8),
                          child: Container(
                              key: ValueKey(
                                  'serverSwitch.version-source.${row['id']}'),
                              decoration: ShapeDecoration(
                                  color: colors.chip, shape: efCut(br: 6)),
                              padding: const EdgeInsets.fromLTRB(8, 4, 14, 4),
                              child: Text('${row['label']}',
                                  style: EfType.ui(11,
                                      weight: 600, color: colors.ink)))))),
              const SizedBox(width: 12),
              Text('${row['version'] == '' ? '未识别' : row['version']}',
                  style: EfType.ui(16, weight: 700, color: colors.ink)),
            ]),
            const SizedBox(height: 6),
            Wrap(
                spacing: 10,
                runSpacing: 6,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text(
                      '声明：${row['declaredVersion'] == '' ? '未填写' : row['declaredVersion']}',
                      style: EfType.ui(11, color: colors.ink2)),
                  if (row['mismatch'] == true)
                    Container(
                        color: colors.signal,
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 3),
                        child: Text('版本不一致',
                            style: EfType.ui(11, color: colors.onSignal))),
                ]),
            if ('${row['build'] ?? ''}'.isNotEmpty)
              Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: SelectableText('构建：${row['build']}',
                      style: EfType.ui(10, color: colors.ink2))),
            if ('${row['error'] ?? ''}'.isNotEmpty)
              Text('${row['error']}', style: EfType.ui(11, color: colors.ink2)),
            if ('${row['note'] ?? ''}'.isNotEmpty)
              Text('${row['note']}', style: EfType.ui(11, color: colors.ink2)),
          ]),
        ),
      for (final error in versions['errors'] as List? ?? [])
        Text('$error', style: EfType.ui(11, color: colors.ink2)),
    ]);
  }

  final source = TextEditingController();
  final destination = TextEditingController();

  @override
  void initState() {
    super.initState();
    widget.controller?.addListener(backendChanged);
    wasBusy = widget.controller?.busy ?? false;
    gamePath = widget.controller?.settings['game_folder'] as String?;
    source.text = '${widget.controller?.settings['game_folder'] ?? ''}';
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted &&
          widget.controller?.ready == true &&
          widget.controller?.busy == false) {
        inspect();
      }
    });
  }

  @override
  void dispose() {
    widget.controller?.removeListener(backendChanged);
    actionScroll.dispose();
    detailsScroll.dispose();
    source.dispose();
    destination.dispose();
    super.dispose();
  }

  Widget backupField(String label, TextEditingController field, bool enabled) =>
      Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Row(children: [
            Expanded(
                child: TextField(
                    controller: field,
                    enabled: enabled,
                    decoration: InputDecoration(labelText: label))),
            const SizedBox(width: 8),
            EfButton('浏览',
                small: true,
                onPressed: enabled && widget.pickPath != null
                    ? () async {
                        final value = await widget.pickPath!(
                            folder: true, initial: field.text);
                        if (mounted && value != null) {
                          setState(() => field.text = value);
                        }
                      }
                    : null),
          ]));

  Future<void> backup(String channel) async {
    setState(() {
      message = '';
      preview = null;
    });
    await widget.controller!
        .backupServer(channel, source.text, destination.text);
  }

  Map<String, dynamic>? preview;
  bool loading = false;
  static const names = {
    'cn': '米哈游官服',
    'bilibili': 'Bilibili 服',
    'global': '国际服'
  };

  Future<void> inspect() async {
    setState(() {
      loading = true;
      preview = null;
    });
    try {
      final c = widget.controller;
      if (c == null || !c.ready || c.busy) {
        throw StateError('后端未就绪或有任务正在执行');
      }
      await c.flush();
      await refreshVersions();
      final result =
          await c.backend.call('serverSwitch.preview', {'target': target});
      if (!mounted) return;
      setState(() {
        preview = result;
        message = '当前：${names[result['current']]}  →  ${names[target]}\n'
            '版本：${result['version']}\n'
            '资源目录：${result['resourceRoot']}\n'
            '${result['rename']}\n'
            '覆盖 ${(result['copy'] as List).length} 项，清理 ${(result['remove'] as List).length} 项。\n'
            '切换前会自动备份，失败时回滚。';
      });
    } catch (error) {
      if (mounted) setState(() => message = neoErrorMessage(error));
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    return c == null
        ? page(false)
        : AnimatedBuilder(animation: c, builder: (_, child) => page(c.busy));
  }

  Widget page(bool busy) {
    final c = widget.controller;
    final canDrop = c?.ready == true &&
        !busy &&
        !loading &&
        c?.closing != true &&
        (ModalRoute.of(context)?.isCurrent ?? true);
    final content = Column(children: [
      mark(
          'serverSwitch.header',
          Row(children: [
            for (final (index, label)
                in ['服务器切换 / SERVER', '制作备份 / BACKUP'].indexed) ...[
              if (index > 0) const SizedBox(width: 8),
              EfButton(label,
                  small: true,
                  kind: tab == index ? EfButtonKind.go : EfButtonKind.normal,
                  onPressed: () => setState(() => tab = index)),
            ],
            const Spacer(),
            EfButton('打开目录',
                key: const ValueKey('serverSwitch.open-directory'),
                small: true,
                onPressed: c?.ready == true && c?.closing != true
                    ? openDirectory
                    : null),
            const SizedBox(width: 8),
            EfButton('返回工具', small: true, onPressed: widget.onBack),
          ])),
      const SizedBox(height: 16),
      Expanded(
          child: Padding(
              padding: const EdgeInsets.only(bottom: 82), child: body(busy))),
    ]);
    return DropTarget(
      key: const ValueKey('serverSwitch.drop'),
      enable: canDrop,
      onDragEntered: (_) => setState(() => dragging = true),
      onDragExited: (_) => setState(() => dragging = false),
      onDragDone: (details) {
        setState(() => dragging = false);
        if (!canDrop) return;
        if (details.files.length != 1) {
          showEfToast(context, '请每次拖入一个替换包文件夹');
          return;
        }
        setState(() {
          preview = null;
          message = '';
        });
        c!.businessTask(
            'serverSwitch.import', {'source': details.files.single.path});
      },
      child: Stack(fit: StackFit.expand, children: [
        content,
        if (dragging && canDrop)
          Positioned.fill(
              child: IgnorePointer(
                  child: Container(
            key: const ValueKey('serverSwitch.drop-hint'),
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
                color: EfColors.of(context).panel.withValues(alpha: .96),
                border: Border.all(color: EfColors.of(context).ink)),
            child: const Center(
                child: EfPair('IMPORT PACKAGE', '释放文件夹以导入替换包', size: 22)),
          ))),
      ]),
    );
  }

  Future<void> restore() async {
    setState(() {
      preview = null;
      message = '';
    });
    await widget.controller!.restoreServer();
  }

  Future<void> openDirectory() async {
    try {
      await widget.controller!.backend.call('serverSwitch.openDirectory');
    } catch (error) {
      if (mounted) setState(() => message = '打开目录失败：${neoErrorMessage(error)}');
    }
  }

  Future<void> startSwitch() async {
    await inspect();
    if (!mounted || preview == null || widget.controller?.busy == true) return;
    setState(() {
      preview = null;
      message = '';
    });
    await widget.controller!.switchServer(target);
  }

  Widget panel(Widget child) => Container(
      color: EfColors.of(context).panel,
      padding: const EdgeInsets.all(16),
      child: child);

  Widget actionHint(String text, Widget child) {
    final colors = EfColors.of(context);
    return Tooltip(
        message: text,
        constraints: const BoxConstraints(maxWidth: 320),
        decoration: BoxDecoration(
            color: colors.ink, border: Border.all(color: colors.rule)),
        textStyle: EfType.ui(11, color: colors.panel, height: 1.5),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        child: child);
  }

  Widget pane(ScrollController scroll, Widget child) => Scrollbar(
      controller: scroll,
      thumbVisibility: true,
      radius: Radius.zero,
      child: SingleChildScrollView(
          controller: scroll,
          padding: const EdgeInsets.only(right: 12),
          child: child));

  Widget body(bool busy) {
    final c = widget.controller;
    final enabled = !busy && !loading && c?.ready == true;
    final colors = EfColors.of(context);
    final left =
        Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      mark(
          'serverSwitch.actions',
          panel(
              Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(
                  child: EfPair(tab == 0 ? 'SERVER' : 'BACKUP',
                      tab == 0 ? '原神服务器切换' : '制作替换资源备份',
                      size: 20)),
              if (tab == 0) ...[
                const SizedBox(width: 12),
                actionHint(
                    '恢复上一次未完成的服务器切换。',
                    EfButton('恢复',
                        key: const ValueKey('serverSwitch.restore'),
                        small: true,
                        onPressed: enabled ? restore : null)),
                const SizedBox(width: 8),
                actionHint(
                    '检查当前游戏与目标服务器的替换资源。',
                    EfButton(loading ? '检查中…' : '检查',
                        key: const ValueKey('serverSwitch.check'),
                        small: true,
                        onPressed: enabled ? inspect : null)),
              ],
            ]),
            const SizedBox(height: 18),
            if (tab == 0) ...[
              Text('目标服务器', style: EfType.ui(12, color: colors.ink2)),
              const SizedBox(height: 10),
              AbsorbPointer(
                  absorbing: !enabled,
                  child: Semantics(
                      enabled: enabled,
                      child: EfSegmented(
                          key: const ValueKey('serverSwitch.server'),
                          options: names.values.toList(),
                          current: names.keys.toList().indexOf(target),
                          onChanged: (index) {
                            if (!enabled) return;
                            setState(() {
                              target = names.keys.elementAt(index);
                              preview = null;
                              message = '';
                            });
                            inspect();
                          }))),
              const SizedBox(height: 20),
              Align(
                  alignment: Alignment.centerLeft,
                  child: EfButton('开始切换',
                      small: true,
                      kind: EfButtonKind.go,
                      onPressed: enabled ? startSwitch : null)),
              const SizedBox(height: 12),
              Text('拖入替换包文件夹可自动识别并导入。',
                  style: EfType.ui(11, color: colors.ink2, height: 1.6)),
            ] else ...[
              backupField('游戏目录', source, enabled),
              backupField('备份输出目录', destination, enabled),
              const SizedBox(height: 6),
              Wrap(
                  key: const ValueKey('serverSwitch.backup-actions'),
                  spacing: 10,
                  runSpacing: 8,
                  children: [
                    EfButton('备份国服 / B 服',
                        small: true,
                        kind: EfButtonKind.go,
                        onPressed: enabled ? () => backup('cn') : null),
                    EfButton('备份外服',
                        small: true,
                        onPressed: enabled ? () => backup('global') : null),
                  ]),
            ],
          ]))),
      if (message.isNotEmpty || c != null) ...[
        const SizedBox(height: 12),
        mark(
            'serverSwitch.status',
            panel(Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text('操作状态',
                      style: EfType.ui(11, weight: 600, color: colors.ink2)),
                  const SizedBox(height: 6),
                  if (message.isNotEmpty)
                    SelectableText(message,
                        style: EfType.ui(12, color: colors.ink, height: 1.6)),
                  if (c != null)
                    Padding(
                        padding: EdgeInsets.only(top: message.isEmpty ? 0 : 8),
                        child: Text(c.error ?? c.status,
                            style: EfType.ui(12,
                                color: colors.ink2, height: 1.6))),
                ]))),
      ],
    ]);
    final right =
        Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (tab == 0) ...[
        mark('serverSwitch.versions', panel(versionPanel(enabled, colors))),
        const SizedBox(height: 12),
      ],
      mark(
          'serverSwitch.guide',
          panel(
              Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            EfPair(tab == 0 ? 'RESOURCES' : 'BACKUP GUIDE',
                tab == 0 ? '替换资源' : '备份说明',
                size: 17),
            const SizedBox(height: 12),
            Text(
                tab == 0
                    ? '使用设置中的游戏目录。将国服、外服备份合并为“替换包”，放入 AppData\\server-switch，保留版本号.ini 和中文子目录。'
                    : '选择游戏目录和备份输出目录。默认存入 AppData\\server-switch\\备份包，分别保存国服与外服。',
                style: EfType.ui(12, color: colors.ink2, height: 1.7)),
            const SizedBox(height: 12),
            Divider(height: 1, color: colors.rule),
            const SizedBox(height: 12),
            Text(
                tab == 0
                    ? '切换前自动备份；执行失败时回滚。'
                    : '同一目录自动合并国服与外服版本信息，旧备份保留在 .history 中。',
                style: EfType.ui(12, color: colors.ink, height: 1.7)),
          ]))),
    ]);
    return LayoutBuilder(builder: (_, constraints) {
      if (constraints.maxWidth < 700) {
        return pane(actionScroll,
            Column(children: [left, const SizedBox(height: 16), right]));
      }
      return Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Expanded(flex: 2, child: pane(actionScroll, left)),
        const SizedBox(width: 16),
        Expanded(flex: 1, child: pane(detailsScroll, right)),
      ]);
    });
  }
}
