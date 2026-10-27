import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'backend/neo_controller.dart';
import 'backend/neo_backend.dart';
import 'ef/tokens.dart';
import 'ef/widgets.dart';
import 'ef/toast.dart';
import 'ef/marks.dart';

/// Manual recursive group controls; no game testing or answer workflow.
class NeoBisect extends StatefulWidget {
  const NeoBisect(
      {super.key,
      this.controller,
      required this.onBack,
      this.region,
      this.pickPath});
  final NeoController? controller;
  final VoidCallback onBack;
  final Widget Function(String, Widget)? region;
  final Future<String?> Function({required bool folder, String initial})?
      pickPath;
  @override
  State<NeoBisect> createState() => _NeoBisectState();
}

class _NeoBisectState extends State<NeoBisect> {
  String? sessionId;
  bool hadWorkspace = false;
  String? chosenRoot;
  String selected = 'root.1';
  NeoController? get controller => widget.controller;
  Map<String, dynamic> get data => controller?.bisectState ?? {};
  String get phase => data['status'] as String? ?? 'idle';
  bool get available => controller?.ready == true && controller?.busy == false;
  bool get editable =>
      available && phase == 'ready' && (data['errors'] as List? ?? []).isEmpty;
  EfColors get c => EfColors.of(context);
  List<Map<String, dynamic>> maps(Object? v) => (v as List? ?? [])
      .map((e) => Map<String, dynamic>.from(e as Map))
      .toList();
  // Closed sessions retain their audit report, but no longer populate the workspace.
  bool get showSession => !['idle', 'closed'].contains(phase);
  List<Map<String, dynamic>> get nodes =>
      showSession ? maps(data['nodes']) : [];
  int get recordedCount => showSession ? maps(data['units']).length : 0;
  Map<String, dynamic>? get group =>
      nodes.where((n) => n['id'] == selected).firstOrNull ?? nodes.firstOrNull;
  Widget mark(String id, Widget child) =>
      widget.region?.call(id, child) ?? child;
  static String stateLabel(Object? value) => switch (value) {
        'enabled' => '全部启用',
        'disabled' => '全部停用',
        _ => '部分启用',
      };
  static String actionLabel(Object? value) => switch (value) {
        'enable' => '启用',
        'disable' => '停用',
        'undo' => '撤销启停',
        _ => '$value',
      };

  @override
  void initState() {
    super.initState();
    sessionId = data['sessionId'] as String?;
    hadWorkspace = showSession;
    controller?.addListener(onController);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) unawaited(controller?.loadBisect());
    });
  }

  @override
  void dispose() {
    controller?.removeListener(onController);
    super.dispose();
  }

  void run(String action, [Map<String, dynamic> extra = const {}]) {
    if (!available) return;
    unawaited(controller!.businessTask('bisect.$action', {
      'sessionId': data['sessionId'],
      'generation': data['generation'],
      if (action == 'scan' && chosenRoot != null) 'root': chosenRoot,
      ...extra,
    }));
  }

  @override
  void didUpdateWidget(covariant NeoBisect oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != controller) {
      oldWidget.controller?.removeListener(onController);
      controller?.addListener(onController);
      onController();
    }
  }

  void onController() {
    if (!mounted) return;
    final next = data['sessionId'] as String?;
    if (sessionId != next || (hadWorkspace && !showSession)) {
      selected = 'root.1';
    }
    sessionId = next;
    hadWorkspace = showSession;
    setState(() {});
  }

  void selectGroup(String id) {
    if (!nodes.any((n) => n['id'] == id)) return;
    setState(() => selected = id);
  }

  Widget button(String label, VoidCallback? tap,
      {bool primary = false,
      Key? key,
      double height = 28,
      double fontSize = 10,
      bool navigation = false,
      Color? fill,
      Color? foreground,
      double padding = 9}) {
    final enabled = tap != null && (navigation || available);
    final background = fill ?? (primary ? c.ink : c.chip);
    final ink = foreground ?? (primary ? c.paper : c.ink);
    return _BranchAction(
        label: label,
        onTap: enabled ? tap : null,
        actionKey: key,
        background: background,
        foreground: ink,
        height: height,
        fontSize: fontSize,
        padding: padding);
  }

  Future<void> changeDirectory() async {
    final path = await widget.pickPath?.call(
        folder: true, initial: chosenRoot ?? data['root'] as String? ?? '');
    if (!mounted || path == null || path.isEmpty) return;
    setState(() => chosenRoot = path);
  }

  Widget pair(String en, String zh, {double size = 15}) => Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('// $en',
                style: EfType.ui(size == 24 ? 9 : 8,
                    weight: 600,
                    width: 125,
                    spacing: .14,
                    height: 1.5,
                    color: c.ink2)),
            const SizedBox(height: 1),
            Text(zh,
                style: EfType.ui(size,
                    weight: 700,
                    width: 100,
                    height: size == 24 ? 1.3 : 1.4,
                    color: c.ink)),
          ]);
  Widget text(String value, {double size = 11, bool bold = false}) => Text(
      value,
      style:
          EfType.ui(size, color: c.ink, weight: bold ? 700 : 400, height: 1.7));
  Widget copyText(String value) =>
      SelectableText(value, style: EfType.ui(11, color: c.ink, height: 1.7));
  Future<void> details(String title, Widget content) => showEfDialog<void>(
      context: context,
      builder: (ctx) => EfDialog(
              title:
                  Tooltip(
                      message: title,
                      child: Text(title,
                          maxLines: 2, overflow: TextOverflow.ellipsis)),
              eyebrow: 'MOD GROUPS',
              content: content,
              actions: [
                EfButton('关闭', small: true, onPressed: () => Navigator.pop(ctx))
              ]));

  void history() => details(
      '启停记录 / ${maps(data['history']).length} 次',
      Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        copyText('初始快照：${maps(data['units']).length} 个启用模组 / '
            '${(data['initialDisabled'] as List? ?? []).length} 个初始停用项\n'
            '排查目录：${data['root'] ?? '尚未记录'}'),
        const SizedBox(height: 10),
        if (maps(data['history']).isEmpty) text('每次分组启停及撤销操作会记录在这里。'),
        for (final h in maps(data['history']))
          Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: copyText(
                  '${actionLabel(h['type'])} / ${h['groupId']} ${h['undone'] == true ? '/ 已撤销' : ''}\n'
                  '启用数量：${(h['beforeEnabled'] as List? ?? []).length} → ${(h['afterEnabled'] as List? ?? []).length}')),
        copyText('恢复记录：${data['logPath'] ?? '尚未创建'}'),
        if (data['sessionId'] != null)
          EfButton('导出记录', small: true, onPressed: export),
      ]));

  void iniDetails(Map<String, dynamic> item) => details(
      '${item['modName']} / ${item['name']}',
      Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        const EfEyebrow('CURRENT LOGICAL PATH'),
        copyText('${item['currentPath'] ?? item['originalPath']}'),
        const SizedBox(height: 10),
        const EfEyebrow('TARGET PATH'),
        copyText('${item['currentTargetPath'] ?? item['targetPath']}'),
        const SizedBox(height: 10),
        copyText('初始所属资源状态：启用\n记录时的 SHA-256：${item['sha256']}'),
        const SizedBox(height: 14),
        const EfPair('OPERATIONS', '关联启停记录', size: 16),
        if (maps(item['operations']).isEmpty) text('所属模组发生启停变化后，这里会显示对应操作和路径。'),
        for (final op in maps(item['operations']))
          Padding(
              padding: const EdgeInsets.only(top: 10),
              child: copyText('${actionLabel(op['type'])} / ${op['groupId']}\n'
                  '所属模组：${op['resourceEnabled'] == true ? '启用' : '停用'}\n${op['logicalPath']}')),
      ]));

  void modDetails(Map<String, dynamic> item) => details(
      '${item['name']}',
      Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        text('记录依据：资源浏览页的初始启停状态。'),
        for (final ini
            in maps(data['inis']).where((i) => i['unitId'] == item['id']))
          smallAction('INI / ${ini['name']} ↗', () => iniDetails(ini)),
        for (final e
            in maps(data['entries']).where((e) => e['unitId'] == item['id']))
          Padding(
              padding: const EdgeInsets.only(top: 10),
              child: copyText(
                  '${e['link'] == true ? 'Junction 入口' : '模组或联接内子模组'}\n'
                  '${e['parent']}\\${e['currentName']}\n初始名称：${e['initialName']}\n目标：${e['originalTarget']}\n'
                  '别名入口：${(e['aliases'] as List? ?? []).join('\n')}')),
      ]));

  Future<void> export() async {
    if (!available) return;
    try {
      final result = await controller!.backend.call('bisect.export');
      if (mounted) {
        details(
            '记录已导出',
            Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              copyText('${result['path']}'),
              const SizedBox(height: 10),
              EfButton('复制路径',
                  small: true,
                  onPressed: () => Clipboard.setData(
                      ClipboardData(text: '${result['path']}')))
            ]));
      }
    } catch (e) {
      if (mounted) showEfToast(context, neoErrorMessage(e));
    }
  }

  Map<String, dynamic>? node(Object? id) =>
      nodes.where((n) => n['id'] == id).firstOrNull;
  int count(Map<String, dynamic> n) =>
      (n['count'] as num?)?.toInt() ?? (n['unitIds'] as List? ?? []).length;
  String name(Map<String, dynamic> n) =>
      n['id'] == 'root' ? '全部模组' : '${n['label']} 组';
  List<Map<String, dynamic>> children(Map<String, dynamic>? n) =>
      (n?['children'] as List? ?? [])
          .map(node)
          .whereType<Map<String, dynamic>>()
          .toList();
  List<Map<String, dynamic>> ancestors() {
    final path = <Map<String, dynamic>>[], seen = <Object?>{};
    var n = group;
    while (n != null && seen.add(n['id'])) {
      path.insert(0, n);
      n = node(n['parent']);
    }
    return path;
  }

  Widget smallAction(String label, VoidCallback? tap, {Key? key}) =>
      button(label, tap, key: key, height: 25, fontSize: 9, padding: 6);

  Widget badge(Map<String, dynamic> n, {bool inverse = false}) {
    final ink = inverse ? c.paper : c.ink;
    return Container(
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
        decoration: BoxDecoration(border: Border.all(color: ink)),
        child: Text(stateLabel(n['state']),
            maxLines: 1, style: EfType.ui(8, height: 1.35, color: ink)));
  }

  Widget eyebrow(String label, {bool inverse = false}) => Text('// $label',
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
      style: EfType.ui(7,
          weight: 600,
          width: 125,
          spacing: .14,
          height: 1.5,
          color: inverse ? c.paper : c.ink2));

  Future<void> catalog({bool pathOnly = false}) async {
    final values = pathOnly ? ancestors() : nodes;
    await showEfDialog<void>(
        context: context,
        builder: (ctx) => EfDialog(
                title: Text(pathOnly ? '完整分组路径' : '分组目录'),
                eyebrow: 'GROUP DIRECTORY',
                scrollContent: false,
                content: SizedBox(
                    height: 240,
                    child: ListView.builder(
                        key: const ValueKey('bisect.catalog.list'),
                        itemCount: values.length,
                        itemExtent: 46,
                        itemBuilder: (_, i) {
                          final n = values[i];
                          return Material(
                              color: c.panel,
                              child: InkWell(
                                  key: ValueKey('catalog.select.${n['id']}'),
                                  onTap: () {
                                    Navigator.pop(ctx);
                                    selectGroup('${n['id']}');
                                  },
                                  child: Container(
                                      padding: const EdgeInsets.symmetric(
                                          horizontal: 8),
                                      decoration: BoxDecoration(
                                          border: Border(
                                              bottom:
                                                  BorderSide(color: c.rule))),
                                      child: Row(children: [
                                        Expanded(
                                            child: Tooltip(
                                                message: name(n),
                                                child: Text(name(n),
                                                    maxLines: 1,
                                                    overflow:
                                                        TextOverflow.ellipsis,
                                                    style: EfType.ui(11,
                                                        weight: 600,
                                                        color: c.ink)))),
                                        Text(
                                            '${count(n)} 个 / ${stateLabel(n['state'])}',
                                            style: EfType.ui(9, color: c.ink2)),
                                      ]))));
                        })),
                actions: [
                  EfButton('关闭',
                      small: true, onPressed: () => Navigator.pop(ctx))
                ]));
  }

  Future<void> groupMods(Map<String, dynamic> n) async {
    final ids = (n['unitIds'] as List? ?? []).toSet();
    final units =
        maps(data['units']).where((u) => ids.contains(u['id'])).toList();
    final entries = maps(data['entries']);
    final byUnit = <Object?, List<Map<String, dynamic>>>{};
    for (final entry in entries) {
      byUnit.putIfAbsent(entry['unitId'], () => []).add(entry);
    }
    await showEfDialog<void>(
        context: context,
        builder: (ctx) => EfDialog(
                title: Text('${name(n)} / 组内模组'),
                eyebrow: 'GROUP MODS',
                scrollContent: false,
                content: SizedBox(
                    height: 240,
                    child: ListView.builder(
                        key: const ValueKey('bisect.mods.list'),
                        itemCount: units.length,
                        itemExtent: 52,
                        itemBuilder: (_, i) {
                          final item = units[i],
                              owned = byUnit[item['id']] ?? [];
                          final on = owned.isNotEmpty &&
                              owned.every((e) => e['enabled'] == true);
                          final off = owned.isNotEmpty &&
                              owned.every((e) => e['enabled'] != true);
                          final relative =
                              '${owned.firstOrNull?['relative'] ?? item['name']}';
                          return Material(
                              color: c.panel,
                              child: InkWell(
                                  key: ValueKey('mod.open.${item['id']}'),
                                  onTap: () => modDetails(item),
                                  child: Container(
                                      padding: const EdgeInsets.symmetric(
                                          horizontal: 8),
                                      decoration: BoxDecoration(
                                          border: Border(
                                              bottom:
                                                  BorderSide(color: c.rule))),
                                      child: Row(children: [
                                        Text('${i + 1}'.padLeft(2, '0'),
                                            style: EfType.ui(8, color: c.ink2)),
                                        const SizedBox(width: 10),
                                        Expanded(
                                            child: Column(
                                                crossAxisAlignment:
                                                    CrossAxisAlignment.start,
                                                mainAxisAlignment:
                                                    MainAxisAlignment.center,
                                                children: [
                                              Tooltip(
                                                  message: '${item['name']}',
                                                  child: Text('${item['name']}',
                                                      maxLines: 1,
                                                      overflow:
                                                          TextOverflow.ellipsis,
                                                      style: EfType.ui(11,
                                                          weight: 600,
                                                          color: c.ink))),
                                              Tooltip(
                                                  message: relative,
                                                  child: Text(relative,
                                                      maxLines: 1,
                                                      overflow:
                                                          TextOverflow.ellipsis,
                                                      style: EfType.ui(8,
                                                          color: c.ink2))),
                                            ])),
                                        const SizedBox(width: 8),
                                        Text(
                                            on
                                                ? '已启用'
                                                : off
                                                    ? '已停用'
                                                    : '部分启用',
                                            style: EfType.ui(9, color: c.ink)),
                                      ]))));
                        })),
                actions: [
                  EfButton('关闭',
                      small: true, onPressed: () => Navigator.pop(ctx))
                ]));
  }

  Widget command() {
    Widget action(String title, VoidCallback? tap,
            {bool back = false, Key? key}) =>
        button(title, tap,
            key: key,
            height: 28,
            navigation: back,
            fill: back ? c.signal : const Color(0xff303030),
            foreground: back ? c.onSignal : const Color(0xffededed));
    return mark(
        'bisect.command',
        Container(
            height: 48,
            color: const Color(0xff161616),
            padding: const EdgeInsets.symmetric(horizontal: 22),
            child: Row(children: [
              Expanded(
                  child: Row(children: [
                Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('// MOD BISECT',
                          style: EfType.ui(7,
                              width: 125,
                              spacing: .14,
                              color: const Color(0xffa3a3a3))),
                      Text('二分排查',
                          style: EfType.ui(17,
                              weight: 700,
                              height: 1.2,
                              color: const Color(0xffededed))),
                    ]),
                const SizedBox(width: 18),
                Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                  Text('$recordedCount',
                      style: EfType.ui(27,
                          weight: 600,
                          height: 1,
                          color: const Color(0xffededed))),
                  Text('已记录模组',
                      style: EfType.ui(7, color: const Color(0xffa3a3a3))),
                ]),
              ])),
              action('分组目录', nodes.isEmpty ? null : () => catalog()),
              const SizedBox(width: 6),
              action('操作记录', history),
              const SizedBox(width: 6),
              action('刷新状态', phase == 'ready' ? () => run('refresh') : null),
              const SizedBox(width: 6),
              action(
                  '恢复初始状态',
                  ['ready', 'recovery'].contains(phase)
                      ? () => run('restore')
                      : null,
                  key: const ValueKey('bisect.restore')),
              const SizedBox(width: 6),
              action('结束记录', phase == 'ready' ? () => run('finish') : null),
              const SizedBox(width: 6),
              action('返回工具', widget.onBack, back: true),
            ])));
  }

  Widget pathBar() {
    final path = ancestors();
    final visible = path.length > 4
        ? <Map<String, dynamic>?>[
            path.first,
            null,
            ...path.skip(path.length - 2)
          ]
        : path.cast<Map<String, dynamic>?>();
    final directory = '${chosenRoot ?? data['root'] ?? '设置中的 GIMI\\Mods'}';
    return Container(
        height: 30,
        padding: const EdgeInsets.symmetric(horizontal: 22),
        decoration:
            BoxDecoration(border: Border(bottom: BorderSide(color: c.rule))),
        child: Row(children: [
          if (path.isEmpty) text('尚未记录模组', size: 10),
          Expanded(
              child: Row(mainAxisSize: MainAxisSize.min, children: [
            for (var i = 0; i < visible.length; i++) ...[
              if (i > 0) Text(' / ', style: EfType.ui(9, color: c.ink2)),
              if (visible[i] == null)
                button('…', () => catalog(pathOnly: true),
                    height: 23,
                    padding: 7,
                    navigation: true,
                    key: const ValueKey('bisect.ancestors'))
              else
                Flexible(
                    child: Tooltip(
                        message: name(visible[i]!),
                        child: visible[i]!['id'] == group?['id']
                            ? Text('${visible[i]!['label']}',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: EfType.ui(10, weight: 700, color: c.ink))
                            : button(
                                visible[i]!['id'] == 'root'
                                    ? '全部模组'
                                    : '${visible[i]!['label']}',
                                () => selectGroup('${visible[i]!['id']}'),
                                height: 23,
                                padding: 6,
                                navigation: true))),
            ],
          ])),
          if (phase == 'recovery' ||
              phase == 'blocked' ||
              (data['errors'] as List? ?? []).isNotEmpty)
            button('状态需核对 / 查看', showIssues,
                height: 22,
                fontSize: 9,
                navigation: true,
                fill: c.signal,
                foreground: c.onSignal)
          else
            Tooltip(
                message: directory,
                child: SizedBox(
                    width: 220,
                    child: Text(directory,
                        key: const ValueKey('bisect.directory'),
                        textAlign: TextAlign.right,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: EfType.ui(8, color: c.ink2)))),
          const SizedBox(width: 8),
          button(
              '更换目录',
              ['idle', 'closed'].contains(phase) && widget.pickPath != null
                  ? changeDirectory
                  : null,
              height: 23,
              fontSize: 9,
              padding: 6,
              key: const ValueKey('bisect.changeDirectory')),
        ]));
  }

  void showIssues() => details(
      '记录与状态说明',
      Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        if (controller?.error != null) copyText(controller!.error!),
        copyText('${data['message'] ?? '可独立启停每个分组。'}'),
        for (final error in data['errors'] as List? ?? []) copyText('$error'),
        for (final warning in data['warnings'] as List? ?? [])
          copyText('$warning'),
        if (showSession) copyText('联接内子模组的改名会作用于目标目录。INI 为附属记录。'),
      ]));

  Widget operatorPanel() {
    final n = group;
    final recovery = phase == 'recovery';
    return Material(
        color: c.panel,
        shape: efCut(tl: 10, side: BorderSide(color: c.rule)),
        clipBehavior: Clip.antiAlias,
        child: Container(
            decoration: BoxDecoration(
                border: Border(top: BorderSide(color: c.ink, width: 3))),
            child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(13, 8, 13, 9),
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(children: [
                        Expanded(
                            child: pair('GROUP CONTROLS', '操作面板', size: 14)),
                        if (n != null) badge(n)
                      ]),
                      const SizedBox(height: 6),
                      if (recovery) ...[
                        text('发现未结束的记录，请核对状态后继续。', size: 10),
                        const SizedBox(height: 6),
                        if (data['mode'] == 'manual')
                          button('核对状态并继续分组', () => run('resume'),
                              primary: true,
                              key: const ValueKey('bisect.resume')),
                        const SizedBox(height: 6),
                        button('恢复初始状态并结束', () => run('restore')),
                      ] else if (n != null) ...[
                        Tooltip(
                            message: name(n),
                            child: Text('当前 ${name(n)} / ${count(n)} 个',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: EfType.ui(10, color: c.ink))),
                        const SizedBox(height: 6),
                        button(
                            n['state'] == 'enabled' ? '停用本组' : '启用本组',
                            editable
                                ? () => run('toggle', {
                                      'groupId': n['id'],
                                      'enabled': n['state'] != 'enabled'
                                    })
                                : null,
                            fill: c.signal,
                            foreground: c.onSignal,
                            height: 28,
                            key: ValueKey('group.toggle.${n['id']}')),
                        const SizedBox(height: 6),
                        Row(children: [
                          Expanded(
                              child: button(
                                  '继续二分 ↘',
                                  editable &&
                                          children(n).isEmpty &&
                                          count(n) > 1
                                      ? () => run('split', {'groupId': n['id']})
                                      : null,
                                  height: 25,
                                  fontSize: 9,
                                  padding: 6,
                                  key: ValueKey('group.split.${n['id']}'))),
                          const SizedBox(width: 6),
                          Expanded(
                              child: button('查看模组 ↗', () => groupMods(n),
                                  navigation: true,
                                  height: 25,
                                  fontSize: 9,
                                  padding: 6,
                                  key: ValueKey('group.mods.${n['id']}'))),
                        ]),
                        const SizedBox(height: 7),
                        Text(
                            children(n).isNotEmpty
                                ? '本组已拆分，点击子组进入下一级。'
                                : count(n) == 1
                                    ? '本组仅有一个模组，不能继续二分。'
                                    : '每组独立启停；初始停用项不参与。',
                            style: EfType.ui(8, color: c.ink2, height: 1.6)),
                      ],
                      if (controller?.error != null ||
                          (data['errors'] as List? ?? []).isNotEmpty)
                        Padding(
                            padding: const EdgeInsets.only(top: 6),
                            child: button('查看错误与恢复说明', showIssues,
                                height: 24, fontSize: 9, navigation: true)),
                    ]))));
  }

  Widget currentNode(Map<String, dynamic> n) => Semantics(
      selected: true,
      label: '当前 ${name(n)}，${count(n)} 个模组，${stateLabel(n['state'])}',
      child: Material(
          color: c.ink,
          shape: efCut(tl: 9, br: 10),
          clipBehavior: Clip.antiAlias,
          child: Container(
              key: const ValueKey('bisect.current.trace'),
              decoration: BoxDecoration(
                  border: Border(top: BorderSide(color: c.signal, width: 3))),
              child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 10, 16, 8),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Row(children: [
                          Container(width: 7, height: 7, color: c.signal),
                          const SizedBox(width: 7),
                          Expanded(
                              child: eyebrow('CURRENT GROUP', inverse: true))
                        ]),
                        const SizedBox(height: 2),
                        Row(children: [
                          Expanded(
                              child: Tooltip(
                                  message: name(n),
                                  child: Text(name(n),
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: EfType.ui(12,
                                          weight: 700, color: c.paper)))),
                          badge(n, inverse: true)
                        ]),
                        Expanded(
                            child: Row(
                                crossAxisAlignment: CrossAxisAlignment.end,
                                children: [
                              Flexible(
                                  child: FittedBox(
                                      fit: BoxFit.scaleDown,
                                      alignment: Alignment.bottomLeft,
                                      child: Text('${count(n)}',
                                          style: EfType.ui(44,
                                              weight: 600,
                                              height: 1.05,
                                              color: c.paper)))),
                              const SizedBox(width: 8),
                              Padding(
                                  padding: const EdgeInsets.only(bottom: 6),
                                  child: Text(
                                      '个模组 / 启用 ${n['enabledCount'] ?? 0}',
                                      style: EfType.ui(8, color: c.paper))),
                            ])),
                      ])))));

  Widget contextNode(Map<String, dynamic>? n, {bool parent = false}) =>
      Material(
          color: c.panel,
          child: Container(
              decoration: BoxDecoration(
                  border: Border(left: BorderSide(color: c.ink, width: 2))),
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    eyebrow(parent ? 'PARENT / 上一级' : 'SIBLING / 同级另一组'),
                    const SizedBox(height: 3),
                    Row(children: [
                      Expanded(
                          child: Tooltip(
                              message: n == null ? '已到初始记录' : name(n),
                              child: Text(n == null ? '已到初始记录' : name(n),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: EfType.ui(12,
                                      weight: 700, color: c.ink)))),
                      const SizedBox(width: 6),
                      Text(n == null ? '—' : '${count(n)}',
                          style: EfType.ui(21,
                              weight: 600, height: 1.2, color: c.ink)),
                      const SizedBox(width: 6),
                      button(parent ? '←' : '查看',
                          n == null ? null : () => selectGroup('${n['id']}'),
                          navigation: true,
                          height: 24,
                          fontSize: 9,
                          padding: 5,
                          key: ValueKey(
                              parent ? 'group.parent' : 'group.sibling')),
                    ]),
                  ])));

  Widget childNode(Map<String, dynamic> n) => Material(
      color: c.panel,
      shape: efCut(tl: 9, br: 10),
      clipBehavior: Clip.antiAlias,
      child: Container(
          decoration: BoxDecoration(
              border: Border(top: BorderSide(color: c.ink, width: 2))),
          child: Stack(children: [
            if (n['state'] == 'disabled')
              Positioned.fill(
                  child: Opacity(
                      opacity: .12,
                      child: EfHatch(child: const SizedBox.expand()))),
            Padding(
                padding: const EdgeInsets.fromLTRB(12, 7, 12, 7),
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(children: [
                        Expanded(
                            child: Tooltip(
                                message: name(n),
                                child: Text(name(n),
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: EfType.ui(12,
                                        weight: 700, color: c.ink)))),
                        badge(n)
                      ]),
                      Expanded(
                          child: Row(
                              crossAxisAlignment: CrossAxisAlignment.center,
                              children: [
                            Flexible(
                                child: FittedBox(
                                    fit: BoxFit.scaleDown,
                                    alignment: Alignment.centerLeft,
                                    child: Text('${count(n)}',
                                        style: EfType.ui(34,
                                            weight: 600,
                                            height: 1.1,
                                            color: c.ink)))),
                            const SizedBox(width: 8),
                            Text('个模组 / 启用 ${n['enabledCount'] ?? 0}',
                                style: EfType.ui(8, color: c.ink2)),
                          ])),
                      Row(children: [
                        Expanded(
                            child: button(
                                n['state'] == 'enabled' ? '停用本组' : '启用本组',
                                editable
                                    ? () => run('toggle', {
                                          'groupId': n['id'],
                                          'enabled': n['state'] != 'enabled'
                                        })
                                    : null,
                                height: 23,
                                fontSize: 9,
                                padding: 5,
                                key: ValueKey('child.toggle.${n['id']}'))),
                        const SizedBox(width: 5),
                        button('前往 ↗', () => selectGroup('${n['id']}'),
                            navigation: true,
                            height: 23,
                            fontSize: 9,
                            padding: 6,
                            key: ValueKey('group.enter.${n['id']}')),
                      ]),
                    ])),
          ])));

  Widget emptyCanvas() => Center(
          child: Row(mainAxisSize: MainAxisSize.min, children: [
        Text('00',
            style: EfType.ui(140, weight: 600, height: 1, color: c.rule)),
        const SizedBox(width: 45),
        SizedBox(
            width: 350,
            child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  eyebrow('RECORD ENABLED MODS'),
                  Text('从已启用模组开始',
                      style: EfType.ui(25, weight: 700, color: c.ink)),
                  const SizedBox(height: 10),
                  text('记录后，模组将分成 A、B 两组。\n分组关系和启停控制会显示在这里。', size: 11),
                  const SizedBox(height: 14),
                  button('记录已启用模组 →', () => run('scan'),
                      primary: true,
                      height: 34,
                      key: const ValueKey('bisect.scan')),
                  if (controller?.error != null) ...[
                    const SizedBox(height: 8),
                    button('查看记录错误', showIssues, navigation: true)
                  ],
                ])),
      ]));

  Widget canvas() {
    final n = group;
    if (n == null) {
      return mark(
          'bisect.canvas',
          phase == 'blocked'
              ? Center(
                  child: SizedBox(
                      width: 520,
                      child: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            pair('RECOVERY', '恢复记录需要处理', size: 24),
                            const SizedBox(height: 12),
                            copyText('${data['message']}'),
                            const SizedBox(height: 12),
                            button('查看恢复说明', showIssues, navigation: true)
                          ])))
              : emptyCanvas());
    }
    final parent = node(n['parent']), next = children(n);
    final sibling =
        children(parent).where((v) => v['id'] != n['id']).firstOrNull;
    return mark('bisect.canvas', LayoutBuilder(builder: (context, box) {
      Widget at(String id, Rect r, Widget child) => Positioned(
          left: box.maxWidth * r.left / 960,
          top: box.maxHeight * r.top / 360,
          width: box.maxWidth * r.width / 960,
          height: box.maxHeight * r.height / 360,
          child: mark(id, child));
      return Stack(clipBehavior: Clip.hardEdge, children: [
        Positioned.fill(
            child: IgnorePointer(
                child: CustomPaint(
                    painter: _BranchWires(c.ink2, sibling != null,
                        next.isNotEmpty, next.length > 1)))),
        at('bisect.parent', const Rect.fromLTWH(28, 262, 230, 80),
            contextNode(parent, parent: true)),
        if (sibling != null)
          at('bisect.sibling', const Rect.fromLTWH(370, 286, 220, 56),
              contextNode(sibling)),
        at(
            'bisect.current',
            const Rect.fromLTWH(370, 143, 220, 108),
            KeyedSubtree(
                key: ValueKey('graph.current.${n['id']}'),
                child: currentNode(n))),
        if (next.isNotEmpty)
          at('bisect.child.1', const Rect.fromLTWH(696, 28, 222, 112),
              childNode(next[0]))
        else
          at(
              'bisect.next',
              const Rect.fromLTWH(696, 100, 222, 110),
              Material(
                  color: c.panel,
                  child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            eyebrow('NEXT LEVEL'),
                            const SizedBox(height: 7),
                            text('没有下一层', bold: true, size: 14),
                            const SizedBox(height: 5),
                            text(
                                count(n) == 1
                                    ? '本组仅有一个模组，\n不能继续二分。'
                                    : '点击操作面板中的\n「继续二分」。',
                                size: 10)
                          ])))),
        if (next.length > 1)
          at('bisect.child.2', const Rect.fromLTWH(696, 234, 222, 112),
              childNode(next[1])),
        at('bisect.controls', const Rect.fromLTWH(28, 18, 260, 180),
            operatorPanel()),
      ]);
    }));
  }

  Widget footer() {
    final n = group, parent = node(n?['parent']);
    return SizedBox(
        height: 76,
        child: Stack(children: [
          Positioned(
              left: 22,
              top: 26,
              width: 90,
              height: 25,
              child: button('← 上一级',
                  parent == null ? null : () => selectGroup('${parent['id']}'),
                  navigation: true,
                  height: 25,
                  fontSize: 9,
                  padding: 6,
                  key: const ValueKey('bisect.up'))),
          Positioned(
              left: 117,
              top: 26,
              child: button(
                  '撤销',
                  editable &&
                          maps(data['history']).any((h) =>
                              ['enable', 'disable'].contains(h['type']) &&
                              h['undone'] != true)
                      ? () => run('undo')
                      : null,
                  height: 25,
                  fontSize: 9,
                  padding: 6)),
          Positioned(
              right: 22,
              top: 8,
              child: Text(
                  '第 ${ancestors().isEmpty ? 0 : ancestors().length - 1} 层 / '
                  '${showSession ? data['groupCount'] ?? 0 : 0} 个末级组',
                  style: EfType.ui(8, color: c.ink2))),
          Positioned(
              right: 22,
              top: 26,
              width: 90,
              height: 25,
              child: button(
                  '末级组再二分',
                  editable &&
                          nodes.any((n) => children(n).isEmpty && count(n) > 1)
                      ? () => run('splitLeaves')
                      : null,
                  height: 25,
                  fontSize: 9,
                  padding: 6,
                  key: const ValueKey('group.splitLeaves'))),
        ]));
  }

  @override
  Widget build(BuildContext context) => Column(children: [
        command(),
        pathBar(),
        Expanded(child: canvas()),
        footer(),
      ]);
}

class _BranchWires extends CustomPainter {
  const _BranchWires(
      this.color, this.sibling, this.firstChild, this.secondChild);
  final Color color;
  final bool sibling, firstChild, secondChild;
  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    canvas.scale(size.width / 960, size.height / 360);
    final paint = Paint()
      ..color = color.withValues(alpha: .7)
      ..strokeWidth = 1
      ..style = PaintingStyle.stroke;
    final junctionY = sibling ? (197.0 + 314.0) / 2 : 197.0;
    final parent = Path()
      ..moveTo(370, 197)
      ..lineTo(314, 197);
    if (sibling) {
      parent
        ..lineTo(314, 314)
        ..lineTo(370, 314);
    }
    parent
      ..moveTo(258, 302)
      ..lineTo(286, 302)
      ..lineTo(286, junctionY)
      ..lineTo(314, junctionY);
    canvas.drawPath(parent, paint);
    if (firstChild) {
      canvas.drawPath(
          Path()
            ..moveTo(590, 197)
            ..lineTo(642, 197)
            ..lineTo(642, 84)
            ..lineTo(696, 84),
          paint);
    }
    if (secondChild) {
      canvas.drawPath(
          Path()
            ..moveTo(642, 197)
            ..lineTo(642, 290)
            ..lineTo(696, 290),
          paint);
    }
    final leader = Path()
      ..moveTo(288, 152)
      ..lineTo(326, 152)
      ..lineTo(370, 178);
    for (final metric in leader.computeMetrics()) {
      for (double start = 0; start < metric.length; start += 8) {
        canvas.drawPath(
            metric.extractPath(start, (start + 4).clamp(0, metric.length)),
            paint);
      }
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(_BranchWires oldDelegate) =>
      color != oldDelegate.color ||
      sibling != oldDelegate.sibling ||
      firstChild != oldDelegate.firstChild ||
      secondChild != oldDelegate.secondChild;
}

/// A clipped, left-to-right accent wipe shared by every action on this page.
class _BranchAction extends StatefulWidget {
  const _BranchAction(
      {required this.label,
      required this.onTap,
      required this.background,
      required this.foreground,
      required this.height,
      required this.fontSize,
      required this.padding,
      this.actionKey});
  final String label;
  final VoidCallback? onTap;
  final Color background, foreground;
  final double height, fontSize, padding;
  final Key? actionKey;
  @override
  State<_BranchAction> createState() => _BranchActionState();
}

class _BranchActionState extends State<_BranchAction> {
  bool hovered = false, focused = false, pressed = false;
  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context), enabled = widget.onTap != null;
    final active = enabled && (hovered || pressed);
    final duration = Ef.d(context, pressed ? Ef.press : Ef.wipe);
    return Semantics(
        button: true,
        enabled: enabled,
        child: Material(
            color: enabled ? widget.background : c.chip.withValues(alpha: .55),
            shape: efCut(
                br: 7,
                side: focused && enabled
                    ? BorderSide(color: c.trace, width: 2)
                    : BorderSide.none),
            clipBehavior: Clip.antiAlias,
            child: InkWell(
                key: widget.actionKey,
                onTap: widget.onTap,
                hoverColor: Colors.transparent,
                focusColor: Colors.transparent,
                highlightColor: Colors.transparent,
                splashColor: Colors.transparent,
                onHover: (value) => setState(() => hovered = value),
                onFocusChange: (value) => setState(() => focused = value),
                onHighlightChanged: (value) => setState(() => pressed = value),
                child: SizedBox(
                    height: widget.height,
                    child: Stack(alignment: Alignment.center, children: [
                      Positioned.fill(
                          child: IgnorePointer(
                              child: AnimatedFractionallySizedBox(
                                  alignment: Alignment.centerLeft,
                                  widthFactor: active ? 1 : 0,
                                  heightFactor: 1,
                                  duration: duration,
                                  curve: Ef.mech,
                                  child: ColoredBox(color: c.signal)))),
                      Padding(
                          padding:
                              EdgeInsets.symmetric(horizontal: widget.padding),
                          child: Center(
                              widthFactor: 1,
                              child: AnimatedDefaultTextStyle(
                                  duration: duration,
                                  curve: Ef.mech,
                                  style: EfType.ui(widget.fontSize,
                                      weight: 700,
                                      width: 100,
                                      height: 1.4,
                                      color: !enabled
                                          ? c.ink2.withValues(alpha: .45)
                                          : active
                                              ? c.onSignal
                                              : widget.foreground),
                                  child: Text(widget.label,
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis)))),
                    ])))));
  }
}
