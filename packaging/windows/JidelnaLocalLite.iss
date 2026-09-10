; Inno Setup script for JidelnaLocalLite (Windows production candidate).
; Display product name: JLL. Installer file: JidelnaLocalLite-0.6.1-Setup.exe
; Authenticode is NOT REQUIRED — release is UNSIGNED BY DESIGN.
; Build after PyInstaller onedir: dist\JidelnaLocalLite\

#define MyAppName "JidelnaLocalLite"
#define MyProductName "JLL"
#define MyCompany "Altisima"
#define MyAppVersion "0.6.1"
#define MyFileVersion "0.6.1.0"
#define MyAppExeName "JidelnaLocalLite.exe"
; Paths relative to this .iss file (packaging/windows/).
#define MyOnedirSource "..\..\dist\JidelnaLocalLite"
#define MyOutputDir "..\..\dist\release\0.6.1"

[Setup]
AppId={{A6F2C8E1-4B7D-4F9A-9C31-8E5D2A7B6C10}
AppName={#MyProductName}
AppVersion={#MyAppVersion}
AppVerName={#MyProductName} {#MyAppVersion}
AppPublisher={#MyCompany}
AppCopyright=Copyright © 2026 Altisima
DefaultDirName=C:\Gastro\{#MyAppName}
DefaultGroupName={#MyProductName}
DisableProgramGroupPage=yes
OutputDir={#MyOutputDir}
OutputBaseFilename={#MyAppName}-{#MyAppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyProductName}
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=jll.ico
VersionInfoVersion={#MyFileVersion}
VersionInfoCompany={#MyCompany}
VersionInfoDescription=JLL – Jídelna Lokal Lite Setup
VersionInfoProductName={#MyProductName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCopyright=Copyright © 2026 Altisima
VersionInfoOriginalFileName={#MyAppName}-{#MyAppVersion}-Setup.exe
; SignTool intentionally unset — UNSIGNED BY DESIGN (Authenticode not required).

[Languages]
Name: "czech"; MessagesFile: "compiler:Languages\Czech.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Vytvořit zástupce na ploše"; GroupDescription: "Další ikony:"; Flags: unchecked

[Files]
Source: "{#MyOnedirSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{commonappdata}\{#MyAppName}"
Name: "{commonappdata}\{#MyAppName}\config"; Permissions: users-modify
Name: "{commonappdata}\{#MyAppName}\logs"; Permissions: users-modify
Name: "{commonappdata}\{#MyAppName}\reset-backups"; Permissions: users-modify

[Icons]
Name: "{group}\{#MyProductName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyProductName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Spustit {#MyProductName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Do NOT wipe ProgramData config/logs/reset-backups by default.
