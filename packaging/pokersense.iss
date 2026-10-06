; Inno Setup: builds an offline AA engineering preview, not a release acceptance.
;
; Expects `dist/PokerSense-AA/` (PyInstaller's COLLECT folder, containing
; PokerSense-AA.exe + dependencies) to already exist -- run the PyInstaller
; build first:
;   pyinstaller packaging/pokersense.spec --distpath dist --workpath build --noconfirm
;   iscc packaging/pokersense.iss
;
; Local frozen-executable smoke checks precede CI packaging. Installation and
; hardware acceptance are distinct checks, not implied by successful compilation.

#define MyAppName "PokerSense AA Preview"
#define MyAppVersion "0.2.0-dev1"
#define MyWindowsVersion "0.2.0.1"
#define MyAppExeName "PokerSense-AA.exe"

[Setup]
AppId={{DAAA46F2-54F6-4B29-A71E-07A4520DA201}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyWindowsVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
OutputDir=..\dist
OutputBaseFilename=PokerSense-AA-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "..\dist\PokerSense-AA\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
