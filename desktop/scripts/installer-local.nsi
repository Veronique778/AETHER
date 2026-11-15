Unicode true
RequestExecutionLevel user
!include "MUI2.nsh"
!include "LogicLib.nsh"
Name "AETHER 1.0.0"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\AETHER"
Icon "..\src-tauri\icons\icon.ico"
UninstallIcon "..\src-tauri\icons\icon.ico"
VIProductVersion "1.0.0.0"
VIAddVersionKey "ProductName" "AETHER"
VIAddVersionKey "FileDescription" "AETHER Desktop installer"
VIAddVersionKey "FileVersion" "1.0.0"
VIAddVersionKey "LegalCopyright" "AETHER team"
!define UNKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\space.aether.desktop"
!define WVKEY "Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
Section
  SetShellVarContext current
  SetRegView 32
  ReadRegStr $0 HKLM "${WVKEY}" "pv"
  ${If} $0 == ""
    ReadRegStr $0 HKCU "${WVKEY}" "pv"
  ${EndIf}
  !ifdef WEBVIEW2
  ${If} $0 == ""
  ${OrIf} $0 == "0.0.0.0"
    InitPluginsDir
    SetOutPath "$PLUGINSDIR"
    SetCompress off
    File /oname=WebView2Setup.exe "${WEBVIEW2}"
    SetCompress auto
    ExecWait '"$PLUGINSDIR\WebView2Setup.exe" /silent /install' $0
    ${If} $0 != 0
      MessageBox MB_ICONSTOP "WebView2 installation failed ($0)." /SD IDOK
      SetErrorLevel 1
      Abort
    ${EndIf}
  ${EndIf}
  !else
  ${If} $0 == ""
    MessageBox MB_ICONINFORMATION "AETHER needs Microsoft Edge WebView2 Runtime (included in Windows 11 and updated Windows 10). If AETHER does not start, install it from https://go.microsoft.com/fwlink/p/?LinkId=2124703" /SD IDOK
  ${EndIf}
  !endif
  SetOutPath "$INSTDIR"
  File /oname=AETHER.exe "${APP}"
  File /oname=aether-backend.exe "${BACKEND}"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateShortCut "$SMPROGRAMS\AETHER.lnk" "$INSTDIR\AETHER.exe"
  CreateShortCut "$DESKTOP\AETHER.lnk" "$INSTDIR\AETHER.exe"
  WriteRegStr HKCU "${UNKEY}" "DisplayName" "AETHER"
  WriteRegStr HKCU "${UNKEY}" "DisplayVersion" "1.0.0"
  WriteRegStr HKCU "${UNKEY}" "Publisher" "AETHER team"
  WriteRegStr HKCU "${UNKEY}" "DisplayIcon" "$INSTDIR\AETHER.exe"
  WriteRegStr HKCU "${UNKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
SectionEnd
Section "Uninstall"
  SetShellVarContext current
  SetRegView 32
  Delete "$SMPROGRAMS\AETHER.lnk"
  Delete "$DESKTOP\AETHER.lnk"
  Delete "$INSTDIR\AETHER.exe"
  Delete "$INSTDIR\aether-backend.exe"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNKEY}"
SectionEnd
