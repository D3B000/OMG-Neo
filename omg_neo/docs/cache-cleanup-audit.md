# 缓存清理范围核对（2026-10-26）

以当前应用实际使用的 AppData 为边界。手动清理删除下表中的可清理文件；退出清理按每个类别保留最新一个完整条目。清理前检查全部候选，不跟随符号链接或 Windows 联接。

| 产生位置 | 产生行为 | 处理 |
| --- | --- | --- |
| `cache/` | 兼容层缓存、构建选项记忆 | 纳入 |
| `resource-backups/` | 模组 INI 写回备份 | 纳入，每个操作目录为一份 |
| `dll-backups/` | 覆盖 GIMI DLL 前备份 | 纳入 |
| `server-switch/backups/` | 切服事务恢复备份 | 纳入；存在 pending.json 时全部保护 |
| `server-switch/备份包/.history/` | 导出备份覆盖历史 | 纳入 |
| `server-switch/替换包/.history/` | 替换包再次导入的覆盖历史 | 本次补齐 |
| `server-switch/原神资源替换包/.history/`、`server-switch/.history/` | 兼容布局下历史 | 本次补齐 |
| `server-switch/.server-import-<32位token>/` | 导入中断的暂存 | 本次补齐 |
| `server-switch/备份包/.server-backup-<32位token>/` | 默认导出中断的暂存 | 本次补齐 |
| `build-work/temp/` | 源码 ZIP、云构建 part 下载 | 已纳入 |
| `temp/injection-*/` | 注入请求和结果暂存 | 已纳入 |
| `temp/omg_gimi_rollback_*/`、`temp/omg_gimi_latest.zip` | GIMI 更新兼容层暂存 | 本次补齐 |
| `update-*/` | Neo 更新 ZIP 暂存 | 已纳入 |
| 指定的 `config.json.tmp`、`build-options.tmp`、`build-products.tmp`、`resource-cards.tmp`、`server-switch/pending.tmp` | 原子写入中断残留 | 本次补齐；pending.tmp 在待恢复事务存在时保护 |
| `log/omg_*.log[.轮转编号]`、`log/injector-*.log` | 服务与注入运行日志 | 本次补齐；保护正在使用的日志及其轮转文件 |

以下文件保留：配置与最近配置恢复副本、替换包及当前导出的备份包、构建源码/云构建文件/产物/输入、手动导出的日志和 UI 调整截图、注入生命周期记录、冻结运行时的 `_MEI*` 目录，以及不符合已知规则的临时文件。

用户自选的 AppData 外备份输出目录不会递归扫描，外部 `.history` 也不会自动删除。模组移动可能在游戏或来源目录遗留 `.omg-recovery-*`；这可能是故障后唯一原件，必须保留。`.omg-move-*`、`.modFolder-*.tmp`、`.neo-*.dll` 等外部暂存由对应操作的 finally 清理，统一清理不会遍历游戏、模组和任意外部目录。

资源浏览器的 INI/目录缓存、Flutter 图像缓存等为内存缓存，退出进程即释放。

## 用量刷新修复

旧前端只在启动时读取用量，之后生成的切服备份不会立即反映。现改为进入缓存页、点击“刷新用量”、切服/导入/导出/更新/构建/写回等相关任务完成后重新读取。异步读取在关闭或销毁控制器后不会更新界面。

对用户指出的 server-import-20261026 发行目录进行只读扫描：两份切服备份分别为 477 和 195280549 字节，合计 195281026 字节（186.23 MiB）。检查冻结后端归档确认该版本已经包含 server-switch/backups 扫描规则；未对真实备份执行删除。
