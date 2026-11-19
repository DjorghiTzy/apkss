; Installer Windows (Inno Setup 6). Jalankan build_windows.bat terlebih dahulu.
; Kompilasi: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
#define AppName "Screenshot Manager"
#ifndef AppVersion
  #define AppVersion "1.0.2"
#endif

[Setup]
AppId={{6F1C2E4A-8B3D-4E59-9A71-5C2D0B7E3F10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Screenshot Manager
DefaultDirName={localappdata}\Programs\ScreenshotManager
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=ScreenshotManager-Setup-{#AppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\ScreenshotManager.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
; tutup aplikasi yang sedang jalan saat update, data pengguna tidak disentuh
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\ScreenshotManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\ScreenshotManager.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\ScreenshotManager.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ScreenshotManager.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall
