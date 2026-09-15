; Instalador del Sistema de Gestión de Escuchas Diferidas.
;
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" instalador\EscuchasDiferidas.iss
;
; Dos decisiones que conviene no cambiar sin leer esto:
;
; 1. SE INSTALA EN LA CARPETA DEL USUARIO, no en Program Files. El programa
;    escribe al lado suyo —la base de la causa, el perfil, el log de errores—
;    y Program Files no deja escribir sin permisos de administrador. En
;    `app/config.py` hay una salida de emergencia que manda los datos a
;    %LOCALAPPDATA% si el destino es de sólo lectura, pero conviene no
;    depender de ella: el analista espera encontrar su base donde instaló.
;
; 2. NO SE BORRAN LOS DATOS AL DESINSTALAR. Adentro de esa carpeta puede haber
;    meses de trabajo sobre una causa en trámite. Desinstalar el programa no
;    puede llevarse la prueba.

#define Nombre        "Sistema de Gestion de Escuchas Diferidas"
#define NombreCorto   "EscuchasDiferidas"
#define Version       "1.0"
#define Editor        "Seccion de Investigaciones"
#define Ejecutable    "EscuchasDiferidas.exe"

; Ruta de la compilacion de PyInstaller. Se puede pasar por linea de comandos:
;     ISCC.exe /DOrigen="F:\EscuchasDiferidas\dist\EscuchasDiferidas" ...
#ifndef Origen
  #define Origen "..\dist\EscuchasDiferidas"
#endif
#ifndef Salida
  #define Salida "."
#endif

[Setup]
AppId={{B7E4A1C2-5F3D-4A8B-9E6C-2D1F8A4B7C39}
AppName={#Nombre}
AppVersion={#Version}
AppPublisher={#Editor}
DefaultDirName={userpf}\{#NombreCorto}
DefaultGroupName={#Nombre}
DisableProgramGroupPage=yes
; Sin privilegios de administrador: se instala para el usuario que lo corre.
PrivilegesRequired=lowest
OutputDir={#Salida}
OutputBaseFilename={#NombreCorto}_v{#Version}_Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; El paquete ronda los 640 MB; sin esto el instalador no arranca en equipos
; con poco espacio y el error no dice por qué.
ExtraDiskSpaceRequired=0
DirExistsWarning=no
UninstallDisplayName={#Nombre}

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"; \
    GroupDescription: "Accesos directos:"

[Files]
Source: "{#Origen}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#Nombre}"; Filename: "{app}\{#Ejecutable}"
Name: "{group}\Carpeta de datos"; Filename: "{app}\datos"
Name: "{group}\Desinstalar"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#NombreCorto}"; Filename: "{app}\{#Ejecutable}"; Tasks: escritorio

[Run]
Filename: "{app}\{#Ejecutable}"; Description: "Abrir el programa"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Nada. Los datos de la causa se quedan: ver el encabezado de este archivo.

[Messages]
es.WelcomeLabel2=Se va a instalar [name/ver].%n%nEl motor de transcripción (Whisper) y el modelo NO vienen incluidos: se copian aparte en la carpeta «recursos» junto al programa. Ver el README.
