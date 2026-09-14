# Sistema de Gestión de Escuchas Diferidas

Aplicación de escritorio multi-caso para la gestión, análisis y exportación de
comunicaciones interceptadas (escuchas diferidas).

Migra la macro VBA original (`1_ElegirRaiz_FINAL_v2.txt`) a una aplicación
**Python + PySide6 + SQLite**, eliminando la dependencia de Excel como almacén
de datos. El diseño visual sigue `mockup_interfaz_v2.html` y la arquitectura el
blueprint `Pseudocodigo_Escuchas_Diferidas.txt`.

## Requisitos

- Python 3.10+ (probado con 3.14)
- Dependencias en `requirements.txt` (PySide6, openpyxl, python-docx, pytest)

## Puesta en marcha

```powershell
# 1. Crear el entorno virtual (una sola vez)
python -m venv .venv

# 2. Activar e instalar dependencias
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Ejecutar la aplicación
python main.py

# 4. Correr las pruebas
pytest
```

La base de datos se crea automáticamente en `datos/escuchas.db` al primer
arranque.

## Estructura del proyecto

```
app/
  config.py              Constantes ajustables (patrón de audio, extensiones, offsets…)
  db.py                  Esquema SQLite + conexión/inicialización + migraciones
  models.py              Dataclasses de dominio (RegistroParseado, ResumenPreview…)
  repositorios.py        Acceso a datos (casos, abonados, registros, avisos, memoria)
  sesion.py              Identidad del analista que firma cada anotación
  core/                  Funciones puras (sin I/O, testeables)
    normalizers.py         números, claves, acentos (NFKD), clave de dedup
    fechas.py              parseo/format de fecha-hora argentina
    direccion.py           saneo e inferencia ENTRANTE/SALIENTE/…
    cd_extractor.py        extracción del CD desde la ruta
    archivos.py            emparejamiento TXT/audio por nombre base
    colores.py             paleta automática por abonado
    interesado.py          "¿de quién es esta comunicación?" (la línea pinchada)
    interlocutor.py        "¿con quién habló?" (la otra punta)
  analisis/
    validador.py           avisos: coordenadas, fechas, duplicados parciales
    vinculos.py            vínculos entre casos (mismo abonado, misma antena)
    patrones.py            patrones de comunicación por abonado
    eventos.py             eventos clave de la causa
    cobertura.py           qué tramos del audio quedaron sin transcribir
    grafo.py               nodos y aristas del grafo de vínculos
  importadores/
    datos_causa.py         DatosCausa.txt: CD, fecha y abonados declarados
    txt_parser.py          lectura robusta UTF-8/ANSI + parseo clave:valor
    txt_importador.py      escaneo recursivo + emparejamiento + clasificación
    sms_importador.py      mensajes de texto
    excel_importador.py    alta desde .xlsx
    db_importador.py       traer registros de otra base del sistema
  exportadores/
    errores.py             InformeVacio
    excel_exportador.py    exporta el caso a .xlsx (TOTAL + INDICE, colores, ESTADO)
    word_judicial.py       informe judicial (formato Transcriptor Forense)
  servicios/
    importacion.py         orquesta preview + escritura en DB + avisos
    edicion.py             edición de campos con HistorialCambio + deshacer
    memoria.py             memoria de "corresponde a" (caso/global, migrar entre causas)
    transcripcion.py       recursos de Whisper + limpieza de texto y segmentos
    whisper_worker.py      motor Whisper en proceso aparte (stdin/stdout JSON)
    audios.py              localización de archivos de audio, con caché
    papelera.py            enviar a papelera y restaurar comunicaciones enteras
  ui/                    Interfaz PySide6
    tema.py                hoja de estilos (paleta del mockup v2), claro y oscuro
    atajos.py              lista única de atajos + chuleta de F1
    errores.py             captura de errores no manejados, con contexto y aviso
    flow_layout.py         disposición que acomoda solo los chips de filtro
    dialogos.py            exportación, color de abonado, analista, entrega
    ventana_principal.py   topbar + sidebar + stack de pantallas
    reproductor.py         audio embebido: velocidad, tramo, ancla, salida
    editor_onda.py         forma de onda con zoom, selección y tramos sin texto
    transcripcion_sincronizada.py  lista de frases sincronizada con el audio
    transcribir.py         proceso Whisper + diálogo de lote
    pantalla_casos.py      listar/crear/abrir casos
    pantalla_importar.py   elegir carpeta → preview → confirmar
    pantalla_resumen.py    estado de la causa y por dónde seguir
    pantalla_total.py      tabla TOTAL + panel de detalle
    pantalla_corregir.py   Desgrabar: la mesa de trabajo mecanográfica
    pantalla_indice.py     abonados, colores, líneas intervenidas, memoria
    pantalla_validaciones.py  avisos pendientes con enlace al registro
    pantalla_mapa.py       mapa de cobertura con sectores azimuth+radio
    pantalla_grafo.py      grafo de vínculos entre abonados
    pantalla_timeline.py   línea de tiempo de las comunicaciones
    pantalla_vinculos.py   vínculos detectados entre casos
    pantalla_exportaciones.py  historial de lotes de exportación con deshacer
    pantalla_papelera.py   comunicaciones eliminadas, con restaurar
    pantalla_auditoria.py  log de todas las acciones del sistema
main.py                  Punto de entrada
tests/                   Suite de pruebas (pytest)
```

## Cómo se trabaja una causa

El menú lateral sigue el orden del trabajo real: **PREPARAR** (Casos, Importar),
**TRABAJAR** (Resumen, Tabla TOTAL, Desgrabar, Índice, Validaciones),
**ANALIZAR** (Mapa, Grafo, Timeline, Vínculos) y **CERRAR** (Exportaciones,
Papelera, Auditoría).

1. **Casos** → crear o abrir la causa.
2. **Importar** → elegir la carpeta del CD; se ve un preview antes de escribir nada.
3. **Resumen** → dónde quedó el trabajo y por dónde seguir.
4. **Tabla TOTAL** → escuchar, marcar de interés, mandar a transcribir el lote.
5. **Desgrabar** → escuchar y escribir: anclar minutos, atribuir voces, corregir.
6. **Índice** → nombrar abonados, marcar las líneas intervenidas, elegir colores.
7. **Validaciones** → resolver lo que quedó dudoso en la importación.
8. **Mapa / Grafo / Timeline / Vínculos** → análisis.
9. **Exportaciones** → informes Word/Excel, con deshacer por lote.

El programa **retoma donde quedaste**: al abrirlo vuelve a la causa, la pantalla,
la comunicación y hasta el segundo del audio en que estabas. Lo que se guarda es
el LUGAR, no el trabajo —ese ya está en la base desde que se escribió—, así que
si el rastro se pierde lo único que pasa es que arranca en Casos.

### Ordenar la grilla

Clic en el encabezado de cualquier columna. Cada celda lleva su clave de orden
real, no el texto: las fechas van por `fecha_inicio_dt` (como texto,
"04/09/2026" sería anterior a "1/12/2025"), el CD y la duración como números
(el CD 10 va después del 2, no entre el 1 y el 2), el interés por su nivel.

Con la tabla ordenable, "fila N = registro N" deja de valer: el id del registro
viaja en la celda de Orden y `_registro_de_fila()` es lo único que traduce
posición a registro.

### Eliminar comunicaciones

En la Tabla TOTAL se eligen filas (Ctrl y Shift) y con el botón derecho se
eliminan. Es para deshacer una carga equivocada —el mismo día importado dos
veces desde carpetas distintas, una entrega que no era de la causa—: antes la
única salida era vaciar el caso entero, que se llevaba puesto todo el trabajo.

No se borran: van a la **Papelera** con todo su trabajo —transcripción,
contexto, interés, marcas de audio, historial de cambios— y vuelven enteras con
`Ctrl+Z` o desde esa pantalla. Vaciar la papelera es el único punto del programa
donde una comunicación deja de existir.

No es un borrado lógico con una columna "eliminado": hay 29 consultas distintas
sobre `Registro` y olvidarse de filtrar en una sola haría reaparecer una
comunicación borrada en un informe judicial. La fila **sale** de `Registro` y se
guarda entera en `Papelera`.

Lo que el filtro esconde nunca se borra, aunque `Ctrl+A` lo haya seleccionado.
Los audios en disco no se tocan.

### Las entregas (CD)

Una causa no recibe "un CD" sino una serie: cada entrega llega con su número,
su identificador, su fecha y las líneas intervenidas de ESE día, todo declarado
en su `DatosCausa.txt`. El Resumen lista las entregas con cuánto material trajo
cada una y cuánto se trabajó; un clic lleva a la Tabla TOTAL filtrada a esa
entrega. El informe judicial se arma con la misma unidad.

### La columna Interesado

Contesta "¿de quién es esta comunicación?" y es la guía con la que se recorre
la Tabla TOTAL. Sale, en este orden: los nombres de las dos puntas si están
cargados en el Índice; si no, el nombre de la línea intervenida de la que salió
el archivo; y si tampoco, su número. Recién cuando no se sabe nada dice
NO IDENTIFICADO. Así la columna sirve desde la primera importación y mejora
sola a medida que se nombran abonados.

Nombrar un abonado en el Índice recalcula la causa entera
(`repo.recalcular_interesados`), no solo las filas de ese número: el resultado
no depende del orden en que se fue nombrando.

### Rendimiento de la Tabla TOTAL

La grilla no pone widgets por fila. Contexto e Interés se editan con un
delegado que arma el desplegable recién al entrar a la celda; cuando eran dos
`QComboBox` permanentes por fila, poblar 300 comunicaciones tardaba **131
segundos** y en un equipo modesto no terminaba. Hoy son 0,2 s.

Si alguna vez hace falta volver a poner algo en una celda, que no sea con
`setCellWidget`: un widget por fila multiplica por el largo de la causa.

### Atajos

Con la grilla enfocada alcanza una tecla: `Espacio` reproduce, `I` marca o
desmarca **de interés**, `0` lo quita, `E` marca como escuchada, `Supr` manda a
la papelera. Desde cualquier parte: `Ctrl+Espacio`, `Ctrl+E`, `Ctrl+F`,
`Ctrl+Z` (deshacer el envío a la papelera) y `Alt+↑`/`Alt+↓`. `F1` muestra la
lista completa, y la pantalla Desgrabar tiene la suya propia.

### Transcripción automática

El motor Whisper corre en un **proceso separado** con un Python que tenga
`openai-whisper` + `torch` instalados; el venv de la aplicación no los necesita.
El modelo `.pt` y `ffmpeg.exe` se autodetectan en `recursos/` o en la carpeta
del Transcriptor Forense (ver `config.DIRS_RECURSOS_WHISPER`).

Hay dos motores. `openai` (modelos `.pt`) es el de fábrica; `faster`
(faster-whisper, modelos CTranslate2) agrega filtro VAD, que recorta los
silencios antes de transcribir. **`faster` no es más rápido en equipos chicos**
—medido en 4 CPU sin GPU es un 40% más lento con el mismo modelo—; su razón de
ser es dar acceso a `large-v3`, que con el motor `openai` sería impracticable.

Al transcribir en lote se elige el modelo, y el diálogo lista **solo los que
están en el equipo** y estima cuánto va a tardar el lote. Referencia medida
(sin GPU, 4 CPU lógicas): una causa de 27 min de audio tarda ~20 min con
`openai/small` y ~66 min con `faster/large-v3`.

El worker corre con control de alucinaciones: `condition_on_previous_text=False`
(sin él, ante un silencio Whisper arrastra su propia salida y entra en bucle
repitiendo la última frase), reintentos por temperatura y umbrales de
compresión, confianza y detección de voz. El `initial_prompt` está disponible
pero **apagado por defecto**: medido sobre audio real mejora la segmentación
pero agrega frases que no están en la grabación. Ver `config.WHISPER_PROMPT_BASE`.

Whisper devuelve cada frase con el segundo en que se dijo, y esos tiempos se
guardan: en el panel de detalle la transcripción queda **navegable** —clic en
una frase para saltar a ese momento, doble clic para corregirla— y se resalta
sola la frase que está sonando. Los registros sin tiempos (TXT importado, carga
manual) siguen usando el editor de texto libre.

### Tema claro y oscuro

El botón ☀/☾ de la barra superior alterna la paleta, y la elección se recuerda
en el equipo. El oscuro es el de fábrica —aguanta una jornada larga de escucha
con la luz baja—; el claro existe para proyectar el mapa o el grafo en una
reunión y para trabajar con luz de oficina.

### Dos grabaciones de la misma comunicación

Cuando las dos líneas de una llamada están intervenidas, la prestadora la
entrega dos veces con dos archivos distintos. Es **una** comunicación —una sola
fila, la deduplicación está bien— pero son dos audios, y suele escucharse mejor
el de la central más cercana. El segundo se guarda en
`Registro.audio_alternativo` y el reproductor ofrece pasar de uno al otro;
antes se descartaba en silencio y cuál sobrevivía dependía del orden de
escaneo.

### De interés: el eje del trabajo

El interés es **binario**: la comunicación sirve para el expediente o no sirve.
Antes había bajo/medio/alto y en la práctica el analista no distingue tres
grados mientras escucha; decide si la transcribe y si va al informe.

Esa marca es lo que ordena el circuito: se escucha, se marca con `I`, y
después **se transcribe lo marcado** (no la causa entera: son horas de máquina
sobre material que no va a ningún lado) y **eso mismo es lo que entra al
informe judicial**, que habla de "cada archivo considerado de interés".

Una base marcada con el esquema viejo se unifica al abrirla: bajo, medio y alto
pasan a "de interés", porque para lo que se usa el dato significaban lo mismo.

### Desgrabar: la mesa de trabajo

Desgrabar una escucha no es editar un texto: es escuchar y escribir a la vez.
El cursor tiene que quedarse donde está y el audio obedecer igual —parar, volver
dos segundos, bajar a 0,8×— sin que la mano salga del teclado. Eso es lo que
hacen oTranscribe, Express Scribe e InqScribe, y es lo que no se podía hacer
desde el panel de la Tabla TOTAL, donde el reproductor está al lado pero hay que
ir a buscarlo con el mouse.

La pantalla se llama **Desgrabar** y no "Corregir" a propósito: desde que los
tiempos de Whisper pasaron a ser conjetura (ver abajo), ahí no se corrige un
borrador, ahí se desgraba. "Transcribir" ya es el botón que lanza Whisper.

**La cola.** Aparecen las comunicaciones con borrador y sin revisar, en orden.
Al darlas por desgrabadas (`Ctrl+G`) se pasa sola a la siguiente.

**Los atajos se interceptan antes que el editor**, con un filtro de eventos: no
alcanza con `QShortcut`, porque el campo de texto que tiene el foco consume
teclas. El filtro solo actúa con esta pantalla a la vista, así que en el resto
del programa las mismas teclas siguen significando lo de siempre.

| Tecla | Qué hace |
|---|---|
| `Espacio` | Sonar desde la marca; al parar vuelve ahí (fuera del texto) |
| `Ctrl+Espacio` | Pausar y seguir, incluso escribiendo |
| `F2` | Corregir el texto de esta frase |
| `F3` / `F4` | Retroceder / adelantar 5 s |
| `F5` / `F6` | Más lento / más rápido (sin cambiar el tono) |
| `F7` / `F8` | Llevar el audio a la frase / la edición a lo que suena |
| `F9` | Repetir el tramo en bucle |
| `Ctrl+1` / `Ctrl+2` | Marcar quién habla |
| `Ctrl+T` | Fijar el minuto de esta frase acá y pasar a la siguiente |
| `Ctrl+Shift+T` | Anclarla y correr todas las de abajo lo mismo |
| `Ctrl+U` / `Ctrl+Supr` | Unir con la de arriba / quitar |
| `Enter` / `Shift+Enter` / `Ctrl+Enter` | Guardar / nueva abajo / partir |
| `Ctrl+Z` / `Ctrl+Y` | Deshacer / rehacer |

**El cursor de trabajo se ve.** Un filete verde marca la frase sobre la que
actúan los atajos; el fondo ámbar, la que está sonando. Mientras se sincroniza
van por lugares distintos, y ver las dos es justamente lo que hace falta.
Mientras el cursor fue invisible, tres reportes distintos de "se va a otro lado"
tenían todos la misma causa.

### Los tiempos de Whisper son conjetura, no dato

El motor se desfasa: a partir de cierto punto toda la transcripción queda unos
segundos corrida. Esos tiempos sirven para ordenar la lista, no para afirmar
cuándo se dijo algo —que es lo que un informe judicial afirma cuando lo
imprime—.

Por eso se distinguen. **Provisorio** es lo que dijo la máquina: se muestra
`~0:18`, en gris e itálica. **Anclado** es lo que el analista fijó escuchando,
con `Ctrl+T`: se muestra firme. El orden de las frases sí es confiable (Whisper
transcribe de corrido), así que corregir un minuto **no** reordena la lista:
reordenar rompería lo único que estaba bien para honrar lo que estaba mal.

Eso tiene una consecuencia en el control de calidad: **la detección de tramos
sin transcribir solo corre con todos los minutos confirmados.** Medir la
cobertura contra tiempos inventados reclamaba medio audio en transcripciones que
estaban completas, y un aviso que suena siempre es un aviso apagado. Mientras
falten anclas la pantalla lo dice, en vez de callarse y hacer creer que verificó.

### Modo texto

Corregir renglón por renglón sirve para arreglar una palabra, pero no para lo
que Whisper hace mal de verdad: partir una oración en cinco pedazos y juntar dos
turnos en uno. El botón **📝 Modo texto** muestra la transcripción entera como
texto plano —un renglón por frase, con `1.` / `2.` adelante si la voz está
marcada— y al volver se rearma todo conservando los minutos: lo que no se tocó
mantiene el suyo exacto y lo nuevo reparte el hueco entre sus vecinas.

Borrar un salto de línea une dos frases; agregar uno las parte.

### Entregar lo desgrabado

Terminada la jornada, el botón **Entregar desgrabación** saca en un Word todo lo
que se desgrabó y todavía no se entregó, sin volver a elegirlo comunicación por
comunicación. Se puede acotar a lo del día o a lo propio, y destildar lo que se
quiera dejar para la próxima.

El criterio por defecto es "sin entregar" y no "hoy": si se desgraba un viernes
a la tarde y se entrega el lunes, "hoy" dejaría afuera el trabajo propio.

**No es una segunda vía de salida**: llama al mismo exportador y registra el
mismo lote que el informe de la Tabla TOTAL, así que se deshace igual desde
Exportaciones. Si generara el Word por otro camino, Exportaciones dejaría de ser
el registro completo de lo que se elevó al juzgado, que es para lo que sirve.

### La salida de audio

El reproductor deja elegir por dónde suena y lo recuerda. No es un lujo: en
Windows, un manos libres Bluetooth se conecta por el perfil *Hands-Free*, que es
mono y de calidad telefónica. Sobre escuchas que ya vienen en G.711 a 8 kHz y
con ruido de línea, eso multiplica el trabajo. La pantalla avisa cuando la
salida elegida es de manos libres.

### La transcripción es editable

Whisper se saltea pasajes —los que se hablan encimados, los que se escuchan
mal— e inventa frases donde no hay nada. En la transcripción sincronizada, con
el botón derecho sobre una frase se **agrega** la que falta (queda anclada en el
tiempo, entre sus dos vecinas) o se **quita** la que sobra; doble clic corrige
el texto. Antes había que arreglarlo en el Word exportado y la corrección se
perdía en la siguiente exportación.

### Quién habla en cada renglón

El informe judicial numera cada frase con su interlocutor: `1.` el que llama,
`2.` el que atiende. Eso se alternaba a ciegas, lo que es falso apenas alguien
dice dos frases seguidas. En la transcripción sincronizada cada frase tiene un
botón `1`/`2` que se marca con un clic mientras se escucha, y el informe usa lo
marcado. Las frases sin atribuir heredan la del renglón anterior (dentro de un
turno suele seguir hablando el mismo); si no hay ninguna atribuida, se alterna
como antes.

En el Word los renglones salen todos iguales: numerados y sin anotaciones al
margen. La distinción es **para el analista mientras trabaja**, no para el
expediente —un informe judicial con dos clases de renglón anotadas al costado
abre una discusión que no es la que el documento viene a zanjar—. En la lista,
la voz marcada a mano se ve firme y la deducida apagada, y al dar por desgrabada
la pantalla dice cuántas quedaron sin marcar.

### Cuando algo se rompe

Un `excepthook` global captura toda excepción que no haya atrapado nadie —code
suelto, dentro de un slot de Qt o de un temporizador, que es donde pasa casi
todo acá—. No cierra el programa: el trabajo en curso no debería perderse por un
error de una pantalla.

Cada error queda en `datos/errores.log` con un encabezado que dice **versión,
entorno, analista y dónde estaba trabajando** (causa, registro, pantalla,
segundo del audio). El traceback dice qué línea falló; el encabezado dice sobre
qué, que es lo que hace la diferencia entre poder reproducirlo y no cuando el
reporte viene de otra máquina.

En pantalla sale un aviso con el detalle desplegable y un botón para abrir la
carpeta, así el analista puede mandar el archivo sin ir a buscarlo. El mismo
error no avisa dos veces (hay una firma por `tipo:archivo:línea`): sin eso, un
fallo adentro de un repintado tapaba la pantalla de diálogos imposibles de
cerrar. Pasado 1 MB el log se archiva como `errores.1.log` y empieza uno nuevo.

### Quién firma

Al primer arranque se pide el nombre del analista, que queda visible en la barra
superior y se puede cambiar con un clic. Ese nombre firma cada edición, cada
lote de exportación, cada aviso resuelto y cada línea del log de auditoría.

## Compilar el ejecutable

```powershell
py -m pip install -r requirements.txt
py -m PyInstaller EscuchasDiferidas.spec
```

Queda en `dist/EscuchasDiferidas/` (~636 MB, modo carpeta). El ejecutable
**escribe al lado suyo**: `datos/escuchas.db`, `datos/perfil.json` y
`datos/errores.log`. Eso no es un detalle — corriendo desde el código fuente
"de dónde leo" y "dónde escribo" son la misma carpeta, pero empaquetado no: en
modo *onefile* PyInstaller extrae todo a una carpeta temporal que borra al
cerrar, así que la base de datos se iría con ella. Por eso `app/config.py`
separa `RAIZ_APP` (lectura) de `DIR_DATOS` (escritura), y por eso el `.spec`
compila en modo carpeta.

Si el destino no deja escribir (instalado en Program Files), los datos caen en
`%LOCALAPPDATA%\EscuchasDiferidas`.

### Lo que NO va adentro del ejecutable

- **El motor de transcripción.** Whisper y torch pesan gigas y corren en un
  intérprete aparte; el ejecutable busca un Python del equipo que los tenga.
- **El modelo y ffmpeg.** Se copian a `recursos/` **al lado del ejecutable**,
  con la estructura `recursos/modelos/whisper/small.pt` y `recursos/ffmpeg/`.
  Así se actualiza el programa sin volver a mover 483 MB.

De los 636 MB, **300 MB son QtWebEngine**, que existe solo para el Mapa. Si
alguna vez hay que distribuir una versión liviana, reemplazar el mapa por una
imagen estática baja el paquete a ~330 MB.

## Estado de implementación

Avance según el orden sugerido del pseudocódigo (sección 7):

- [x] **Fase 1 — Núcleo**: esquema SQLite, dataclasses, funciones puras
  (normalización, fechas, dirección, CD, emparejamiento) con pruebas.
- [x] **Fase 2 — Importación mínima viable**: escaneo con preview, emparejamiento
  TXT/audio y las tres categorías (completo / audio faltante / transcripción
  faltante), escritura en base con avisos de validación.
- [x] **Fase 3 — Cierre del primer ciclo**: exportador Excel, edición inline con
  HistorialCambio y deshacer, memoria de "corresponde a".
- [x] **Fase 4 — Avanzado**: panel de validaciones, informe Word y judicial con
  lotes y deshacer, mapa de cobertura, grafo de vínculos, línea de tiempo,
  detección de vínculos entre casos, análisis de patrones, log de auditoría,
  reproductor embebido con marcas y transcripción automática con Whisper.
- [~] **Fase 5 — Pulido** (en curso):
  - [x] identidad del analista en auditoría, historial, lotes y avisos
  - [x] transcripción sincronizada con el audio (tiempos de Whisper)
  - [x] Resumen del caso + atajos de una tecla + chuleta en F1
  - [x] número de CD tomado del `DatosCausa.txt` de cada entrega, en vez de
    adivinarlo desde la ruta (que agarraba carpetas ajenas a la causa)
  - [x] eliminar una causa entera, con confirmación escrita y constancia en
    auditoría
  - [x] tema claro además del oscuro, recordado entre arranques
  - [x] papelera: eliminar comunicaciones sin perderlas, con restaurar
  - [x] columna Interlocutor, atada al Índice y a la memoria «corresponde a»
  - [x] migrar identificaciones de «corresponde a» entre causas y a global
  - [x] pantalla **Desgrabar**: audio manejado por teclado, anclaje de minutos,
    atribución de voces, modo texto y deshacer
  - [x] elegir la salida de audio, con aviso de perfil manos libres
  - [x] retomar el trabajo donde quedó (causa, pantalla, registro, segundo)
  - [x] entregar en Word lo desgrabado y no informado, en una sola operación
  - [x] gestor de errores con contexto, aviso en pantalla y rotación del log
  - [x] auditoría de cierre: 10 defectos encontrados y corregidos
  - [ ] pantalla de configuración (rutas de Whisper, offset horario, patrón)
  - [ ] recordar los anchos de columna
  - [ ] copia de seguridad automática de `datos/escuchas.db`
  - [ ] hash de integridad de los audios (cadena de custodia)
  - [ ] empaquetado con PyInstaller (el `.spec` existe; falta probarlo en una
    máquina limpia y armar el instalador)

### Bugs del .bas original ya corregidos

| Bug | Corrección |
|-----|------------|
| BUG-01 patrón laxo | patrón configurable en `config.PATRON_AUDIO` |
| BUG-02 acentos | `unicodedata.normalize('NFKD')` en `core/normalizers.py` |
| BUG-03 ORDEN frágil | id autoincremental nativo; `orden` solo visual |
| BUG-04 CD vacío | etiqueta explícita `SIN CD DETECTADO` + aviso |
| BUG-05 anti-duplicados O(n) | índice `UNIQUE(caso_id, clave_dedup)` + set precargado |
| BUG-06 huérfanos invisibles | escaneo de ambos tipos + clasificación en 3 estados |

## Pruebas

`pytest` corre **866 pruebas** (~6 min) sobre las funciones puras del núcleo, el
esquema y sus migraciones, el escáner de carpetas y el servicio de importación
de punta a punta (deduplicación, memoria de "corresponde a", avisos), más las
pantallas: firma del analista, la mesa de Desgrabar con sus atajos, el anclaje
de minutos, el modo texto, la papelera, la entrega, el retomar sesión y el
gestor de errores.

Las pruebas de interfaz usan `QT_QPA_PLATFORM=offscreen`, así que corren sin
monitor y sirven en CI.

Dos reglas que se siguen acá y conviene mantener:

- **Una prueba tiene que fallar contra el código viejo.** Es lo único que
  distingue un arreglo de una reescritura con suerte. Los diez defectos de la
  auditoría de cierre se verificaron así antes de darlos por corregidos.
- **Un doble de prueba tiene que ser más pobre que el original, nunca más
  rico.** Un `QDialog` falso que definía `Accepted` —que el real no expone en la
  instancia— hizo pasar la prueba mientras el botón "Migrar" no hacía nada en el
  programa.
