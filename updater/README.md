# OMG-Neo TUI Updater

随 OMG-Neo 完整包分发的 Windows x64 终端更新器，支持 GitHub 最新版本下载和手动添加本地 ZIP。版本 0.0.1；不自动启动应用或游戏，不自动结束进程。直接运行安装根目录的 `OMG-Neo-Updater.exe`，无需从 Release 单独下载更新器。

## 使用

将 `OMG-Neo-Updater.exe` 放在 OMG-Neo 根目录即可运行；也支持放在安装目录外。不要放进会被替换的 `backend`、`data`。例如：

```text
D:/Tools/
  OMG-Neo/                  ← 菜单 1 选择这里
    omg_neo.exe
    OMG-Neo-Updater.exe     ← 随包分发，更新应用时排除
    backend/
    data/
    AppData/
  OMG-Neo-v0.0.1.zip        ← 菜单 2 添加这个 ZIP
  OMG-Neo-v0.0.1.zip.sha256
```

1. 正常退出 OMG-Neo，等待其后端和注入端结束。
2. 主菜单直接按数字键执行，无需回车。按 **1** 设置包含 `omg_neo.exe` 的原安装目录，路径输入完仍需回车。
3. 菜单 **7** 查询并下载 GitHub 最新正式版本；版本相同直接返回。也可用菜单 **2** 添加完整本地 ZIP，支持在终端中拖入路径。不要先将包解压覆盖安装。
4. ZIP 旁若有同名 `.zip.sha256` 或 `.sha256`，自动核对（优先 `.zip.sha256`）；也可用菜单 **3** 输入校验值，或输入／拖入 `.sha256` 文件路径。文件支持纯哈希或 `哈希  包文件名`，有文件名时必须与 ZIP 匹配。`--sha256` 参数同样支持文件路径。
5. 菜单 **4** 查看目标、包信息、哈希、解压大小与备份位置。
6. 菜单 **5** 再次显示操作内容，直接按回车开始更新；输入其他内容后回车取消。
7. 成功后从原安装路径启动 OMG-Neo。旧版本备份不自动清理。

可预填路径，仍须在 TUI 中确认：

```powershell
& .\OMG-Neo-Updater.exe --install-dir 'D:\Tools\OMG-Neo' `
  --package 'D:\Downloads\OMG-Neo-v0.0.1.zip'
```

允许从 OMG-Neo 根目录或独立 updater 目录运行；更新时安装根目录不改名，当前 updater 不替换。Debug 与 Release 可以互换，同版本 0.0.1 的重新构建包也允许更新。

旧 ZIP 未附版本清单时会明确显示“旧包未附版本清单”；它仍经过路径、完整运行资源、x64 PE 和可选 SHA-256 检查。没有外部校验值时仅计算本地哈希；这不证明发布者身份，清单和 SHA-256 也不等于数字签名。

## 保留与替换规则

程序根目录中的 `omg_neo.exe`、DLL/PDB、`data`、`backend`、`README.txt`、`launch.ps1`、`native_assets.json` 和 `update-manifest.json` 属于程序文件。更新只替换这些根条目，新版不再需要的旧 DLL 随旧程序进入备份。

`AppData`、`ui-reviews`、导出文件、当前 `OMG-Neo-Updater.exe` 以及其他未管理根条目直接排除：不扫描其内容、不复制、不移动、不做逐文件哈希。安装根目录也不移动。备份只包含旧程序，不包含用户数据快照；回退程序时，用户数据保持当前状态。后端的 `AppData/.backend.lock` 是唯一需要打开的用户数据控制文件，全程持有它以阻止后端并发启动。

程序文件使用路径／链接检查；排除目录中的链接不会被遍历。ZIP 禁止携带 AppData、导出数据或未知根条目。自定义 `OMGNEO_DATA_ROOT` 仍不被操作。

## 随包更新器与交接

`omg_neo/build_release.ps1` 会构建 updater，并将 `OMG-Neo-Updater.exe` 和 `.exe.sha256` 放入分发包根目录。更新器识别这些条目，校验 PE 与 SHA-256 后，暂存到 `.updater-pending/`，不覆盖正在执行的 updater。应用更新成功后，更新器自动退出，提示下次启动 OMG-Neo 完成交接。

新版后端启动后，后台线程校验暂存哈希，静默将根目录的 updater 替换为新版并更新 SHA-256 文件。Windows 若报告旧 updater 仍占用文件，后台最多等待 60 秒；超时保留待更新文件，下次启动重试。不弹终端，不启动更新器，也不阻塞应用界面。此交接依赖包含 `backend/updater_handoff.py` 的新版后端；旧版应用不具备该能力。

`.updater-pending` 是保留的程序控制目录，由更新事务管理，禁止 ZIP 直接提供该目录。当前 updater 只支持在分发包根目录按标准文件名交接；不要放在 `backend` 或 `data` 内。

## 下载进度与末尾校验

下载显示进度条和百分比，网络传输完成后切到独立的 SHA-256 校验阶段。下载后的重复 ZIP 哈希已合并，预览复用已校验的包；真正安装前仍重验 ZIP，避免预览后包被修改。解压后的程序清单校验也有进度。已达到 Content-Length 时不再额外等一次 EOF。Windows 控制台关闭快速编辑，防止选中输出暂停程序。

## 事务、备份与恢复

事务保存在安装目录旁的 `.安装目录名.updates/<时间戳>-<随机编号>/`，包含 `journal.json`、新程序 `stage/`、旧程序 `backup/` 和恢复时保留的新程序 `failed-install/`。

流程：校验 ZIP → 检查空间及进程 → 解压同卷暂存 → 校验程序 → 暂存新版 updater（如有）→ 再次检查进程 → 持久化旧／新程序根条目清单 → 逐条将旧程序移入 backup → 逐条将新程序移回原路径 → 标记成功。AppData 和当前 updater 在整个过程中都留在原位。

每次改名是同卷元数据操作，不复制用户数据。多条目替换并非整个安装的原子操作，但改名前已持久化事务清单；普通异常会恢复旧程序，被终止后可在菜单 **6** 选择记录并输入 `RECOVER`。恢复过程可重复执行，兼容旧更新器的整目录备份事务。

成功后在菜单 **6** 选择记录并输入 `ROLLBACK`，只回退程序；不回退用户数据，也不覆盖正在运行的 updater。事务备份不自动清理；确认版本稳定后再清理已结束记录，保留未完成事务。

## 设计与代码

| 文件 | 职责 |
| --- | --- |
| `main.py` | 全屏刷新数字菜单、路径输入、预览确认、进度、恢复／回退入口 |
| `engine.py` | ZIP／清单验证、用户数据保留、同卷切换、事务与恢复 |
| `platform_ops.py` | Win32 按完整映像路径检查占用进程、更新器锁和后端字节锁 |
| `sources.py` | GitHub Release 查询、下载与独立校验进度 |
| `build.ps1` | PyInstaller 独立单文件 EXE 和 SHA-256 |
| `tests/test_updater.py` | 临时目录、故障、中断和路径检查测试 |
| `tests/verify_frozen.py` | 使用实际 ZIP 验证冻结 EXE 的完整菜单更新及回退 |

目前不依赖 Rich/Textual/Qt；终端菜单由 Python 标准库与 Windows 控制台 API 实现，打包 EXE 无需用户安装 Python。菜单以数字选择，ANSI 可用时清屏着色，不可用时退化为普通控制台文本。

## 构建和测试

从 OMG-Neo 根目录执行：

```powershell
$pythonExe = 'F:\Python\Python311\python.exe'
$env:PYTHONUTF8 = '1'
& $pythonExe -m unittest discover -s updater\tests -v
if ($LASTEXITCODE -ne 0) { throw 'Updater tests failed' }
& .\updater\build.ps1 -Python $pythonExe
```

产物为 `updater/dist/OMG-Neo-Updater.exe` 及 `.exe.sha256`。构建只需要 Python 3.11 与现有 PyInstaller；程序运行时只使用标准库。

冻结 EXE 的实际包回归：

```powershell
& $pythonExe .\updater\tests\verify_frozen.py `
  --updater .\updater\dist\OMG-Neo-Updater.exe `
  --release '<完整 Release ZIP 的路径>' `
  --debug '<完整 Debug ZIP 的路径>'
if ($LASTEXITCODE -ne 0) { throw 'Frozen updater integration failed' }
```

该脚本仅在自动创建的临时安装目录执行更新和回退，不启动游戏或修改真实安装。结果在 `updater/validation`，不要把它当作对用户实际游戏数据的验收。

## 新构建包的清单

`omg_neo/build_release.ps1` 现在在完整后端打包完成后调用清单生成器，再进行洁净审计。清单格式：

```json
{
  "schema": 1,
  "product": "OMG-Neo",
  "version": "0.0.1+1",
  "configuration": "Release",
  "files": {
    "omg_neo.exe": {"size": 12345, "sha256": "..."}
  }
}
```

实际清单覆盖全部分发文件，清单自身不作自哈希。验包器继续负责生成 ZIP 和相邻 SHA-256。旧的已交付 ZIP 不会被追写或修改。

## GitHub 更新

默认仓库为 `D3B000/OMG-Neo`。菜单 **7** 查询 `/releases/latest` 的正式版本，优先 GitHub API，API 不可用或限流时回退 releases HTML 和 expanded_assets。只选择唯一的 OMG-Neo Release ZIP，排除源码、Debug 和 updater 包；资源缺失或存在歧义时明确报错。

直接复用 `OMGLite/src/omg/core/download.py`：系统代理／直连与 GitHub 镜像错峰竞争、TLS 证书校验、按网络缓存可用通道、自动重试和 Range 断点续传。构建脚本将这个共享模块打入独立 EXE，无需安装 OMG-Neo 后端依赖。

本地版本来自 `update-manifest.json`，与最新 Release 标签比较时忽略 `v` 前缀；标签未提供 Flutter `+build` 时按主版本比较，双方都提供时也比较 build。同版本无需下载或更新。旧安装缺少清单时不能确认版本相同，因此继续下载并预览。本地 ZIP 菜单仍允许手动同版本重建。

下载保存在安装目录旁的 `.安装目录名.updates/downloads`，中断的 `.part` 文件可续传。发布 API 提供的 SHA-256 和资源大小用于核对下载，随后检查 ZIP、包内版本清单与 Release 标签及前端模式，再进入预览、回车确认和现有事务引擎。Release ZIP 必须包含有效版本清单；HTML 回退时没有 API 哈希，仍执行包结构和清单校验。
