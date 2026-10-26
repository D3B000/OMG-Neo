# Neo 使用的 OMGLite 子集

此目录仅保留 OMG-Neo 服务端、独立注入端使用的业务源码和 loader 资源，
不是完整的旧版 OMGLite 桌面应用。工作区旁边的原始 OMGLite 不受此次清理影响。
原始 MIT 许可保留在 `LICENSE`。

## 2026-10-26 清理记录

以 `backend/*.py` 的全部模块为保守入口，递归解析绝对导入、相对导入、
包初始化文件及函数内部的延迟导入；再检查动态加载、打包配置、前端和测试引用。
清理前后，Neo 依赖的 30 个 OMGLite 模块完全一致。

删除了 12 个 Python 文件，共 229,831 字节、5,947 行（包含注释和空行）：

| 路径（相对于 `src/omg/`） | 原用途／删除依据 |
| --- | --- |
| `domain/media/`（3 个文件） | 启动器媒体提取工具；Neo 没有调用入口。 |
| `domain/modtools/`（3 个文件） | 旧模组优化、纹理缩放工具；Neo 没有调用入口。 |
| `domain/settings.py` | 旧 Qt 设置页面控制器；Neo 使用 Flutter 设置页面和 `backend/settings_store.py`。 |
| `core/config.py` | 旧配置管理器；Neo 使用自己的设置存储，旧配置导入也不依赖该模块。 |
| `core/idle_fade_fsm.py` | 旧窗口闲置渐隐状态机。 |
| `core/window_behavior.py` | 旧 Qt 窗口行为。 |
| `core/list_render.py` | 旧 Qt 列表渲染策略。 |
| `core/win32/__init__.py` | 未使用的空包。 |

同时删除无人读取的 `core/config.default.json` 和清理时存在的 Python 字节码缓存、空目录。
运行或测试后 Python 可能重新生成保留模块的缓存。

## 特别保留的依赖

- `mods_manager`、`gachabase`：Neo 资源浏览仍使用。
- `alchemy`、`build_env`、`source_prep`、`lanzou`：便捷构建及下载链路仍使用。
- `gimi_update`、`gimi_signals`、`download`、`updates`：更新链路及兼容导出仍使用。
- `instance_ipc`：`updates` 内部有条件导入，不能仅凭启动时没有加载就删除。
- `domain/launch`、`domain/inject`：独立注入端和服务端的进程检查仍使用；
  Neo 跳过注入校验不代表 `injection_probe` 没有导入依赖。
- loader EXE/DLL、`backend/vendor/ritual`：原生运行依赖。
  `ritual_loader` 的两个动态加载点加载的是原生 PYD，不是被删除的 Python 模块。

此次仅删除未使用文件，没有裁剪保留模块内部的兼容函数或改动业务流程。
这些源码原先多数未进入 PyInstaller 的依赖图，因此不承诺发布包或内存有明显下降。

## 验证与复查

在 OMG-Neo 根目录执行：

```powershell
python backend/validation/audit_lite_sources.py
python -m unittest discover -s backend/tests -p 'test_*.py'
```

审计清单保存在 `backend/validation/lite-audit-before.json` 和
`lite-audit-after.json`；脚本只生成报告，不执行删除。
静态审计不能替代原生运行验证；增加新的动态导入时需要人工复核。

本次验证结果：

- 源码后端测试：96 项通过。
- 全新 PyInstaller 服务端／注入端构建成功，已删除模块均未进入两个依赖图。
- 指定新构建服务端后重跑测试：96 项通过（使用源码故障夹具的测试仍在源码进程运行）。
- 新构建注入端在空配置下正常返回“未配置游戏目录”结果，保持请求令牌，未获取服务端锁。
- 未启动真实游戏或执行真实注入。

日志及运行结果位于 `backend/validation/lite-cleanup-*.log`、
`backend/validation/lite-cleanup-runtime.json`；验证构建位于
`backend/dist/lite-cleanup-20261026/omg_backend/`。
