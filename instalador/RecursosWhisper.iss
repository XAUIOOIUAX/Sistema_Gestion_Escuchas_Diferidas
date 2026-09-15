; Paquete de recursos de transcripción: el modelo de Whisper y ffmpeg.
;
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" instalador\RecursosWhisper.iss
;
; Va SEPARADO del programa a propósito. Son ~650 MB que cambian una vez cada
; nunca, mientras que el programa se actualiza seguido: juntos, cada
; actualización obligaría a mover el modelo de nuevo a cada equipo.
;
; Se instala en `recursos\` AL LADO del ejecutable, que es donde
; `config.DIRS_RECURSOS_WHISPER` lo busca.
;
; Trae TODO lo necesario para transcribir: el modelo, ffmpeg y el motor
; empaquetado (`whisper_worker.exe`, con whisper y torch adentro).
;
; NO hace falta instalar Python ni nada más. Antes sí: el motor corría en un
; intérprete del equipo y había que hacer `pip install openai-whisper`, que no
; es algo que se le pueda pedir a un puesto de trabajo de una fiscalía.
;
; En los equipos que sólo desgraban sobre lo ya transcripto, este paquete no
; hace falta.

#define Nombre      "Motor de transcripcion - Escuchas Diferidas"
#define Version     "1.0"
#define Editor      "Seccion de Investigaciones"
#define AppNombre   "EscuchasDiferidas"

#ifndef Origen
  #define Origen "..\recursos_stage\recursos"
#endif
#ifndef Salida
  #define Salida "."
#endif

[Setup]
AppId={{C8F5B2D3-6A4E-4B9C-8F7D-3E2A9B5C8D41}
AppName={#Nombre}
AppVersion={#Version}
AppPublisher={#Editor}
; La MISMA carpeta donde se instaló el programa: los recursos van al lado del
; ejecutable. Si el programa no está instalado, el instalador avisa y corta.
DefaultDirName={userpf}\{#AppNombre}
DisableProgramGroupPage=yes
DisableDirPage=no
PrivilegesRequired=lowest
OutputDir={#Salida}
OutputBaseFilename=RecursosWhisper_v{#Version}_Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DirExistsWarning=no
UninstallDisplayName={#Nombre}

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "{#Origen}\*"; DestDir: "{app}\recursos"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Code]
{ No dejar que se instale en una carpeta donde no está el programa: los
  recursos ahí no los va a encontrar nadie y el analista se queda esperando
  que la transcripción funcione. }
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    if not FileExists(ExpandConstant('{app}\{#AppNombre}.exe')) then
    begin
      Result := False;
      MsgBox('En esa carpeta no está {#AppNombre}.exe.' + #13#10#13#10 +
             'Los recursos tienen que quedar AL LADO del programa para que ' +
             'los encuentre. Elegí la carpeta donde instalaste el Sistema de ' +
             'Gestión de Escuchas Diferidas.', mbError, MB_OK);
    end;
  end;
end;

[Messages]
es.WelcomeLabel2=Se va a instalar el motor de transcripción completo: el modelo de Whisper, ffmpeg y el ejecutable del motor.%n%nNo hace falta instalar Python ni ninguna otra cosa.%n%nEn los puestos que sólo desgraban sobre material ya transcripto, este paquete no es necesario.
