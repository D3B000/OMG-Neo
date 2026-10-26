# OMG-Neo 使用说明书

> 版本：v0.0.1 ｜ 平台：Windows 10/11 x64 ｜ 更新日期：2026-10-23

---

## 1. 项目简介

OMG-Neo 是一个面向 3DMigoto 系模组加载器（GIMI 及其 ORFix / TexFx 组件）的 Windows 桌面管理工具，覆盖 **GIMI 更新、模组浏览与启停、游戏启动与注入、便捷构建、原神服务器切换** 的完整流程。

应用采用前后端分离的分体服务（split-service）架构：

| 部分 | 形态 | 职责 |
| --- | --- | --- |
| 前端 | Flutter 桌面程序 `omg_neo.exe`（960×540 逻辑像素） | 全部界面：首页 / 浏览 / 工具 / 设置 |
| 后端 | Python 常驻服务 `omg_backend.exe`（stdio JSON Lines 协议） | 配置、任务调度、GIMI 更新、资源索引、构建与仪式 |
| 注入端 | `omg_injector.exe`（按需启动的独立进程） | 仅在点击"启动游戏"时执行一次 DLL 注入任务 |

前端启动时自动拉起同目录 `backend/` 下的后端服务，二者通过标准输入输出管道通信；**不监听网络端口、不安装系统服务、不需要系统 Python**。

适用游戏：使用 GIMI 的 Windows 游戏（默认识别原神 `YuanShen.exe` / `GenshinImpact.exe`）。

---

## 2. 运行环境与获取

**环境要求**

- Windows 10 / 11，x64
- 对安装目录有写入权限（配置、缓存、日志写在程序旁的 `AppData/`）
- 无需安装 Python、Flutter 或任何开发工具链

**获取与运行**

1. 解压整个发布 ZIP 到任意有写入权限的目录（例如 `D:\Games\OMG-Neo`）。
2. 双击运行 `omg_neo.exe`。

> ⚠️ **必须完整保留整个目录**（`backend/`、`data/` 和所有 DLL），不能只复制 EXE 单独运行。

**目录结构（发布包）**

```text
OMG-Neo/
├── omg_neo.exe            # 主程序
├── *.dll / data/          # Flutter 运行时
└── backend/
    ├── omg_backend.exe    # 常驻后端服务
    ├── omg_injector.exe   # 注入端（仅启动游戏时运行）
    └── _internal/         # Python 运行时与 loader / ritual 二进制
AppData/                   # 首次运行后生成：配置、缓存、日志
```

开发机上也可用 `omg_neo/launch.ps1`（或 `launch.ps1 -Resources` 直接打开浏览页）启动已构建的发布版。

---

## 3. 快速开始（首次配置）

1. 首次启动后进入底部导航的 **设置 → 路径**。
2. **游戏目录**：选择游戏主目录（含 `YuanShen.exe` / `GenshinImpact.exe` 的文件夹）。
3. **GIMI 目录**：选择 GIMI 模组加载器所在目录（其中必须包含 `d3dx.ini`）。
4. 如原先使用 OMGLite，可在设置中 **导入旧 OMGLite 配置**（只读取源文件，不会修改旧配置）。
5. 返回 **首页**：应用会自动读取 GIMI / ORFix / TexFx 的实际版本；缺失时显示"未检测"。

设置采用**改动即生效**的即时保存，没有保存按钮；每项修改去抖后写入 `AppData/config.json` 并同步备份。

---

## 4. 页面使用说明

底部导航四个页面：**首页 / 浏览 / 工具 / 设置**。窗口标题栏支持拖动、最小化、关闭；顶部中央显示通知横幅（最多 3 条，可手动关闭）。

### 4.1 首页

- 页面中央为 OMG NEO 字标与 **启动游戏** 按钮；下方依次显示 GIMI / ORFix / TexFx 版本块。
- 右上角为 **检查更新**：获取 GIMI 远端 Release 信息，发现新版本后变为 **更新**。
- 更新过程显示 24 格进度条，支持**取消**（取消会等待回退收尾，不会留下半套文件）；更新使用白名单保护自定义文件（白名单在设置 → GIMI 维护）。
- **启动游戏**：依次执行路径 / 进程 / DLL 预检 → 同步 Hunting/Warning 到 `d3dx.ini` → 调用注入端 → 监视游戏。启动任务进行中不可取消；任务成功后游戏仍在运行时，按钮不会重复触发，游戏退出后才恢复。
- 游戏运行期间，GIMI 更新、DLL 替换等操作会被拒绝并提示先退出游戏。

### 4.2 浏览（资源）

以设置中的 **GIMI/Mods** 为根目录的文件夹浏览器：

- **布局**：面包屑导航（支持逐级回跳与展开子目录）、页头居中搜索、三列卡片（文件夹 108px / 模组 84×84 缩略图）。
- **搜索**：可选"当前目录 / 全局"；全局搜索递归遍历 Mods，按名称匹配，自动跳过循环链接。
- **启停**：点击模组卡片切换启用 / 停用（底层为 `DISABLED` 前缀重命名，设置中的显示同步刷新）。
- **切换键**：点击"切换键"按钮查看该模组的按键明细预览。
- **右键菜单**：在资源管理器打开、文件夹 ↔ 模组卡片转换、缩略图遮罩开关、配置文件子菜单。
- **拖放移动**：可将本机文件 / 目录拖入当前目录；操作先完整复制到暂存区、校验后提交，任何一步失败都会回退，不覆盖已有文件。
- **写回**：将切换键写回整个 Mods 根（读取 `GIMI/d3dx_user.ini`），写回前自动备份全部候选 INI 到 `AppData/resource-backups/时间-ID`，并逐文件报告成功 / 跳过 / 失败。
- 支持 junction / 符号链接指向外置存储；游戏内需按原有方式重新加载模组。

### 4.3 工具

工具页包含三个入口：

**① 便捷构建控制台**（详见第 5 节）
左侧四张操作卡片（D3D11 / 构建 / 文件优化 / 自动化）纵向滚动，右侧固定终端实时显示输出，支持**导出日志**（写入 `AppData/logs/build-时间戳.log`）与清空。

**② 便捷关联（JUNCTION / INCLUDE）**

- **JUNCTION**：把资源目录链接为符号目录（默认目标为设置中的 `GIMI\Mods`），可编辑符号名称、浏览原生目录；创建前检查本地磁盘、名称合法性与唯一性，拒绝递归目录关系。
- **INCLUDE**：在与 GIMI 同级的已有 Mods 中新建或追加 `modFolder.ini`，写入 `include_recursive` 与 `exclude_recursive = DISABLED*`，已有配置保留追加，相同路径不重复添加。

**③ 服务器切换**（详见第 6 节）

### 4.4 设置

| 分页 | 内容 |
| --- | --- |
| 路径 | 游戏 / GIMI 目录输入与浏览、导入 OMGLite 旧配置 |
| GIMI | Hunting 0/1/2、Warning 0/1（去抖写入 `d3dx.ini`）、启动检查更新开关、更新白名单（添加文件 / 文件夹 / 删除，保存为 GIMI 内相对路径） |
| 启动 | 启动方式 Native / Shell / Manual、自定义启动命令、注入方式 Hook / Inject / Bypass、额外 DLL 多行输入 |
| 缓存 | 显示缓存占用并支持清理（只清理 Neo 数据根的 `cache/`，不碰 GIMI、Mods 或构建产物；拒绝目录中的链接） |
| OMG | 深色 / 浅色外观、HEX 强调色（默认 `#39C5BB`，全界面即时生效）、UI 调整工具入口 |

**UI 调整工具**：点击标题栏框选图标或按 **F8**，可框选当前页面组件并添加批注，导出截图 + 标注图 + JSON + 文字说明到 `ui-reviews/`，用于把界面问题带回开发流程。

---

## 5. 便捷构建控制台

四张卡片对应一条完整流水线，全部任务在后端串行执行，切页不丢失进度：

1. **D3D11**：选择 GitHub 源码或已构建文件两种来源；源码模式可刷新远端版本列表、下载并解压；已构建模式下载蓝奏云批次 DLL（无需本机 MSBuild）。
2. **构建**：显示构建环境状态（可重新检测）、选择工程、执行编译或"优化构建"；已构建文件模式以下载代替本地表单。
3. **文件优化（仪式）**：神秘仪式开关与目标文件路径预览，可选 包装 / 涂装(py) / 涂装(rs)，依赖随包的 `ritual_bundle.pyd` / Cython / UPX / Rust DLL，缺少组件时对应按钮自动禁用。
4. **自动化**：串联"构建 → 仪式 → 复制到 GIMI"，任一步失败或取消即停止后续；复制前检测游戏进程，运行中拒绝替换，原 DLL 自动备份到 `AppData/dll-backups`。
5. **清理**：扫描源码工程、已构建文件、构建产物、仪式产物、输入暂存与临时文件，显示真实占用；勾选确认后执行，仅接受后端生成的扫描项，不会触及 GIMI / Mods / 配置。

产物登记在 `AppData/build-products.json`（来源、路径、SHA-256、时间），复制前校验哈希，拒绝未登记或已变化的旧 DLL。

---

## 6. 原神服务器切换（国服 / 国际服 / B服）

入口：**工具 → 服务器切换**，游戏路径沿用设置中的游戏目录，资源包放在 `AppData/server-switch`。

**准备替换包**（推荐使用原切换器制作）：

1. 将"原神国际服务器切换器.exe"放入国服游戏目录，点击"备份国服"；再放入国际服目录点击"备份外服"。
2. 合并两侧备份（保留国服 / 国际服目录与 `版本号.ini` 双边版本信息），命名为"替换包"。
3. 放入 `AppData/server-switch/`。B 服需额外包含 `PCGameSDK.dll` 与登录窗口组件。

**使用流程**：备份预览 → 制作备份（可选）→ 预览切换 → 应用 / 恢复。切换前游戏与启动器必须退出；每次实际切换先备份受影响文件到 `backups/<事务编号>`，普通异常自动回滚；被强制结束时可"恢复未完成的切换"。

> 注意：切换不迁移账号、角色或存档；不联网验证版本；替换包与游戏目录中的链接会被拒绝。自定义 `cn/global/bilibili` 目录格式（含 `manifest.json`）仍受支持，详见 `omg_neo/docs/server-switch.md`。

---

## 7. 数据目录说明

所有用户数据保存在程序旁的 `AppData/`（便携模式，不写 `%LOCALAPPDATA%`）：

| 内容 | 位置 |
| --- | --- |
| 应用设置 / 备份 | `config.json`、`config.json.bak` |
| 构建页选项 | `build-options.json` |
| 产物登记（来源 / 哈希） | `build-products.json` |
| 资源卡片偏好 | `resource-cards.json` |
| 构建工作区（project / artifact / output / input / temp） | `build-work/` |
| 资源索引缓存 | `cache/` |
| 后端日志 / 导出日志 | `log/`、`logs/` |
| 写回 / DLL 备份 | `resource-backups/`、`dll-backups/` |
| 服务器切换资源与事务 | `server-switch/` |
| 通用临时文件 | `temp/` |

再次分发软件时请使用原始 ZIP，不要把使用后生成的 `AppData` 一起分发。

---

## 8. 常见问题（FAQ）

| 现象 | 原因与处理 |
| --- | --- |
| 启动提示后端被占用 | 同一数据根已有后端在运行；请检查是否重复启动了应用，或残留的 `omg_backend.exe` 进程 |
| "请先配置包含 d3dx.ini 的 GIMI 目录" | 设置 → 路径 中 GIMI 目录缺失或指向错误 |
| 更新 / 复制 DLL 时提示游戏正在运行 | 先完全退出游戏与米哈游启动器再重试 |
| Hunting / Warning 修改后游戏内不生效 | 需在游戏内重新加载或下次启动；INI 同步结果会以通知告知 |
| 版本显示"未检测" | GIMI 目录未配置或 `d3dx.ini` 中无版本信息，属正常提示，非 0.0.0 |
| 缓存清理被拒绝 | 缓存目录内检测到链接 / 联接点，已中止清理以保护数据 |
| 关闭应用时出现等待弹窗 | 存在构建 / 仪式 / 注入等不可取消阶段，应用正在等待安全收尾；该过程不会终止已启动的游戏 |

---

## 9. 开发者指南

**源码运行（前端）**

```powershell
cd omg_neo
flutter pub get
flutter run -d windows            # 启动主界面
flutter run -d windows -- --resources   # 启动并选中浏览页
```

未找到随包后端时，客户端会从项目父目录查找 `backend/main.py`；可用 `OMGNEO_PYTHON` 指定开发解释器。

**构建完整发布包**

```powershell
cd omg_neo
.\build_release.ps1 -Flutter F:\flutter\bin\flutter.bat -Python F:\Python\Python311\python.exe
# Debug 配置（保留 UI 调整工具）：
.\build_release.ps1 -Configuration Debug -Flutter ... -Python ...
.\launch.ps1
```

`build_release.ps1` 会依次执行 Flutter Release 构建与 `backend\build.ps1`（PyInstaller onedir 冻结后端，并生成 `omg_injector.exe`），输出到 `dist/OMG-Neo/`，发布前自动检查不夹带个人配置与日志。

**测试**

```powershell
# 后端集成测试（工作区根目录）
python -m unittest discover -s OMG-Neo/backend/tests -v

# 前端
cd omg_neo ; flutter analyze ; flutter test

# 发布包 Dart → 冻结后端通信验证
dart tools/smoke_backend.dart dist/OMG-Neo/backend/omg_backend.exe
```

---

## 10. 注意事项

- 应用会修改游戏侧的 DLL 与 INI（更新 GIMI、复制产物、写回切换键）；所有可回退操作均有自动备份，但建议在首次使用前自行备份游戏目录与 GIMI 目录。
- 服务器切换涉及游戏客户端文件替换，务必确认替换包版本与游戏版本一致，并提前退出游戏与启动器。
- 模组文件位于 GIMI/Mods，请通过应用内启停管理，不要直接重命名目录，以免索引与实际状态不一致。
- 本项目与游戏官方无关，未使用任何官方素材；模组内容来源于用户自备的 Mods 目录。

---

*详细设计文档见 `omg_neo/docs/`，后端进程模型见 `backend/PROCESS_MODEL.md`。*
