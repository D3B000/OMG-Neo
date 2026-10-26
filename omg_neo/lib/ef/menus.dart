import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'marks.dart';
import 'tokens.dart';

ButtonStyle _itemStyle(BuildContext context, {bool selected = false}) {
  final c = EfColors.of(context);
  bool active(Set<WidgetState> states) =>
      selected ||
      states.contains(WidgetState.hovered) ||
      states.contains(WidgetState.focused);
  return ButtonStyle(
    minimumSize: const WidgetStatePropertyAll(Size(0, 36)),
    padding: const WidgetStatePropertyAll(EdgeInsets.symmetric(horizontal: 12)),
    shape: WidgetStatePropertyAll(efCut(br: 6)),
    textStyle: WidgetStatePropertyAll(EfType.ui(12, weight: 600)),
    backgroundColor: WidgetStateProperty.resolveWith(
        (s) => active(s) ? c.signal : Colors.transparent),
    foregroundColor:
        WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.disabled)
            ? c.ink2
            : active(s)
                ? c.onSignal
                : c.ink),
    iconColor:
        WidgetStateProperty.resolveWith((s) => active(s) ? c.onSignal : c.ink),
    overlayColor: const WidgetStatePropertyAll(Colors.transparent),
    animationDuration: Ef.d(context, Ef.press),
    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
  );
}

/// A compact selector with native Flutter menu navigation and dismissal.
class EfDropdown extends StatefulWidget {
  const EfDropdown(
      {super.key,
      required this.value,
      required this.items,
      required this.onChanged});
  final String value;
  final List<String> items;
  final ValueChanged<String>? onChanged;
  @override
  State<EfDropdown> createState() => _EfDropdownState();
}

class _EfDropdownState extends State<EfDropdown> {
  final focus = FocusNode();
  final controller = MenuController();
  bool keyboardInteraction = false;
  @override
  void initState() {
    super.initState();
    HardwareKeyboard.instance.addHandler(observeKey);
  }

  bool observeKey(KeyEvent event) {
    if (event is KeyDownEvent && (focus.hasFocus || controller.isOpen)) {
      keyboardInteraction = true;
    }
    return false;
  }

  void clearPointerFocus() {
    final keys = HardwareKeyboard.instance.logicalKeysPressed;
    if (keys.contains(LogicalKeyboardKey.escape) ||
        keys.contains(LogicalKeyboardKey.enter)) {
      keyboardInteraction = true;
    }
    // MenuAnchor restores its trigger after closing. Pointer use should leave
    // the page unfocused; keyboard use keeps the trigger for further navigation.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && !keyboardInteraction && focus.hasFocus) focus.unfocus();
    });
  }

  @override
  void dispose() {
    HardwareKeyboard.instance.removeHandler(observeKey);
    focus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = EfColors.of(context);
    final value =
        widget.items.contains(widget.value) ? widget.value : widget.items.first;
    return TapRegion(
        groupId: controller,
        onTapOutside: (_) {
          keyboardInteraction = false;
          final activeContext = FocusManager.instance.primaryFocus?.context;
          final menuFocused = activeContext != null &&
              MenuController.maybeOf(activeContext) == controller;
          if (controller.isOpen || menuFocused) {
            FocusScope.of(context).unfocus();
          } else {
            focus.unfocus();
          }
          // Closing the overlay can restore focus to its trigger after this tap.
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted && focus.hasFocus) focus.unfocus();
          });
        },
        child: LayoutBuilder(
            builder: (context, constraints) => MenuAnchor(
                  controller: controller,
                  childFocusNode: focus,
                  onClose: clearPointerFocus,
                  consumeOutsideTap: true,
                  crossAxisUnconstrained: false,
                  clipBehavior: Clip.antiAlias,
                  style: MenuStyle(
                    backgroundColor: WidgetStatePropertyAll(c.panel),
                    surfaceTintColor:
                        const WidgetStatePropertyAll(Colors.transparent),
                    shadowColor:
                        const WidgetStatePropertyAll(Colors.transparent),
                    elevation: const WidgetStatePropertyAll(0),
                    padding: const WidgetStatePropertyAll(EdgeInsets.all(4)),
                    minimumSize: WidgetStatePropertyAll(
                        Size(constraints.maxWidth.clamp(160, 360), 0)),
                    maximumSize: WidgetStatePropertyAll(
                        Size(constraints.maxWidth.clamp(160, 360), 300)),
                    side: WidgetStatePropertyAll(BorderSide(color: c.rule)),
                    shape: WidgetStatePropertyAll(efCut(br: 12)),
                  ),
                  menuChildren: [
                    for (final item in widget.items)
                      Listener(
                          onPointerDown: (_) => keyboardInteraction = false,
                          child: Semantics(
                              selected: item == value,
                              child: MenuItemButton(
                                autofocus: item == value,
                                style: _itemStyle(context,
                                    selected: item == value),
                                leadingIcon: SizedBox(
                                    width: 16,
                                    child: item == value
                                        ? const Icon(Icons.check, size: 14)
                                        : null),
                                onPressed: widget.onChanged == null
                                    ? null
                                    : () => widget.onChanged!(item),
                                child: Text(item.isEmpty ? '未选择项目' : item,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis),
                              ))),
                  ],
                  builder: (context, controller, child) => Listener(
                      onPointerDown: (_) => keyboardInteraction = false,
                      child: TextButton(
                        focusNode: focus,
                        onPressed: widget.onChanged == null
                            ? null
                            : () => controller.isOpen
                                ? controller.close()
                                : controller.open(),
                        style: ButtonStyle(
                          shape: WidgetStatePropertyAll(efCut(br: 6)),
                          padding: const WidgetStatePropertyAll(
                              EdgeInsets.symmetric(horizontal: 8)),
                          minimumSize:
                              const WidgetStatePropertyAll(Size(0, 28)),
                          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                          backgroundColor: WidgetStatePropertyAll(c.chip),
                          foregroundColor: WidgetStatePropertyAll(c.ink),
                          side: WidgetStateProperty.resolveWith((s) =>
                              BorderSide(
                                  color: s.contains(WidgetState.focused)
                                      ? c.ink
                                      : Colors.transparent)),
                        ),
                        child: Row(children: [
                          Expanded(
                              child: Text(value.isEmpty ? '未选择项目' : value,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: EfType.ui(11, color: c.ink))),
                          Icon(
                              controller.isOpen
                                  ? Icons.expand_less
                                  : Icons.expand_more,
                              size: 16)
                        ]),
                      )),
                )));
  }
}

/// Uses EditableText's actual available actions, preserving clipboard behavior.
Widget efTextContextMenu(BuildContext context, EditableTextState state) =>
    _EfTextContextMenu(
        anchor: state.contextMenuAnchors.primaryAnchor,
        items: state.contextMenuButtonItems);

class _EfTextContextMenu extends StatelessWidget {
  const _EfTextContextMenu({required this.anchor, required this.items});
  final Offset anchor;
  final List<ContextMenuButtonItem> items;

  SingleActivator? accelerator(ContextMenuButtonItem item) =>
      switch (item.type) {
        ContextMenuButtonType.cut =>
          const SingleActivator(LogicalKeyboardKey.keyX, control: true),
        ContextMenuButtonType.copy =>
          const SingleActivator(LogicalKeyboardKey.keyC, control: true),
        ContextMenuButtonType.paste =>
          const SingleActivator(LogicalKeyboardKey.keyV, control: true),
        ContextMenuButtonType.selectAll =>
          const SingleActivator(LogicalKeyboardKey.keyA, control: true),
        _ => null,
      };

  String label(BuildContext context, ContextMenuButtonItem item) =>
      item.label ??
      switch (item.type) {
        ContextMenuButtonType.cut => '剪切',
        ContextMenuButtonType.copy => '复制',
        ContextMenuButtonType.paste => '粘贴',
        ContextMenuButtonType.selectAll => '全选',
        ContextMenuButtonType.delete => '删除',
        _ => AdaptiveTextSelectionToolbar.getButtonLabel(context, item),
      };
  String shortcut(ContextMenuButtonItem item) => switch (item.type) {
        ContextMenuButtonType.cut => 'Ctrl+X',
        ContextMenuButtonType.copy => 'Ctrl+C',
        ContextMenuButtonType.paste => 'Ctrl+V',
        ContextMenuButtonType.selectAll => 'Ctrl+A',
        _ => '',
      };

  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) return const SizedBox.shrink();
    final c = EfColors.of(context);
    return Padding(
      padding: const EdgeInsets.all(8),
      child: CustomSingleChildLayout(
        delegate: DesktopTextSelectionToolbarLayoutDelegate(
            anchor: anchor - const Offset(8, 8)),
        child: SizedBox(
            width: 220,
            child: Material(
              key: const ValueKey('ef.context-menu'),
              color: c.panel,
              elevation: 0,
              surfaceTintColor: Colors.transparent,
              shape: efCut(br: 12, side: BorderSide(color: c.rule)),
              clipBehavior: Clip.antiAlias,
              child: Shortcuts(
                  shortcuts: {
                    const SingleActivator(LogicalKeyboardKey.arrowDown):
                        const NextFocusIntent(),
                    const SingleActivator(LogicalKeyboardKey.arrowUp):
                        const PreviousFocusIntent(),
                    const SingleActivator(LogicalKeyboardKey.escape):
                        const DismissIntent(),
                    for (final item in items)
                      if (accelerator(item) != null)
                        accelerator(item)!: _TextMenuIntent(item.onPressed),
                  },
                  child: Actions(
                      actions: {
                        _TextMenuIntent:
                            CallbackAction<_TextMenuIntent>(onInvoke: (intent) {
                          intent.callback?.call();
                          return null;
                        }),
                        DismissIntent:
                            CallbackAction<DismissIntent>(onInvoke: (_) {
                          ContextMenuController.removeAny();
                          return null;
                        }),
                      },
                      child: FocusScope(
                        autofocus: true,
                        child: Padding(
                            padding: const EdgeInsets.all(4),
                            child: Column(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  for (final item in items)
                                    MenuItemButton(
                                      style: _itemStyle(context),
                                      onPressed: item.onPressed,
                                      child: SizedBox(
                                          width: 188,
                                          child: Row(children: [
                                            Expanded(
                                                child:
                                                    Text(label(context, item))),
                                            Text(shortcut(item),
                                                style: const TextStyle(
                                                    fontSize: 10)),
                                          ])),
                                    ),
                                ])),
                      ))),
            )),
      ),
    );
  }
}

class _TextMenuIntent extends Intent {
  const _TextMenuIntent(this.callback);
  final VoidCallback? callback;
}
