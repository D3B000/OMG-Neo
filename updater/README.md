# OMG-Neo TUI Updater

独立 Windows x64 终端更新器，当前使用手动添加的本地 ZIP。版本 0.0.1；不联网，不自动启动应用或游戏，不自动结束进程。

## 使用

将 `OMG-Neo-Updater.exe` 放在 OMG-Neo 安装目录**外面**，双击运行。例如：

```text
D:/Tools/
  OMG-Neo-Updater.exe
  OMG-Neo/                  ← 菜单 1 选择这里
    omg_neo.exe
    backend/
    data/
    AppData/
  OMG-Neo-v0.0.1.zip        ← 菜单 2 添加这个 ZIP
  OMG-Neo-v0.0.1.zip.sha256
```

1. 正常退出 OMG-Neo，等待其后端和注入端结束。
2. 菜单 **1** 设置包含 `omg_neo.exe` 的原安装目录。
3. 菜单 **2** 添加完整 ZIP；支持在终端中拖入路径。不要先将包解压覆盖安装。
4. ZIP 旁若有同名 `.zip.sha256`，自动核对；也可用菜单 **3** 输入校验值。
5. 菜单 **4** 查看目标、包信息、哈希、解压大小与备份位置。
6. 菜单 **5** 再次显示操作内容，输入 `UPDATE` 后更新。
7. 成功后从原安装路径启动 OMG-Neo。旧版本备份不自动清理。

可预填路径，仍须在 TUI 中确认：

```powershell
& .\OMG-Neo-Updater.exe --install-dir 'D:\Tools\OMG-Neo' `
  --package 'D:\Downloads\OMG-Neo-v0.0.1.zip'
```

不要将更新器本身或终端工作目录放在待更新目录内，否则 Windows 可能阻止替换。Debug 与 Release 可以互换，同版本 0.0.1 的重新构建包也允许更新。

旧 ZIP 未附版本清单时会明确显示“旧包未附版本清单”；它仍经过路径、完整运行资源、x64 PE 和可选 SHA-256 检查。没有外部校验值时仅计算本地哈希；这不证明发布者身份，清单和 SHA-256 也不等于数字签名。

## 保留与替换规则

程序根目录中的 `omg_neo.exe`、所有 DLL/PDB、`data`、`backend`、`README.txt`、`launch.ps1`、`native_assets.json` 和 `update-manifest.json` 属于程序文件。新包提供它们的新副本，旧包多余的 DLL、PDB 和后端依赖随整个旧目录进入备份。

其他根目录内容都保留，包括 `AppData`、`ui-reviews`、自定义导出文件和未知用户目录。它们复制到新暂存目录，并逐文件核对 SHA-256；安装路径保持原样，保存的绝对路径不因更新而变化。运行期 `.backend.lock` 不复制到新目录。

ZIP 不允许携带 AppData 或其他未知的根目录内容，避免包覆盖用户数据。`backend` 和 `data` 是程序专用目录，不适合存放个人文件。原安装目录中的个人内容无论是否属于保留规则，都在完整旧目录备份中。

自定义 `OMGNEO_DATA_ROOT` 指向的外部数据根不被扫描、复制或删除。更新期间也应确保使用该数据根的应用正常退出。符号链接、junction 和其他重解析点会被拒绝，更新器不遍历外部链接。

## 事务、备份与恢复

假设安装目录为 `D:/Tools/OMG-Neo`，事务目录位于同级：

```text
D:/Tools/.OMG-Neo.updates/
  .lock
  <时间戳>-<随机编号>/
    journal.json           # 目标、包哈希、版本、模式和持久状态
    stage/                 # 准备中的新程序和已校验用户数据
    backup/                # 切换后完整旧安装目录
    failed-install/        # 恢复中保留的失败新目录（若有）
```

核心流程：校验 ZIP → 检查空间和运行进程 → 解压到同卷暂存 → 校验清单／运行资源 → 复制并校验用户数据 → 再次检查进程 → 原目录改名为 backup → 暂存目录改名为原安装路径 → 标记成功。

准备期间持有与默认 AppData 后端相同的字节锁，阻止其在复制期间写数据。Windows 不允许带打开后代文件句柄的目录改名，因此在最终进程检查与改名之前释放该锁。请在整个操作期间保持应用关闭；目录改名或文件占用导致的异常会进入恢复流程。

每一步关键状态以临时 JSON、flush/fsync 和原子替换方式记录。两次目录改名之间存在短暂窗口，不声称整个更新是一个原子文件系统操作，也不保证磁盘损坏或硬件断电时的文件系统持久性。

- **普通异常或 Ctrl+C**：已切换的目录尽量自动恢复；原始异常和现场保留。
- **进程被终止／操作中断**：重新运行更新器，选择同一安装路径，菜单 **6** 选择未结束记录，输入 `RECOVER`。安装目录暂时不存在时也可设置原路径并进入恢复菜单。
- **更新成功后回退程序**：菜单 **6** 选择对应已完成事务，输入 `ROLLBACK`。从该事务备份取出旧程序，但保留**当前**用户设置和数据；回退前的完整安装也进入一个新备份事务。
- 不完整事务会阻止后续更新，必须先恢复。恢复记录损坏、路径不匹配或原始备份缺失时停止，不猜测其他目录。

备份会占用磁盘空间，更新器目前不自动清理。确认新版本稳定并且不再需要回退后，可自行归档或移除已结束的事务目录；不要删除未完成事务或其中唯一的 backup。

## 设计与代码

| 文件 | 职责 |
| --- | --- |
| `main.py` | 全屏刷新数字菜单、路径输入、预览确认、进度、恢复／回退入口 |
| `engine.py` | ZIP／清单验证、用户数据保留、同卷切换、事务与恢复 |
| `platform_ops.py` | Win32 按完整映像路径检查占用进程、更新器锁和后端字节锁 |
| `sources.py` | 更新来源边界；GitHub 方法预留 |
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

## GitHub 预留

`sources.UpdateSource` 定义 `check_latest(configuration) -> Release` 与 `fetch_release(release, destination) -> Path`。`GitHubSource` 当前明确抛出 `NotImplementedError`，菜单只显示未启用提示，没有后台请求或假更新结果。

仓库公开后，在该适配器中实现仓库配置、Release 资源选择、限时下载、校验来源和临时文件提交。获取到本地 ZIP 后仍走现有 `inspect_package`、预览确认和事务引擎，不允许下载逻辑绕过文件检查或直接覆盖安装目录。
