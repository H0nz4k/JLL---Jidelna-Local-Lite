; Inno Setup script for JidelnaLocalLite (Windows production candidate).
; ProductName: JidelnaLocalLite
; Do not invent a company/publisher legal name — AppPublisher uses product name only.
; Build after PyInstaller onedir: dist\JidelnaLocalLite\
; This candidate is UNSIGNED unless an Authenticode cert is wired externally.

#define MyAppName "JidelnaLocalLite"
#define MyAppVersion "0.6.0"
#define MyAppExeName "JidelnaLocalLite.exe"
#define MyRepoRoot "..\.."
#define MyOnedirSource "{#MyRepoRoot}\dist\JidelnaLocalLite"
#define MyOutputDir "{#MyRepoRoot}\dist\release\0.6.0"

[Setup]
AppId={{A6F2C8E1-4B7D-4F9A-9C31-8E5D2A7B6C10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppName}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#MyOutputDir}
OutputBaseFilename={#MyAppName}-{#MyAppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
; SignTool intentionally unset — unsigned candidate unless cert is provided.

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
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Spustit {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Do NOT wipe ProgramData config/logs/reset-backups by default.
