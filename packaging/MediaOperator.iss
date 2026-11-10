
#define AppVersion "0.4.1"
[Setup]
AppId={{102997A8-6D84-4A52-B13E-9F5E9F29DD64}
AppName=Media Operator
AppVersion={#AppVersion}
AppPublisher=Media Operator
DefaultDirName={code:DefaultInstallDir}
DisableDirPage=no
DefaultGroupName=Media Operator
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
AppMutex=MediaOperatorDesktopWindow
DisableProgramGroupPage=yes
OutputDir={#MediaOutput}
OutputBaseFilename=MediaOperatorSetup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\MediaOperator.exe
SetupLogging=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[InstallDelete]
Type: files; Name: "{app}\_internal\app\static\media-ui\app.js"
Type: files; Name: "{app}\_internal\app\static\media-ui\desktop.js"
Type: files; Name: "{app}\_internal\app\static\media-ui\index.html"
Type: files; Name: "{app}\_internal\app\static\media-ui\styles.css"
Type: dirifempty; Name: "{app}\_internal\app\static\media-ui"

[Files]
Source: "{#MediaDist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#WebViewSetup}"; DestDir: "{tmp}"; DestName: "WebView2Setup.exe"; Flags: deleteafterinstall; Check: NeedsWebView

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"

[Icons]
Name: "{autoprograms}\Media Operator"; Filename: "{app}\MediaOperator.exe"
Name: "{autodesktop}\Media Operator"; Filename: "{app}\MediaOperator.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MediaOperator.exe"; Description: "Open Media Operator"; Flags: postinstall skipifsilent nowait

[Code]
function DefaultInstallDir(Param: String): String;
begin
  if DirExists('D:\') then
    Result := 'D:\Media Operator'
  else
    Result := ExpandConstant('{localappdata}\Programs\Media Operator');
end;

function WebViewAt(Root: Integer): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(Root, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version)
      and (Version <> '') and (Version <> '0.0.0.0');
end;

function NeedsWebView(): Boolean;
begin
  Result := not (WebViewAt(HKLM32) or WebViewAt(HKLM64) or WebViewAt(HKCU));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep = ssPostInstall) and NeedsWebView() then
  begin
    if not Exec(ExpandConstant('{tmp}\WebView2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
      or ((ResultCode <> 0) and not (ResultCode = 3010)) then
      RaiseException('WebView2 Runtime installation failed. Check your internet connection and run Setup again.');
  end;
end;
