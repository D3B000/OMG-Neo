# OMG-Neo

面向 GIMI / 3DMigoto 的 Windows 桌面管理工具，使用 Flutter 前端、Python 后端和独立注入进程。

## 源码结构

- `omg_neo/`：Flutter Windows 应用、字体、图标、测试及构建脚本。
- `backend/`：stdio 后端、独立注入入口、测试和 PyInstaller 配置。
- `OMGLite/src/omg/`：本次导入的共享业务源码快照（core、domain），及必要 loader 原生资源；不依赖仓库外的 OMGLite 目录。
- `backend/vendor/ritual/`：现有仪式功能所需原生 DLL/PYD/工具。PYD 需要 Python 3.11 x64；这些文件是运行依赖，不是本仓库构建出的发布包。
- `intro.md`：用户使用说明。

共享代码的原始 MIT 许可见 `OMGLite/LICENSE`；字体许可见 `omg_neo/fonts/Saira-OFL.txt`。原生组件保留现有二进制，仓库不包含这些组件的全部原生构建源码。

## 构建

需要 Windows x64、Python 3.11 x64、Flutter Windows SDK、Visual Studio C++ 桌面开发工具和 Windows SDK。

```powershell
python -m pip install -r backend/requirements.txt
cd omg_neo
flutter pub get
flutter analyze
flutter test --dart-define=OMG_UI_REVIEW=true --no-pub
python -m unittest discover -s ../backend/tests -p 'test_*.py'
.\build_release.ps1 -Configuration Release
```

完整应用输出到 `omg_neo/dist/OMG-Neo/`。必须分发整个目录（包括 backend、data 和 DLL）。
详见 [手动构建指南](omg_neo/docs/手动构建指南.md) 和 [Agent 构建流程](omg_neo/docs/Agent构建流程.md)。旧文档中工作区级的 `OMGLite/src` 在此仓库中位于根目录下的 `OMGLite/src`。

初次源码导入不包含日志、缓存、运行配置、截图批注、下载的构建工程和已生成的发布包。
