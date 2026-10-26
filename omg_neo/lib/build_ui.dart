import 'dart:io';
import 'package:flutter/material.dart';
import 'ef/menus.dart';
import 'ef/fields.dart';
import 'ef/tokens.dart';
import 'ef/marks.dart';
import 'ef/widgets.dart';
import 'ef/toast.dart';
import 'backend/neo_controller.dart';

class BuildDraft {
  int source = 0, ritualType = 0, copyType = 0;
  String version = '未获取版本', project = '未选择项目';
  bool optimize = true, ritual = true, autoRitual = false, autoMove = false;
  final target = TextEditingController();
  final logs = <String>['终端已就绪。操作仅产生预览输出。'];
  void dispose() => target.dispose();
}

class BuildConsole extends StatefulWidget {
  const BuildConsole(
      {super.key,
      required this.draft,
      required this.onBack,
      this.controller,
      this.pickPath,
      required this.region});
  final NeoController? controller;
  final Future<String?> Function({required bool folder, String initial})?
      pickPath;
  final BuildDraft draft;
  final VoidCallback onBack;
  final Widget Function(String, Widget) region;
  @override
  State<BuildConsole> createState() => _BuildConsoleState();
}

class _BuildConsoleState extends State<BuildConsole> {
  BuildDraft get d => widget.draft;
  EfColors get c => EfColors.of(context);
  final scroll = ScrollController(), output = ScrollController();
  bool cleanup = false;
  bool exporting = false;
  NeoController? get live => widget.controller;
  bool get available => live?.ready == true && live?.busy == false;
  List<String> get logs => live?.buildLogs ?? d.logs;
  final selectedCleanup = <String>{};
  int seenLogs = 0;
  int seenLogRevision = 0;
  bool buildRequested = false;

  void requestBuildWhenReady() {
    if (live?.ready != true) {
      buildRequested = false;
    } else if (!buildRequested) {
      buildRequested = true;
      live!.loadBuild();
    }
  }

  @override
  void initState() {
    super.initState();
    seenLogs = logs.length;
    seenLogRevision = live?.buildLogRevision ?? 0;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        requestBuildWhenReady();
        followOutput();
      }
    });
  }

  @override
  void didUpdateWidget(covariant BuildConsole oldWidget) {
    super.didUpdateWidget(oldWidget);
    requestBuildWhenReady();
    if (logs.length == seenLogs &&
        seenLogRevision == (live?.buildLogRevision ?? 0)) {
      return;
    }
    seenLogs = logs.length;
    seenLogRevision = live?.buildLogRevision ?? 0;
    followOutput();
  }

  void followOutput([int correction = 0]) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && output.hasClients) {
        final end = output.position.maxScrollExtent;
        if ((output.offset - end).abs() > .1) {
          output.jumpTo(end);
          // Lazy rows can revise their estimated extent after a long line lays out.
          if (correction < 8) followOutput(correction + 1);
        }
      }
    });
  }

  Future<void> openWorkspace() async {
    if (live == null) {
      showEfToast(context, '工作目录仅在连接后端后可用。');
      return;
    }
    try {
      await live!.backend.call('build.openWorkspace');
    } catch (error) {
      if (mounted) showEfToast(context, '打开工作目录失败：$error');
    }
  }

  void change(Map<String, dynamic> patch) {
    live?.selectBuild(patch);
  }

  void run(String action) {
    if (live == null) {
      log({
            'download': d.source == 0 ? '下载源码' : '下载已构建文件',
            'compile': '构建',
            'ritual': '神秘仪式',
            'environment': '环境检测'
          }[action] ??
          action);
      return;
    }
    live?.businessTask('build.$action');
  }

  Map<String, dynamic> get state => live?.buildState ?? {};
  void syncDraft() {
    final options = state['options'] as Map?;
    if (options == null) return;
    d.source = options['source'] as int;
    d.ritualType = options['ritualType'] as int;
    d.copyType = options['copyType'] as int;
    d.version = options['version'] as String;
    d.project = options['project'] as String;
    d.optimize = options['optimize'] as bool;
    d.ritual = options['ritual'] as bool;
    d.autoRitual = options['autoRitual'] as bool;
    d.autoMove = options['autoMove'] as bool;
    if (d.target.text != options['target']) {
      d.target.text = options['target'] as String;
    }
  }

  @override
  void dispose() {
    scroll.dispose();
    output.dispose();
    super.dispose();
  }

  Widget region(String id, Widget child) => widget.region('build.$id', child);
  void log(String text) {
    setState(() => d.logs.add('[预览] $text：尚未连接业务。'));
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && output.hasClients) {
        output.jumpTo(output.position.maxScrollExtent);
      }
    });
  }

  Widget button(String label, VoidCallback tap,
          {bool primary = false, String? key, bool enabled = true}) =>
      SizedBox(
          height: 28,
          child: EfButton(label,
              key: key == null ? null : ValueKey(key),
              small: true,
              kind: primary ? EfButtonKind.go : EfButtonKind.normal,
              onPressed: !enabled || live != null && !available ? null : tap));
  Widget compactSegments(String id, List<String> labels, int current,
          ValueChanged<int> change) =>
      SizedBox(
          height: 29,
          child: Row(children: [
            for (int i = 0; i < labels.length; i++)
              Expanded(
                  child: Semantics(
                      button: true,
                      selected: current == i,
                      child: Material(
                          color: current == i ? c.ink : c.chip,
                          child: InkWell(
                              key: ValueKey('$id.$i'),
                              onTap: live != null && !available
                                  ? null
                                  : () => setState(() => change(i)),
                              child: Center(
                                  child: Text(labels[i],
                                      style: EfType.ui(11,
                                          weight: 600,
                                          color: current == i
                                              ? c.paper
                                              : c.ink)))))))
          ]));
  Widget switchRow(
          String id, String title, bool value, ValueChanged<bool> change) =>
      SizedBox(
          height: 28,
          child: Row(children: [
            Expanded(child: Text(title, style: EfType.ui(11, color: c.ink))),
            SizedBox(
                width: 48,
                height: 28,
                child: Semantics(
                    label: title,
                    child: EfSwitch(
                        key: ValueKey(id),
                        value: value,
                        onChanged: (v) {
                          if (live == null || available) {
                            setState(() => change(v));
                          }
                        }))),
          ]));
  Widget dropdown(String id, String value, List<String> items,
          ValueChanged<String> change) =>
      SizedBox(
          height: 28,
          child: EfDropdown(
            key: ValueKey(id),
            value: value,
            items: items,
            onChanged: live != null && !available
                ? null
                : (v) {
                    setState(() => change(v));
                    if (v == '更新选项') {
                      run(id == 'build.version' ? 'releases' : 'environment');
                    }
                  },
          ));
  Widget panel(String id, String en, String zh, Widget child,
          {bool right = false, bool lower = false}) =>
      region(
          id,
          Container(
              decoration: ShapeDecoration(color: c.panel, shape: efCut(tl: 18)),
              padding: const EdgeInsets.all(16),
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(children: [
                      Container(width: 24, height: 3, color: c.ink),
                      const SizedBox(width: 10),
                      Text(en,
                          style: EfType.ui(9,
                              weight: 600, color: c.ink2, spacing: .14)),
                      const Spacer(),
                      Text(zh, style: EfType.ui(16, weight: 700, color: c.ink))
                    ]),
                    const SizedBox(height: 14),
                    child,
                  ])));
  @override
  Widget build(BuildContext context) {
    syncDraft();
    return Column(children: [
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        EfPair(cleanup ? 'CLEANUP' : 'BUILD CONSOLE', cleanup ? '清理' : '便捷构建',
            size: 20),
        const Spacer(),
        SizedBox(
            height: 28,
            child: EfButton('工作目录',
                key: const ValueKey('build.open-workspace'),
                small: true,
                onPressed: live == null || live!.ready && !live!.closing
                    ? openWorkspace
                    : null)),
        const SizedBox(width: 8),
        if (!cleanup)
          button('清理', () {
            setState(() => cleanup = true);
            run('cleanup.scan');
          }),
        if (live?.busy == true && live!.taskKind.startsWith('build.'))
          SizedBox(
              height: 28,
              child:
                  EfButton('取消任务', small: true, onPressed: live!.cancelTask)),
        const SizedBox(width: 8),
        button(cleanup ? '返回构建' : '返回工具',
            cleanup ? () => setState(() => cleanup = false) : widget.onBack)
      ]),
      const SizedBox(height: 12),
      Expanded(
          child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Expanded(
            flex: 6,
            child: Scrollbar(
                controller: scroll,
                thumbVisibility: true,
                child: SingleChildScrollView(
                    key: const ValueKey('build.cards-scroll'),
                    controller: scroll,
                    padding: const EdgeInsets.only(right: 12, bottom: 82),
                    child: cleanup
                        ? cleanupPage()
                        : Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                                downloadPanel(),
                                const SizedBox(height: 12),
                                buildPanel(),
                                const SizedBox(height: 12),
                                ritualPanel(),
                                const SizedBox(height: 12),
                                automationPanel(),
                              ])))),
        const SizedBox(width: 20),
        Expanded(
            flex: 5,
            child: Padding(
                padding: const EdgeInsets.only(bottom: 84), child: terminal())),
      ])),
    ]);
  }

  Widget downloadPanel() => panel(
      'download',
      'DOWNLOAD',
      'D3D11',
      Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        compactSegments('build.source', ['GitHub 源码', '已构建文件'], d.source, (v) {
          d.source = v;
          change({'source': v});
        }),
        const SizedBox(height: 9),
        if (d.source == 0)
          Row(children: [
            const SizedBox(width: 3),
            Expanded(
                child: dropdown(
                    'build.version',
                    d.version,
                    live == null
                        ? ['未获取版本', '预览版本', '更新选项']
                        : [
                            if ((state['releases'] as List? ?? []).isEmpty)
                              '未获取版本',
                            ...(state['releases'] as List? ?? [])
                                .map((r) => r['tag'] as String),
                            '更新选项'
                          ], (v) {
              if (v != '更新选项') {
                d.version = v;
                change({'version': v});
              }
            })),
            const SizedBox(width: 8),
            button('刷新', () => run('releases')),
            const SizedBox(width: 6),
            button('下载', () => run('download'),
                primary: true, key: 'build.download')
          ])
        else
          button('下载已构建文件', () => run('download'),
              primary: true, key: 'build.download-prebuilt'),
        const SizedBox(height: 8),
        Text(d.source == 0 ? '选择版本 / 下载源码' : '下载后可直接进行文件优化',
            style: EfType.ui(9, color: c.ink2)),
      ]));
  Widget buildPanel() => panel(
      'compile',
      'BUILD',
      '构建',
      d.source == 1
          ? Padding(
              padding: const EdgeInsets.only(top: 20),
              child: Text('已构建文件无需本地构建。\n可在文件优化卡片中选择目标文件并执行优化。',
                  style: EfType.ui(12, color: c.ink2, height: 1.8)))
          : Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                Text('环境', style: EfType.ui(11, color: c.ink)),
                const Spacer(),
                Tooltip(
                    message:
                        state['environment']?['text'] as String? ?? '尚未检测构建环境',
                    child: Text(
                        state['environment']?['ready'] == true
                            ? '已就绪'
                            : (state['environment']?['text'] != null
                                ? '未就绪'
                                : '未检测'),
                        style: EfType.ui(10, color: c.ink2))),
                const SizedBox(width: 8),
                button('重新检测', () => run('environment'))
              ]),
              const SizedBox(height: 8),
              Row(children: [
                Expanded(
                    child: dropdown(
                        'build.project',
                        d.project,
                        live == null
                            ? ['未选择项目', '本地项目（预览）', '更新选项']
                            : [
                                '',
                                ...List<String>.from(state['projects'] ?? []),
                                '更新选项'
                              ], (v) {
                  if (v != '更新选项') {
                    d.project = v;
                    change({'project': v});
                  }
                })),
                const SizedBox(width: 8),
                button('构建', () => run('compile'),
                    primary: true,
                    key: 'build.compile',
                    enabled:
                        live == null || state['capabilities']?['build'] == true)
              ]),
              const SizedBox(height: 8),
              switchRow('build.optimize', '优化构建', d.optimize, (v) {
                d.optimize = v;
                change({'optimize': v});
              }),
            ]),
      lower: true);
  Widget ritualPanel() => panel(
      'optimize',
      'FILE OPTIMIZATION',
      '文件优化',
      Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        switchRow('build.ritual', '神秘仪式', d.ritual, (v) {
          d.ritual = v;
          change({'ritual': v});
        }),
        if (d.ritual) ...[
          const SizedBox(height: 6),
          Row(children: [
            Expanded(
                child: TextField(
                    key: const ValueKey('build.target'),
                    contextMenuBuilder: efTextContextMenu,
                    controller: d.target,
                    readOnly: true,
                    textAlignVertical: TextAlignVertical.center,
                    style: EfType.ui(12, color: c.ink),
                    decoration:
                        efInputDecoration(context, '目标文件', hint: '请选择目标文件'))),
            const SizedBox(width: 6),
            button('浏览', browseTarget)
          ]),
          const SizedBox(height: 7),
          Row(children: [
            Expanded(
                child: compactSegments('build.ritualType',
                    ['包装', '涂装(py)', '涂装(rs)'], d.ritualType, (v) {
              d.ritualType = v;
              change({'ritualType': v});
            })),
            const SizedBox(width: 6),
            button('执行', () => run('ritual'),
                primary: true,
                key: 'build.run-ritual',
                enabled: live == null ||
                    (state['capabilities']?['ritual'] as List? ??
                            [false, false, false])[d.ritualType] ==
                        true)
          ])
        ] else
          Padding(
              padding: const EdgeInsets.only(top: 15),
              child:
                  Text('开启后配置目标文件和仪式类型。', style: EfType.ui(10, color: c.ink2))),
      ]),
      right: true);
  Widget automationPanel() => panel(
      'automation',
      'AUTOMATION',
      '自动化',
      Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('复制到 GIMI', style: EfType.ui(9, color: c.ink2, height: 1)),
        const SizedBox(height: 3),
        Row(children: [
          Expanded(
              child: compactSegments(
                  'build.copyType', ['构建产物', '仪式产物'], d.copyType, (v) {
            d.copyType = v;
            change({'copyType': v});
          })),
          const SizedBox(width: 6),
          button('复制', () => run('copy'), primary: true, key: 'build.copy')
        ]),
        const SizedBox(height: 4),
        switchRow('build.autoRitual', '构建完成后执行神秘仪式', d.autoRitual, (v) {
          d.autoRitual = v;
          change({'autoRitual': v});
        }),
        switchRow('build.autoMove', '完成后自动复制到 GIMI', d.autoMove, (v) {
          d.autoMove = v;
          change({'autoMove': v});
        }),
      ]),
      right: true,
      lower: true);
  Future<void> browseTarget() async {
    if (widget.pickPath != null) {
      final path =
          await widget.pickPath!(folder: false, initial: d.target.text);
      if (path != null && mounted) {
        change({'target': path});
        setState(() => d.target.text = path);
      }
      return;
    }
    var path = d.target.text;
    await showEfDialog<void>(
        context: context,
        builder: (_) => EfDialog(
                eyebrow: 'TARGET FILE',
                title: const Text('目标文件'),
                content: SizedBox(
                    width: 420,
                    child: TextFormField(
                        contextMenuBuilder: efTextContextMenu,
                        initialValue: path,
                        onChanged: (v) => path = v,
                        decoration: const InputDecoration(
                            labelText: '目标文件路径', hintText: '输入用于预览的文件路径'))),
                actions: [
                  button('取消', () => Navigator.pop(context)),
                  button('确定', () {
                    d.target.text = path;
                    Navigator.pop(context);
                  })
                ]));
  }

  Future<void> exportLogs() async {
    final content = logs.join('\n');
    setState(() => exporting = true);
    try {
      final logRoot = live != null && state['workspace'] is String
          ? '${Directory(state['workspace'] as String).parent.path}/logs'
          : 'logs';
      final directory = await Directory(logRoot).create(recursive: true);
      final file = File(
          '${directory.path}/build-${DateTime.now().microsecondsSinceEpoch}.log');
      await file.writeAsString('$content\n', flush: true);
      if (!mounted) return;
      await showEfDialog<void>(
          context: context,
          builder: (context) => EfDialog(
                title: const EfPair('LOG EXPORT', '日志已导出', size: 22),
                content: SizedBox(
                    width: 440,
                    child: SelectableText(file.absolute.path,
                        contextMenuBuilder: efTextContextMenu,
                        key: const ValueKey('build.export-path'))),
                actions: [
                  EfButton('关闭',
                      small: true, onPressed: () => Navigator.pop(context))
                ],
              ));
    } catch (error) {
      if (mounted) {
        showEfToast(context, '日志导出失败：$error');
      }
    } finally {
      if (mounted) setState(() => exporting = false);
    }
  }

  Widget terminal() {
    final lines = logs.expand((text) => text.split('\n')).toList();
    return region(
        'terminal',
        Container(
          color: c.panel,
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Container(
              key: const ValueKey('build.terminal-header'),
              height: 32,
              color: Ef.commandBar,
              padding: const EdgeInsets.symmetric(horizontal: 14),
              child: Row(children: [
                Text('>_',
                    semanticsLabel: '终端',
                    style: EfType.ui(16, weight: 700, color: Colors.white)),
                const Spacer(),
                terminalAction(
                    exporting ? '导出中…' : '导出',
                    const ValueKey('build.export-log'),
                    exporting || logs.isEmpty ? null : exportLogs),
                const SizedBox(width: 6),
                terminalAction('清空', const ValueKey('build.clear-log'),
                    logs.isEmpty ? null : () => setState(() => logs.clear())),
              ]),
            ),
            Divider(height: 1, color: c.rule),
            Expanded(
                child: lines.isEmpty
                    ? Center(
                        child: Padding(
                            padding: const EdgeInsets.all(20),
                            child: Text('终端已清空，后续操作的输出将显示在这里。',
                                textAlign: TextAlign.center,
                                style: EfType.ui(12, color: c.ink2))))
                    : Scrollbar(
                        controller: output,
                        thumbVisibility: true,
                        child: ListView.builder(
                          controller: output,
                          padding: const EdgeInsets.symmetric(
                              horizontal: 14, vertical: 14),
                          itemCount: lines.length,
                          itemBuilder: (context, index) => Padding(
                              padding: const EdgeInsets.only(bottom: 4),
                              child: Row(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    SizedBox(
                                        width: 30,
                                        child: Text(
                                            (index + 1)
                                                .toString()
                                                .padLeft(3, '0'),
                                            style: EfType.ui(10,
                                                color: c.ink2, height: 1.7))),
                                    const SizedBox(width: 10),
                                    Expanded(
                                        child: SelectableText(lines[index],
                                            contextMenuBuilder:
                                                efTextContextMenu,
                                            style: TextStyle(
                                                fontFamily: 'Consolas',
                                                fontFamilyFallback: const [
                                                  'Microsoft YaHei',
                                                  'Noto Sans SC'
                                                ],
                                                fontSize: 12,
                                                color: c.ink,
                                                height: 1.45))),
                                  ])),
                        ))),
            Divider(height: 1, color: c.rule),
            Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                child: Text(
                    live == null
                        ? '未连接后端'
                        : live!.busy && live!.taskKind.startsWith('build.')
                            ? '${live!.status}${live!.taskProgress == null ? '' : ' · ${(live!.taskProgress! * 100).toStringAsFixed(0)}%'}'
                            : '就绪 / ${state['workspace'] ?? '等待连接'}',
                    style: EfType.ui(10, color: c.ink2))),
          ]),
        ));
  }

  Widget terminalAction(String label, Key key, VoidCallback? onPressed) =>
      SizedBox(
          height: 24,
          child: TextButton(
            key: key,
            style: ButtonStyle(
              minimumSize: const WidgetStatePropertyAll(Size(44, 24)),
              padding: const WidgetStatePropertyAll(
                  EdgeInsets.symmetric(horizontal: 10)),
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              shape: WidgetStatePropertyAll(efCut(br: 6)),
              backgroundColor: WidgetStateProperty.resolveWith((states) =>
                  states.contains(WidgetState.hovered) ||
                          states.contains(WidgetState.pressed)
                      ? c.signal
                      : const Color(0xFF303030)),
              foregroundColor: WidgetStateProperty.resolveWith((states) =>
                  states.contains(WidgetState.disabled)
                      ? Colors.white38
                      : states.contains(WidgetState.hovered) ||
                              states.contains(WidgetState.pressed)
                          ? c.onSignal
                          : Colors.white),
            ),
            onPressed: onPressed,
            child: Text(label, style: EfType.ui(11, weight: 600)),
          ));

  Widget cleanupPage() => region(
      'cleanup',
      Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        const SizedBox(height: 12),
        for (final item in live?.cleanup['items'] as List? ?? [])
          Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Container(
                  color: c.panel,
                  padding: const EdgeInsets.all(14),
                  child: Row(children: [
                    Checkbox(
                        value: selectedCleanup.contains(item['id']),
                        onChanged: available
                            ? (value) => setState(() {
                                  if (value == true) {
                                    selectedCleanup.add(item['id'] as String);
                                  } else {
                                    selectedCleanup.remove(item['id']);
                                  }
                                })
                            : null),
                    Expanded(
                      child: Text('${item['group']} / ${item['name']}',
                          style: EfType.ui(13, weight: 700, color: c.ink)),
                    ),
                    Text(
                        '${((item['bytes'] as num) / 1048576).toStringAsFixed(2)} MB',
                        style: EfType.ui(11, color: c.ink2))
                  ]))),
        Row(children: [
          Text('已选择 ${selectedCleanup.length} 项',
              style: EfType.ui(11, color: c.ink2)),
          const Spacer(),
          button('重新扫描', () {
            selectedCleanup.clear();
            run('cleanup.scan');
          }),
          const SizedBox(width: 8),
          button(
              '全选',
              () => setState(() {
                    selectedCleanup.addAll(
                        (live?.cleanup['items'] as List? ?? [])
                            .map((item) => item['id'] as String));
                  })),
          const SizedBox(width: 8),
          button('清理选中', confirmCleanup)
        ]),
        const SizedBox(height: 12),
        Text('仅清理 Neo 构建工作区；选择项目后可删除对应源码、批次或产物。',
            style: EfType.ui(11, color: c.ink2)),
      ]));

  Future<void> confirmCleanup() async {
    if (selectedCleanup.isEmpty) return;
    final items = (live?.cleanup['items'] as List? ?? [])
        .where((item) => selectedCleanup.contains(item['id']))
        .toList();
    final confirmed = await showEfDialog<bool>(
        context: context,
        builder: (context) => EfDialog(
                eyebrow: 'CONFIRM',
                title: const Text('清理选中项'),
                content: SizedBox(
                    width: 420,
                    child: SingleChildScrollView(
                        child: Text(
                            '将删除：\n${items.map((i) => '${i['group']} / ${i['name']}').join('\n')}'))),
                actions: [
                  EfButton('取消',
                      small: true,
                      onPressed: () => Navigator.pop(context, false)),
                  EfButton('删除',
                      small: true,
                      kind: EfButtonKind.danger,
                      onPressed: () => Navigator.pop(context, true))
                ]));
    if (confirmed == true && mounted) {
      await live?.businessTask(
          'build.cleanup.apply', {'ids': selectedCleanup.toList()});
      if (mounted) setState(selectedCleanup.clear);
    }
  }
}
