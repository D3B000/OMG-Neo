# QtCore/PySide6 可行性与稳定性分析

## 结论

可移除，但属于调度层重构，复杂度中高；直接排除包会破坏现有功能。
Neo 的可见 UI 已由 Flutter 承担，Python 侧 Qt 主要承担事件循环、跨线程事件与定时器。
应保留对外协议、配置格式、启动时机、取消/回滚、独立注入进程及结果校验。
移除 Qt 并不自动提高稳定性，关键是显式保留当前的串行状态管理和跨线程投递语义。

## 已执行的探针

`validation/probe_qt_feasibility.py` 为每个模块创建独立进程，并通过 import finder 阻止
PySide6/shiboken6，同时查询 Qt6Core.dll 是否被原生代码加载。探针不启动游戏、编译或注入。

13 个目标可在未加载 Qt 的情况下导入：配置、资源、关联目录、服务器备份/切换/版本、
下载、更新部署辅助函数、Win32 loader/launcher/进程监控、构建环境模块，以及原生仪式库。
原生仪式库实际完成了一次 PE 分析；它和 Cython 分析扩展的导入表中也未发现 Qt。
这不等同于全部原生构建和真实注入流程已经通过无 Qt 回归。

四个直接阻塞目标是 `omg.core.alchemy`、`omg.core.gimi_update`、
`omg.domain.launch.controller` 和 `omg.domain.launch.worker`：它们在模块级定义 Qt 类。
服务入口、注入监督器和注入入口本身也直接使用 Qt。
具体结果见 `omg_neo/validation/qt-removal-feasibility.json`。

## 推荐结构与复杂度

| 区域 | 替换方式 | 难度/风险 |
| --- | --- | --- |
| 注入端 | 抽出纯任务装配/执行函数，保留一个 threading.Thread，join 后原子提交结果 | 中等；重点验证原生线程环境、freeze_support 和清理顺序 |
| 服务端 | 主控制循环读取 queue.Queue；工作线程只投递事件，控制线程独占状态与协议输出 | 中高；重点保留请求应答和任务事件顺序 |
| 定时器 | 控制循环用 monotonic 截止时间处理 INI 防抖、游戏判活、关闭检查 | 中等；保留 400 ms 防抖与 1.5 s 最长落盘窗口 |
| 构建/更新封装 | 纯函数移入无 Qt 核心模块；原 Qt 线程包装作为 OMGLite 兼容层保留 | 中等；不能只修 Neo 入口而保留间接 Qt 导入 |
| 打包 | 两份依赖图均确认无 Qt 后，再排除 PySide6/shiboken6 并补齐原生 CRT | 较低，但必须做冻结包回归 |

不使用模拟 PySide6 的全局假模块。Qt 包装类与核心函数应清晰分层，避免改变其它 OMGLite 界面行为。
工作线程不得直接调用状态回调替代原来的 queued Signal，否则会引入并发写状态风险。
Python 3.11 的 Queue 没有新版本的 shutdown API，应采用显式关闭事件/哨兵和限时等待。

只让服务端或注入端其中一方脱离 Qt，不会立刻节省整套共享 Qt DLL；两份依赖图都必须消除依赖。
即使完成迁移，也继续保留独立注入端，因为原生 DLL 的进程级退出无法用线程隔离。

## 体积判断

当前 PySide6 目录约 19.89 MiB，shiboken6 约 1.07 MiB，共约 20.96 MiB。
这包括 C 运行库和翻译文件，不能简单按目录总量当作最终净节省。
`3dmloader.dll` 仍依赖 MSVCP140/VCRUNTIME140 系列；移除 PySide 的 DLL 搜索路径时，
必须确保这些 CRT 在正式包中仍可独立解析，不能仅依靠开发机已安装的运行库。
目前 loader/ritual 库作为 data 收集，完整移除 Qt 时应把原生 DLL/PYD 纳入明确的二进制依赖扫描，
验证在未安装开发工具和 Qt 的机器上仍可加载，避免 Qt 间接携带的 CRT 消失后才暴露缺失依赖。

其中 96 个 Qt 翻译文件约 6.18 MiB。当前业务代码没有 QTranslator 安装/加载调用，
这是不重写事件循环即可单独验证的裁剪候选。该数已包含在 20.96 MiB 中，不能叠加计算。
本轮未裁剪翻译文件，也未更改 Qt 依赖。

## 本轮落实的低风险加固

故障注入复现了 `Bridge.completed()` 的问题：构建状态读取抛 PermissionError 后，
完成事件丢失、activeTask 未清空，shutdown 仍等待已结束的 worker。

已把 worker 引用和忙状态清理放入 finally，并使可选快照读取失败仍产生终态事件。
已存在构建快照的任务不再重复调用 BuildService.state，避免重复读取与重复异常点。
新增两项回归覆盖构建状态读取失败和整体快照失败；两者都能收到完成事件并正常关闭。
对正常成功、取消、配置保存和文件回滚逻辑不作调整。

注入端目前仅借用 LaunchController 的私有 `_build_task()`，且用 20 ms 定时器等待
自定义 finished 信号与真实 QThread 结束；未来抽取纯装配函数、统一执行结果后可以消除这些绕行。
不应为减少代码而移除服务端快速路径预检、任务 token、超时、原子结果文件或取消回滚。

## 实施顺序

1. 当前版本先采用异常收尾加固，保留 Qt。
2. 抽取纯任务装配/执行函数，保留旧 Qt 包装，分别验证 Neo 与 OMGLite。
3. 先迁移一次性注入端，验证真实原生注入与关闭，再迁移常驻服务的调度循环。
4. 无 Qt 冻结包验证配置/资源/构建/部署/备份/服务器切换/取消/重连/退出与 TLS/代理。
5. 最后移除依赖并实测体积、冷启动、内存和长任务退出，不预先承诺收益。

## 参考

- Qt 线程归属与 queued signal： https://doc.qt.io/qtforpython-6/PySide6/QtCore/QObject.html#thread-affinity
- Python 3.11 线程安全队列： https://docs.python.org/3.11/library/queue.html
- Python 3.11 线程生命周期： https://docs.python.org/3.11/library/threading.html#thread-objects
