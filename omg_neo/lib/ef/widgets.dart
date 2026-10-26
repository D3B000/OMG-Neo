// Endfield components for Flutter. Each one says in its comment what it MEANS.
import 'package:flutter/material.dart';
import 'menus.dart';
import 'package:flutter/services.dart';

import 'marks.dart';
import 'tokens.dart';

/// Wide upper-case label. `slash: true` adds the "//" section prefix.
class EfEyebrow extends StatelessWidget {
  const EfEyebrow(this.text, {super.key, this.slash = false, this.color});
  final String text;
  final bool slash;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return Text('${slash ? '// ' : ''}${text.toUpperCase()}',
        style: EfType.eyebrow(color ?? c.ink2));
  }
}

/// Page overlay shown while files hover over an enabled drop target.
class EfDropHint extends StatelessWidget {
  const EfDropHint(this.en, this.zh, {super.key});
  final String en, zh;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return IgnorePointer(
        child: Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
          color: c.panel.withValues(alpha: .96),
          border: Border.all(color: c.ink)),
      child: Center(child: EfPair(en, zh, size: 22)),
    ));
  }
}

/// English small above, Chinese bold below: the standard way to name a section.
class EfPair extends StatelessWidget {
  const EfPair(this.en, this.zh, {super.key, this.size = 22});
  final String en;
  final String zh;
  final double size;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          EfEyebrow(en, slash: true),
          const SizedBox(height: 2),
          Text(zh,
              style: EfType.ui(size, weight: 700, color: c.ink, height: 1.3)),
        ]);
  }
}

/// Index tag (No.024). Dark block, bottom-right corner cut. `current` turns it yellow.
class EfTag extends StatelessWidget {
  const EfTag(this.text, {super.key, this.current = false});
  final String text;
  final bool current;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return DecoratedBox(
      decoration: ShapeDecoration(
          color: current ? c.signal : c.tagBg, shape: efCut(br: Ef.cutSmall)),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(7, 2, 10, 2),
        child: Text(text,
            style: EfType.ui(12,
                weight: 600,
                width: 112,
                color: current ? c.onSignal : c.tagFg)),
      ),
    );
  }
}

/// Filter chip. Active = yellow fill. Count in the field face.
class EfChip extends StatelessWidget {
  const EfChip(this.label,
      {super.key, this.count, this.active = false, this.onTap});
  final String label;
  final int? count;
  final bool active;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    final fg = active ? c.onSignal : c.ink;
    return Semantics(
      button: true,
      selected: active,
      child: GestureDetector(
        onTap: onTap,
        child: AnimatedContainer(
          duration: Ef.d(context, Ef.press),
          constraints: const BoxConstraints(minHeight: 36),
          padding: const EdgeInsets.fromLTRB(12, 0, 14, 0),
          decoration: ShapeDecoration(
              color: active ? c.signal : c.chip, shape: efCut(br: Ef.cutSmall)),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Text(label, style: EfType.ui(14, weight: 600, color: fg)),
            if (count != null) ...[
              const SizedBox(width: 6),
              Text('$count', style: EfType.field(fg)),
            ],
          ]),
        ),
      ),
    );
  }
}

enum EfButtonKind { normal, go, danger }

/// Button. Corner cut bottom-right. Pressing wipes a fill in from the left
/// (yellow; red for danger). `go` is the one main action and is yellow at rest.
class EfButton extends StatefulWidget {
  const EfButton(this.label,
      {super.key,
      this.onPressed,
      this.kind = EfButtonKind.normal,
      this.small = false,
      this.expand = false});
  final String label;
  final VoidCallback? onPressed;
  final EfButtonKind kind;
  final bool small;
  final bool expand;

  @override
  State<EfButton> createState() => _EfButtonState();
}

class _EfButtonState extends State<EfButton> {
  bool _down = false;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    final enabled = widget.onPressed != null;
    final wipe = widget.kind == EfButtonKind.danger ? c.danger : c.signal;
    final rest = widget.kind == EfButtonKind.go ? c.signal : c.chip;
    final fg = !enabled
        ? c.ink2
        : _down
            ? (widget.kind == EfButtonKind.danger ? c.panel : c.onSignal)
            : (widget.kind == EfButtonKind.go
                ? c.onSignal
                : (widget.kind == EfButtonKind.danger ? c.danger : c.ink));
    final h = widget.small ? 36.0 : Ef.touch;
    return Semantics(
      button: true,
      enabled: enabled,
      child: GestureDetector(
        onTapDown: enabled ? (_) => setState(() => _down = true) : null,
        onTapCancel: () => setState(() => _down = false),
        onTapUp: enabled
            ? (_) {
                setState(() => _down = false);
                widget.onPressed!();
              }
            : null,
        child: ClipPath(
          clipper: ShapeBorderClipper(shape: efCut(br: Ef.cutButton)),
          child: SizedBox(
            height: h,
            width: widget.expand ? double.infinity : null,
            child: Stack(fit: StackFit.passthrough, children: [
              Positioned.fill(
                  child: ColoredBox(
                      color: enabled ? rest : c.chip.withValues(alpha: 0.6))),
              Positioned.fill(
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: AnimatedFractionallySizedBox(
                    duration: Ef.d(context, _down ? Ef.press : Ef.wipe),
                    curve: Ef.mech,
                    widthFactor: _down ? 1 : 0,
                    heightFactor: 1,
                    child: ColoredBox(
                        color: widget.kind == EfButtonKind.go
                            ? c.ink.withValues(alpha: 0.12)
                            : wipe),
                  ),
                ),
              ),
              Padding(
                padding:
                    EdgeInsets.symmetric(horizontal: widget.small ? 14 : 20),
                child: Center(
                  widthFactor: widget.expand ? null : 1,
                  child: Text(widget.label,
                      style: EfType.ui(widget.small ? 13 : 15,
                          weight: 700, width: 112, color: fg)),
                ),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}

/// One record in a list: tag, date field, name, meta. A hairline below. Pressing
/// drops a trace bar at the left edge and shifts the row 6px right.
class EfRecord extends StatefulWidget {
  const EfRecord(
      {super.key,
      required this.no,
      required this.date,
      required this.name,
      required this.meta,
      this.current = false,
      this.onTap});
  final String no;
  final String date;
  final String name;
  final String meta;
  final bool current;
  final VoidCallback? onTap;

  @override
  State<EfRecord> createState() => _EfRecordState();
}

class _EfRecordState extends State<EfRecord> {
  bool _down = false;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    final on = _down || widget.current;
    final dur = Ef.d(context, Ef.row);
    return Semantics(
      button: widget.onTap != null,
      selected: widget.current,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTapDown: (_) => setState(() => _down = true),
        onTapCancel: () => setState(() => _down = false),
        onTapUp: (_) {
          setState(() => _down = false);
          widget.onTap?.call();
        },
        child: Container(
          decoration:
              BoxDecoration(border: Border(bottom: BorderSide(color: c.rule))),
          child: Stack(children: [
            AnimatedPositioned(
              duration: dur,
              curve: Ef.snap,
              left: 0,
              top: 0,
              bottom: on ? 0 : null,
              height: on ? null : 0,
              width: Ef.traceBar,
              child: ColoredBox(
                  color: c
                      .trace), // a line: ink on light, yellow on dark. "Current" is the yellow tag.
            ),
            AnimatedPadding(
              duration: dur,
              curve: Ef.snap,
              padding:
                  EdgeInsets.fromLTRB(on ? 14 : 8, Ef.rowPad, 4, Ef.rowPad),
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(children: [
                      EfTag(widget.no, current: widget.current),
                      const SizedBox(width: 10),
                      Text(widget.date, style: EfType.field(c.ink2)),
                      const Spacer(),
                      Text(widget.meta, style: EfType.field(c.ink2)),
                    ]),
                    const SizedBox(height: 6),
                    Text(widget.name,
                        style: EfType.text(16,
                            weight: 500, color: c.ink, height: 1.5)),
                  ]),
            ),
          ]),
        ),
      ),
    );
  }
}

/// Panel: white sheet, hairline border, a short dark tab on the top edge, one
/// corner cut (the one facing the centre of the screen).
class EfPanel extends StatelessWidget {
  const EfPanel(
      {super.key,
      required this.child,
      this.cutBr = Ef.cutPanel,
      this.padding = const EdgeInsets.all(16)});
  final Widget child;
  final double cutBr;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return Stack(children: [
      DecoratedBox(
        decoration: ShapeDecoration(
            color: c.panel,
            shape: efCut(br: cutBr, side: BorderSide(color: c.rule))),
        child: Padding(padding: padding, child: child),
      ),
      Positioned(
          left: 0,
          top: 0,
          width: 56,
          height: Ef.tab,
          child: ColoredBox(color: c.ink)),
    ]);
  }
}

/// Big figures with labels. `alert` puts a yellow flag behind the number.
class EfFigure extends StatelessWidget {
  const EfFigure(this.value, this.label, {super.key, this.alert = false});
  final String value;
  final String label;
  final bool alert;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Container(
        padding:
            alert ? const EdgeInsets.symmetric(horizontal: 6) : EdgeInsets.zero,
        color: alert ? c.signal : null,
        child: Text(value,
            style: EfType.ui(36,
                weight: 700,
                width: 112,
                color: alert ? c.onSignal : c.ink,
                height: 1.1)),
      ),
      const SizedBox(height: 4),
      Text(label, style: EfType.ui(13, weight: 600, color: c.ink2)),
    ]);
  }
}

/// State stamp. Solid = live, dashed = still backstage, yellow = look at this.
enum EfStateKind { live, draft, alert }

class EfState extends StatelessWidget {
  const EfState(this.text, {super.key, this.kind = EfStateKind.live});
  final String text;
  final EfStateKind kind;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    final alert = kind == EfStateKind.alert;
    return CustomPaint(
      painter: kind == EfStateKind.draft ? _DashedBox(c.ink2) : null,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
        decoration: kind == EfStateKind.live
            ? BoxDecoration(border: Border.all(color: c.ink))
            : (alert ? BoxDecoration(color: c.signal) : null),
        child: Text(text,
            style:
                EfType.ui(12, weight: 600, color: alert ? c.onSignal : c.ink)),
      ),
    );
  }
}

class _DashedBox extends CustomPainter {
  _DashedBox(this.color);
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()..color = color;
    void dash(Offset a, Offset b) {
      final len = (b - a).distance;
      final dir = (b - a) / len;
      for (var d = 0.0; d < len; d += 6) {
        canvas.drawLine(a + dir * d, a + dir * (d + 3).clamp(0, len), p);
      }
    }

    final r = Offset.zero & size;
    dash(r.topLeft, r.topRight);
    dash(r.topRight, r.bottomRight);
    dash(r.bottomRight, r.bottomLeft);
    dash(r.bottomLeft, r.topLeft);
  }

  @override
  bool shouldRepaint(_DashedBox old) => old.color != color;
}

/// Something to notice: a yellow flag block, then the sentence.
class EfNotice extends StatelessWidget {
  const EfNotice(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return Container(
      decoration:
          BoxDecoration(color: c.panel, border: Border.all(color: c.rule)),
      child: IntrinsicHeight(
        child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Container(
              width: 28,
              color: c.signal,
              alignment: Alignment.center,
              child: Text('!',
                  style: EfType.ui(15, weight: 800, color: c.onSignal))),
          Expanded(
              child: Padding(
                  padding: const EdgeInsets.all(10),
                  child: Text(text, style: EfType.ui(14, color: c.ink)))),
        ]),
      ),
    );
  }
}

/// Facts row in the field face, separated by thin vertical rules.
class EfFacts extends StatelessWidget {
  const EfFacts(this.items, {super.key});
  final List<String> items;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return Wrap(runSpacing: 4, children: [
      for (var i = 0; i < items.length; i++)
        Container(
          padding: EdgeInsets.only(left: i == 0 ? 0 : 10, right: 10),
          decoration: BoxDecoration(
              border: i == 0 ? null : Border(left: BorderSide(color: c.rule))),
          child: Text(items[i], style: EfType.field(c.ink2)),
        ),
    ]);
  }
}

/// Top bar of an app screen: section eyebrow + bold title, hairline below.
/// No elevation, no colour fill, no centred title.
class EfTopBar extends StatelessWidget implements PreferredSizeWidget {
  const EfTopBar(
      {super.key,
      required this.en,
      required this.title,
      this.leading,
      this.actions = const []});
  final String en;
  final String title;
  final Widget? leading;
  final List<Widget> actions;

  @override
  Size get preferredSize => const Size.fromHeight(64);

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return Container(
      height: 64,
      padding: const EdgeInsets.symmetric(horizontal: Ef.pad),
      decoration: BoxDecoration(
          color: c.paper, border: Border(bottom: BorderSide(color: c.rule))),
      child: Row(children: [
        if (leading != null) ...[leading!, const SizedBox(width: 12)],
        Expanded(child: EfPair(en, title, size: 20)),
        ...actions,
      ]),
    );
  }
}

class EfTabItem {
  const EfTabItem(this.en, this.zh);
  final String en;
  final String zh;
}

/// Bottom tab bar. Current tab = yellow block with a cut corner and a dark
/// tab line on top; others are quiet text. No icons-only tabs: always a label.
class EfTabBar extends StatelessWidget {
  const EfTabBar(
      {super.key,
      required this.items,
      required this.current,
      required this.onTap});
  final List<EfTabItem> items;
  final int current;
  final ValueChanged<int> onTap;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    final bottom = MediaQuery.of(context).padding.bottom;
    return Container(
      padding: EdgeInsets.fromLTRB(8, 8, 8, 8 + bottom),
      decoration: BoxDecoration(
          color: c.panel, border: Border(top: BorderSide(color: c.rule))),
      child: Row(children: [
        for (var i = 0; i < items.length; i++)
          Expanded(
            child: Semantics(
              button: true,
              selected: i == current,
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTap: () => onTap(i),
                child: AnimatedContainer(
                  duration: Ef.d(context, Ef.wipe),
                  curve: Ef.mech,
                  height: 52,
                  margin: const EdgeInsets.symmetric(horizontal: 3),
                  decoration: ShapeDecoration(
                      color: i == current ? c.signal : Colors.transparent,
                      shape: efCut(br: Ef.cutSmall)),
                  child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Text(items[i].en.toUpperCase(),
                            style: EfType.eyebrow(
                                    i == current ? c.onSignal : c.ink2)
                                .copyWith(fontSize: 9)),
                        Text(items[i].zh,
                            style: EfType.ui(14,
                                weight: i == current ? 700 : 500,
                                color: i == current ? c.onSignal : c.ink)),
                      ]),
                ),
              ),
            ),
          ),
      ]),
    );
  }
}

/// Text field: label above in the eyebrow face, white input, hairline frame
/// that turns into a 2px ink/trace line at the bottom when focused, help below.
class EfField extends StatelessWidget {
  const EfField(
      {super.key, required this.label, this.hint, this.help, this.initial});
  final String label;
  final String? hint;
  final String? help;
  final String? initial;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(label, style: EfType.ui(13, weight: 600, color: c.ink2)),
      const SizedBox(height: 6),
      TextFormField(
        contextMenuBuilder: efTextContextMenu,
        initialValue: initial,
        style: EfType.ui(16, color: c.ink),
        decoration: InputDecoration(
          isDense: true,
          filled: true,
          fillColor: c.panel,
          hintText: hint,
          hintStyle: EfType.ui(16, color: c.ink2),
          contentPadding:
              const EdgeInsets.symmetric(horizontal: 12, vertical: 13),
          enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.zero,
              borderSide: BorderSide(color: c.rule)),
          focusedBorder: UnderlineInputBorder(
              borderRadius: BorderRadius.zero,
              borderSide: BorderSide(color: c.trace, width: 2)),
        ),
      ),
      if (help != null) ...[
        const SizedBox(height: 6),
        Text(help!, style: EfType.ui(12, color: c.ink2)),
      ],
    ]);
  }
}

/// Square switch. On = yellow track, dark knob; off = chip track, hairline knob.
class EfSwitch extends StatelessWidget {
  const EfSwitch({super.key, required this.value, required this.onChanged});
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return Semantics(
      toggled: value,
      button: true,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () => onChanged(!value),
        child: SizedBox(
            width: 52,
            height: 48,
            child: Center(
                child: AnimatedContainer(
              duration: Ef.d(context, Ef.wipe),
              curve: Ef.mech,
              width: 48,
              height: 26,
              padding: const EdgeInsets.all(3),
              color: value ? c.signal : c.chip,
              alignment: value ? Alignment.centerRight : Alignment.centerLeft,
              child: Container(
                  width: 20, height: 20, color: value ? c.onSignal : c.panel),
            ))),
      ),
    );
  }
}

/// Segmented control: hairline frame, current segment filled with ink (not
/// yellow: yellow is reserved for "where you are" in navigation and the main action).
class EfSegmented extends StatelessWidget {
  const EfSegmented(
      {super.key,
      required this.options,
      required this.current,
      required this.onChanged});
  final List<String> options;
  final int current;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return Container(
      decoration: BoxDecoration(border: Border.all(color: c.ink)),
      child: Row(children: [
        for (var i = 0; i < options.length; i++)
          Expanded(
            child: Semantics(
              button: true,
              inMutuallyExclusiveGroup: true,
              checked: i == current,
              child: GestureDetector(
                onTap: () => onChanged(i),
                child: AnimatedContainer(
                  duration: Ef.d(context, Ef.wipe),
                  curve: Ef.mech,
                  height: 44,
                  alignment: Alignment.center,
                  color: i == current ? c.ink : Colors.transparent,
                  child: Text(options[i],
                      style: EfType.ui(14,
                          weight: 600, color: i == current ? c.paper : c.ink)),
                ),
              ),
            ),
          ),
      ]),
    );
  }
}

/// Mechanical progress: a segmented bar that fills in hard steps, with a field readout.
class EfProgress extends StatelessWidget {
  const EfProgress({super.key, required this.value, this.label = 'LOADING'});
  final double value;
  final String label;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    const n = 24;
    final lit = (value * n).floor();
    return Semantics(
      label: label,
      value: '${(value * 100).round()}%',
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          EfEyebrow(label, color: c.ink),
          const Spacer(),
          Text('${(value * 100).round().toString().padLeft(3, '0')}%',
              style: EfType.field(c.ink)),
        ]),
        const SizedBox(height: 8),
        Row(children: [
          for (var i = 0; i < n; i++)
            Expanded(
              child: Container(
                height: 10,
                margin: EdgeInsets.only(right: i == n - 1 ? 0 : 2),
                color: i < lit ? c.signal : c.chip,
              ),
            ),
        ]),
      ]),
    );
  }
}

/// Empty state: a hatched block with one plain sentence and, if there is one, the next action.
class EfEmpty extends StatelessWidget {
  const EfEmpty({super.key, required this.text, this.action});
  final String text;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return Container(
      decoration: BoxDecoration(border: Border.all(color: c.rule)),
      child: EfHatch(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 28, horizontal: 16),
          child: Column(children: [
            Container(
              color: c.paper,
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              child:
                  Text(text, style: EfType.ui(15, weight: 600, color: c.ink)),
            ),
            if (action != null) ...[const SizedBox(height: 14), action!],
          ]),
        ),
      ),
    );
  }
}

/// Toast: dark bar, yellow flag square on the left. Short, then gone.
class EfToast extends StatefulWidget {
  const EfToast(this.text, {super.key, this.onClose, this.onRead});
  final String text;
  final VoidCallback? onClose;
  final ValueChanged<bool>? onRead;
  @override
  State<EfToast> createState() => _EfToastState();
}

class _EfToastState extends State<EfToast> {
  final scroll = ScrollController();
  bool started = false, read = false;
  @override
  void initState() {
    super.initState();
    scroll.addListener(() {
      if (started &&
          scroll.hasClients &&
          scroll.position.maxScrollExtent > 0 &&
          scroll.offset >= scroll.position.maxScrollExtent - 1) {
        finish(true);
      }
    });
  }

  void finish(bool overflow) {
    if (read || !mounted) return;
    read = true;
    widget.onRead?.call(overflow);
  }

  Future<void> begin() async {
    if (started || !mounted || !scroll.hasClients) return;
    started = true;
    final distance = scroll.position.maxScrollExtent;
    if (distance <= 0) {
      finish(false);
      return;
    }
    // With reduced motion, allow manual horizontal scrolling and wait until
    // the end has been reached before starting the dismissal timer.
    if (MediaQuery.disableAnimationsOf(context)) return;
    await Future<void>.delayed(const Duration(milliseconds: 1000));
    if (!mounted || !scroll.hasClients) return;
    await scroll.animateTo(distance,
        duration: Duration(milliseconds: (distance / 38 * 1000).ceil()),
        curve: Curves.linear);
  }

  @override
  void dispose() {
    scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    WidgetsBinding.instance.addPostFrameCallback((_) => begin());
    final c = EfColors.of(context);
    return ColoredBox(
        color: c.panel,
        child: Row(children: [
          SizedBox(
              width: 5,
              height: double.infinity,
              child: ColoredBox(color: c.signal)),
          Expanded(
              child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  child: SingleChildScrollView(
                      controller: scroll,
                      scrollDirection: Axis.horizontal,
                      child: Text(widget.text,
                          softWrap: false,
                          maxLines: 1,
                          style: EfType.ui(13, weight: 600, color: c.ink))))),
          if (widget.onClose != null)
            SizedBox(
                width: 36,
                height: 36,
                child: IconButton(
                    tooltip: '关闭通知',
                    onPressed: widget.onClose,
                    style: IconButton.styleFrom(
                        shape: const RoundedRectangleBorder()),
                    icon: Icon(Icons.close, size: 16, color: c.ink))),
          const SizedBox(width: 8),
        ]));
  }
}

/// Bottom sheet frame: hatch band on top with the grabber, then eyebrow + title.
class EfSheet extends StatelessWidget {
  const EfSheet(
      {super.key,
      required this.en,
      required this.title,
      required this.children});
  final String en;
  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return DecoratedBox(
      decoration:
          ShapeDecoration(color: c.panel, shape: efCut(tl: Ef.cutPanel)),
      child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SizedBox(
              height: 18,
              child: EfHatch(
                  child: Center(
                      child: Container(width: 40, height: 4, color: c.ink))),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(Ef.pad, 12, Ef.pad, 8),
              child: EfPair(en, title, size: 20),
            ),
            ...children,
            SizedBox(height: 12 + MediaQuery.of(context).padding.bottom),
          ]),
    );
  }
}

/// A plain action row inside a sheet or settings list.
class EfActionRow extends StatelessWidget {
  const EfActionRow(this.label,
      {super.key, this.meta, this.danger = false, this.onTap});
  final String label;
  final String? meta;
  final bool danger;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return Semantics(
      button: true,
      child: GestureDetector(
        onTap: onTap,
        behavior: HitTestBehavior.opaque,
        child: Container(
          constraints: const BoxConstraints(minHeight: Ef.touch + 4),
          padding: const EdgeInsets.symmetric(horizontal: Ef.pad),
          decoration:
              BoxDecoration(border: Border(top: BorderSide(color: c.rule))),
          child: Row(children: [
            Expanded(
                child: Text(label,
                    style: EfType.ui(16,
                        weight: 600, color: danger ? c.danger : c.ink))),
            if (meta != null) Text(meta!, style: EfType.field(c.ink2)),
            const SizedBox(width: 8),
            Text('›', style: EfType.ui(18, color: c.ink2)),
          ]),
        ),
      ),
    );
  }
}

/// Section heading inside a long text: hatch band behind a bold title.
class EfBarTitle extends StatelessWidget {
  const EfBarTitle(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    return Stack(children: [
      Positioned(
          left: 0,
          right: 0,
          top: 6,
          bottom: 6,
          child: EfHatch(child: const SizedBox.expand())),
      Container(
        color: c.paper,
        margin: const EdgeInsets.only(right: 40),
        padding: const EdgeInsets.only(right: 10),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Container(width: Ef.traceBar, height: 22, color: c.trace),
          const SizedBox(width: 10),
          Flexible(child: Text(text, style: EfType.h2(c.ink))),
        ]),
      ),
    ]);
  }
}

/// Opens [EfSheet] content as a real modal bottom sheet: pushed up in 360ms
/// with the mech curve, closed in 240ms, scrim fades in 200ms, no bounce.
/// Reduced motion: it simply appears and goes.
Future<T?> showEfSheet<T>(BuildContext context, WidgetBuilder builder) {
  final c = EfColors.of(context);
  final still = MediaQuery.of(context).disableAnimations;
  return Navigator.of(context).push<T>(PageRouteBuilder<T>(
    opaque: false,
    barrierDismissible: true,
    barrierLabel: '关闭',
    barrierColor: c.scrim,
    transitionDuration: still ? Duration.zero : Ef.sheetIn,
    reverseTransitionDuration: still ? Duration.zero : Ef.sheetOut,
    pageBuilder: (context, _, __) =>
        Align(alignment: Alignment.bottomCenter, child: builder(context)),
    transitionsBuilder: (context, animation, _, child) => SlideTransition(
      position: Tween(begin: const Offset(0, 1), end: Offset.zero).animate(
          CurvedAnimation(
              parent: animation,
              curve: Ef.mech,
              reverseCurve: Ef.mech.flipped)),
      child: child,
    ),
  ));
}

/// Shared modal route; keeps keyboard focus in the dialog and supports Escape.
Future<T?> showEfDialog<T>({
  required BuildContext context,
  required WidgetBuilder builder,
  bool barrierDismissible = true,
}) =>
    Navigator.of(context, rootNavigator: true).push<T>(efDialogRoute<T>(
        context: context,
        builder: builder,
        barrierDismissible: barrierDismissible));

/// Also exposes the route for status dialogs that are removed after async work.
RawDialogRoute<T> efDialogRoute<T>({
  required BuildContext context,
  required WidgetBuilder builder,
  bool barrierDismissible = true,
}) {
  final c = EfColors.of(context);
  final still = MediaQuery.disableAnimationsOf(context);
  return _EfDialogRoute<T>(
    barrierDismissible: barrierDismissible,
    barrierLabel: MaterialLocalizations.of(context).modalBarrierDismissLabel,
    barrierColor: c.scrim,
    transitionDuration: still ? Duration.zero : Ef.dialogIn,
    pageBuilder: (dialogContext, _, __) =>
        InheritedTheme.captureAll(context, builder(dialogContext)),
    transitionBuilder: (context, animation, _, child) =>
        FadeTransition(opacity: animation, child: child),
  );
}

class _EfDialogRoute<T> extends RawDialogRoute<T> {
  _EfDialogRoute(
      {required super.pageBuilder,
      required super.barrierDismissible,
      required super.barrierLabel,
      required super.barrierColor,
      required super.transitionDuration,
      required super.transitionBuilder})
      : super(traversalEdgeBehavior: TraversalEdgeBehavior.closedLoop);
  @override
  Duration get reverseTransitionDuration =>
      transitionDuration == Duration.zero ? Duration.zero : Ef.dialogOut;
}

/// Compact desktop dialog, following the same frame in both themes.
class EfDialog extends StatelessWidget {
  const EfDialog({
    super.key,
    required this.title,
    required this.content,
    this.actions = const [],
    this.eyebrow = 'DIALOG',
    this.width = 520,
    this.scrollContent = true,
  });
  final Widget title, content;
  final List<Widget> actions;
  final String eyebrow;
  final double width;
  final bool scrollContent;

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    final frame = Container(
      key: const ValueKey('ef.dialog.frame'),
      decoration: ShapeDecoration(
        color: c.panel,
        shape: efCut(br: 20, side: BorderSide(color: c.rule)),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Align(
            alignment: Alignment.topLeft,
            child: Container(width: 64, height: 4, color: c.ink)),
        Flexible(
            child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 22, 24, 24),
          child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (title is! EfPair) ...[
                  EfEyebrow(eyebrow, slash: true),
                  const SizedBox(height: 8),
                ],
                DefaultTextStyle(
                    style:
                        EfType.ui(22, weight: 700, color: c.ink, height: 1.35),
                    child: title),
                const SizedBox(height: 20),
                Flexible(
                    child: scrollContent
                        ? SingleChildScrollView(
                            child: DefaultTextStyle(
                                style: EfType.ui(13, color: c.ink, height: 1.7),
                                child: content))
                        : DefaultTextStyle(
                            style: EfType.ui(13, color: c.ink, height: 1.7),
                            child: content)),
                if (actions.isNotEmpty) ...[
                  const SizedBox(height: 24),
                  Wrap(
                      alignment: WrapAlignment.end,
                      spacing: 10,
                      runSpacing: 10,
                      children: [
                        for (final action in actions)
                          _DialogAction(child: action)
                      ]),
                ],
              ]),
        )),
      ]),
    );
    final animation = ModalRoute.of(context)?.animation;
    return Dialog(
      elevation: 0,
      backgroundColor: Colors.transparent,
      surfaceTintColor: Colors.transparent,
      shadowColor: Colors.transparent,
      insetPadding: const EdgeInsets.symmetric(horizontal: 28, vertical: 24),
      shape: const RoundedRectangleBorder(),
      child: SizedBox(
          width: width,
          child: Theme(
              data: Theme.of(context).copyWith(
                  inputDecorationTheme: InputDecorationTheme(
                isDense: true,
                filled: true,
                fillColor: c.paper,
                labelStyle: EfType.ui(12, color: c.ink2),
                hintStyle: EfType.ui(12, color: c.ink2),
                contentPadding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
                border: OutlineInputBorder(
                    borderRadius: BorderRadius.zero,
                    borderSide: BorderSide(color: c.rule)),
                enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.zero,
                    borderSide: BorderSide(color: c.rule)),
                focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.zero,
                    borderSide: BorderSide(color: c.ink, width: 2)),
              )),
              child: animation == null
                  ? frame
                  : AnimatedBuilder(
                      animation: animation,
                      child: frame,
                      builder: (context, child) => ClipRect(
                          clipper:
                              _DialogReveal(Ef.mech.transform(animation.value)),
                          child: child),
                    ))),
    );
  }
}

class _DialogReveal extends CustomClipper<Rect> {
  const _DialogReveal(this.progress);
  final double progress;
  @override
  Rect getClip(Size size) =>
      Rect.fromLTWH(0, 0, size.width, size.height * progress);
  @override
  bool shouldReclip(_DialogReveal oldClipper) =>
      oldClipper.progress != progress;
}

class _DialogAction extends StatefulWidget {
  const _DialogAction({required this.child});
  final Widget child;
  @override
  State<_DialogAction> createState() => _DialogActionState();
}

class _DialogActionState extends State<_DialogAction> {
  bool focused = false;
  @override
  Widget build(BuildContext context) {
    final button = widget.child;
    if (button is! EfButton) return button;
    return FocusableActionDetector(
      enabled: button.onPressed != null,
      mouseCursor: SystemMouseCursors.click,
      onShowFocusHighlight: (value) => setState(() => focused = value),
      shortcuts: const {
        SingleActivator(LogicalKeyboardKey.enter): ActivateIntent(),
        SingleActivator(LogicalKeyboardKey.space): ActivateIntent(),
      },
      actions: {
        ActivateIntent: CallbackAction<ActivateIntent>(onInvoke: (_) {
          button.onPressed?.call();
          return null;
        })
      },
      child: DecoratedBox(
        position: DecorationPosition.foreground,
        decoration: ShapeDecoration(
            shape: efCut(
                br: Ef.cutButton,
                side: BorderSide(
                    width: 2,
                    color: focused
                        ? EfColors.of(context).ink
                        : Colors.transparent))),
        child: button,
      ),
    );
  }
}
