#include "flutter_window.h"

#include <optional>
#include <shobjidl.h>
#include <flutter/standard_method_codec.h>

#include "flutter/generated_plugin_registrant.h"

FlutterWindow::FlutterWindow(const flutter::DartProject& project)
    : project_(project) {}

FlutterWindow::~FlutterWindow() {}

bool FlutterWindow::OnCreate() {
  if (!Win32Window::OnCreate()) {
    return false;
  }

  RECT frame = GetClientArea();

  // The size here must match the window dimensions to avoid unnecessary surface
  // creation / destruction in the startup path.
  flutter_controller_ = std::make_unique<flutter::FlutterViewController>(
      frame.right - frame.left, frame.bottom - frame.top, project_);
  // Ensure that basic setup of the controller was successful.
  if (!flutter_controller_->engine() || !flutter_controller_->view()) {
    return false;
  }
  RegisterPlugins(flutter_controller_->engine());
  SetChildContent(flutter_controller_->view()->GetNativeWindow());

  lifecycle_channel_ =
      std::make_unique<flutter::MethodChannel<flutter::EncodableValue>>(
          flutter_controller_->engine()->messenger(), "omg_neo/lifecycle",
          &flutter::StandardMethodCodec::GetInstance());
  lifecycle_channel_->SetMethodCallHandler(
      [this](const auto& call, auto result) {
        if (call.method_name() != "finishExit") {
          result->NotImplemented();
          return;
        }
        // Flutter teardown must run on this platform thread. Hide the HWND
        // before stopping its message pump, so a slow GPU/plugin destructor
        // cannot leave a visible, non-responsive window on the desktop.
        ::ShowWindow(GetHandle(), SW_HIDE);
        result->Success();
        ::PostQuitMessage(0);
      });

  path_channel_ = std::make_unique<flutter::MethodChannel<flutter::EncodableValue>>(
      flutter_controller_->engine()->messenger(), "omg_neo/paths",
      &flutter::StandardMethodCodec::GetInstance());
  path_channel_->SetMethodCallHandler(
      [this](const auto& call, auto result) {
        if (call.method_name() != "pick") {
          result->NotImplemented();
          return;
        }
        bool folder = true;
        std::wstring initial;
        if (const auto* args = std::get_if<flutter::EncodableMap>(call.arguments())) {
          auto it = args->find(flutter::EncodableValue("folder"));
          if (it != args->end() && std::holds_alternative<bool>(it->second)) {
            folder = std::get<bool>(it->second);
          }
          it = args->find(flutter::EncodableValue("initial"));
          if (it != args->end() && std::holds_alternative<std::string>(it->second)) {
            const auto& value = std::get<std::string>(it->second);
            int count = MultiByteToWideChar(CP_UTF8, 0, value.c_str(), -1, nullptr, 0);
            if (count > 1) {
              initial.resize(count);
              MultiByteToWideChar(CP_UTF8, 0, value.c_str(), -1, initial.data(), count);
              initial.resize(count - 1);
            }
          }
        }
        IFileOpenDialog* dialog = nullptr;
        HRESULT hr = CoCreateInstance(CLSID_FileOpenDialog, nullptr, CLSCTX_INPROC_SERVER,
                                      IID_PPV_ARGS(&dialog));
        if (FAILED(hr)) {
          result->Error("DIALOG", "无法创建路径选择对话框");
          return;
        }
        DWORD options = 0;
        dialog->GetOptions(&options);
        dialog->SetOptions(options | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST |
                          (folder ? FOS_PICKFOLDERS : FOS_FILEMUSTEXIST));
        if (!initial.empty()) {
          IShellItem* start = nullptr;
          if (SUCCEEDED(SHCreateItemFromParsingName(initial.c_str(), nullptr,
                                                    IID_PPV_ARGS(&start)))) {
            dialog->SetFolder(start);
            start->Release();
          }
        }
        hr = dialog->Show(GetHandle());
        if (hr == HRESULT_FROM_WIN32(ERROR_CANCELLED)) {
          dialog->Release();
          result->Success();
          return;
        }
        IShellItem* item = nullptr;
        if (SUCCEEDED(hr)) hr = dialog->GetResult(&item);
        PWSTR path = nullptr;
        if (SUCCEEDED(hr)) hr = item->GetDisplayName(SIGDN_FILESYSPATH, &path);
        if (SUCCEEDED(hr)) {
          int count = WideCharToMultiByte(CP_UTF8, 0, path, -1, nullptr, 0, nullptr, nullptr);
          std::string value(count, '\0');
          WideCharToMultiByte(CP_UTF8, 0, path, -1, value.data(), count, nullptr, nullptr);
          value.resize(count - 1);
          result->Success(flutter::EncodableValue(value));
        } else {
          result->Error("DIALOG", "路径选择失败");
        }
        if (path) CoTaskMemFree(path);
        if (item) item->Release();
        dialog->Release();
      });

  // Dart shows the window after loading the saved appearance and painting its
  // first frame. An automatic native show can expose an unthemed startup frame.

  return true;
}

void FlutterWindow::OnDestroy() {
  lifecycle_channel_ = nullptr;
  path_channel_ = nullptr;
  if (flutter_controller_) {
    flutter_controller_ = nullptr;
  }

  Win32Window::OnDestroy();
}

LRESULT
FlutterWindow::MessageHandler(HWND hwnd, UINT const message,
                              WPARAM const wparam,
                              LPARAM const lparam) noexcept {
  // Give Flutter, including plugins, an opportunity to handle window messages.
  if (flutter_controller_) {
    std::optional<LRESULT> result =
        flutter_controller_->HandleTopLevelWindowProc(hwnd, message, wparam,
                                                      lparam);
    if (result) {
      return *result;
    }
  }

  switch (message) {
    case WM_FONTCHANGE:
      flutter_controller_->engine()->ReloadSystemFonts();
      break;
  }

  return Win32Window::MessageHandler(hwnd, message, wparam, lparam);
}
