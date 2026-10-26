import 'package:flutter/material.dart';
import 'ef/menus.dart';

import 'ef/tokens.dart';
import 'ef/fields.dart';
import 'ef/marks.dart';
import 'ef/widgets.dart';
import 'ef/toast.dart';

/// Editing state; persistence is owned by the application controller.
class SettingsDraft {
  int page = 0, hunting = 2, warning = 0, launchMethod = 0, injection = 0;
  bool autoCheck = false, custom = false, libraries = false;
  bool cleanupOnExit = false;
  int? selectedEntry;
  final whitelist = <({String path, bool folder})>[
    (path: '示例配置.ini', folder: false),
    (path: '示例日志.txt', folder: false),
    (path: '示例目录/', folder: true),
  ];
  final game = TextEditingController(), gimi = TextEditingController();
  final command = TextEditingController(), dlls = TextEditingController();
  final accent = TextEditingController(text: '#39C5BB');
  void load(Map<String, dynamic> config) {
    game.text = config['game_folder'] as String;
    gimi.text = config['gimi_folder'] as String;
    command.text = config['custom_launch_cmd'] as String;
    dlls.text = config['extra_libraries'] as String;
    accent.text = config['accent_color'] as String;
    hunting = config['hunting'] as int;
    warning = config['warning'] as int;
    launchMethod =
        ['native', 'shell', 'manual'].indexOf(config['launch_method']);
    injection = ['hook', 'inject', 'bypass']
        .indexOf(config['custom_launch_inject_mode']);
    autoCheck = config['auto_check_update'] == true;
    cleanupOnExit = config['cleanup_on_exit'] == true;
    custom = config['custom_launch_enabled'] == true;
    libraries = config['extra_libraries_enabled'] == true;
    selectedEntry = null;
    whitelist
      ..clear()
      ..addAll((config['gimi_update_whitelist'] as List)
          .cast<String>()
          .map((p) => (path: p, folder: p.endsWith('/') || p.endsWith('\\'))));
  }

  Map<String, dynamic> toSettings() => {
        'game_folder': game.text.trim(),
        'gimi_folder': gimi.text.trim(),
        'hunting': hunting,
        'warning': warning,
        'auto_check_update': autoCheck,
        'cleanup_on_exit': cleanupOnExit,
        'launch_method': ['native', 'shell', 'manual'][launchMethod],
        'custom_launch_enabled': custom,
        'custom_launch_cmd': command.text.trim(),
        'custom_launch_inject_mode': ['hook', 'inject', 'bypass'][injection],
        'extra_libraries_enabled': libraries,
        'extra_libraries': dlls.text,
        'gimi_update_whitelist': whitelist.map((x) => x.path).toList(),
      };
  void dispose() {
    for (final controller in [game, gimi, command, dlls, accent]) {
      controller.dispose();
    }
  }
}

class NeoSettings extends StatefulWidget {
  const NeoSettings(
      {super.key,
      required this.draft,
      required this.dark,
      required this.onTheme,
      required this.onAccent,
      this.openReview,
      required this.region,
      this.onChanged,
      this.pickPath,
      this.onImport,
      this.live = false,
      this.ready = true,
      this.cacheBytes,
      this.cacheClearing = false,
      this.cacheProgress,
      this.cacheMessage = '',
      this.onRefreshCache,
      this.onClearCache});
  final SettingsDraft draft;
  final bool dark;
  final VoidCallback onTheme;
  final VoidCallback? openReview;
  final ValueChanged<Color> onAccent;
  final Widget Function(String, Widget) region;
  final VoidCallback? onChanged, onImport, onClearCache, onRefreshCache;
  final Future<String?> Function({required bool folder, String initial})?
      pickPath;
  final bool live, ready;
  final int? cacheBytes;
  final bool cacheClearing;
  final double? cacheProgress;
  final String cacheMessage;
  @override
  State<NeoSettings> createState() => _NeoSettingsState();
}

class _NeoSettingsState extends State<NeoSettings> {
  SettingsDraft get d => widget.draft;
  EfColors get c => EfColors.of(context);
  final scroll = ScrollController();
  final whitelistScroll = ScrollController();

  @override
  void initState() {
    super.initState();
    if (d.page == 3) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) widget.onRefreshCache?.call();
      });
    }
  }

  @override
  void dispose() {
    scroll.dispose();
    whitelistScroll.dispose();
    super.dispose();
  }

  Widget region(String name, Widget child) =>
      widget.region('settings.$name', child);
  Widget button(String label, VoidCallback tap, {bool primary = false}) =>
      EfButton(label,
          small: true,
          onPressed: tap,
          kind: primary ? EfButtonKind.go : EfButtonKind.normal);
  Widget section(String en, String zh) => _SettingsSection(en, zh);
  List<Widget> cards(List<Widget> content) {
    final result = <Widget>[];
    var en = ['PATHS', 'GIMI', 'LAUNCH METHOD', 'STORAGE', 'OMG'][d.page];
    var title = ['路径配置', 'GIMI 配置', '启动方法', '缓存管理', 'OMG'][d.page];
    var body = <Widget>[];
    void flush() {
      if (body.isEmpty) return;
      result.add(region(
          'card.${en.toLowerCase()}',
          Padding(
              padding: const EdgeInsets.only(bottom: 14),
              child: Container(
                  key: ValueKey('settings.card.$en'),
                  decoration:
                      ShapeDecoration(color: c.panel, shape: efCut(tl: 18)),
                  padding: const EdgeInsets.all(16),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _SettingsSection(en, title),
                        const SizedBox(height: 12),
                        ...body,
                      ])))));
    }

    for (final item in content) {
      if (item is _SettingsSection) {
        flush();
        en = item.english;
        title = item.title;
        body = [];
      } else {
        body.add(item);
      }
    }
    flush();
    return result;
  }

  Widget label(String text, {String? help}) =>
      Row(mainAxisSize: MainAxisSize.min, children: [
        Text(text, style: EfType.ui(12, weight: 600, color: c.ink)),
        if (help != null)
          Tooltip(
              message: help,
              child: Semantics(
                  button: true,
                  label: '查看$text说明',
                  child: SizedBox(
                      width: 30,
                      height: 30,
                      child: InkWell(
                          key: ValueKey('settings.help.$text'),
                          hoverColor: c.chip,
                          onTap: () => showEfDialog<void>(
                              context: context,
                              builder: (_) =>
                                  EfDialog(
                                      eyebrow: 'HELP',
                                      title: Text(text),
                                      content: SizedBox(
                                          width: 440,
                                          child: SelectableText(help,
                                              contextMenuBuilder:
                                                  efTextContextMenu,
                                              style: EfType.ui(13, color: c.ink, height: 1.7))),
                                      actions: [
                                        button(
                                            '关闭', () => Navigator.pop(context))
                                      ])),
                          child: Center(
                              child: CustomPaint(
                                  size: const Size(18, 18),
                                  painter: _HelpGlyph(c.ink))))))),
      ]);
  Widget row(String name, Widget control,
          {String? help, String? description, bool divider = true}) =>
      Container(
          constraints: const BoxConstraints(minHeight: 48),
          padding: const EdgeInsets.symmetric(vertical: 4),
          decoration: BoxDecoration(
              border:
                  divider ? Border(bottom: BorderSide(color: c.rule)) : null),
          child: Row(children: [
            Expanded(
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                  label(name, help: help),
                  if (description != null)
                    Padding(
                        padding: const EdgeInsets.only(top: 3, right: 20),
                        child: Text(description,
                            style: EfType.ui(11, color: c.ink2, height: 1.5))),
                ])),
            const SizedBox(width: 12),
            control
          ]));
  Widget switchRow(
          String id, String title, bool value, ValueChanged<bool> change,
          {String? help, String? description}) =>
      region(
          id,
          row(
              title,
              Semantics(
                  label: title,
                  child: EfSwitch(
                      key: ValueKey('settings.$id'),
                      value: value,
                      onChanged: (v) {
                        setState(() => change(v));
                        widget.onChanged?.call();
                      })),
              help: help,
              divider: !((id == 'custom' || id == 'libraries') && value),
              description: description));
  Widget segments(String id, String title, List<String> options, int selected,
          ValueChanged<int> change,
          {String? help}) =>
      region(
          id,
          row(
              title,
              SizedBox(
                  width: options.length == 3 ? 264 : 176,
                  child: EfSegmented(
                      options: options,
                      current: selected,
                      onChanged: (i) {
                        setState(() => change(i));
                        widget.onChanged?.call();
                      })),
              help: help,
              divider: id != 'launchMethod'));
  InputDecoration fieldDecoration(String label,
          {String? hint, String? error}) =>
      efInputDecoration(context, label, hint: hint, error: error);

  @override
  Widget build(BuildContext context) => AbsorbPointer(
      absorbing: widget.live && !widget.ready,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const EfPair('CONFIG', '设置', size: 24),
          const Spacer(),
          if (!widget.live)
            Text('仅界面预览 / 不写入配置', style: EfType.ui(10, color: c.ink2)),
        ]),
        const SizedBox(height: 20),
        Expanded(
            child:
                Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          region(
              'categories',
              SizedBox(
                  width: 155,
                  child: Column(children: [
                    for (int i = 0; i < 5; i++)
                      Padding(
                          padding: const EdgeInsets.only(bottom: 8),
                          child: SizedBox(
                              width: double.infinity,
                              child: button(
                                  ['路径', 'GIMI', '启动', '缓存', 'OMG'][i], () {
                                setState(() => d.page = i);
                                if (i == 3) widget.onRefreshCache?.call();
                                if (scroll.hasClients) scroll.jumpTo(0);
                              }, primary: d.page == i)))
                  ]))),
          const SizedBox(width: 34),
          Expanded(
              child: region(
                  'content',
                  Scrollbar(
                      controller: scroll,
                      thumbVisibility: true,
                      child: SingleChildScrollView(
                          controller: scroll,
                          padding: const EdgeInsets.only(right: 16, bottom: 82),
                          child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                EfPair(
                                    [
                                      'PATHS',
                                      'GIMI',
                                      'STARTUP',
                                      'CACHE',
                                      'OMG'
                                    ][d.page],
                                    [
                                      '路径配置',
                                      'GIMI 配置',
                                      '启动配置',
                                      '缓存',
                                      'OMG'
                                    ][d.page],
                                    size: 18),
                                const SizedBox(height: 10),
                                ...cards(switch (d.page) {
                                  0 => paths(),
                                  1 => gimi(),
                                  2 => startup(),
                                  3 => cache(),
                                  _ => omg()
                                }),
                              ]))))),
        ])),
        if (widget.cacheClearing || widget.cacheMessage.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Semantics(
              liveRegion: true,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(widget.cacheMessage,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: EfType.ui(12, color: c.ink2)),
                  if (widget.cacheClearing) ...[
                    const SizedBox(height: 8),
                    LinearProgressIndicator(
                        key: const ValueKey('settings.cache.progress'),
                        value: widget.cacheProgress,
                        color: c.signal,
                        backgroundColor: c.chip,
                        minHeight: 6),
                  ],
                ],
              ),
            ),
          ),
      ]));
  List<Widget> paths() => [
        const SizedBox(height: 12),
        pathField('game', '游戏', d.game, '选择游戏所在文件夹…',
            help: '在游戏启动器中打开游戏所在文件夹。选择包含游戏可执行文件的目录，不需要精确到 .exe。'),
        const SizedBox(height: 18),
        pathField('gimi', 'GIMI', d.gimi, '选择 GIMI 目录…'),
        if (widget.onImport != null) ...[
          const SizedBox(height: 18),
          Align(
              alignment: Alignment.centerLeft,
              child: button('导入 OMGLite 配置', widget.onImport!)),
        ],
      ];
  Widget pathField(
          String id, String name, TextEditingController controller, String hint,
          {String? help}) =>
      region(
          'paths.$id',
          Row(children: [
            SizedBox(width: 84, child: label(name, help: help)),
            Expanded(
                child: TextField(
                    contextMenuBuilder: efTextContextMenu,
                    key: ValueKey('settings.path.$id'),
                    controller: controller,
                    style: EfType.ui(12, color: c.ink),
                    decoration: fieldDecoration('$name 目录', hint: hint))),
            const SizedBox(width: 12),
            button('浏览', () async {
              final result = await enterPath('浏览$name目录',
                  initial: controller.text, hint: hint);
              if (result != null && mounted) controller.text = result;
            }),
          ]));
  Future<String?> enterPath(String title,
          {String initial = '', String hint = '输入路径', bool folder = true}) =>
      widget.pickPath != null
          ? widget.pickPath!(folder: folder, initial: initial)
          : showEfDialog<String>(
              context: context,
              builder: (_) => _PathPreviewDialog(
                  title: title, initial: initial, hint: hint));
  List<Widget> gimi() => [
        section('D3DX.INI', 'd3dx.ini'),
        segments('hunting', 'Hunting', ['0', '1', '2'], d.hunting,
            (i) => d.hunting = i),
        segments(
            'warning', 'Warning', ['0', '1'], d.warning, (i) => d.warning = i),
        section('UPDATES', '更新'),
        switchRow(
            'autoCheck', '打开 OMG 时检查更新', d.autoCheck, (v) => d.autoCheck = v),
        const SizedBox(height: 12),
        region(
            'whitelist',
            Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                label('更新白名单', help: '更新时保留列表中的文件。文件夹条目保留其目录下的所有文件。'),
                const Spacer(),
                Tooltip(
                    message: '添加白名单文件',
                    child: button('添加文件', () => addWhitelist(false))),
                const SizedBox(width: 8),
                Tooltip(
                    message: '添加白名单文件夹',
                    child: button('添加文件夹', () => addWhitelist(true))),
                const SizedBox(width: 8),
                Tooltip(
                    message: '删除选中的白名单条目',
                    child: EfButton('删除',
                        small: true,
                        onPressed: d.selectedEntry == null
                            ? null
                            : () {
                                setState(() {
                                  d.whitelist.removeAt(d.selectedEntry!);
                                  d.selectedEntry = null;
                                });
                                widget.onChanged?.call();
                              })),
              ]),
              const SizedBox(height: 6),
              Container(
                  height: 112,
                  color: c.paper,
                  child: d.whitelist.isEmpty
                      ? Center(
                          child: Text('添加文件或文件夹后，白名单条目将在这里显示。',
                              style: EfType.ui(11, color: c.ink2)))
                      : ListView.builder(
                          controller: whitelistScroll,
                          itemCount: d.whitelist.length,
                          itemBuilder: (_, i) => Material(
                              color: d.selectedEntry == i ? c.signal : c.paper,
                              child: InkWell(
                                  onTap: () => setState(() => d.selectedEntry =
                                      d.selectedEntry == i ? null : i),
                                  child: Padding(
                                      padding: const EdgeInsets.symmetric(
                                          horizontal: 12, vertical: 9),
                                      child: Row(children: [
                                        Icon(
                                            d.whitelist[i].folder
                                                ? Icons.folder_outlined
                                                : Icons.description_outlined,
                                            size: 16,
                                            color: d.selectedEntry == i
                                                ? c.onSignal
                                                : c.ink),
                                        const SizedBox(width: 10),
                                        Expanded(
                                            child: Text(d.whitelist[i].path,
                                                style: EfType.ui(12,
                                                    color: d.selectedEntry == i
                                                        ? c.onSignal
                                                        : c.ink))),
                                      ])))))),
            ])),
      ];
  Future<void> addWhitelist(bool folder) async {
    final path = await enterPath(folder ? '添加白名单文件夹' : '添加白名单文件',
        initial: d.gimi.text,
        folder: folder,
        hint: folder ? '例如 Mods/' : '例如 d3dx.ini');
    if (path == null || !mounted) return;
    var relative = path;
    if (widget.live) {
      final prefix = d.gimi.text
          .trim()
          .replaceAll('\\', '/')
          .replaceFirst(RegExp(r'/+$'), '');
      final normalized = path.replaceAll('\\', '/');
      if (prefix.isEmpty ||
          !normalized.toLowerCase().startsWith('${prefix.toLowerCase()}/')) {
        showEfToast(context, '请选择 GIMI 目录内的文件或子文件夹。');
        return;
      }
      relative = normalized.substring(prefix.length + 1);
    }
    final name = folder && !relative.endsWith('/') && !relative.endsWith('\\')
        ? '$relative/'
        : relative;
    setState(() {
      d.whitelist.add((path: name, folder: folder));
      d.selectedEntry = d.whitelist.length - 1;
    });
    widget.onChanged?.call();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && whitelistScroll.hasClients) {
        whitelistScroll.animateTo(whitelistScroll.position.maxScrollExtent,
            duration: Ef.d(context, const Duration(milliseconds: 280)),
            curve: Ef.mech);
      }
    });
  }

  List<Widget> startup() => [
        segments('launchMethod', '启动方法', ['Native', 'Shell', 'Manual'],
            d.launchMethod, (i) => d.launchMethod = i,
            help:
                'Native：直接启动游戏。\nShell：通过 3DMigoto 启动。\nManual：由你手动打开游戏。\nManual 模式下不执行自定义启动命令。'),
        section('ADVANCED', '高级'),
        switchRow('custom', '自定义启动', d.custom, (v) => d.custom = v,
            help: '开启后使用自定义启动命令与注入方式。路径含空格时使用英文双引号。点击首页启动游戏时执行。'),
        if (d.custom) ...[
          const SizedBox(height: 12),
          region(
              'command',
              TextField(
                  contextMenuBuilder: efTextContextMenu,
                  key: const ValueKey('settings.command'),
                  controller: d.command,
                  decoration: fieldDecoration('自定义启动命令',
                      hint: r'例：G:\Tools\Launcher.exe -windowed'))),
          if (d.launchMethod == 2)
            Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text('Manual 模式下，自定义命令不参与启动。',
                    style: EfType.ui(11, color: c.ink2))),
          segments('injection', '注入方式', ['Hook', 'Inject', 'Bypass'],
              d.injection, (i) => d.injection = i,
              help:
                  'Hook：全局钩子。\nInject：启动后注入。\nBypass：跳过 d3d11.dll；额外注入库仍单独配置。'),
        ],
        switchRow('libraries', '注入库', d.libraries, (v) => d.libraries = v,
            help: '每行填写一个 DLL 绝对路径，按填写顺序排列。点击首页启动游戏时加载。'),
        if (d.libraries) ...[
          const SizedBox(height: 12),
          region(
              'dlls',
              TextField(
                  contextMenuBuilder: efTextContextMenu,
                  key: const ValueKey('settings.dlls'),
                  controller: d.dlls,
                  minLines: 3,
                  maxLines: 5,
                  decoration:
                      fieldDecoration('额外 DLL 路径', hint: '每行一个 DLL 绝对路径…')))
        ],
      ];
  List<Widget> cache() => [
        section('STORAGE', '缓存与备份管理'),
        switchRow('cleanupOnExit', '关闭时清理过时文件', d.cleanupOnExit,
            (v) => d.cleanupOnExit = v,
            help: '退出 OMG-Neo 时清理旧缓存和备份，每类保留最新一份。默认关闭。'),
        const SizedBox(height: 16),
        Text(
            widget.cacheBytes == null
                ? '缓存与备份用量尚未检测。'
                : 'Neo 缓存与备份：${(widget.cacheBytes! / 1024 / 1024).toStringAsFixed(2)} MB',
            style: EfType.ui(12, color: c.ink2)),
        const SizedBox(height: 8),
        Text('包含切服恢复备份、替换包导入历史、模组写回和 DLL 备份、下载临时文件及旧运行日志。',
            style: EfType.ui(12, color: c.ink2)),
        if (widget.onRefreshCache != null) ...[
          const SizedBox(height: 8),
          Align(
              alignment: Alignment.centerLeft,
              child: button('刷新用量', widget.onRefreshCache!)),
        ],
        const SizedBox(height: 16),
        Align(
            alignment: Alignment.centerLeft,
            child: button(
                '清理缓存与备份',
                widget.onClearCache == null
                    ? () => showEfToast(context, '仅预览，未删除任何缓存。')
                    : () async {
                        final yes = await showEfDialog<bool>(
                            context: context,
                            builder: (context) => EfDialog(
                                    eyebrow: 'CONFIRM',
                                    title: const Text('清理 Neo 缓存与备份'),
                                    content: const Text(
                                        '删除 Neo 缓存、临时文件及历史备份，手动清理不保留最新一份。保留配置、游戏和模组原文件、构建产物、当前导出的备份包及待恢复的切服备份。'),
                                    actions: [
                                      EfButton('取消',
                                          small: true,
                                          onPressed: () =>
                                              Navigator.pop(context, false)),
                                      EfButton('清理',
                                          small: true,
                                          kind: EfButtonKind.danger,
                                          onPressed: () =>
                                              Navigator.pop(context, true))
                                    ]));
                        if (yes == true) widget.onClearCache!();
                      })),
      ];
  List<Widget> omg() => [
        section('APPEARANCE', '外观'),
        switchRow('dark', '深色外观', widget.dark, (_) => widget.onTheme()),
        const SizedBox(height: 14),
        region(
            'accent',
            Row(children: [
              Container(width: 28, height: 28, color: c.signal),
              const SizedBox(width: 12),
              Expanded(
                  child: TextField(
                      contextMenuBuilder: efTextContextMenu,
                      controller: d.accent,
                      decoration: fieldDecoration('强调色', hint: '#39C5BB'),
                      onSubmitted: (_) => applyAccent())),
              const SizedBox(width: 12),
              button('应用颜色', applyAccent),
              const SizedBox(width: 8),
              button('恢复默认', () {
                d.accent.text = '#39C5BB';
                applyAccent();
              }),
            ])),
        if (widget.openReview != null) ...[
          const SizedBox(height: 18),
          button('打开 UI 调整工具', widget.openReview!),
        ],
      ];
  void applyAccent() {
    final hex = d.accent.text.trim().replaceFirst('#', '');
    if (!RegExp(r'^[0-9a-fA-F]{6}$').hasMatch(hex)) {
      showEfToast(context, '请输入六位十六进制颜色，例如 #39C5BB。');
      return;
    }
    widget.onAccent(Color(int.parse('FF$hex', radix: 16)));
    d.accent.text = '#${hex.toUpperCase()}';
  }
}

class _PathPreviewDialog extends StatefulWidget {
  const _PathPreviewDialog(
      {required this.title, required this.initial, required this.hint});
  final String title, initial, hint;
  @override
  State<_PathPreviewDialog> createState() => _PathPreviewDialogState();
}

class _PathPreviewDialogState extends State<_PathPreviewDialog> {
  late final input = TextEditingController(text: widget.initial);
  @override
  void dispose() {
    input.dispose();
    super.dispose();
  }

  void submit() {
    if (input.text.trim().isNotEmpty) {
      Navigator.pop(context, input.text.trim());
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return EfDialog(
        eyebrow: 'PATH',
        title: Text(widget.title),
        content: SizedBox(
            width: 440,
            child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('输入用于预览的路径。', style: EfType.ui(12, color: c.ink2)),
                  const SizedBox(height: 14),
                  TextField(
                      contextMenuBuilder: efTextContextMenu,
                      controller: input,
                      autofocus: true,
                      decoration: InputDecoration(
                          labelText: '路径',
                          hintText: widget.hint,
                          border: const OutlineInputBorder(
                              borderRadius: BorderRadius.zero)),
                      onSubmitted: (_) => submit()),
                ])),
        actions: [
          EfButton('取消', small: true, onPressed: () => Navigator.pop(context)),
          EfButton('确定', small: true, kind: EfButtonKind.go, onPressed: submit)
        ]);
  }
}

class _SettingsSection extends StatelessWidget {
  const _SettingsSection(this.english, this.title);
  final String english, title;
  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return Row(children: [
      Container(width: 24, height: 3, color: c.ink),
      const SizedBox(width: 10),
      Text('// $english',
          style: EfType.ui(9, weight: 600, color: c.ink2, spacing: .14)),
      const Spacer(),
      Text(title, style: EfType.ui(15, weight: 700, color: c.ink)),
    ]);
  }
}

/// A vector help glyph remains visible without depending on the icon font.
class _HelpGlyph extends CustomPainter {
  _HelpGlyph(this.color);
  final Color color;
  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawCircle(
        size.center(Offset.zero),
        size.shortestSide / 2 - 1,
        Paint()
          ..color = color
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.3);
    final text = TextPainter(
        text: TextSpan(
            text: '?',
            style: TextStyle(
                fontFamily: 'Saira',
                fontWeight: FontWeight.w700,
                fontSize: 13,
                color: color)),
        textDirection: TextDirection.ltr)
      ..layout();
    text.paint(canvas,
        Offset((size.width - text.width) / 2, (size.height - text.height) / 2));
  }

  @override
  bool shouldRepaint(_HelpGlyph old) => old.color != color;
}
