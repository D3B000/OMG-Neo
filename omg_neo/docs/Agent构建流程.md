# OMG-Neo 构建流程：Agent 参考

核对日期：2026-10-26。本文件是执行参考，不是自动任务，也不授予运行真实游戏、注入、切服、删除旧版本或上传产物的额外权限。详细人工步骤见 [手动构建指南](手动构建指南.md)。

## 1. 入口和事实来源

| 文件 | 作用 |
| --- | --- |
| `omg_neo/build_release.ps1` | 完整包入口；支持 Debug/Release；隔离 Flutter 设置，构建并组装前后端 |
| `backend/build.ps1` | 调用正式 spec；向指定空目录复制完整冻结后端 |
| `backend/neo_hosts.spec` | 两份独立 Analysis/PYZ，单次 COLLECT 共享运行时；依赖冲突和注入端依赖检查 |
| `omg_neo/validation/verify_distribution_v001.py` | 洁净审计、冻结服务检查、README、ZIP、CRC、SHA-256、报告 |
| `backend/PROCESS_MODEL.md` | 常驻服务和一次性注入端行为 |
| `backend/PACKAGING.md` | 双入口打包及依赖裁剪依据 |
| `omg_neo/lib/review.dart` | UI 调整工具开关 |
| `omg_neo/lib/backend/neo_backend.dart` | 后端定位、便携数据目录、stdio 传输 |
| `omg_neo/windows/runner/main.cpp` | Windows runner 与当前渲染器设置 |

开始前读取适用的 AGENTS.md 和用户当前指令。本文与脚本不一致时，检查实际实现；不要用旧聊天记录替代当前脚本。

## 2. 输入与默认选择

- 构建模式：用户要求 Debug 或含 UI 工具时用 Debug；普通分发使用 Release。用户有明确要求时优先遵循。
- 包名：使用英文、数字、点、下划线或连字符组成的单目录名；包含版本、模式和时间戳。
- 根目录：默认 `omg_neo/dist/<本次批次>`，保留旧包；现有验证器只接受 dist 内的根目录。
- 工具路径：本机 Flutter `F:\flutter\bin\flutter.bat`，Dart `F:\flutter\bin\dart.bat`，Python `F:\Python\Python311\python.exe`。重新确认存在，不能当作所有机器的约定。
- 本地版本、时间和目标路径都应实际读取。`pubspec.yaml` 当前为 `0.0.1+1`，不是永远不变的默认。

## 3. 目录边界与串行约束

```text
OMG-RE/OMGLite/src/omg/                 ← 相邻业务源码及 loader 资源
OMG-RE/OMG-Neo/backend/                 ← Neo Python 入口及服务
OMG-RE/OMG-Neo/backend/vendor/ritual/    ← 原生仪式资源
OMG-RE/OMG-Neo/omg_neo/                 ← Flutter 源码及统一入口
```

不要同时在同一源码 checkout 中构建多个模式或多个包。即使 Debug/Release 的 runner 输出目录不同，仍共享：

- `windows/flutter/ephemeral`、`.dart_tool` 和插件生成文件；
- 后端 `build`、`dist/omg_backend` 及 PyInstaller 工作区；
- 某些验证脚本的固定输出文件。

遇到运行中的构建，等其完成或与使用者协调；不能删除 Flutter 锁或杀死所有 dart/python 进程。独立 checkout 仍需注意共同 SDK 的锁与任务范围。

不要批量清理 dist、AppData 或旧包。若确需递归移动或删除，先解析并校验绝对路径边界，确认授权。一般失败恢复直接选新包名即可。

## 4. 执行阶段

### A. 预检

1. 确认路径、模式、目标目录未存在；检查近期源码是否仍被其他工作修改。
2. 检查 Flutter、Python、Visual Studio C++/Windows SDK；记录实际工具版本。
3. 确认 krr.ico、Saira.ttf、OMGLite 模块、loader 和 vendor/ritual 存在。
4. 检查 Python 的 PyInstaller、QtCore 和运行依赖；项目未提供完整锁文件，不擅自全局升级依赖。
5. 缺少 Flutter 依赖时执行 pub get，保留 pubspec.lock；离线使用缓存需显式选择 --offline。
6. 记录源码身份：有 Git 时读取 revision/status；没有 Git 时明确说明，并记录关键输入哈希与构建开始/结束时间。

### B. 检查

从 `omg_neo` 目录运行：

```powershell
& $flutterExe analyze
if ($LASTEXITCODE -ne 0) { throw 'Flutter analyze failed' }
& $flutterExe test --dart-define=OMG_UI_REVIEW=true --no-pub
if ($LASTEXITCODE -ne 0) { throw 'Flutter tests failed' }
& $pythonExe -m unittest discover -s ..\backend\tests -p 'test_*.py'
if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed' }
```

Release 另跑隐藏入口的独立测试：

```powershell
& $flutterExe test test/distribution_ui_test.dart --dart-define=OMG_UI_REVIEW=false --no-pub
if ($LASTEXITCODE -ne 0) { throw 'Release distribution UI test failed' }
```

纯构建复现且同一源码已有可信检查结果时，可按任务范围复用；说明哪些是历史结果，哪些本次实际执行。不要照抄本文或旧报告中的测试数量当作本次结果。

### C. 完整构建

以下变量作为同一次构建的上下文保留，验包时不要再生成另一个时间戳：

```powershell
$ErrorActionPreference = 'Stop'
$appRoot = 'G:\ObjNotFound\Tool4game\Landfill\OMG-RE\OMG-Neo\omg_neo'
$flutterExe = 'F:\flutter\bin\flutter.bat'
$dartExe = 'F:\flutter\bin\dart.bat'
$pythonExe = 'F:\Python\Python311\python.exe'
$configuration = 'Debug'  # 按用户要求改为 Release
$modeLabel = $configuration.ToLowerInvariant()
$buildStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$packageName = "OMG-Neo-v0.0.1-$modeLabel-$buildStamp"
$destinationRoot = Join-Path $appRoot "dist\agent-$buildStamp"
$packageRoot = Join-Path $destinationRoot $packageName
Set-Location -LiteralPath $appRoot
if (Test-Path -LiteralPath $packageRoot) { throw 'Target already exists' }

& .\build_release.ps1 -Flutter $flutterExe -Python $pythonExe `
  -Configuration $configuration -PackageName $packageName `
  -DestinationRoot $destinationRoot
```

统一脚本内部顺序：

1. 验证新包名、目标不存在和图标；复制图标到 runner。
2. 写入 `.build-tools/<Configuration>/.flutter_settings`，指定 `build-distribution-<mode>`。
3. 仅在 Flutter 调用期间覆盖 APPDATA；finally 恢复。
4. 构建 Windows 前端：显式模式、OMG_UI_REVIEW、完整图标字体和 --no-pub。
5. 仅收集 data、omg_neo.exe、DLL 和可选 native_assets.json。
6. 调用 backend/build.ps1，使用 neo_hosts.spec 构建服务和注入端并共享依赖。
7. 复制到新包 backend，执行脚本自带的初步隐私检查。

脚本自身不创建 ZIP。原生 INFO/deprecation 的 stderr 输出不是单独的失败依据；以退出码、异常及产物检查为准。外部命令失败必须停止后续交付。

### D. 产物验收与归档

先验证洁净包，再启动 GUI。默认最少应存在：

```text
<包名>/
  omg_neo.exe
  flutter_windows.dll
  desktop_drop_plugin.dll
  screen_retriever_windows_plugin.dll
  window_manager_plugin.dll
  data/
    flutter_assets/
      kernel_blob.bin                 # Debug
    app.so                            # Release
  backend/
    omg_backend.exe
    omg_injector.exe
    _internal/                        # 共享冻结运行时与资源
```

data 中的模式文件是二选一的关键检查目标，其余文件以 Flutter 实际输出为准。

```powershell
New-Item -ItemType Directory -Path (Join-Path $appRoot 'validation') -Force | Out-Null
if ($configuration -eq 'Debug') {
  & $pythonExe .\validation\verify_distribution_v001.py $packageName $destinationRoot --debug
} else {
  & $pythonExe .\validation\verify_distribution_v001.py $packageName $destinationRoot
}
if ($LASTEXITCODE -ne 0) { throw 'Distribution verification failed' }
```

验证器会写 README，创建 ZIP、SHA-256 和 `validation/distribution-<包名>.json`，并在临时数据目录启动后端检查 hello/flush/shutdown。它不是只读检查；同名 ZIP 已存在时不会覆盖。版本文字仍固定为 v0.0.1，版本升级时先同步脚本。

可选传输层检查使用实际 Dart 客户端：

```powershell
& $dartExe run tools/smoke_backend.dart (Join-Path $packageRoot 'backend\omg_backend.exe')
if ($LASTEXITCODE -ne 0) { throw 'Dart transport smoke failed' }
```

该工具显式使用临时数据目录。执行前仍应读取当前工具实现，确认检查行为符合任务范围。

`tools/verify_portable.dart` 则刻意不指定 dataRoot，会在包旁生成 AppData，不要在归档前对洁净包使用；如需测试便携默认目录，在验收副本上运行。

### E. 可选 GUI 验收

从原始 ZIP 解压副本，设置工作目录为副本根目录。Debug 检查 F8、弹窗截图和导出；Release 检查入口隐藏。检查基本导航、配置读写与正常退出。不要默认触发真实启动游戏、注入、切服或修改用户模组。

若使用界面自动化，遵循适用 computer-use 技能。不能把组件测试、冻结服务 smoke 或 EXE 存在表述为真实游戏功能全部通过。

## 5. 架构与兼容性约束

- `omg_backend.exe` 常驻，使用 stdio 协议；只有 launch.start 才应创建一次性注入端。
- 注入完成必须同时验证进程退出码和带 token 的原子结果，不能只凭退出码 0。
- 不让注入端导入 main、构建、资源或 requests/urllib3 等服务模块。neo_hosts.spec 会对此失败退出。
- 两个 EXE 各自分析、各自压缩代码，通过一次 COLLECT 共享 DLL/资源。不能复制一个 EXE 改名充当另一个，也不能随意使用 MERGE 替换现有方案。
- 共享目标同名不同内容属于需要分析的冲突，不能改成“后复制者覆盖”。base_library.zip 有明确的成员合并和冲突检查。
- 当前仍使用 PySide6 QtCore。Qt 移除文档是分析，不代表已实现。
- 保留现有对软件 OpenGL、可选 PyOpenSSL/cryptography 分支和特定误收集 ICU 的过滤。不要进一步排除 Python 原生 TLS 或加载器需要的 CRT。
- Windows runner 当前关闭 Impeller，使用硬件加速 Skia；不要把它描述为关闭硬件加速。
- 应用使用包旁 AppData，或显式 OMGNEO_DATA_ROOT；构建时临时设置的 APPDATA 只是 Flutter 配置隔离，不是应用数据迁移。
- 若任务只要求构建，不更改业务源码、默认配置、渲染器、版本号或数据路径。

## 6. 失败处理

| 失败阶段 | 后续动作 |
| --- | --- |
| 工具／依赖预检 | 修复明确缺失项；不自动升级全局环境 |
| Flutter 编译 | 记录退出码和实际错误；检查共享生成目录、SDK/插件与运行中文件占用 |
| PyInstaller | 检查 DLL/PYD、模块缺失、ABI 和 spec 冲突；不移除隔离断言来强行通过 |
| 目标非空 | 换新包名／空目标，不混合旧运行库 |
| 审计发现 AppData、日志或配置 | 重新生成洁净包；不从用户运行目录挑着删数据来伪装新包 |
| 前端时间戳落后源码 | 重新编译并组包；构建期间源码变化则不能称为一致快照 |
| 校验或 smoke 失败 | 不归档为成功；保留实际日志和错误，修复后重新验证 |
| 已有 ZIP | 换新目标；不得默默覆盖已交付归档 |

沙箱拒绝与编译失败分开报告。遇到自动审批拒绝，解释被拒绝的具体操作与理由，继续可做的安全检查；不能换工具规避权限限制。

## 7. 交付记录模板

```text
构建模式：Debug / Release
源码身份：Git revision + 状态，或无 Git 的输入哈希/时间记录
开始/结束时间：本地时区
实际工具版本：Flutter / Dart / Python / PyInstaller
执行命令：完整入口参数
应用目录：绝对路径
ZIP / SHA-256：绝对路径及校验值
验证报告：绝对路径
实际检查：命令、退出码、通过/跳过数量
UI 调整工具：启用 / 已隐藏
人工验收：执行内容；未执行则明确写未执行
限制：真实游戏、注入、切服或外部网络哪些未验证
```

面向用户的最终消息只需提供模式、产物链接、实际验证结果和必要限制。构建日志、报告及交接记录承担详细证据，不能用“构建成功”替代验证说明。
