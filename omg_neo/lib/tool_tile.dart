import 'package:flutter/material.dart';
import 'ef/tokens.dart';
import 'ef/marks.dart';

class ToolTile extends StatefulWidget {
  const ToolTile(
      {super.key,
      required this.number,
      required this.english,
      required this.title,
      required this.detail,
      required this.icon,
      required this.onTap});
  final String number, english, title, detail;
  final IconData icon;
  final VoidCallback onTap;
  @override
  State<ToolTile> createState() => _ToolTileState();
}

class _ToolTileState extends State<ToolTile> {
  bool hover = false, down = false;
  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context), active = hover || down;
    final ink = active ? c.onSignal : c.ink,
        secondary = active ? c.onSignal : c.ink2;
    return Semantics(
        button: true,
        label: widget.title,
        child: Material(
            color: active ? c.signal : c.panel,
            shape: efCut(br: 22),
            clipBehavior: Clip.antiAlias,
            child: InkWell(
                onTap: widget.onTap,
                onHover: (v) => setState(() => hover = v),
                onHighlightChanged: (v) => setState(() => down = v),
                hoverColor: Colors.transparent,
                highlightColor: Colors.transparent,
                child: Padding(
                    padding: const EdgeInsets.all(22),
                    child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(children: [
                            Text(widget.number,
                                style: EfType.ui(27,
                                    weight: 600, color: secondary)),
                            const Spacer(),
                            Icon(widget.icon, color: ink, size: 29)
                          ]),
                          const Spacer(),
                          Text('// ${widget.english}',
                              style: EfType.ui(10,
                                  weight: 600, color: secondary, spacing: .14)),
                          const SizedBox(height: 3),
                          Text(widget.title,
                              style: EfType.ui(22, weight: 700, color: ink)),
                          const SizedBox(height: 10),
                          Text(widget.detail,
                              style:
                                  EfType.ui(12, color: secondary, height: 1.7)),
                          const SizedBox(height: 12),
                          Align(
                              alignment: Alignment.centerRight,
                              child:
                                  Icon(Icons.north_east, size: 19, color: ink)),
                        ])))));
  }
}
