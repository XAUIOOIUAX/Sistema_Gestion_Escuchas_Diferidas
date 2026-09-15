# Instalación en una máquina externa

**No hace falta instalar Python ni ninguna otra cosa.** Son dos ejecutables y
nada más.

---

## Paso 1 — El programa (todos los equipos)

Ejecutar **`EscuchasDiferidas_v1.0_Setup.exe`** (163 MB).

- Se instala en `C:\Users\<usuario>\AppData\Local\Programs\EscuchasDiferidas`
- **No pide permisos de administrador**
- Crea acceso directo en el escritorio si se tilda la opción

**Por qué no va en `Archivos de programa`:** el programa escribe al lado suyo
—la base de la causa, el perfil del analista, el log de errores— y esa carpeta
necesita permisos de administrador para escribir. Instalándolo en la carpeta
del usuario, el analista encuentra su base donde instaló.

Con esto ya se puede: importar CDs, escuchar, desgrabar, marcar interés,
interpretar y exportar informes.

Lo único que falta es transcribir automáticamente.

---

## Paso 1 bis — Habilitar el equipo (una vez por máquina)

Al abrirse por primera vez el programa no entra: muestra un **código de
equipo** y espera una clave. Recién después toca la base de datos.

**Del lado del analista:** aprieta *Copiar*, manda el código, pega la clave que
le devuelvan, listo. Es para siempre y no se vuelve a pedir.

**Del lado de quien administra:**

```bash
py herramientas/firmar_licencia.py A1B2C-3D4E5-F6A7B-8C9D0
```

Imprime la clave para ESE equipo y para ninguno otro. Se manda por donde sea:
no es un secreto, no sirve en otra máquina.

### Lo que hay que cuidar

`herramientas/clave_privada.txt` es la credencial del sistema. Con ella se
emiten claves para cualquier equipo; sin ella no se emite ninguna, ni teniendo
el código fuente entero. Está en `.gitignore` y no debe salir de la máquina de
quien administra. **Si se pierde, no hay forma de emitir claves nuevas** y hay
que generar otro par —lo que invalida todas las ya entregadas.

Conviene anotar a quién se le dio cada clave. El programa no lleva ese
registro, y es el dato que sirve el día que haya que saber quién tiene la
herramienta.

### Habilitar varios equipos de una vez

La clave se puede dejar escrita de antemano en:

```
<carpeta del programa>\datos\licencia.clave
```

El archivo va **en UTF-8 sin BOM** y con la clave sola adentro. El detalle no
es menor: `Set-Content -Encoding utf8` de PowerShell 5.1 antepone un BOM, y
hasta la versión 1.0 eso hacía rechazar una clave correcta con el cartel «esa
clave no habilita este equipo» —que manda a sospechar justo de lo que estaba
bien—. Desde entonces el programa lo tolera, pero la forma segura es:

```powershell
[System.IO.File]::WriteAllText($ruta, $clave, (New-Object System.Text.UTF8Encoding($false)))
```

### Qué protege esto y qué no

Evita que la herramienta circule por descuido: copiar la carpeta a otra máquina
no se lleva la habilitación. **No** frena a alguien que se proponga quitar la
verificación del ejecutable —una aplicación de escritorio se puede modificar—.
La protección de fondo es administrativa; esto es la barrera técnica.

---

## Paso 2 — El motor de transcripción (sólo donde se transcribe)

Ejecutar **`RecursosWhisper_v1.0_Setup.exe`**.

**Elegir la MISMA carpeta donde se instaló el programa.** El instalador
verifica que ahí esté `EscuchasDiferidas.exe` y corta con un aviso si no: los
recursos en otro lado no los encuentra nadie, y el analista se queda esperando
que la transcripción funcione.

Trae todo: el modelo de Whisper, ffmpeg y el motor empaquetado.

```
EscuchasDiferidas\
    EscuchasDiferidas.exe
    recursos\
        motor\whisper_worker.exe      ← el motor, con whisper y torch adentro
        ffmpeg\bin\ffmpeg.exe
        modelos\whisper\small.pt
```

El programa lo encuentra solo. No hay nada que configurar.

---

## Cómo repartirlo

**Conviene separar los roles.** La transcripción es un proceso de máquina que
corre en lote y sin supervisión: no tiene sentido poner el motor en cada puesto
para que cada analista transcriba sus propios audios.

| Rol | Qué instalar |
|---|---|
| **Analista** (desgraba, interpreta, informa) | Paso 1 |
| **Equipo de transcripción** | Pasos 1 y 2 |

---

## Advertencias

**Windows va a avisar que el programa no está firmado.** SmartScreen dice
«Windows protegió su PC»: hay que hacer clic en *Más información* → *Ejecutar
de todas formas*. Se soluciona firmando los instaladores con un certificado,
que es un trámite aparte.

**Un equipo, una base.** Cada instalación tiene su propio
`datos\escuchas.db` y el trabajo hecho en una no aparece en la otra. Si dos
analistas trabajan la misma causa, hoy son dos bases separadas. La pantalla
**Auditoría** muestra arriba qué base se está usando, que es lo único que
distingue una instalación de otra.

**Al desinstalar NO se borran los datos.** Adentro de esa carpeta puede haber
meses de trabajo sobre una causa en trámite.

**La transcripción tarda.** Referencia medida en un equipo de 4 núcleos sin
placa de video: una causa con 27 minutos de audio lleva unos 20 minutos. Se
lanza y se deja corriendo.

---

## Verificación después de instalar

1. Abrir el programa: pide la habilitación (paso 1 bis) y después el
   nombre del analista. Las dos cosas, una sola vez por equipo.
2. **Auditoría** → el bloque «BASE DE DATOS EN USO» muestra la ruta.
3. **Casos** → crear una causa de prueba.
4. **Importar** → elegir una carpeta de CD; tiene que mostrar el preview antes
   de escribir nada.
5. Sólo donde se instaló el motor: en **Tabla TOTAL**, marcar una comunicación
   con la tecla `I` y apretar **«🎙 Transcribir marcadas»**. Si falta algo, el
   programa dice exactamente qué.

Si algo falla, queda en `datos\errores.log` con la versión, el analista y en
qué pantalla estaba. Desde el aviso de error hay un botón para abrir esa
carpeta.
