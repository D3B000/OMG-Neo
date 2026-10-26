import 'dart:async';
import 'dart:ui' as ui;
import 'package:desktop_drop/desktop_drop.dart';
import 'package:flutter/material.dart';
import 'ef/menus.dart';
import 'backend/neo_controller.dart';
import 'ef/marks.dart';
import 'ef/tokens.dart';
import 'ef/widgets.dart';
import 'frontend_memory.dart';
import 'resource_keys_dialog.dart';

// UI fixtures only; toggles never rename folders or write configuration.
class ResourcePreview {
  ResourcePreview(this.id, this.name, this.category, this.element, this.letter,
      {this.enabled = true,
      this.uiKey,
      this.masked = false,
      this.keys = const [],
      this.relativePath = '',
      this.isDirectory = true,
      this.isMod = true,
      this.isLink = false,
      this.targetPath,
      this.blockedReason,
      this.thumbnailPath});
  final bool isLink;
  final String? targetPath, blockedReason;
  final String relativePath;
  final bool isDirectory;
  bool isMod, masked;
  final String? thumbnailPath;
  final String? uiKey;
  final String id, name, category, element, letter;
  final List<(String, String)> keys;
  bool enabled;
}

class ResourcesDraft {
  final path = <String>[];
  final scrollPositions = <String, double>{};
  void rememberScroll(String path, double offset) {
    scrollPositions.remove(path);
    scrollPositions[path] = offset;
    if (scrollPositions.length > 128) {
      scrollPositions.remove(scrollPositions.keys.first);
    }
  }

  String scope = '当前目录';
  bool showEmpty = true;
  bool showDisabledPrefix = false;
  bool enabledFirst = true;

  final search = TextEditingController();
  final folderScroll = ScrollController();
  final items = <ResourcePreview>[
    ResourcePreview('a1', 'A / 角色外观示例', '角色', '火', 'A',
        keys: [('切换外观（示例）', 'X'), ('切换配色（示例）', 'Shift + X')]),
    ResourcePreview('a2', 'A / 配色示例', '角色', '火', 'A', enabled: false),
    ResourcePreview('b1', 'B / 角色外观示例', '角色', '水', 'B'),
    ResourcePreview('c1', 'C / 武器外观示例', '武器', '全部', 'C'),
    ResourcePreview('d1', 'D / 怪物外观示例', '怪物', '全部', 'D', enabled: false),
    ResourcePreview('e1', 'E / 界面替换示例', '其它', '全部', 'E'),
  ];
  void dispose() {
    search.dispose();
    folderScroll.dispose();
  }
}

/// Folder-only resource preview, with local search and enabled-state drafts.
class ResourceBrowser extends StatefulWidget {
  const ResourceBrowser(
      {super.key,
      required this.draft,
      required this.region,
      required this.notice,
      this.controller,
      required this.onSettings});
  final ResourcesDraft draft;
  final NeoController? controller;
  final Widget Function(String, Widget) region;
  final ValueChanged<String> notice;
  final VoidCallback onSettings;
  @override
  State<ResourceBrowser> createState() => _ResourceBrowserState();
}

class _ResourceBrowserState extends State<ResourceBrowser> {
  ResourcesDraft get d => widget.draft;
  EfColors get c => EfColors.of(context);
  NeoController? get live => widget.controller;
  bool get available =>
      live?.ready == true && live?.busy == false && live?.closing == false;
  int epoch = -1;
  bool requested = false;
  bool dragging = false;
  Timer? searchTimer;
  String? inlineError;
  String? loadedPath;
  @override
  void dispose() {
    searchTimer?.cancel();
    rememberScroll();
    PaintingBinding.instance.imageCache.clear();
    super.dispose();
  }

  Map<String, dynamic> get view => {
        'query': d.search.text.trim(),
        'recursive': d.scope == '全局',
        'hideEmpty': !d.showEmpty,
      };
  void rememberScroll() {
    if (d.folderScroll.hasClients) {
      d.rememberScroll(d.path.join('/'), d.folderScroll.offset);
    }
  }

  void restoreScroll() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !d.folderScroll.hasClients) return;
      d.folderScroll.jumpTo((d.scrollPositions[d.path.join('/')] ?? 0)
          .clamp(0, d.folderScroll.position.maxScrollExtent));
    });
  }

  Future<void> reload() async {
    if (!mounted || live?.closing == true) return;
    if (live != null && !live!.ready) {
      if (live!.canReconnect) await live!.reconnect();
      if (!mounted || !live!.ready) return;
    }
    if (live?.busy == true) {
      searchTimer?.cancel();
      searchTimer = Timer(const Duration(milliseconds: 150), reload);
      return;
    }
    inlineError = null;
    live?.browseResources(d.path.join('/'), view);
  }

  Future<void> call(String method, Map<String, dynamic> params) async {
    try {
      await live?.resourceCall(method, params);
    } catch (error) {
      if (mounted) setState(() => inlineError = '$error');
    }
  }

  Map<String, dynamic>? convertedSnapshot;
  List<ResourcePreview> convertedItems = [];
  @override
  void initState() {
    super.initState();
    scheduleLoad();
  }

  @override
  void didUpdateWidget(covariant ResourceBrowser oldWidget) {
    super.didUpdateWidget(oldWidget);
    scheduleLoad();
  }

  void scheduleLoad() {
    if (live == null) return;
    if (!live!.resourcesLoaded && epoch != live!.resourceEpoch) {
      epoch = live!.resourceEpoch;
      requested = false;
      d.path.clear();
    }
    if (live!.resourcesLoaded && epoch != live!.resourceEpoch) {
      epoch = live!.resourceEpoch;
      final path = live!.resources['relativePath'] as String? ?? '';
      if (loadedPath != path) {
        rememberScroll();
        loadedPath = path;
        d.path
          ..clear()
          ..addAll(path.isEmpty ? [] : path.split('/'));
        restoreScroll();
      }
    }
    if (!live!.resourcesLoaded && available && !requested) {
      requested = true;
      WidgetsBinding.instance.addPostFrameCallback((_) async {
        if (mounted) reload();
      });
    }
  }

  void navigate(List<String> path) {
    searchTimer?.cancel();
    rememberScroll();
    inlineError = null;
    if (live == null) {
      setState(() {
        d.path
          ..clear()
          ..addAll(path);
      });
      restoreScroll();
      return;
    }
    d.search.clear();
    live!.browseResources(path.join('/'), view);
  }

  List<ResourcePreview> get actual {
    if (identical(convertedSnapshot, live?.resources)) return convertedItems;
    convertedSnapshot = live?.resources;
    convertedItems = (live?.resources['items'] as List? ?? [])
        .map((item) => ResourcePreview(
            item['id'] as String, item['name'] as String, '', '', '',
            enabled: item['enabled'] == true,
            uiKey: item['uiKey'] as String?,
            masked: item['masked'] == true,
            relativePath: item['relativePath'] as String,
            isDirectory: item['isDirectory'] == true,
            isMod: item['isMod'] == true,
            isLink: item['isLink'] == true,
            targetPath: item['targetPath'] as String?,
            blockedReason: item['blockedReason'] as String?,
            thumbnailPath: item['thumbnailPath'] as String?,
            keys: (item['keys'] as List? ?? [])
                .map((key) => (
                      '${key['section_name']} / ${key['variable']}',
                      '${key['key'] ?? '未指定'}${key['back'] == null ? '' : ' / ${key['back']}'}'
                    ))
                .toList()))
        .toList();
    return convertedItems;
  }

  static const categories = ['角色', '武器', '怪物', '其它'];
  String displayName(ResourcePreview item) {
    if (d.showDisabledPrefix || !item.isMod) return item.name;
    final name = item.name.replaceFirst(
        RegExp(r'^\s*(?:disabled[\s_]+)+', caseSensitive: false), '');
    return name.isEmpty ? item.name : name;
  }

  Key cardKey(ResourcePreview item) =>
      ValueKey('resources.card.${item.uiKey ?? item.id}');
  List<ResourcePreview> get visible {
    final items = live != null
        ? actual
            .where((item) => item.name
                .toLowerCase()
                .contains(d.search.text.trim().toLowerCase()))
            .toList()
        : d.items
            .where((item) =>
                d.path.isNotEmpty &&
                item.category == d.path.first &&
                item.name
                    .toLowerCase()
                    .contains(d.search.text.trim().toLowerCase()))
            .toList();
    items.sort((a, b) {
      if (d.enabledFirst) {
        final aEnabled = a.isMod && a.enabled;
        final bEnabled = b.isMod && b.enabled;
        if (aEnabled != bEnabled) return aEnabled ? -1 : 1;
      }
      if (a.isDirectory != b.isDirectory) return a.isDirectory ? -1 : 1;
      final name =
          displayName(a).toLowerCase().compareTo(displayName(b).toLowerCase());
      if (name != 0) return name;
      final original = a.name.toLowerCase().compareTo(b.name.toLowerCase());
      return original != 0
          ? original
          : a.relativePath
              .toLowerCase()
              .compareTo(b.relativePath.toLowerCase());
    });
    return items;
  }

  List<String> get folders =>
      categories.where((name) => name.contains(d.search.text.trim())).toList();

  Widget button(String label, VoidCallback tap,
          {Key? key,
          bool active = false,
          bool compact = false,
          bool? enabled}) =>
      SizedBox(
          height: compact ? 28 : 36,
          child: EfButton(label,
              key: key,
              small: true,
              onPressed: (enabled ?? (live == null || available)) ? tap : null,
              kind: active ? EfButtonKind.go : EfButtonKind.normal));

  @override
  Widget build(BuildContext context) {
    final canDrop = available && (ModalRoute.of(context)?.isCurrent ?? true);
    return DropTarget(
        key: const ValueKey('resources.drop'),
        enable: canDrop,
        onDragEntered: (_) => setState(() => dragging = true),
        onDragExited: (_) => setState(() => dragging = false),
        onDragDone: (details) {
          setState(() => dragging = false);
          if (!canDrop || details.files.isEmpty) return;
          rememberScroll();
          live?.businessTask('resources.move', {
            ...view,
            'path': d.path.join('/'),
            'sources': details.files.map((file) => file.path).toList(),
          });
        },
        child: Stack(fit: StackFit.expand, children: [
          page(),
          if (dragging && canDrop)
            const Positioned.fill(
                child: EfDropHint(
              'IMPORT RESOURCES',
              '释放文件或文件夹以移入当前目录',
              key: ValueKey('resources.drop-hint'),
            )),
        ]));
  }

  Widget page() =>
      Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        widget.region(
            'resources.header',
            Row(children: [
              const EfPair('RESOURCE BROWSER', '资源浏览', size: 24),
              const SizedBox(width: 20),
              Expanded(
                  child: Center(
                      child: SizedBox(
                          width: 350,
                          height: 34,
                          child: Row(children: [
                            SizedBox(
                                width: 98,
                                child: EfDropdown(
                                    value: d.scope,
                                    items: const ['当前目录', '全局'],
                                    onChanged: (value) {
                                      setState(() => d.scope = value);
                                      reload();
                                    })),
                            const SizedBox(width: 6),
                            Expanded(
                                child: TextField(
                                    contextMenuBuilder: efTextContextMenu,
                                    key: const ValueKey('resources.search'),
                                    controller: d.search,
                                    style: EfType.ui(12, color: c.ink),
                                    onChanged: (_) {
                                      setState(() {});
                                      searchTimer?.cancel();
                                      searchTimer = Timer(
                                          const Duration(milliseconds: 300),
                                          reload);
                                    },
                                    decoration: InputDecoration(
                                      hintText: d.scope == '全局'
                                          ? '搜索整个 Mods'
                                          : '搜索当前目录',
                                      prefixIcon:
                                          const Icon(Icons.search, size: 17),
                                      contentPadding:
                                          const EdgeInsets.symmetric(
                                              horizontal: 10),
                                      suffixIcon: d.search.text.isEmpty
                                          ? null
                                          : IconButton(
                                              tooltip: '清空搜索',
                                              icon: const Icon(Icons.close,
                                                  size: 15),
                                              onPressed: () => setState(() {
                                                    d.search.clear();
                                                    reload();
                                                  })),
                                    )))
                          ])))),
              const SizedBox(width: 20),
              button(live?.canReconnect == true ? '重新连接' : '刷新', () {
                requested = false;
                reload();
              }, enabled: live == null || available || live!.canReconnect),
              const SizedBox(width: 6),
              button('写回', confirmWriteback),
              if (live?.writebackLogs.isNotEmpty == true) ...[
                const SizedBox(width: 6),
                button(
                    '报告',
                    () => showEfDialog<void>(
                        context: context,
                        builder: (context) => EfDialog(
                                eyebrow: 'WRITEBACK REPORT',
                                width: 680,
                                title: const Text('写回报告'),
                                content: SizedBox(
                                    width: 620,
                                    height: 360,
                                    child: SingleChildScrollView(
                                        child: SelectableText(
                                            live!.writebackLogs.join('\n'),
                                            contextMenuBuilder:
                                                efTextContextMenu))),
                                actions: [
                                  EfButton('关闭',
                                      small: true,
                                      onPressed: () => Navigator.pop(context))
                                ]))),
              ],
              if (live?.busy == true &&
                  live!.taskKind.startsWith('resources.')) ...[
                const SizedBox(width: 6),
                SizedBox(
                    height: 36,
                    child: EfButton('取消',
                        small: true, onPressed: live!.cancelTask)),
              ],
              const SizedBox(width: 6),
              settingsMenu(),
            ])),
        const SizedBox(height: 10),
        widget.region(
            'resources.breadcrumb',
            SizedBox(
                height: 28,
                child: Row(children: [
                  SizedBox(
                      width: 28,
                      height: 28,
                      child: IconButton(
                          tooltip: '返回上一级',
                          padding: EdgeInsets.zero,
                          constraints: const BoxConstraints(),
                          onPressed:
                              d.path.isEmpty || live != null && !available
                                  ? null
                                  : () => navigate(
                                      d.path.sublist(0, d.path.length - 1)),
                          icon: const Icon(Icons.arrow_back, size: 16))),
                  Expanded(
                      child: SingleChildScrollView(
                          scrollDirection: Axis.horizontal,
                          child: Row(children: [
                            button('Mods', () => navigate([]),
                                key: const ValueKey('resources.root'),
                                active: d.path.isEmpty,
                                compact: true),
                            for (int i = 0; i < d.path.length; i++) ...[
                              const SizedBox(
                                  width: 18,
                                  child: Icon(Icons.chevron_right, size: 14)),
                              button(d.path[i],
                                  () => navigate(d.path.sublist(0, i + 1)),
                                  compact: true,
                                  active: i == d.path.length - 1),
                            ],
                          ]))),
                  const SizedBox(width: 10),
                  SizedBox(
                      width: 28,
                      height: 28,
                      child: IconButton(
                          tooltip: '在资源管理器打开当前目录',
                          padding: EdgeInsets.zero,
                          onPressed: available
                              ? () => call(
                                  'resources.open', {'path': d.path.join('/')})
                              : null,
                          icon: const Icon(Icons.folder_open_outlined,
                              size: 17))),
                  const SizedBox(width: 4),
                  directoryMenu(false),
                  const SizedBox(width: 4),
                  directoryMenu(true),
                ]))),
        const SizedBox(height: 10),
        if (inlineError != null ||
            live?.error != null ||
            (live?.noticeKind == 'resources.move' && live?.busy == false))
          Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: InkWell(
                  onTap: () => showEfDialog<void>(
                      context: context,
                      builder: (context) => EfDialog(
                              eyebrow: 'RESOURCE OPERATION',
                              title: const Text('资源操作详情'),
                              content: SizedBox(
                                  width: 560,
                                  child: SingleChildScrollView(
                                      child:
                                          SelectableText(
                                              inlineError ??
                                                  live?.error ??
                                                  live?.status ??
                                                  '',
                                              contextMenuBuilder:
                                                  efTextContextMenu))),
                              actions: [
                                EfButton('关闭',
                                    small: true,
                                    onPressed: () => Navigator.pop(context))
                              ])),
                  child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Row(children: [
                        Icon(Icons.info_outline, size: 14, color: c.ink2),
                        const SizedBox(width: 6),
                        Expanded(
                            child: Text(
                                live?.ready == false
                                    ? '后端连接已断开'
                                    : inlineError != null || live?.error != null
                                        ? '资源操作未完成'
                                        : '资源操作已完成',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: EfType.ui(11, color: c.ink2))),
                        Text('查看详情', style: EfType.ui(11, color: c.ink2)),
                      ])))),
        Expanded(child: widget.region('resources.cards', folderView())),
      ]);

  Widget folderView() {
    final root = live == null && d.path.isEmpty;
    final shown = visible;
    final shownFolders = folders;
    final count = root ? shownFolders.length : shown.length;
    if (count == 0) {
      if (live != null && !live!.resourcesLoaded) {
        return live!.ready && live!.busy
            ? const Center(
                child: SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2)))
            : const SizedBox.shrink();
      }
      return Center(
          child: Text('当前目录没有匹配的资源。', style: EfType.ui(13, color: c.ink2)));
    }
    final indices = {
      for (final entry in shown.indexed) cardKey(entry.$2): entry.$1
    };
    return LayoutBuilder(
        builder: (_, constraints) => GridView.builder(
              key: const ValueKey('resources.folder-grid'),
              controller: d.folderScroll,
              findChildIndexCallback: root ? null : (key) => indices[key],
              padding: const EdgeInsets.only(right: 8, bottom: 82),
              gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: constraints.maxWidth >= 760
                      ? 3
                      : constraints.maxWidth >= 480
                          ? 2
                          : 1,
                  mainAxisExtent: root ? 100 : 108,
                  crossAxisSpacing: 12,
                  mainAxisSpacing: 12),
              itemCount: count,
              itemBuilder: (_, index) => root
                  ? folderCard(shownFolders[index])
                  : cardMenu(
                      shown[index],
                      !shown[index].isMod
                          ? realFolderCard(shown[index])
                          : resourceCard(shown[index])),
            ));
  }

  Widget realFolderCard(ResourcePreview item) => Material(
      color: c.panel,
      shape: efCut(br: 8),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
          key: ValueKey('resources.directory.${item.name}'),
          onTap: live == null || available
              ? () => item.blockedReason == null
                  ? navigate(item.relativePath.split('/'))
                  : setState(() => inlineError = item.blockedReason)
              : null,
          child: Padding(
              padding: const EdgeInsets.all(12),
              child: Row(children: [
                thumbnail(item),
                const SizedBox(width: 10),
                Icon(
                    item.isLink
                        ? Icons.folder_shared_outlined
                        : Icons.folder_outlined,
                    size: 17,
                    color: c.ink2),
                const SizedBox(width: 6),
                Expanded(
                    child: Text(item.name,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: EfType.ui(14, weight: 700, color: c.ink))),
                Icon(Icons.chevron_right, size: 17, color: c.ink2)
              ]))));

  Widget settingItem(
          String id, String label, bool checked, VoidCallback change) =>
      Semantics(
          checked: checked,
          child: MenuItemButton(
              key: ValueKey('resources.settings.$id'),
              leadingIcon: SizedBox(
                  width: 16,
                  height: 16,
                  child: checked ? const Icon(Icons.check, size: 14) : null),
              onPressed: change,
              child: Text(label)));

  Widget settingsMenu() => MenuAnchor(
      style: resourceMenuStyle(context),
      menuChildren: [
        settingItem('enabled-first', '启用模组在前', d.enabledFirst,
            () => setState(() => d.enabledFirst = !d.enabledFirst)),
        settingItem('disabled-prefix', '显示 DISABLED 前缀', d.showDisabledPrefix,
            () => setState(() => d.showDisabledPrefix = !d.showDisabledPrefix)),
        settingItem('empty-folders', '显示空文件夹', d.showEmpty, () {
          setState(() => d.showEmpty = !d.showEmpty);
          rememberScroll();
          reload();
        }),
      ],
      builder: (_, controller, child) => button('设置',
          () => controller.isOpen ? controller.close() : controller.open(),
          enabled: live?.closing != true));

  Widget directoryMenu(bool ini) => Builder(
      builder: (anchor) => SizedBox(
            width: 28,
            height: 28,
            child: IconButton(
              key: ValueKey(
                  ini ? 'resources.menu.ini' : 'resources.menu.folders'),
              tooltip: ini ? '当前目录的 INI 文件' : '当前目录的所有文件夹',
              padding: EdgeInsets.zero,
              icon: Icon(
                  ini ? Icons.description_outlined : Icons.folder_outlined,
                  size: 17),
              onPressed: live != null && !available
                  ? null
                  : () async {
                      final path = d.path.join('/');
                      try {
                        final List entries;
                        if (live != null) {
                          final result = await live!.resourceCall(
                              'resources.directory', {'path': path});
                          entries = result[ini ? 'files' : 'folders'] as List;
                        } else if (!ini && d.path.isEmpty) {
                          entries = [
                            for (final name in categories)
                              {'name': name, 'path': name}
                          ];
                        } else {
                          entries = [
                            for (final item in d.items.where((item) =>
                                d.path.isNotEmpty &&
                                item.category == d.path.first &&
                                (ini
                                    ? !item.isDirectory &&
                                        item.name.toLowerCase().endsWith('.ini')
                                    : item.isDirectory)))
                              {
                                'name': item.name,
                                'path': [...d.path, item.name].join('/')
                              }
                          ];
                        }
                        if (!mounted ||
                            !anchor.mounted ||
                            d.path.join('/') != path) {
                          return;
                        }
                        final box = anchor.findRenderObject() as RenderBox;
                        final overlay = Navigator.of(anchor)
                            .overlay!
                            .context
                            .findRenderObject() as RenderBox;
                        final position = box.localToGlobal(
                            Offset(0, box.size.height),
                            ancestor: overlay);
                        final selected = await showMenu<String>(
                          context: anchor,
                          position: RelativeRect.fromLTRB(
                              overlay.size.width - 252, position.dy + 6, 32, 0),
                          constraints: BoxConstraints(
                              minWidth: 220,
                              maxWidth: 220,
                              maxHeight:
                                  (overlay.size.height - position.dy - 22)
                                      .clamp(80, 480)),
                          color: c.panel,
                          surfaceTintColor: Colors.transparent,
                          elevation: 0,
                          shape: efCut(br: 8, side: BorderSide(color: c.rule)),
                          items: entries.isEmpty
                              ? [
                                  PopupMenuItem<String>(
                                      enabled: false,
                                      child: Text(
                                          ini ? '当前目录没有 INI 文件。' : '当前目录没有文件夹。',
                                          style: EfType.ui(12, color: c.ink2)))
                                ]
                              : [
                                  for (final entry in entries)
                                    PopupMenuItem<String>(
                                        value: entry['path'] as String,
                                        height: 36,
                                        child: Text(entry['name'] as String,
                                            maxLines: 2,
                                            overflow: TextOverflow.ellipsis,
                                            style: EfType.ui(12, color: c.ink)))
                                ],
                        );
                        if (!mounted ||
                            selected == null ||
                            d.path.join('/') != path) {
                          return;
                        }
                        if (ini) {
                          await call('resources.open',
                              {'path': selected, 'config': true});
                        } else {
                          navigate(selected.split('/'));
                        }
                      } catch (error) {
                        if (mounted) {
                          setState(() => inlineError = '$error');
                        }
                      }
                    },
            ),
          ));

  Widget cardMenu(ResourcePreview item, Widget child) => ResourceCardMenu(
      key: cardKey(item),
      item: item,
      enabled: live == null || available,
      loadConfigs: () async => live == null || !item.isMod
          ? []
          : (await live!.resourceCall('resources.configs', {
              'id': item.id,
              'revision': live!.resources['revision']
            }))['files'] as List,
      open: () => call('resources.open', {'path': item.relativePath}),
      openConfig: (path) =>
          call('resources.open', {'path': path, 'config': true}),
      change: (patch) {
        if (live == null) {
          setState(() {
            item.isMod = patch['isMod'] as bool? ?? item.isMod;
            item.masked = patch['masked'] as bool? ?? item.masked;
          });
        } else {
          rememberScroll();
          live!.businessTask('resources.card', {
            ...view,
            'path': d.path.join('/'),
            'id': item.id,
            'revision': live!.resources['revision'],
            ...patch
          });
        }
      },
      child: child);

  Future<void> confirmWriteback() async {
    if (live == null) {
      widget.notice('写回预览：未修改资源或配置文件。');
      return;
    }
    final confirmed = await showEfDialog<bool>(
        context: context,
        builder: (context) => EfDialog(
                eyebrow: 'CONFIRM',
                title: const Text('写回模组参数'),
                content: const SizedBox(
                    width: 420,
                    child: Text(
                        '读取 GIMI/d3dx_user.ini，将差分值写回整个 Mods 目录的 INI（跳过文件名含 DISABLED 的文件）。执行前会备份原文件；写回范围不受当前目录影响。')),
                actions: [
                  EfButton('取消',
                      small: true,
                      onPressed: () => Navigator.pop(context, false)),
                  EfButton('备份并写回',
                      small: true,
                      kind: EfButtonKind.go,
                      onPressed: () => Navigator.pop(context, true))
                ]));
    if (confirmed == true && mounted) {
      requested = false;
      await live!.businessTask('resources.writeback');
    }
  }

  Widget folderCard(String category) => Material(
      color: c.panel,
      shape: efCut(br: 8),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
          key: ValueKey('resources.directory.$category'),
          onTap: () {
            d.search.clear();
            navigate([category]);
          },
          child: Padding(
              padding: const EdgeInsets.all(12),
              child: Row(children: [
                Icon(Icons.folder_outlined, size: 32, color: c.ink2),
                const SizedBox(width: 14),
                Expanded(
                    child: Text(category,
                        style: EfType.ui(14, weight: 700, color: c.ink))),
                Icon(Icons.chevron_right, size: 17, color: c.ink2),
              ]))));

  Widget thumbnail(ResourcePreview item) => SizedBox(
      width: 84,
      height: 84,
      child: Material(
          color: c.chip,
          child: InkWell(
            key: ValueKey('resources.thumbnail.${item.id}'),
            onTap: () => showEfDialog<void>(
                context: context,
                builder: (_) => EfDialog(
                      eyebrow: 'PREVIEW',
                      title: Text(displayName(item)),
                      content: SizedBox(
                          width: 300,
                          height: 160,
                          child: Center(
                              child: item.thumbnailPath == null
                                  ? const Text('该资源未提供预览图。')
                                  : Image(
                                      image: boundedPreviewImage(
                                          item.thumbnailPath!,
                                          width: 300,
                                          height: 160,
                                          pixelRatio:
                                              MediaQuery.devicePixelRatioOf(
                                                  context)),
                                      fit: BoxFit.contain,
                                      filterQuality: FilterQuality.high,
                                      errorBuilder: (_, error, stack) =>
                                          const Text('预览图无法读取')))),
                      actions: [
                        button('打开图片', () async {
                          try {
                            await live!.resourceCall('resources.openImage', {
                              'id': item.id,
                              'revision': live!.resources['revision'],
                            });
                          } catch (error) {
                            if (mounted) widget.notice('打开图片失败：$error');
                          }
                        },
                            key: const ValueKey('resources.preview.open'),
                            enabled: item.thumbnailPath != null &&
                                live?.ready == true &&
                                live?.closing != true),
                        button('关闭', () => Navigator.pop(context),
                            enabled: true),
                      ],
                    )),
            child: ImageFiltered(
                imageFilter: ui.ImageFilter.blur(
                    sigmaX: item.masked ? 12 : 0, sigmaY: item.masked ? 12 : 0),
                child: item.thumbnailPath == null
                    ? Center(
                        child:
                            Icon(Icons.image_outlined, size: 30, color: c.ink2))
                    : Image(
                        image: boundedPreviewImage(item.thumbnailPath!,
                            width: 84,
                            height: 84,
                            pixelRatio: MediaQuery.devicePixelRatioOf(context)),
                        fit: BoxFit.cover,
                        filterQuality: FilterQuality.high,
                        errorBuilder: (_, error, stack) =>
                            Icon(Icons.broken_image_outlined, color: c.ink2))),
          )));

  Widget resourceCard(ResourcePreview item) => Semantics(
      label: displayName(item),
      toggled: item.enabled,
      button: true,
      child: Material(
          color: c.panel,
          shape: efCut(br: 12),
          clipBehavior: Clip.antiAlias,
          child: Stack(fit: StackFit.expand, children: [
            InkWell(
                key: ValueKey('resources.item.${item.id}'),
                onTap: live != null && !available
                    ? null
                    : () {
                        if (live == null) {
                          setState(() => item.enabled = !item.enabled);
                        } else {
                          live!.businessTask('resources.toggle', {
                            ...view,
                            'path': d.path.join('/'),
                            'id': item.id,
                            'enabled': !item.enabled,
                            'revision': live!.resources['revision']
                          });
                        }
                      },
                child: Padding(
                    padding: const EdgeInsets.fromLTRB(10, 14, 10, 10),
                    child: Row(children: [
                      thumbnail(item),
                      const SizedBox(width: 12),
                      Expanded(
                          child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                            Tooltip(
                                message: displayName(item),
                                child: Text(displayName(item),
                                    maxLines: 2,
                                    overflow: TextOverflow.ellipsis,
                                    style: EfType.ui(12,
                                        weight: 700,
                                        color: c.ink,
                                        height: 1.3))),
                            Align(
                                alignment: Alignment.bottomRight,
                                child: SizedBox(
                                    height: 28,
                                    child: EfButton('切换键',
                                        key: ValueKey(
                                            'resources.keys.${item.id}'),
                                        small: true,
                                        onPressed: () => showKeys(item)))),
                          ])),
                    ]))),
            Positioned(
              left: 0,
              right: 0,
              top: 0,
              height: 4,
              child: IgnorePointer(
                  child: ColoredBox(
                      key: ValueKey(
                          'resources.status-track.${item.uiKey ?? item.id}'),
                      color: c.chip,
                      child: Align(
                          alignment: Alignment.centerLeft,
                          child: AnimatedFractionallySizedBox(
                              key: ValueKey(
                                  'resources.status.${item.uiKey ?? item.id}'),
                              duration: Ef.d(context, Ef.tabOut),
                              curve: Ef.mech,
                              widthFactor: item.enabled ? 1 : 0,
                              heightFactor: 1,
                              child: AnimatedContainer(
                                  duration: Ef.d(context, Ef.tabOut),
                                  curve: Ef.mech,
                                  color: c.signal))))),
            ),
          ])));

  void showKeys(ResourcePreview item) {
    final future = live == null || item.keys.isNotEmpty
        ? Future.value(item.keys)
        : live!
            .resourceKeys(item.id, live!.resources['revision'] as int)
            .then((keys) => keys
                .map((key) => (
                      '${key['section_name']} / ${key['variable']}',
                      '${key['key'] ?? '未指定'}${key['back'] == null ? '' : ' / ${key['back']}'}'
                    ))
                .toList());
    showEfDialog<void>(
      context: context,
      builder: (_) => ResourceKeysDialog(
          name: displayName(item), bindings: future, preview: live == null),
    );
  }
}

MenuStyle resourceMenuStyle(BuildContext context) => MenuStyle(
      backgroundColor: WidgetStatePropertyAll(EfColors.of(context).panel),
      surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
      elevation: const WidgetStatePropertyAll(0),
      shape: WidgetStatePropertyAll(
          efCut(br: 8, side: BorderSide(color: EfColors.of(context).rule))),
      padding: const WidgetStatePropertyAll(EdgeInsets.all(4)),
    );

class ResourceCardMenu extends StatefulWidget {
  const ResourceCardMenu(
      {super.key,
      required this.item,
      required this.child,
      required this.enabled,
      required this.loadConfigs,
      required this.open,
      required this.openConfig,
      required this.change});
  final ResourcePreview item;
  final Widget child;
  final bool enabled;
  final Future<List> Function() loadConfigs;
  final VoidCallback open;
  final ValueChanged<String> openConfig;
  final ValueChanged<Map<String, dynamic>> change;
  @override
  State<ResourceCardMenu> createState() => _ResourceCardMenuState();
}

class _ResourceCardMenuState extends State<ResourceCardMenu> {
  final menu = MenuController();
  Future<List>? configs;
  @override
  void didUpdateWidget(ResourceCardMenu oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.item.id != widget.item.id) {
      configs = null;
      if (menu.isOpen) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) menu.close();
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => MenuAnchor(
      controller: menu,
      style: resourceMenuStyle(context),
      menuChildren: [
        MenuItemButton(onPressed: widget.open, child: const Text('在资源管理器打开')),
        if (widget.item.isMod) ...[
          SubmenuButton(
              menuStyle: resourceMenuStyle(context),
              menuChildren: [
                FutureBuilder<List>(
                    future: configs,
                    builder: (context, result) =>
                        Column(mainAxisSize: MainAxisSize.min, children: [
                          if (!result.hasData)
                            MenuItemButton(
                                child: Text(
                                    result.hasError ? '配置文件读取失败' : '正在读取…')),
                          if (result.hasData && result.data!.isEmpty)
                            const MenuItemButton(child: Text('没有配置文件')),
                          for (final file in result.data ?? [])
                            MenuItemButton(
                                onPressed: () =>
                                    widget.openConfig(file['path'] as String),
                                child: Text(file['name'] as String)),
                        ]))
              ],
              child: const Text('配置文件')),
          MenuItemButton(
              onPressed: () => widget.change({'masked': !widget.item.masked}),
              child: Text(widget.item.masked ? '关闭缩略图遮罩' : '开启缩略图遮罩')),
        ],
        MenuItemButton(
            onPressed: widget.item.isDirectory
                ? () => widget.change({'isMod': !widget.item.isMod})
                : null,
            child: Text(widget.item.isMod ? '转换为文件夹卡片' : '转换为模组卡片')),
      ],
      builder: (_, controller, child) => GestureDetector(
          onSecondaryTapDown: !widget.enabled
              ? null
              : (details) {
                  setState(() {
                    configs = widget.loadConfigs();
                  });
                  controller.open(position: details.localPosition);
                },
          child: widget.child));
}
