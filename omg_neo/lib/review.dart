import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'ef/menus.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';

import 'ef/tokens.dart';
import 'ef/widgets.dart';

const uiReviewEnabled =
    bool.fromEnvironment('OMG_UI_REVIEW', defaultValue: !kReleaseMode);

class ReviewController {
  final regions = <String, GlobalKey>{};
  bool _opening = false;
  void dispose() => regions.clear();
  Future<void> open(
    BuildContext context,
    GlobalKey capture,
    String screen,
  ) async {
    if (!uiReviewEnabled || _opening) return;
    _opening = true;
    ui.Image? image;
    try {
      await WidgetsBinding.instance.endOfFrame;
      final boundary =
          capture.currentContext?.findRenderObject() as RenderRepaintBoundary?;
      if (boundary == null || !context.mounted) return;
      image = await boundary.toImage(pixelRatio: 1);
      final map = <String, Rect>{};
      for (final entry in regions.entries) {
        final box = entry.value.currentContext?.findRenderObject();
        if (box is RenderBox && box.attached && box.hasSize) {
          final p = box.localToGlobal(Offset.zero, ancestor: boundary);
          map[entry.key] = p & box.size;
        }
      }
      if (!context.mounted) {
        return;
      }
      final snapshot = image;
      await showEfDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (_) =>
            ReviewEditor(snapshot: snapshot, components: map, screen: screen),
      );
    } finally {
      image?.dispose();
      _opening = false;
    }
  }
}

class ReviewRegion extends StatefulWidget {
  const ReviewRegion({
    super.key,
    required this.controller,
    required this.id,
    required this.child,
  });
  final ReviewController controller;
  final String id;
  final Widget child;
  @override
  State<ReviewRegion> createState() => _ReviewRegionState();
}

class _ReviewRegionState extends State<ReviewRegion> {
  final key = GlobalKey();
  @override
  void initState() {
    super.initState();
    widget.controller.regions[widget.id] = key;
  }

  @override
  void didUpdateWidget(ReviewRegion oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.id != widget.id ||
        oldWidget.controller != widget.controller) {
      if (oldWidget.controller.regions[oldWidget.id] == key) {
        oldWidget.controller.regions.remove(oldWidget.id);
      }
      widget.controller.regions[widget.id] = key;
    }
  }

  @override
  void dispose() {
    if (widget.controller.regions[widget.id] == key) {
      widget.controller.regions.remove(widget.id);
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => SizedBox(key: key, child: widget.child);
}

class ReviewHost extends StatefulWidget {
  const ReviewHost({
    super.key,
    required this.controller,
    required this.captureKey,
    required this.screen,
    required this.child,
  });
  final ReviewController controller;
  final GlobalKey captureKey;
  final String screen;
  final Widget child;
  @override
  State<ReviewHost> createState() => _ReviewHostState();
}

class _ReviewHostState extends State<ReviewHost> {
  @override
  void initState() {
    super.initState();
    // Modal routes have their own focus scope outside the workspace subtree.
    if (uiReviewEnabled) HardwareKeyboard.instance.addHandler(handleKey);
  }

  bool handleKey(KeyEvent event) {
    final keyboard = HardwareKeyboard.instance;
    if (event.logicalKey != LogicalKeyboardKey.f8 ||
        keyboard.isControlPressed ||
        keyboard.isAltPressed ||
        keyboard.isMetaPressed ||
        keyboard.isShiftPressed) {
      return false;
    }
    if (event is KeyDownEvent && mounted) {
      widget.controller.open(context, widget.captureKey, widget.screen);
    }
    return true;
  }

  @override
  void dispose() {
    if (uiReviewEnabled) HardwareKeyboard.instance.removeHandler(handleKey);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Focus(
      autofocus: true,
      skipTraversal: true,
      includeSemantics: false,
      debugLabel: 'Workspace neutral focus',
      child: widget.child);
}

class Annotation {
  Annotation(this.rect, {this.note = ''});
  final Rect rect;
  String note;
}

class ReviewEditor extends StatefulWidget {
  const ReviewEditor({
    super.key,
    required this.snapshot,
    required this.components,
    required this.screen,
  });
  final ui.Image snapshot;
  final Map<String, Rect> components;
  final String screen;
  @override
  State<ReviewEditor> createState() => _ReviewEditorState();
}

class _ReviewEditorState extends State<ReviewEditor> {
  final marks = <Annotation>[];
  final note = TextEditingController();
  final directory = TextEditingController(
    text: '${Directory.current.path}${Platform.pathSeparator}ui-reviews',
  );
  int selected = -1;
  bool showComponents = true, saving = false;
  Offset? start, end;
  String status = '拖动框选区域，再填写修改说明。';
  Size get sourceSize =>
      Size(widget.snapshot.width.toDouble(), widget.snapshot.height.toDouble());
  @override
  void dispose() {
    note.dispose();
    directory.dispose();
    super.dispose();
  }

  void select(int index) {
    setState(() {
      selected = index;
      note.text = marks[index].note;
    });
  }

  Map<String, dynamic> rectJson(Rect r) => {
        'x': r.left,
        'y': r.top,
        'width': r.width,
        'height': r.height,
      };
  String get json => const JsonEncoder.withIndent('  ').convert({
        'schemaVersion': 1,
        'screen': widget.screen,
        'canvas': {'width': sourceSize.width, 'height': sourceSize.height},
        'components': [
          for (final e in widget.components.entries)
            {'id': e.key, ...rectJson(e.value)},
        ],
        'annotations': [
          for (int i = 0; i < marks.length; i++)
            {
              'id': i + 1,
              ...rectJson(marks[i].rect),
              'normalized': {
                'x': marks[i].rect.left / sourceSize.width,
                'y': marks[i].rect.top / sourceSize.height,
                'width': marks[i].rect.width / sourceSize.width,
                'height': marks[i].rect.height / sourceSize.height,
              },
              'components': widget.components.entries
                  .where((e) => e.value.overlaps(marks[i].rect))
                  .map((e) => e.key)
                  .toList(),
              'note': marks[i].note,
            },
        ],
      });
  Future<Uint8List> png({required bool annotated}) async {
    if (!annotated) {
      final data = await widget.snapshot.toByteData(
        format: ui.ImageByteFormat.png,
      );
      return data!.buffer.asUint8List();
    }
    final recorder = ui.PictureRecorder();
    final canvas = Canvas(recorder);
    canvas.drawImage(widget.snapshot, Offset.zero, Paint());
    MarkPainter(
      marks: marks,
      components: widget.components,
      showComponents: showComponents,
      selected: -1,
      accent: EfColors.of(context).signal,
    ).paint(canvas, sourceSize);
    final picture = recorder.endRecording();
    final result = await picture.toImage(
      widget.snapshot.width,
      widget.snapshot.height,
    );
    final data = await result.toByteData(format: ui.ImageByteFormat.png);
    result.dispose();
    picture.dispose();
    return data!.buffer.asUint8List();
  }

  Future<void> export() async {
    setState(() => saving = true);
    try {
      final dir = Directory(directory.text.trim());
      await dir.create(recursive: true);
      final base =
          '${dir.path}${Platform.pathSeparator}${widget.screen}-${DateTime.now().millisecondsSinceEpoch}';
      await File('$base.png').writeAsBytes(await png(annotated: false));
      await File('$base-marked.png').writeAsBytes(await png(annotated: true));
      await File('$base.json').writeAsString(json);
      // Companion markdown keeps long Chinese notes readable beside the numbered image.
      await File('$base.md').writeAsString(
        '# ${widget.screen}\n\n画布 ${sourceSize.width.toInt()} × ${sourceSize.height.toInt()}\n\n${[
          for (int i = 0; i < marks.length; i++)
            '${i + 1}. ${marks[i].note.isEmpty ? '（未填写说明）' : marks[i].note}'
        ].join('\n')}\n',
      );
      if (mounted) setState(() => status = '已导出原图、标记图、组件 JSON 和说明：\n$base');
    } catch (e) {
      if (mounted) setState(() => status = '导出失败：$e');
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return Dialog(
      elevation: 0,
      surfaceTintColor: Colors.transparent,
      shadowColor: Colors.transparent,
      insetPadding: const EdgeInsets.all(14),
      shape: const RoundedRectangleBorder(),
      backgroundColor: c.paper,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            Row(
              children: [
                const EfPair('UI REVIEW', 'UI 调整工具', size: 20),
                const SizedBox(width: 16),
                Text(
                  '${widget.screen} / ${sourceSize.width.toInt()} × ${sourceSize.height.toInt()}',
                  style: EfType.ui(11, color: c.ink2),
                ),
                const Spacer(),
                IconButton(
                  tooltip: '关闭调整工具',
                  onPressed: () => Navigator.pop(context),
                  icon: const Icon(Icons.close),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Expanded(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Semantics(
                                label: '显示组件位置',
                                child: EfSwitch(
                                    value: showComponents,
                                    onChanged: (v) =>
                                        setState(() => showComponents = v))),
                            const Text('显示组件位置'),
                            const Spacer(),
                            Text(
                              '${marks.length} 个标记',
                              style: EfType.ui(11, color: c.ink2),
                            ),
                          ],
                        ),
                        Expanded(
                          child: Center(
                            child: AspectRatio(
                              aspectRatio: sourceSize.aspectRatio,
                              child: LayoutBuilder(
                                builder: (_, box) {
                                  Offset pos(Offset p) => Offset(
                                        (p.dx / box.maxWidth * sourceSize.width)
                                            .clamp(0, sourceSize.width),
                                        (p.dy /
                                                box.maxHeight *
                                                sourceSize.height)
                                            .clamp(0, sourceSize.height),
                                      );
                                  return GestureDetector(
                                    behavior: HitTestBehavior.opaque,
                                    onPanStart: (d) => setState(() {
                                      start = pos(d.localPosition);
                                      end = start;
                                    }),
                                    onPanUpdate: (d) => setState(
                                      () => end = pos(d.localPosition),
                                    ),
                                    onPanEnd: (_) {
                                      if (start == null || end == null) return;
                                      final r = Rect.fromPoints(start!, end!);
                                      if (r.width > 5 && r.height > 5) {
                                        marks.add(Annotation(r));
                                        select(marks.length - 1);
                                      }
                                      setState(() {
                                        start = null;
                                        end = null;
                                      });
                                    },
                                    child: Stack(
                                      fit: StackFit.expand,
                                      children: [
                                        RawImage(
                                          image: widget.snapshot,
                                          fit: BoxFit.fill,
                                        ),
                                        CustomPaint(
                                          painter: MarkPainter(
                                            marks: marks,
                                            components: widget.components,
                                            showComponents: showComponents,
                                            selected: selected,
                                            accent: c.signal,
                                            source: sourceSize,
                                            draft: start != null && end != null
                                                ? Rect.fromPoints(start!, end!)
                                                : null,
                                          ),
                                        ),
                                      ],
                                    ),
                                  );
                                },
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(height: 10),
                        Text(
                          '框选图像中的组件；导出坐标以原始逻辑像素为准。',
                          style: EfType.ui(11, color: c.ink2),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 18),
                  SizedBox(
                    width: 245,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Expanded(
                          child: ListView(
                            children: [
                              for (int i = 0; i < marks.length; i++)
                                ListTile(
                                  dense: true,
                                  selected: selected == i,
                                  selectedTileColor: c.signal,
                                  selectedColor: c.onSignal,
                                  title: Text(
                                    '#${i + 1} ${marks[i].note.isEmpty ? '未填写说明' : marks[i].note}',
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                  onTap: () => select(i),
                                  trailing: IconButton(
                                    color: selected == i ? c.onSignal : c.ink,
                                    tooltip: '删除标记',
                                    icon: const Icon(Icons.close, size: 16),
                                    onPressed: () => setState(() {
                                      marks.removeAt(i);
                                      selected = -1;
                                      note.clear();
                                    }),
                                  ),
                                ),
                            ],
                          ),
                        ),
                        TextField(
                          contextMenuBuilder: efTextContextMenu,
                          controller: note,
                          enabled: selected >= 0,
                          maxLines: 3,
                          onChanged: (text) {
                            if (selected >= 0) {
                              setState(() => marks[selected].note = text);
                            }
                          },
                          decoration: InputDecoration(
                            labelText: selected >= 0
                                ? '标记 #${selected + 1} 的说明'
                                : '先框选一个区域',
                            alignLabelWithHint: true,
                          ),
                        ),
                        const SizedBox(height: 10),
                        TextField(
                          contextMenuBuilder: efTextContextMenu,
                          controller: directory,
                          decoration: const InputDecoration(
                            labelText: '导出目录',
                            isDense: true,
                          ),
                        ),
                        const SizedBox(height: 10),
                        EfButton(
                          saving ? '正在导出…' : '导出图片与 JSON',
                          small: true,
                          kind: EfButtonKind.go,
                          onPressed: saving ? null : export,
                        ),
                        const SizedBox(height: 6),
                        EfButton(
                          '复制 JSON',
                          small: true,
                          onPressed: () async {
                            await Clipboard.setData(ClipboardData(text: json));
                            if (mounted) setState(() => status = '已复制组件位置与批注。');
                          },
                        ),
                        const SizedBox(height: 8),
                        SizedBox(
                          height: 48,
                          child: SingleChildScrollView(
                            child: SelectableText(
                              status,
                              contextMenuBuilder: efTextContextMenu,
                              style: EfType.ui(10, color: c.ink2),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class MarkPainter extends CustomPainter {
  MarkPainter({
    required this.marks,
    required this.components,
    required this.showComponents,
    required this.selected,
    required this.accent,
    this.source,
    this.draft,
  });
  final List<Annotation> marks;
  final Map<String, Rect> components;
  final bool showComponents;
  final int selected;
  final Color accent;
  final Size? source;
  final Rect? draft;
  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    if (source != null) {
      canvas.scale(size.width / source!.width, size.height / source!.height);
    }
    void label(String text, Offset p, Color fill) {
      final tp = TextPainter(
        text: TextSpan(
          text: text,
          style: TextStyle(
            fontFamily: 'Saira',
            fontSize: 11,
            color: efForeground(fill),
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      canvas.drawRect(
        Rect.fromLTWH(p.dx, p.dy, tp.width + 8, 18),
        Paint()..color = fill,
      );
      tp.paint(canvas, p + const Offset(4, 1));
    }

    if (showComponents) {
      for (final e in components.entries) {
        canvas.drawRect(
          e.value.deflate(1),
          Paint()
            ..color = const Color(0x885C5C5C)
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1,
        );
        label(e.key, e.value.topLeft, const Color(0xFFE4E4E0));
      }
    }
    for (int i = 0; i < marks.length; i++) {
      final r = marks[i].rect;
      canvas.drawRect(r, Paint()..color = accent.withValues(alpha: .2));
      canvas.drawRect(
        r,
        Paint()
          ..color = const Color(0xFF161616)
          ..style = PaintingStyle.stroke
          ..strokeWidth = selected == i ? 3 : 2,
      );
      label('#${i + 1}', r.topLeft, accent);
    }
    if (draft != null) {
      canvas.drawRect(
        draft!,
        Paint()
          ..color = const Color(0xFF161616)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2,
      );
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(MarkPainter old) => true;
}
