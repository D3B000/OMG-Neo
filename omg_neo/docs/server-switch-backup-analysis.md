# 原切换器备份清单与 OMG-Neo 实现

分析对象：原神三服切换器目录中的 `原神国际服务器切换器.exe`（2025-08-15），以及随附标记 7.0.0 的原神资源替换包。未执行原 EXE，结论来自备份区域中的路径字符串、通配符和实际资源包交叉核对；未反汇编验证全部条件分支。

## 证据与结论

EXE 文件偏移 `0x343d43` 开始出现“原神资源备份包”以及国服目标目录；`0x3440fc` 至 `0x345028` 出现对应的源路径和备份目标路径；`0x8e79e8` 至 `0x8e8846` 出现国际服清单。国服与国际服清单基本对称，EXE 名称、数据目录名不同。

`0x343f9f` 附近依次出现 `YuanShen_Data\StreamingAssets\`、`*.blk`（`0x343fbf`）和目标路径。国际服区域也出现对应 StreamingAssets 源、目标路径。结合现有包中的单个根目录 blk，OMG-Neo 按根目录 `*.blk` 实现；尚未通过动态跟踪证明原 EXE 是否还有额外枚举条件。

现有国服包与国际服包各有 23 个文件：4 个根目录文件、5 个数据目录根文件、3 个元数据文件、10 个插件和 1 个 StreamingAssets 根目录 blk。EXE 还列出当前替换包不存在的历史文件，因此实现采用“明确清单中存在则复制”的规则，并记录不存在的可选项。

## 完整候选清单

以下 `<Data>` 在国服为 `YuanShen_Data`，国际服为 `GenshinImpact_Data`。

游戏根目录：

```text
YuanShen.exe 或 GenshinImpact.exe
mhypbase.dll
UnityPlayer.dll
pkg_version
Audio_Chinese_pkg_version
```

数据目录：

```text
<Data>/app.info
<Data>/globalgamemanagers
<Data>/globalgamemanagers.assets
<Data>/globalgamemanagers.assets.resS
<Data>/upload_crash.exe
<Data>/Managed/Metadata/global-metadata.dat
<Data>/Native/UserAssembly.dll
<Data>/Native/UserAssembly.exp
<Data>/Native/UserAssembly.lib
<Data>/Native/Data/Metadata/global-metadata.dat
<Data>/Native/Data/Metadata/startup-metadata.dat
```

插件目录：

```text
<Data>/Plugins/cri_mana_vpx.dll
<Data>/Plugins/cri_vip_unity_pc.dll
<Data>/Plugins/cri_ware_unity.dll
<Data>/Plugins/d3dcompiler_43.dll
<Data>/Plugins/d3dcompiler_47.dll
<Data>/Plugins/hdiffz.dll
<Data>/Plugins/hpatchz.dll
<Data>/Plugins/mihoyonet.dll
<Data>/Plugins/Mmoron.dll
<Data>/Plugins/MTBenchmark_Windows.dll
<Data>/Plugins/NamedPipeClient.dll
<Data>/Plugins/UnityNativeChromaSDK.dll
<Data>/Plugins/UnityNativeChromaSDK3.dll
<Data>/Plugins/xlua.dll
```

另备份 `<Data>/StreamingAssets/*.blk`，仅该目录直接子文件，不递归复制大型资源子目录。

国服额外组件（存在则复制）：

| 游戏内源路径 | 备份包内目标路径 |
|---|---|
| YuanShen_Data/Plugins/PCGameSDK.dll | PCGameSDK.dll |
| YuanShen_Data/Plugins/BLPlatform64/ 整个目录 | 原神B服新登录框窗口/BLPlatform64/ |

EXE 中 SDK 备份源/目标分别位于 `0x34401e`、`0x344043`，登录窗口路径位于 `0x34408b` 附近。游戏 config.ini 用于识别渠道和读取版本号，备份结果生成“版本号.ini”。这不是整套游戏、账号或存档备份。

## OMG-Neo 使用方式

工具 → 服务器切换 → 制作替换资源备份：

1. 指定游戏目录（默认取设置，可浏览选择另一套游戏）。
2. 指定备份输出目录（默认 AppData/server-switch/备份包）。
3. 点击“备份国服 / B 服”或“备份外服”。程序核验所选类型与 config.ini 的渠道是否一致。

在输出目录中直接保存 `原神米哈游官服` 或 `原神国际服`，并合并维护根目录的 `版本号.ini`。默认路径为 `AppData/server-switch/备份包`。同一输出目录可先后备份国服和国际服；重复备份时，旧文件移入 `.history/<编号>`，不影响另一边资源。自定义输出目录仍受保护，不能与游戏目录互相包含，也不能写进正在使用的替换包目录。

备份保留原格式中文子目录，只记录实际复制的文件。`backup-report.json` 包含复制清单、每个文件大小与 SHA-256，以及缺失的可选项。当前支持版本必需的核心文件缺失时直接失败，以免输出不可切换的包。历史文件如 UnityPlayer.dll、UserAssembly 等不存在时记录为可选缺失。

国服和外服应在同一游戏版本下分别备份。同一输出目录会自动合并两边资源；分别输出时可手动合并，`版本号.ini` 应合并保留 `[配置]` 中 `国服版本` 与 `外服版本` 两个键，随后按使用说明放入 `AppData/server-switch/替换包`。单边备份只声明本次实际备份的一边，不伪造另一边版本。备份报告可以各自另存；切换逻辑不依赖该报告。

写入先放在独立临时目录，全部完成后发布对应的渠道目录及版本记录，异常时回滚本次发布；失败或取消清理本次临时结果，不发布半成品。运行中的游戏和启动器会阻止备份。备份不修改游戏文件。持续变化的外部源文件仍可能导致不一致，应保持游戏和更新器退出。
