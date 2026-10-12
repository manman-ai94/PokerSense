; Inno Setup: the Windows installer of the AA window.
;
; Expects `dist/PokerSense-AA/` (PyInstaller's COLLECT folder, containing
; PokerSense-AA.exe + dependencies) to already exist -- run the PyInstaller
; build first:
;   pyinstaller packaging/pokersense.spec --distpath dist --workpath build --noconfirm
;   iscc packaging/pokersense.iss
; Release builds pass the version: iscc /DMyAppVersion=0.3.0 /DMyWindowsVersion=0.3.0.0
;
; Per-user install (no administrator rights), desktop shortcut, Start-menu
; "check for updates" shortcut. The in-app updater runs this installer with
; /SILENT /WAITPID=<pid> /RELAUNCH=1: it waits for the running program to exit,
; replaces the files and opens the program again.

#define MyAppName "PokerSense AA"
#ifndef MyAppVersion
  #define MyAppVersion "0.2.0.dev1"
#endif
#ifndef MyWindowsVersion
  #define MyWindowsVersion "0.2.0.1"
#endif
#define MyAppExeName "PokerSense-AA.exe"

[Setup]
AppId={{DAAA46F2-54F6-4B29-A71E-07A4520DA201}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=PokerSense
VersionInfoVersion={#MyWindowsVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
AllowNoIcons=yes
OutputDir=..\dist
OutputBaseFilename=PokerSense-AA-Setup
SetupIconFile=assets\PokerSense.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
PrivilegesRequired=lowest
CloseApplications=force
RestartApplications=no

[Languages]
#if FileExists(AddBackslash(CompilerPath) + "Languages\ChineseSimplified.isl")
Name: "chs"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#else
Name: "english"; MessagesFile: "compiler:Default.isl"
#endif

[InstallDelete]
; A new version's libraries replace the old ones entirely.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\recognition"

[Files]
Source: "..\dist\PokerSense-AA\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\{#MyAppName} 检查更新"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--update-now"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Flags: nowait; Check: RelaunchAfterUpdate

[Code]
const
  SYNCHRONIZE = $00100000;

function OpenProcess(Access: Cardinal; Inherit: Boolean; Pid: Cardinal): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function WaitForSingleObject(Handle: THandle; Milliseconds: Cardinal): Cardinal;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function CloseHandle(Handle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

{ The updater passes its own process id; wait (at most a minute) for it to
  exit so its files can be replaced. }
function InitializeSetup(): Boolean;
var
  Pid: Integer;
  Handle: THandle;
begin
  Pid := StrToIntDef(ExpandConstant('{param:WAITPID|0}'), 0);
  if Pid > 0 then
  begin
    Handle := OpenProcess(SYNCHRONIZE, False, Pid);
    if Handle <> 0 then
    begin
      WaitForSingleObject(Handle, 60000);
      CloseHandle(Handle);
    end;
  end;
  Result := True;
end;

function RelaunchAfterUpdate(): Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;
