; AURCO Inventory Manager - Inno Setup installer script
; Build the EXE first:   pyinstaller packaging\aurco.spec --noconfirm --clean
; Then compile this file with Inno Setup 6:  ISCC.exe packaging\installer.iss
; Produces: Output\AURCO_Inventory_Manager_Setup_1.1.0.exe

#define AppName        "AURCO Inventory Manager"
#define AppVersion     "2.20.0"
#define AppPublisher   "AURCO"
#define AppAuthor      "Zain Shami"
#define AppExeName     "AURCO Inventory Manager.exe"

[Setup]
AppId={{8F3B1C42-5A77-4E2B-9C61-AURCO0000001}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright=Created by {#AppAuthor}
DefaultDirName={autopf}\AURCO\{#AppName}
DefaultGroupName=AURCO
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
OutputDir=..\Output
OutputBaseFilename=AURCO_Inventory_Manager_Setup_{#AppVersion}
SetupIconFile=..\assets\aurco.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequired=admin
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";  Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startmenu";    Description: "Create a &Start Menu shortcut"; GroupDescription: "Shortcuts:"
Name: "startupicon";  Description: "Start {#AppName} when Windows starts"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "datafolder";   Description: "Create the default data folder D:\AURCO Inventory (if drive D: exists)"; GroupDescription: "Data:"

[Files]
Source: "..\dist\{#AppName}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\{#AppName}\*";             DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docs\USER_GUIDE.md";            DestDir: "{app}\docs"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#AppName}";           Filename: "{app}\{#AppExeName}"; Tasks: startmenu
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}";      Tasks: startmenu
Name: "{autodesktop}\{#AppName}";     Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}";     Filename: "{app}\{#AppExeName}"; Tasks: startupicon

[Dirs]
Name: "D:\AURCO Inventory";                  Tasks: datafolder; Check: DriveDExists
Name: "D:\AURCO Inventory\Database";         Tasks: datafolder; Check: DriveDExists
Name: "D:\AURCO Inventory\Inventory";        Tasks: datafolder; Check: DriveDExists
Name: "D:\AURCO Inventory\Delivery Notes";   Tasks: datafolder; Check: DriveDExists
Name: "D:\AURCO Inventory\Returns";          Tasks: datafolder; Check: DriveDExists
Name: "D:\AURCO Inventory\Stock Transfers";  Tasks: datafolder; Check: DriveDExists
Name: "D:\AURCO Inventory\Stock Adjustments";Tasks: datafolder; Check: DriveDExists
Name: "D:\AURCO Inventory\Stock Counts";     Tasks: datafolder; Check: DriveDExists
Name: "D:\AURCO Inventory\Reports";          Tasks: datafolder; Check: DriveDExists
Name: "D:\AURCO Inventory\Attachments";      Tasks: datafolder; Check: DriveDExists
Name: "D:\AURCO Inventory\Exports";          Tasks: datafolder; Check: DriveDExists
Name: "D:\AURCO Inventory\Backups";          Tasks: datafolder; Check: DriveDExists
Name: "D:\AURCO Inventory\Logs";             Tasks: datafolder; Check: DriveDExists

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Never delete the user's data folder - only application files are removed.
Type: filesandordirs; Name: "{app}\_internal\__pycache__"

[Code]
function DriveDExists(): Boolean;
begin
  Result := DirExists('D:\');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    Log('AURCO Inventory Manager installed. Data location is chosen on first run.');
end;
