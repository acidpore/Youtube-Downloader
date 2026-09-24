; Inno Setup script for the Windows installer.
; Build: iscc /DAppVersion=1.2.3 packaging\installer.iss   (after packaging\build.py)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F1B3C2E-6B8A-4E0B-9C62-3E2A0F6C9D11}
AppName=YouTube Downloader
AppVersion={#AppVersion}
AppPublisher=acidpore
DefaultDirName={autopf}\YouTube Downloader
DefaultGroupName=YouTube Downloader
UninstallDisplayIcon={app}\YouTubeDownloader.exe
OutputDir=..\dist
OutputBaseFilename=YouTubeDownloader-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\YouTubeDownloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\YouTube Downloader"; Filename: "{app}\YouTubeDownloader.exe"
Name: "{group}\Uninstall YouTube Downloader"; Filename: "{uninstallexe}"
Name: "{autodesktop}\YouTube Downloader"; Filename: "{app}\YouTubeDownloader.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\YouTubeDownloader.exe"; Description: "{cm:LaunchProgram,YouTube Downloader}"; Flags: nowait postinstall skipifsilent
