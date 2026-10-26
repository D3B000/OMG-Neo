#include <flutter/dart_project.h>
#include <flutter/flutter_view_controller.h>
#include <windows.h>
#include <shobjidl.h>

#include "flutter_window.h"
#include "utils.h"

int APIENTRY wWinMain(_In_ HINSTANCE instance, _In_opt_ HINSTANCE prev,
                      _In_ wchar_t *command_line, _In_ int show_command) {
  // Attach to console when present (e.g., 'flutter run') or create a
  // new console when running with a debugger.
  if (!::AttachConsole(ATTACH_PARENT_PROCESS) && ::IsDebuggerPresent()) {
    CreateAndAttachConsole();
  }

  // Initialize COM, so that it is available for use in the library and/or
  // plugins.
  ::CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
  // Stable identity for the application in the Windows taskbar.
  ::SetCurrentProcessExplicitAppUserModelID(L"ObjNotFound.OMGNeo");

  flutter::DartProject project(L"data");
  // This desktop UI uses conventional 2D widgets. Skia keeps hardware
  // acceleration while avoiding Impeller's larger baseline on Windows/ANGLE.
  // It also honors the explicit resource-cache budget set by Dart.
  project.set_impeller_switch(flutter::ImpellerSwitch::Disabled);

  std::vector<std::string> command_line_arguments =
      GetCommandLineArguments();

  project.set_dart_entrypoint_arguments(std::move(command_line_arguments));

  FlutterWindow window(project);
  Win32Window::Point origin(10, 10);
  Win32Window::Size size(960, 540);
  if (!window.Create(L"OMG-Neo", origin, size)) {
    return EXIT_FAILURE;
  }
  window.SetQuitOnClose(true);

  ::MSG msg;
  while (::GetMessage(&msg, nullptr, 0, 0)) {
    ::TranslateMessage(&msg);
    ::DispatchMessage(&msg);
  }

  // Dispose Flutter and its plugins while COM is still initialized. The
  // lifecycle channel already hid the window before ending the message pump.
  ::ShowWindow(window.GetHandle(), SW_HIDE);
  window.Destroy();
  ::CoUninitialize();
  return EXIT_SUCCESS;
}

