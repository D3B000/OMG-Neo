import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:window_manager/window_manager.dart';

import 'ef/tokens.dart';
import 'ef/widgets.dart';
import 'closing_dialog.dart';
import 'ef/toast.dart';
import 'ef/marks.dart';
import 'review.dart';
import 'settings_ui.dart';
import 'build_ui.dart';
import 'link_ui.dart';
import 'server_switch_ui.dart';
import 'tool_tile.dart';
import 'bisect_ui.dart';
import 'update_preview.dart';
import 'home_ui.dart';
import 'resources_ui.dart';
import 'backend/neo_backend.dart';
import 'backend/neo_controller.dart';
import 'startup_appearance.dart';
import 'frontend_memory.dart';

Future<void> main(List<String> args) async {
  WidgetsFlutterBinding.ensureInitialized();
  await FrontendMemoryPolicy().install();
  final backend = ProcessNeoBackend();
  final appearance = await StartupAppearance.load(backend.resolveDataRoot);
  await windowManager.ensureInitialized();
  await windowManager.waitUntilReadyToShow(
    WindowOptions(
      size: const Size(960, 540),
      minimumSize: const Size(960, 540),
      center: true,
      title: 'OMG-Neo',
      titleBarStyle: TitleBarStyle.hidden,
      backgroundColor:
          appearance.dark ? EfColors.dark.paper : EfColors.light.paper,
    ),
    () async {
      await windowManager.setAsFrameless();
      await windowManager.setHasShadow(true);
    },
  );
  final accentArg =
      args.where((arg) => arg.startsWith('--accent=')).firstOrNull;
  final accentValue = accentArg == null
      ? null
      : int.tryParse(accentArg.substring(9), radix: 16);
  final controller = NeoController(backend);
  runApp(NeoApp(
      controller: controller,
      resources: args.contains('--resources'),
      initialDark: appearance.dark,
      initialAccent:
          accentValue == null ? appearance.accent : Color(accentValue)));
  unawaited(controller.start());
  await WidgetsBinding.instance.endOfFrame;
  await windowManager.show();
  await windowManager.focus();
}

class NeoApp extends StatefulWidget {
  const NeoApp(
      {super.key,
      this.resources = false,
      this.initialDark,
      this.initialAccent = Ef.signal,
      this.controller});
  final bool resources;
  final bool? initialDark;
  final Color initialAccent;
  final NeoController? controller;
  @override
  State<NeoApp> createState() => _NeoAppState();
}

class _NeoAppState extends State<NeoApp> {
  final reviewCapture = GlobalKey();
  late bool dark =
      widget.initialDark ?? widget.controller?.settings['theme'] == 'dark';
  late Color accent = widget.initialAccent;
  @override
  Widget build(BuildContext context) => MaterialApp(
        debugShowCheckedModeBanner: false,
        title: 'OMG-Neo',
        theme: efTheme(Brightness.light, accent: accent),
        darkTheme: efTheme(Brightness.dark, accent: accent),
        themeMode: dark ? ThemeMode.dark : ThemeMode.light,
        // Include Navigator overlays so reviews capture dialogs and their scrim.
        builder: (_, child) => uiReviewEnabled
            ? RepaintBoundary(key: reviewCapture, child: child!)
            : child!,
        home: Workspace(
          captureKey: reviewCapture,
          controller: widget.controller,
          resources: widget.resources,
          dark: dark,
          onTheme: () => setState(() => dark = !dark),
          onAccent: (color) => setState(() => accent = color),
        ),
      );
}

class Workspace extends StatefulWidget {
  const Workspace({
    super.key,
    required this.captureKey,
    required this.resources,
    required this.dark,
    required this.onTheme,
    required this.onAccent,
    this.controller,
  });
  final bool resources, dark;
  final GlobalKey captureKey;
  final VoidCallback onTheme;
  final ValueChanged<Color> onAccent;
  final NeoController? controller;
  @override
  State<Workspace> createState() => _WorkspaceState();
}

class _WorkspaceState extends State<Workspace> with WindowListener {
  final review = ReviewController();
  GlobalKey get capture => widget.captureKey;
  final settingsDraft = SettingsDraft();
  late int page = widget.resources ? 1 : 0;
  bool building = false, linking = false, switching = false, bisecting = false;
  final linkDraft = LinkDraft();
  final resourcesDraft = ResourcesDraft();
  final buildDraft = BuildDraft();
  final preview = UpdatePreviewController();
  UpdatePreviewController get updatePreview =>
      widget.controller?.update ?? preview;
  int _settingsEpoch = -1;
  bool _loadingDraft = false, _closing = false;
  String _draftSignature = '';
  String? _lastBackendNotice;
  static const pathsChannel = MethodChannel('omg_neo/paths');
  static const lifecycleChannel = MethodChannel('omg_neo/lifecycle');

  @override
  void initState() {
    super.initState();
    final controller = widget.controller;
    if (controller != null) {
      controller.addListener(backendChanged);
      windowManager.addListener(this);
      unawaited(windowManager.setPreventClose(true));
      for (final field in [
        settingsDraft.game,
        settingsDraft.gimi,
        settingsDraft.command,
        settingsDraft.dlls
      ]) {
        field.addListener(settingsChanged);
      }
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) backendChanged();
      });
    }
  }

  void backendChanged() {
    final controller = widget.controller!;
    final message = controller.error ?? controller.status;
    final streaming = controller.busy &&
        (controller.taskKind.startsWith('build.') ||
            controller.taskKind == 'resources.writeback' ||
            controller.taskKind == 'cache.clear' ||
            controller.taskKind.startsWith('serverSwitch.'));
    if (streaming) _lastBackendNotice = null;
    final silentResource = (controller.noticeKind.startsWith('resources.') &&
            controller.noticeKind != 'resources.writeback') ||
        (page == 1 &&
            !controller.noticeKind.startsWith('build.') &&
            controller.noticeKind != 'resources.writeback');
    if (silentResource) _lastBackendNotice = message;
    if (!_closing &&
        !silentResource &&
        !streaming &&
        message.isNotEmpty &&
        message != _lastBackendNotice) {
      _lastBackendNotice = message;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) notice(message);
      });
    }
    if (controller.ready && controller.settingsEpoch != _settingsEpoch) {
      _loadingDraft = true;
      _settingsEpoch = controller.settingsEpoch;
      settingsDraft.load(controller.settings);
      _draftSignature = jsonEncode(settingsDraft.toSettings());
      _loadingDraft = false;
      final dark = controller.settings['theme'] == 'dark';
      if (dark != widget.dark) widget.onTheme();
      final color = controller.settings['accent_color'] as String;
      widget.onAccent(Color(int.parse('FF${color.substring(1)}', radix: 16)));
    }
    if (mounted) setState(() {});
  }

  void settingsChanged() {
    if (_loadingDraft || widget.controller?.ready != true) return;
    final patch = settingsDraft.toSettings();
    final signature = jsonEncode(patch);
    if (signature == _draftSignature) return;
    _draftSignature = signature;
    widget.controller!.stage(patch);
  }

  Future<String?> pickPath({required bool folder, String initial = ''}) async {
    try {
      return await pathsChannel
          .invokeMethod<String>('pick', {'folder': folder, 'initial': initial});
    } catch (exception) {
      if (mounted) notice('路径选择失败：$exception');
      return null;
    }
  }

  @override
  void onWindowClose() async {
    if (_closing) return;
    if (widget.controller?.bisectActive == true) {
      final leave = await showEfDialog<bool>(
          context: context,
          builder: (ctx) => EfDialog(
                eyebrow: 'BISECT SESSION',
                title: const Text('排查会话尚未结束'),
                content: const Text(
                    '分组结构、初始快照和当前启停状态均已记录。可以返回继续操作，或保留当前状态退出，下次核对后继续使用分组。'),
                actions: [
                  EfButton('返回处理',
                      small: true, onPressed: () => Navigator.pop(ctx, false)),
                  EfButton('保留会话并退出',
                      small: true, onPressed: () => Navigator.pop(ctx, true))
                ],
              ));
      if (leave != true || !mounted) return;
    }
    _closing = true;
    final navigator = Navigator.of(context, rootNavigator: true);
    final closingRoute = efDialogRoute<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) {
        final controller = widget.controller;
        if (controller == null) return const NeoClosingDialog();
        return ListenableBuilder(
          listenable: controller,
          builder: (context, _) => NeoClosingDialog(
              cleanupMessage:
                  controller.cacheCleaning ? controller.cacheMessage : null,
              cleanupProgress: controller.cacheProgress),
        );
      },
    );
    unawaited(navigator.push(closingRoute));
    try {
      // Paint feedback before starting persistence or backend cleanup.
      await WidgetsBinding.instance.endOfFrame;
      await widget.controller?.close();
      await lifecycleChannel.invokeMethod<void>('finishExit');
    } catch (exception) {
      _closing = false;
      if (mounted) {
        navigator.removeRoute(closingRoute);
        notice('关闭失败：$exception；请处理后重试。');
      }
    }
  }

  EfColors get c => EfColors.of(context);
  String get screen => bisecting
      ? 'bisect'
      : building
          ? 'build'
          : switching
              ? 'serverSwitch'
              : linking
                  ? 'links'
                  : ['home', 'resources', 'tools', 'settings'][page];
  void notice(String message) => showEfToast(context, message);
  Widget region(String id, Widget child) => uiReviewEnabled
      ? ReviewRegion(
          key: ValueKey('region.$id'), controller: review, id: id, child: child)
      : KeyedSubtree(key: ValueKey('region.$id'), child: child);
  Widget action(String text, VoidCallback tap, {bool primary = false}) =>
      EfButton(
        text,
        onPressed: tap,
        kind: primary ? EfButtonKind.go : EfButtonKind.normal,
        small: true,
      );
  Widget head(String en, String zh, {Widget? trailing}) => Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          EfPair(en, zh, size: 24),
          const Spacer(),
          if (trailing != null) trailing,
        ],
      );
  Widget rule() => Divider(height: 1, color: c.rule);
  void openReview() => review.open(context, capture, screen);
  void go(int i) => setState(() {
        page = i;
        building = false;
        linking = false;
        switching = false;
        bisecting = false;
      });
  @override
  void dispose() {
    widget.controller?.removeListener(backendChanged);
    if (widget.controller != null) windowManager.removeListener(this);
    review.dispose();
    settingsDraft.dispose();
    buildDraft.dispose();
    linkDraft.dispose();
    resourcesDraft.dispose();
    preview.dispose();
    super.dispose();
  }

  Widget pageGround({required Widget child}) =>
      bisecting ? child : EfContours(child: child);

  @override
  Widget build(BuildContext context) => Scaffold(
        body: ReviewHost(
          controller: review,
          captureKey: capture,
          screen: screen,
          child: ColoredBox(
            color: c.paper,
            child: pageGround(
                child: Column(
              children: [
                region('window.titlebar', caption()),
                Expanded(
                  child: Stack(
                    children: [
                      Positioned.fill(
                        child: Padding(
                          padding: EdgeInsets.fromLTRB(
                              bisecting ? 0 : 32,
                              bisecting
                                  ? 0
                                  : page == 1
                                      ? 14
                                      : 22,
                              bisecting ? 0 : 32,
                              bisecting ||
                                      building ||
                                      linking ||
                                      switching ||
                                      page == 3 ||
                                      page == 1
                                  ? 0
                                  : 84),
                          child: bisecting
                              ? NeoBisect(
                                  controller: widget.controller,
                                  pickPath: pickPath,
                                  region: region,
                                  onBack: () =>
                                      setState(() => bisecting = false))
                              : building
                                  ? buildPage()
                                  : switching
                                      ? NeoServerSwitch(
                                          controller: widget.controller,
                                          region: region,
                                          pickPath: pickPath,
                                          onBack: () =>
                                              setState(() => switching = false))
                                      : linking
                                          ? NeoLinks(
                                              draft: linkDraft,
                                              gimi: settingsDraft.gimi.text,
                                              onBack: () => setState(
                                                  () => linking = false),
                                              pickPath: pickPath,
                                              region: region,
                                              backend:
                                                  widget.controller?.backend,
                                              ready: widget.controller?.ready ==
                                                      true &&
                                                  widget.controller?.busy ==
                                                      false)
                                          : [
                                              home,
                                              resources,
                                              tools,
                                              settings
                                            ][page](),
                        ),
                      ),
                      Positioned(
                        left: 0,
                        right: 0,
                        bottom: 18,
                        child: Center(
                          child: region('navigation.bottom', bottomBar()),
                        ),
                      ),
                      if (bisecting)
                        Positioned(
                            left: 0,
                            right: 0,
                            bottom: 0,
                            child: region(
                                'bisect.progress',
                                AnimatedBuilder(
                                    animation: widget.controller ?? preview,
                                    builder: (_, __) {
                                      final task = widget.controller;
                                      return BottomTaskProgress(
                                          active: task?.busy == true &&
                                              (task?.taskKind
                                                      .startsWith('bisect.') ??
                                                  false),
                                          progress: task?.taskProgress,
                                          message: task?.status ?? '正在处理模组…');
                                    }))),
                      if (switching)
                        Positioned(
                            left: 0,
                            right: 0,
                            bottom: 0,
                            child: region(
                                'serverSwitch.progress',
                                AnimatedBuilder(
                                    animation: widget.controller ?? preview,
                                    builder: (_, child) {
                                      final task = widget.controller;
                                      return BottomTaskProgress(
                                          active: task?.busy == true &&
                                              (task?.taskKind.startsWith(
                                                      'serverSwitch.') ??
                                                  false),
                                          progress: task?.taskProgress,
                                          message: task?.status ?? '');
                                    }))),
                      if (!bisecting &&
                          !building &&
                          !linking &&
                          !switching &&
                          page == 0)
                        Positioned(
                          left: 0,
                          right: 0,
                          bottom: 0,
                          child: region('home.progress',
                              BottomUpdateProgress(controller: updatePreview)),
                        ),
                    ],
                  ),
                ),
              ],
            )),
          ),
        ),
      );
  Widget caption() => Container(
        height: 40,
        color: Colors.transparent,
        child: Row(
          children: [
            Expanded(
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onPanStart: (_) => windowManager.startDragging(),
                child: Padding(
                  padding: const EdgeInsets.only(left: 18),
                  child: Row(
                    children: [
                      Icon(
                        Icons.layers_outlined,
                        color: c.ink,
                        size: 17,
                      ),
                      const SizedBox(width: 10),
                      Text(
                        bisecting
                            ? '二分排查'
                            : building
                                ? '便捷构建'
                                : switching
                                    ? '服务器切换'
                                    : linking
                                        ? '便捷关联'
                                        : 'OMG-Neo',
                        style: EfType.ui(13, weight: 700, color: c.ink),
                      ),
                      const SizedBox(width: 18),
                      Text(
                        'Ordinarily Manage GIMI',
                        style: EfType.ui(9, color: c.ink2, spacing: .14),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            if (uiReviewEnabled)
              IconButton(
                tooltip: 'UI 调整工具 / F8',
                onPressed: openReview,
                icon: Icon(Icons.crop_free, size: 17, color: c.ink2),
              ),
            IconButton(
              tooltip: '最小化',
              onPressed: () => windowManager.minimize(),
              icon: Icon(Icons.remove, size: 17, color: c.ink2),
            ),
            IconButton(
              tooltip: '关闭',
              onPressed: widget.controller == null
                  ? () => windowManager.close()
                  : onWindowClose,
              icon: Icon(Icons.close, size: 17, color: c.ink2),
            ),
          ],
        ),
      );
  Widget home() => NeoHome(
        update: updatePreview,
        region: region,
        versions: widget.controller?.versions,
        launchLabel: widget.controller == null
            ? '启动游戏  ↗'
            : widget.controller!.closing
                ? '正在收尾…'
                : widget.controller!.launchState == 'unverified'
                    ? '游戏运行中（未校验）'
                    : widget.controller!.launchState == 'done'
                        ? '游戏运行中'
                        : widget.controller!.busy
                            ? (widget.controller!.taskKind ==
                                        'serverSwitch.apply' ||
                                    widget.controller!.taskKind ==
                                        'serverSwitch.restore'
                                ? '正在切换服务器…'
                                : '正在执行…')
                            : '启动游戏  ↗',
        onLaunch: widget.controller == null
            ? () => notice('启动游戏：仅预览，未启动实际程序。')
            : widget.controller!.launchEnabled
                ? widget.controller!.launch
                : null,
      );
  void openResources() => go(1);

  Widget tools() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          head('TOOLBOX', '工具'),
          const SizedBox(height: 13),
          Text('构建、关联目录、服务器切换与模组排查。', style: EfType.ui(12, color: c.ink2)),
          const SizedBox(height: 30),
          Expanded(
            child: Row(
              children: [
                toolCard(
                  'tools.build',
                  '01',
                  'BUILD',
                  '便捷构建',
                  '下载、构建与文件优化\n集中查看任务输出',
                  Icons.build_outlined,
                  () => setState(() => building = true),
                ),
                const SizedBox(width: 18),
                toolCard(
                  'tools.link',
                  '02',
                  'LINK',
                  '便捷关联',
                  'JUNCTION 目录联接\nINCLUDE 递归包含',
                  Icons.link,
                  () => setState(() => linking = true),
                ),
                const SizedBox(width: 18),
                toolCard(
                  'tools.serverSwitch',
                  '03',
                  'SERVER',
                  '服务器切换',
                  '官服 / B 服 / 国际服\n使用本地替换资源',
                  Icons.swap_horiz,
                  () => setState(() => switching = true),
                ),
                const SizedBox(width: 18),
                toolCard(
                    'tools.bisect',
                    '04',
                    'BISECT',
                    '二分排查',
                    '递归分组与独立启停\n初始状态记录与恢复',
                    Icons.account_tree_outlined,
                    () => setState(() => bisecting = true)),
              ],
            ),
          ),
        ],
      );
  Widget toolCard(String id, String no, String en, String zh, String detail,
          IconData icon, VoidCallback tap) =>
      Expanded(
          child: region(
              id,
              ToolTile(
                  number: no,
                  english: en,
                  title: zh,
                  detail: detail,
                  icon: icon,
                  onTap: tap)));
  bool navigationSelected(int i) =>
      bisecting ? i == 2 : !building && !linking && !switching && page == i;
  Widget bottomBar() => Container(
        padding: const EdgeInsets.all(4),
        decoration: ShapeDecoration(
          color: Colors.transparent,
          shape: efCut(br: 12, side: BorderSide(color: c.rule)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (int i = 0; i < 4; i++)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 2),
                child: Semantics(
                  selected: navigationSelected(i),
                  child: SizedBox(
                    width: 138,
                    height: 36,
                    child: action(
                      '${['首页', '浏览', '工具', '设置'][i]} / ${[
                        'HOME',
                        'BROWSE',
                        'TOOLS',
                        'CONFIG'
                      ][i]}',
                      () => go(i),
                      primary: navigationSelected(i),
                    ),
                  ),
                ),
              ),
          ],
        ),
      );
  Widget buildPage() => BuildConsole(
      draft: buildDraft,
      controller: widget.controller,
      pickPath: widget.controller == null ? null : pickPath,
      onBack: () => setState(() => building = false),
      region: region);
  Widget settings() => NeoSettings(
      draft: settingsDraft,
      dark: widget.dark,
      onTheme: () {
        widget.onTheme();
        widget.controller?.stage({'theme': widget.dark ? 'light' : 'dark'});
      },
      onAccent: (color) {
        widget.onAccent(color);
        widget.controller?.stage({
          'accent_color':
              '#${color.toARGB32().toRadixString(16).substring(2).toUpperCase()}'
        });
      },
      onChanged: settingsChanged,
      pickPath: widget.controller == null ? null : pickPath,
      onImport: widget.controller == null
          ? null
          : () async {
              final path = await pickPath(folder: false);
              if (path != null) await widget.controller!.importLite(path);
            },
      live: widget.controller != null,
      ready: widget.controller?.ready ?? true,
      onRefreshCache: widget.controller == null
          ? null
          : () => widget.controller!.refreshCache(),
      cacheBytes: widget.controller?.cacheBytes,
      cacheClearing: widget.controller?.taskKind == 'cache.clear' &&
          widget.controller?.busy == true,
      cacheProgress: widget.controller?.taskProgress,
      cacheMessage: widget.controller?.taskKind == 'cache.clear'
          ? widget.controller!.status
          : widget.controller?.cacheMessage ?? '',
      onClearCache: widget.controller == null
          ? null
          : () => widget.controller!.refreshCache(clear: true),
      openReview: uiReviewEnabled ? openReview : null,
      region: region);
  Widget resources() => ResourceBrowser(
      draft: resourcesDraft,
      controller: widget.controller,
      region: region,
      notice: notice,
      onSettings: () => go(3));
}
