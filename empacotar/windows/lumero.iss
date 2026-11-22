; Instalador .exe do Lumero para Windows (Inno Setup 6)
; Gerado pelo GitHub Actions:  ISCC.exe /DVersao=1.0.0 empacotar\windows\lumero.iss
; O Setup copia os arquivos e roda o windows\instalar.ps1, que instala o Python, o
; Ollama e os modelos (as mesmas perguntas do instalador em script).

#ifndef Versao
  #define Versao "1.0.0"
#endif

[Setup]
AppId={{6B1E5C2A-4F7D-4C1B-9B8E-2D5A7F3C9E41}
AppName=Lumero
AppVersion={#Versao}
AppVerName=Lumero {#Versao}
AppPublisher=Lumero
DefaultDirName={localappdata}\Programs\Lumero
PrivilegesRequired=lowest
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputDir=..\..\pacotes
OutputBaseFilename=Lumero-{#Versao}-Windows-Setup
SetupIconFile=..\..\assets\lumero.ico
UninstallDisplayIcon={localappdata}\Lumero\lumero.ico
UninstallDisplayName=Lumero
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ShowLanguageDialog=no
MinVersion=10.0

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Messages]
pt.FinishedLabel=O Lumero foi instalado. Procure "Lumero" no menu Iniciar ou aperte Ctrl+Alt+A.

[Files]
Source: "..\..\lumero.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\lumero_gui.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\lumero_gui.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\assets\lumero.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "..\..\assets\lumero.png"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "..\..\windows\instalar.ps1"; DestDir: "{app}\windows"; Flags: ignoreversion
Source: "..\..\windows\desinstalar.ps1"; DestDir: "{app}\windows"; Flags: ignoreversion

[Run]
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\windows\instalar.ps1"" -SemRegistro"; \
  StatusMsg: "Configurando o Lumero (Python, Ollama e modelos de IA)..."; \
  Flags: waituntilterminated
Filename: "{localappdata}\Lumero\venv\Scripts\pythonw.exe"; \
  Parameters: """{localappdata}\Lumero\lumero_gui.py"""; \
  Description: "Abrir o Lumero agora"; Flags: postinstall nowait skipifsilent skipifdoesntexist

[UninstallRun]
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\windows\desinstalar.ps1"" -Confirmado"; \
  Flags: waituntilterminated; RunOnceId: "LumeroDesinstalar"
