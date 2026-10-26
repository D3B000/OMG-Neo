# junction 与资源浏览加速（2026-10-21）

Neo 的旧 alchemy 工作区名为 `build-work`，当前默认路径是发布包内 `dist/OMG-Neo/AppData/build-work`，包含 project、cloud、artifact、output、input、temp。配置、缓存和日志也位于该 AppData；原 C 盘数据已迁移，详见 [应用内数据目录](应用内数据目录.md)。显式设置 OMGNEO_DATA_ROOT 时改用指定数据根。

## junction

实际 Mods/Hub 为 junction，目标是 `G:/GameMods/ModsHub/In_Use/GI_Mods`。上一版复用了清理操作的 no_links 限制，导致资源页直接丢弃此入口。

现在资源浏览和构建清理采用各自路径策略：

- 资源页保留逻辑路径和面包屑，允许通过实际存在于 Mods 中的目录链接访问外置模组。链接目录显示链接图标和目标提示。
- 启停 junction 只重命名链接入口；在 junction 下启停子模组会作用于目标中的该子模组。
- 深层 INI 枚举按物理目录身份去重，跳过循环，写回同一物理 INI 一次。写回备份使用逻辑路径，差分映射仍按照 Mods 入口路径匹配。
- 操作句柄保存解析后的目标身份和目录时间戳，链接被更换后拒绝旧句柄。路径中的 `..` 不能越出逻辑 Mods 根。
- build-work 清理继续拒绝 junction，允许浏览资源不意味着允许清理外置存储。

## 性能

旧版列表对每个模组先递归 safe_tree，再递归解析全部切换键；Flutter 每次取 visible 都重复构造整份模型，Grid 的每个 itemBuilder 又调用一次 visible。

当前改为：

1. 当前目录与每个直接子目录仅做浅层 scandir，确定条目类型与封面，不递归读取贴图目录，不解析 INI。
2. 目录信息采用有容量限制的 LRU 缓存，按真实目录身份和修改时间失效；面包屑校验每次列表只执行一次。
3. 点击“切换键”后后台解析，弹窗先显示进度。单文件解析缓存按物理路径、mtime 和大小失效，写回后清空。
4. Flutter 仅在列表快照变化时转换模型；Grid 捕获本次筛选结果，避免按卡片重复整表转换和筛选。缩略图保持按可见卡片加载及 cacheWidth=224 解码。

本机真实目录只读对比，前后条目数相同。以下为后两次调用的均值，系统文件缓存已热；不包含图片解码和界面绘制，不代表冷盘或端到端首屏。

| 目录 | 条目数 | 旧版查询 | 新版查询 |
| --- | ---: | ---: | ---: |
| Player_Character/Girl_II | 66 | 94.8 ms | 27.7 ms |
| Plugins | 7 | 678.4 ms | 3.5 ms |
| Weapon | 9 | 90.6 ms | 4.4 ms |

证据为 `validation/junction-perf/benchmark.json`，脚本为 `tools/benchmark_resources.py`。切换键已移至按需读取，列表对比不是相同深度的完整元数据扫描；这正是缩短列表等待时间的改动。

## 验证

- Python：目录链接可浏览；真实 Windows junction 启停不改目标名；写回目标内容并保留原始备份；循环链接终止；目标被替换后旧句柄失效；INI 缓存命中与文件更新失效；清理仍拒绝链接。
- Flutter：切换键请求按需触发、进度展示、后端完成后显示结果；图片和切换键不会误触启停；原有导航与外观测试。
- 真实 Hub 仅做只读枚举和测速；写回、启停均在临时副本测试。
- 冻结后端已在仅保留系统 PATH、空 PYTHONPATH 的环境验证真实 Hub 目录枚举，以及临时副本的按需切换键、启停、写回备份、三种仪式和清理。记录位于 `validation/junction-perf/frozen-real/`、`frozen-fixtures/`。
- 15 项 Python 测试、13 项 Flutter 测试通过，Flutter analyze 无问题。发布目录为 `dist/OMG-Neo-junction-fast/`，启动脚本已指向此目录，保留运行中的旧目录。

Dart 的 dart:io 提供异步目录 / 文件 API，足以承担页面文件读取。本轮结果表明应先减少递归和重复读取；不需要为了资源浏览重写整份 Python 业务。后续如测得图片 I/O 成为瓶颈，可生成磁盘缩略图缓存；重 CPU 解析可放到 isolate。
