import 'package:flutter/material.dart';
import 'ef/marks.dart';
import 'ef/tokens.dart';

class ResourceRootMenu extends StatelessWidget {
  const ResourceRootMenu({
    super.key,
    required this.folders,
    required this.hasDefault,
    required this.selected,
    required this.onSelected,
  });

  final List<String> folders;
  final bool hasDefault;
  final String? selected;
  final ValueChanged<String?>? onSelected;

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
              onPressed: onSelected == null ? null : change,
              child:
                  Text(label, maxLines: 1, overflow: TextOverflow.ellipsis)));

  @override
  Widget build(BuildContext context) => MenuAnchor(
      style: resourceMenuStyle(context).copyWith(
        maximumSize: const WidgetStatePropertyAll(Size(440, 340)),
      ),
      menuChildren: [
        if (hasDefault)
          settingItem('root-default', 'GIMI / Mods', selected == null,
              () => onSelected?.call(null)),
        for (final path in folders)
          Tooltip(
              message: path,
              child: settingItem('root-$path', path, selected == path,
                  () => onSelected?.call(path))),
      ],
      builder: (_, menu, __) => SizedBox(
          width: 28,
          height: 28,
          child: IconButton(
              tooltip: '切换资源目录',
              padding: EdgeInsets.zero,
              icon: const Icon(Icons.swap_horiz, size: 18),
              onPressed: onSelected == null
                  ? null
                  : () {
                      if (menu.isOpen) {
                        menu.close();
                      } else {
                        menu.open();
                      }
                    })));
}

MenuStyle resourceMenuStyle(BuildContext context) => MenuStyle(
      backgroundColor: WidgetStatePropertyAll(EfColors.of(context).panel),
      surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
      elevation: const WidgetStatePropertyAll(0),
      shape: WidgetStatePropertyAll(
          efCut(br: 8, side: BorderSide(color: EfColors.of(context).rule))),
      padding: const WidgetStatePropertyAll(EdgeInsets.all(4)),
    );
