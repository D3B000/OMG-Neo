# 服务端与注入端体积优化

## 方案与复杂度

第三项采用中等复杂度的“独立入口、独立压缩代码、共享运行时”方案。
`injector_main.py` 是注入端唯一入口，`backend_runtime.py` 提供公共路径初始化。
服务端继续重导出 `bootstrap` 以兼容已有测试和脚本；注入端不再反向导入 `main`。
服务端协议、一次性注入进程、任务结果文件与退出隔离机制均保留。

| 方式 | 取舍 |
| --- | --- |
| 复制整个服务端 EXE | 原实现最简单，但注入端重复包含更新、构建与资源业务。 |
| 独立 Analysis/PYZ + 一次 COLLECT | 当前方案；仅打入各自所需代码，Python、Qt、DLL 和资源仍只收集一份。 |
| MERGE | 主要处理外部数据/二进制共享；原包已共享这些文件，且可能引入跨 EXE 提取语义，不采用。 |
| 外置共享字节码或自定义原生启动器 | 可能继续减少共同标准库代码，但需维护导入器、扩展模块定位及 Python ABI，收益不足以抵消复杂度。 |

仍有部分标准库同时嵌入两个压缩 PYZ：注入端本身也需要这些代码。
本项不能节约完整一份注入 EXE 的体积，需区分精简入口收益与前两项依赖裁剪收益。

## 构建保证

`neo_hosts.spec` 分别分析 `main.py` 和 `injector_main.py`。
服务端的依赖图若出现注入入口或 omg.domain.inject / omg.domain.launch，构建立即失败。
注入端的依赖图若出现服务端、资源、构建、requests/urllib3 等业务模块，构建立即失败。
共享依赖遇到同名不同内容也立即失败；两个 base_library.zip 的成员经过冲突检查后合并。
每个 EXE 保留独立的压缩 PYZ，使用普通 onedir 启动，不额外解压另一个 EXE。

前两项已验证的裁剪同时启用：排除 Qt 软件 OpenGL 库及可选 PyOpenSSL/cryptography 分支。
两个入口均未安装 Qt 翻译器，收集阶段裁掉 PySide6/translations。
Python 原生 libssl/libcrypto 保留。两份 EXE 都嵌入 krr.ico。
`build.ps1` 要求输出目录为空，防止旧的冗余 DLL 随更新残留。

## 2026-11-11 构建体积

用同一台机器上的原有 onedir 产物与新构建对比。文件总大小从 50.30 MiB 降至 44.05 MiB，减少 6.25 MiB（约 12.4%）。
其中 96 个 Qt 翻译文件占 6.18 MiB，服务 EXE 缩小约 68 KiB。
共享包中剩余的 PySide6 与 shiboken6 文件约 14.78 MiB，包含两端共用的 QtCore 与部分 C 运行库。移除整套依赖需要迁移两端的事件循环和线程调度，再验证原生依赖的加载。

## 验证与边界

独立的 `validation/neo_hosts_test.spec` 仅给测试包加入外部探针入口，正式 spec 不含该入口。
探针不向依赖分析引入服务端模块，能检验实际精简后的冻结导入图。
测试涵盖进程等待子进程的 freeze_support、注入工作线程完成与清理、实际 loader 名称、
原生 loader 库加载/卸载，以及服务端的验证型 HTTPS、CONNECT 代理和原生构建能力检测。

真实游戏与实际注入 hook 未执行；本地 TLS 服务不能替代线上第三方下载的全部兼容性测试。
具体尺寸、模块清单、测试日志见 `omg_neo/validation/independent-hosts-20261025/`。
