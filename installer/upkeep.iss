; Inno Setup recipe for Upkeep-Setup-<version>.exe (https://jrsoftware.org/isinfo.php).
; build.py runs it after PyInstaller has made dist\Upkeep.exe:
;     ISCC /DAppVersion=1.0.0 installer\upkeep.iss
;
; Installs for the current user only, so no admin rights are needed:
;     the app      -> %LOCALAPPDATA%\Programs\Upkeep\Upkeep.exe
;     shortcuts    -> Start Menu (+ desktop if ticked)
;     uninstaller  -> Windows Settings > Apps
; Your cache and data stay in %APPDATA%\Upkeep and are kept on uninstall or
; update, so installing a new version just replaces the program.

#ifndef AppVersion
  #define AppVersion "dev"
#endif

[Setup]
; Never change AppId: it is how Windows knows a new version is an update of this app.
AppId={{836EABBF-180D-4F63-9BE2-17D75C599FBC}
AppName=Upkeep
AppVersion={#AppVersion}
AppPublisher=Solmejk
AppPublisherURL=https://github.com/Solmejk/MTG_APP
AppSupportURL=https://github.com/Solmejk/MTG_APP/issues
AppUpdatesURL=https://github.com/Solmejk/MTG_APP/releases
DefaultDirName={localappdata}\Programs\Upkeep
DefaultGroupName=Upkeep
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Upkeep-Setup-{#AppVersion}
SetupIconFile=..\files\assets\app_icon.ico
UninstallDisplayIcon={app}\Upkeep.exe
UninstallDisplayName=Upkeep
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Upkeep.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Upkeep"; Filename: "{app}\Upkeep.exe"
Name: "{autodesktop}\Upkeep"; Filename: "{app}\Upkeep.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Upkeep.exe"; Description: "{cm:LaunchProgram,Upkeep}"; Flags: nowait postinstall skipifsilent
