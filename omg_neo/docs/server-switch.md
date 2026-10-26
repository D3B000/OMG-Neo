# 原神服务器切换

入口：工具 → 服务器切换。游戏路径沿用设置中的游戏目录。
资源路径是 OMG-Neo 便携式数据目录下的 `AppData/server-switch`，不是 Windows 用户的 `%APPDATA%`。
自定义 `OMGNEO_DATA_ROOT` 时使用该目录下的 `server-switch`。


替换包制作教学：[Bilibili 视频 BV1WL411Y7wf](https://www.bilibili.com/video/BV1WL411Y7wf?t=0.7)。以下制作步骤依据用户补充的文字说明。

推荐直接使用原切换器制作的备份：

1. 将 `原神国际服务器切换器.exe` 剪切到国服游戏目录，打开后点击“备份国服”。
2. 将该 EXE 剪切到国际服游戏目录，打开后点击“备份外服”。
3. 合并两边生成的备份包，保留国服和国际服目录，以及 `版本号.ini` 的两边版本信息，将合并目录改名为“替换包”。
4. 将“替换包”放入 OMG-Neo 的 `AppData/server-switch`。

```text
AppData/server-switch/
  替换包/
    版本号.ini
    原神米哈游官服/
      YuanShen.exe
      mhypbase.dll
      pkg_version
      YuanShen_Data/...
    原神国际服/
      GenshinImpact.exe
      mhypbase.dll
      pkg_version
      GenshinImpact_Data/...
    PCGameSDK.dll                         （B 服需要）
    原神B服新登录框窗口/BLPlatform64/...    （B 服需要）
```

也支持目录名“原神资源替换包”，或将该包内容直接放在 `server-switch` 下。只能保留一套原格式包，避免选择歧义。
无需重命名中文子目录，也无需添加 manifest.json。读取 `版本号.ini` 中 `[配置]` 的 `国服版本`、`外服版本`；跨国服/国际服转换时两边都须与游戏版本一致。支持 UTF-8 和 GB18030 编码。合并同名版本文件时应保留两个版本键，不能用缺少另一边信息的文件覆盖。

普通官服备份不一定带 B 服组件。需要切换 B 服时，须用包含 B 服 SDK 和登录窗口的备份补齐上述组件。缺失时检查阶段会报错。

原格式包仅在国服包包含 `hdiffz.dll` 且国际服包不含该文件时，将它列为切国际服的清理项。子目录里的备份 config.ini 不会覆盖游戏当前配置。

### 兼容的自定义目录格式

原先的 cn/global/bilibili 格式仍可使用（仅在未发现原格式包时启用）：

用户自行取得与游戏 `config.ini` 中 `game_version` 完全一致的替换文件，按下面的结构放置：

```text
AppData/server-switch/
  cn/
    manifest.json
    YuanShen.exe
    mhypbase.dll
    pkg_version
    YuanShen_Data/...
  global/
    manifest.json
    GenshinImpact.exe
    mhypbase.dll
    pkg_version
    GenshinImpact_Data/...
  bilibili/
    manifest.json
    PCGameSDK.dll
    BLPlatform64/PCGamePlatform.exe
    BLPlatform64/...其他登录组件
```

每个包的 manifest.json 示例：

```json
{"game_version":"7.0.0"}
```

国际服包如确实需要清理旧版差异文件，可以显式声明：

```json
{"game_version":"7.0.0","remove":["GenshinImpact_Data/Plugins/hdiffz.dll"]}
```

cn/global 是差异覆盖包：仅放需要覆盖的文件，不能放整套公共资源。最低必需文件包括上方 EXE、mhypbase.dll、pkg_version，以及数据目录中的 app.info、globalgamemanagers、globalgamemanagers.assets、globalgamemanagers.assets.resS、Native/Data/Metadata/global-metadata.dat 和 startup-metadata.dat。还应补齐当前游戏版本实际需要的插件、Managed 元数据、StreamingAssets 差异文件等；最低文件检查无法证明包内容完整或可信。
可以直接将原切换器“原神米哈游官服”“原神国际服”的内容分别放入 cn/global，并补上 manifest.json。B 服登录 SDK 和 BLPlatform64 放入 bilibili 并补上版本声明。

官服/B 服互切只切换渠道配置和 B 服登录组件。国服/国际服互切重命名数据目录、覆盖差异包、删除另一客户端入口，复用公共游戏资源。游戏和启动器必须退出。配置中其他键保留，但 INI 注释和排版会重新生成。

每次实际切换先将受影响的文件备份到 `backups/<事务编号>`；写入前保存 pending.json。普通异常会自动回滚。程序被强制结束或自动回滚失败时，保留 pending.json 并阻止后续切换，使用“恢复未完成的切换”重试恢复。恢复时须保持相同的游戏路径，勿修改恢复记录或备份。已完成的备份保留供手动恢复，不自动删除。

版本号优先读取 globalgamemanagers 的内嵌版本；缺失时回退到版本配置或 manifest.json，不联网验证、不自动下载。不能迁移账号、角色或存档。替换包以及实际要覆盖、删除的游戏路径中的链接/重解析点会被拒绝；未参与切换的公共资源目录（如 StreamingAssets/AssetBundles）可以使用目录联接。

## 在 OMG-Neo 中制作备份

工具 → 服务器切换 → 制作替换资源备份，可选择源游戏目录和备份输出目录，分别备份国服/B 服与外服。默认保存到 AppData/server-switch/备份包，国服和国际服分别保存为“原神米哈游官服”“原神国际服”；合并保留两边版本配置。覆盖前的旧备份保存在 .history 中。完整候选文件清单及证据见 [备份分析](server-switch-backup-analysis.md)。

界面为独立工具页，提供“服务器切换 / 制作备份”页签和“返回工具”按钮。进入切换页、选择服务器时自动检查；也可直接点击“开始切换”，程序会先执行预检，失败原因显示在当前页，不会修改游戏。支持游戏配置中的 [General] 和 [general]。

切换、恢复和备份任务使用工具页的独立分段进度，不占用首页的更新进度。任务结束（成功、失败或取消）后收起进度。切换期间禁用游戏启动，文件操作完成后解除；后端同样拒绝在任务运行中启动游戏。服务器选择沿用设置页 Hunting 的分段控件。

## 版本采集显示

服务器切换页会收集本地游戏、国服替换包、国际服替换包中 globalgamemanagers 的长度前缀构建字符串，例如 7.1.0_48052158_48145775，显示内嵌版本、构建号及配置声明版本。不固定文件偏移；读取失败、文件缺失或多个候选会明确提示，不用配置值冒充内嵌版本。声明与内嵌版本不一致时显示提示。

进入页面、执行预检及任务结束后自动读取，也可点击“刷新版本”。支持原格式包和 cn/global 自定义包。本功能只采集本地文件，不访问网络，不修改文件，未将单个文件版本视为整套游戏的完整性证明。切换预检优先使用内嵌版本，无法识别内嵌版本时才回退到配置声明。config.ini 缺失或渠道未填写时，按唯一的 EXE 与数据目录组合识别国服/国际服，并以 PCGameSDK.dll 判断 B 服。两套客户端同时存在、或已有明确渠道与文件结构矛盾时仍拒绝操作。实际切换时会生成或更新 config.ini 和检测到的版本号。
