# Nota institucional y plantilla — diseño acordado, sin implementar

Estado: **decidido y postergado**. Se documenta acá para no volver a discutirlo
desde cero. No hay nada de esto en el código todavía.

---

## El problema

Escuchas no produce un informe: produce un **anexo**. Lo que exporta hoy
(`exportar_informe_judicial`) es un listado de comunicaciones por CD y abonado
—material crudo, sin destinatario, sin objeto, sin conclusión—. Es la prueba,
no el informe sobre la prueba.

La nota formal que el organismo usa tiene esta forma:

```
Aguaray (S), 8 de agosto de 2026.
Objeto: Informar.

AL JEFE DE LA SECCIÓN DE INVESTIGACIONES ANTIDROGAS "AGUARAY":

    Elevo al señor Jefe el presente informe, en el marco del Legajo de
    Investigación Fiscal caratulado "…", registrado en Coirón con el nro…

    1. CD NRO. 1 - CD7030…, suministrado por el Magistrado…
       Abonado 387…:
          Dirección / Origen / Destino / Inicio / Fin
          DATOS DE LA CELDA:
          Transcripción:
          FIN DE LA COMUNICACIÓN.
    2. CD NRO. 2 - …

CONCLUSIÓN PARCIAL:
…

SOLICITUD:
…
```

**Las transcripciones van en el CUERPO**, entre la fórmula de elevación y la
conclusión. No son un anexo que se agrega al final.

---

## Por qué Escuchas lo hace solo y no lo delega

Se evaluó exportar un módulo para el generador de informes de
`GIT 4 (INFORMES)`, que ya tiene la plantilla institucional. Se descartó por
dos razones:

1. **GIT 4 es un esqueleto.** Su propia documentación dice «Fase 1 — Esqueleto
   SPA», y sus módulos están vacíos (`gabinete_1.json` = `{"secciones": []}`).
   Colgar la entrega judicial de una aplicación menos madura que la que ya
   funciona es un riesgo sin contrapartida.
2. **Sólo Escuchas tiene los datos para ayudar a redactar.** Sabe cuántas
   comunicaciones hay, cuántas son de interés, qué abonados se identificaron,
   entre qué fechas. Un generador externo recibiría un cuerpo ya escrito.

**Condición que sigue en pie:** la plantilla tiene que ser **dato, no código**.
Si mañana GIT 4 madura, las dos aplicaciones leen el mismo archivo. Y el día
que cambie el Jefe de Sección, se cambia sin tocar el programa.

---

## La plantilla es un `.docx` con marcadores

Un Word y no un archivo de texto: la nota lleva membrete, márgenes, tipografía
y quizá escudo. Con `.docx` el analista la edita en Word.

Dos clases de marcador:

| Forma | Ejemplo | Qué hace |
|---|---|---|
| `{campo}` | `{lugar}`, `{fiscal}` | Sustitución de texto adentro de una frase |
| `{{BLOQUE}}` | `{{CUERPO}}` | Se reemplaza por párrafos generados |

### El destinatario son tres campos, no uno

El tratamiento aparece **dos veces en el cuerpo** («Elevo al señor Jefe…»,
«solicito al señor Jefe…»). Si el destinatario pasa a ser una fiscalía, esas
frases quedan mal, y es un error que nadie nota hasta que el documento salió.

| Campo | Ejemplo | Dónde va |
|---|---|---|
| Etiqueta | `Sección Aguaray` | Sólo para elegirlo de la lista |
| Encabezado | `AL JEFE DE LA SECCIÓN…` | La línea del destinatario |
| Tratamiento | `señor Jefe` | Adentro del cuerpo, dos veces |

Va como **catálogo**, con el patrón de `CatalogoContexto` que ya existe. Al
exportar se elige, con el último usado preseleccionado.

---

## Los campos los declara la plantilla

La lista de datos quedó **abierta**: preventor, secretario, fiscal, auxiliar
fiscal, año, fecha de presentación, «entre otros». Agregar una columna por cada
uno significaría una migración por campo, para siempre.

**Decisión: el programa lee la plantilla, ve qué `{marcadores}` tiene, y pide
esos.** El formulario de la causa se genera de ahí.

El día que la Sección agregue el «Instructor», se escribe `{instructor}` en la
plantilla y el programa lo pide solo. Sin tocar código.

### Dónde vive cada cosa

| Qué | Dónde | Cuándo se carga |
|---|---|---|
| Carátula, Coirón, fiscalía, fiscal, auxiliar, secretario, preventor… | Datos de la causa (clave/valor por caso) | Una vez por causa |
| Lugar, destinatario, tratamiento | Catálogo del organismo | Una vez; se elige al exportar |
| Fecha de presentación, conclusión, solicitud, nro. de informe | Se piden al exportar | Cada vez |
| Año, cuerpo, firma | Automáticos | El programa los sabe |

El **año** sale de la fecha de presentación, no se pregunta. La **fecha de
presentación** viene con hoy por defecto, editable: a veces el informe se fecha
el día que se eleva, no el que se generó.

### Lo que se pierde

No hay columnas tipadas: el programa no puede filtrar causas por fiscal ni
validar que una fecha sea una fecha. Para datos que son todos identificadores
de texto no parece pérdida real. Si alguna vez hace falta «listar las causas de
la Dra. X», eso necesita otra cosa.

### Detalle que sale casi gratis

`{fiscal}` y `{secretario}` se repiten entre causas. El campo puede ofrecer lo
ya escrito en otras causas, con el patrón de la memoria «corresponde a».

---

## Dónde vive el archivo de plantilla

Importa por el empaquetado:

- Se **distribuye** una por defecto en `RAIZ_APP/recursos/plantillas/`
- Al primer arranque se **copia** a `DIR_DATOS/plantillas/` si no está
- El programa **lee la de `DIR_DATOS`**, que es la que el analista edita

Empaquetado, `RAIZ_APP` es de sólo lectura y en modo *onefile* se borra al
cerrar. Si la plantilla editada viviera ahí, la próxima actualización del
programa la pisaría.

---

## Qué se aplica a cada salida

Hoy hay dos salidas que usan el mismo exportador: «Informe judicial» (Tabla
TOTAL) y «Entregar desgrabación» (Desgrabar).

- **Los datos de la causa** (carátula, Coirón) → **en las dos**. Entregar 40
  páginas de desgrabación sin decir de qué causa son es un problema, y hoy
  pasa.
- **La nota institucional completa** → **sólo en el informe judicial**.
  «Entregar desgrabación» es trabajo interno; una carta formal al Jefe sobre
  algo que se pasa por mano lo convierte en un trámite.

---

## El trabajo, en orden

1. **Refactor del exportador.** Hoy `exportar_informe_judicial` es dueño del
   documento: hace `Document()` en la línea 437 y `doc.save()` en la 491. Para
   que las transcripciones sean el *cuerpo* de una nota, tiene que recibir un
   documento y escribir adentro. Son ~50 líneas a extraer, cubiertas por las
   pruebas. **Sin esto, la nota termina con una copia del generador de
   transcripciones**, que es el problema de las dos vías de salida que se viene
   evitando en todo el programa.
2. **Columnas/almacén de datos de la causa + el formulario.** Es el grueso del
   trabajo, aunque no el más difícil.
3. **El archivo de plantilla por defecto**, con los marcadores puestos.
4. **El armado de la nota**, que junta las tres cosas anteriores.

Los pasos 1 y 3 se pueden hacer sin que cambie nada de lo que se ve hoy.

### La trampa técnica conocida

Word parte el texto de un párrafo en fragmentos internos («runs») donde se le
antoja, así que `{lugar}` puede quedar cortado en dos y el reemplazo no
encuentra nada. Se resuelve juntando el texto del párrafo, reemplazando y
reescribiéndolo. Es un problema conocido con solución conocida, pero si no se
sabe de antemano se pierde una tarde.

---

## Lo que quedó sin definir

- **¿Una plantilla o varias?** (elevar a fiscalía, informe de avance, otra
  unidad). Si son varias, el selector va al momento de exportar y cada una
  declara sus campos.
- **¿Un mismo informe va a varias unidades a la vez, o según la causa va a una
  u otra?** Si es a varias, se generaría un documento por unidad con el mismo
  cuerpo y distinto encabezado —no una línea de «copias a», porque cada unidad
  recibe su propio ejemplar elevado—.

---

## Relación con la caja de interpretación

La conclusión **no se autogenera**. El analista escribe una interpretación por
comunicación, en Desgrabar, mientras escucha (ver la caja de interpretación, ya
implementada). La CONCLUSIÓN PARCIAL se arma **juntando** esas interpretaciones,
no redactándolas: el programa recopila, no es autor de nada.

Esa decisión es la que resuelve el riesgo de que se firme sin leer un texto que
escribió la máquina.
