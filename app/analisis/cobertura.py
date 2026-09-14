"""Qué partes del audio quedaron sin transcribir.

Whisper no avisa cuando se saltea un pasaje. Devuelve un texto completo y
plausible, y lo que se comió —el tramo hablado encimado, el que se escucha mal,
el que cortó la prestadora— simplemente no está. Leyendo el texto no hay forma
de darse cuenta: no queda un hueco, queda una conversación que parece entera.

Pero el dato está: los segmentos dicen qué tramos del audio tienen texto, y la
forma de onda dice dónde hay voz. Lo que hay entre medio —sonido sin
transcripción— es exactamente lo que falta escuchar.

Es lo que en Audacity uno ve a ojo comparando la onda con las etiquetas. Acá se
calcula, que es mejor que verlo: en una escucha de veinte minutos nadie compara
a ojo veinte minutos de onda.
"""

from __future__ import annotations

# Pico normalizado (0..1) a partir del cual se considera que hay voz y no piso
# de ruido. Las escuchas telefónicas vienen en G.711 a 8 kHz y con bastante
# ruido de línea; por debajo de esto es el zumbido del canal.
UMBRAL_VOZ = 0.12

# Un hueco más corto que esto es una pausa entre frases, no un pasaje perdido.
MINIMO_HUECO_SEG = 1.2


def _con_texto_y_ancladas(segmentos: list[dict]) -> list[dict]:
    """Las frases escritas cuyo minuto confirmó una persona escuchando.

    Es el único material con el que se puede afirmar algo sobre la cobertura.
    Una frase con tiempo provisorio dice dónde CREE Whisper que se dijo, y el
    motor se desfasa: tomarla como cubierta esconde huecos reales donde el
    tiempo se adelantó, e inventa huecos donde se atrasó.
    """
    return [
        s for s in segmentos
        if str(s.get("texto") or "").strip() and s.get("anclado")
    ]


def sin_confirmar(segmentos: list[dict]) -> int:
    """Cuántas frases escritas tienen todavía el minuto que puso la máquina."""
    return sum(
        1 for s in segmentos
        if str(s.get("texto") or "").strip() and not s.get("anclado")
    )


def cobertura_verificable(segmentos: list[dict]) -> bool:
    """Si se puede afirmar algo sobre qué falta transcribir.

    Hace falta que TODAS las frases escritas tengan el minuto confirmado. Con
    una sola sin anclar la cuenta no cierra: esa frase está en algún lado del
    audio que nadie fijó, así que el sonido que aparece sin texto puede ser
    ella y no un pasaje perdido.

    Es todo o nada a propósito. Verificar solo entre la primera y la última
    anclada dejaba afuera el caso que esto existe para encontrar —la despedida
    que el motor cortó, que cae después de la última frase—. Mejor decir «esto
    todavía no se puede verificar» que verificar la mitad y callarse la otra.
    """
    escritas = [s for s in segmentos if str(s.get("texto") or "").strip()]
    return bool(escritas) and not sin_confirmar(segmentos)


def _cubierto(segmentos: list[dict]) -> list[tuple[float, float]]:
    """Los tramos con texto, ordenados y fusionados si se superponen."""
    tramos = []
    for s in _con_texto_y_ancladas(segmentos):
        inicio = float(s.get("inicio") or 0.0)
        fin = float(s.get("fin") or inicio)
        tramos.append((inicio, max(fin, inicio)))
    tramos.sort()

    fusionados: list[tuple[float, float]] = []
    for inicio, fin in tramos:
        if fusionados and inicio <= fusionados[-1][1]:
            anterior = fusionados[-1]
            fusionados[-1] = (anterior[0], max(anterior[1], fin))
        else:
            fusionados.append((inicio, fin))
    return fusionados


def huecos_con_audio(
    picos: list[float],
    duracion_seg: float,
    segmentos: list[dict],
    *,
    umbral: float = UMBRAL_VOZ,
    minimo_seg: float = MINIMO_HUECO_SEG,
) -> list[tuple[float, float]]:
    """Tramos (desde, hasta) donde suena algo y no hay ninguna frase.

    `picos` son los de la forma de onda, normalizados 0..1 y repartidos
    parejo a lo largo de `duracion_seg`.
    """
    if not picos or duracion_seg <= 0:
        return []

    # Con un solo minuto sin confirmar la comparación no vale: los tiempos de
    # Whisper son conjetura, y medir la cobertura contra ellos reclamaba medio
    # audio sobre transcripciones que estaban completas.
    if not cobertura_verificable(segmentos):
        return []

    cubiertos = _cubierto(segmentos)
    paso = duracion_seg / len(picos)

    def tiene_texto(segundo: float) -> bool:
        return any(a <= segundo <= b for a, b in cubiertos)

    huecos: list[tuple[float, float]] = []
    abierto: float | None = None
    for i, pico in enumerate(picos):
        momento = i * paso
        suena_y_falta = pico >= umbral and not tiene_texto(momento)
        if suena_y_falta and abierto is None:
            abierto = momento
        elif not suena_y_falta and abierto is not None:
            if momento - abierto >= minimo_seg:
                huecos.append((round(abierto, 2), round(momento, 2)))
            abierto = None
    if abierto is not None and duracion_seg - abierto >= minimo_seg:
        huecos.append((round(abierto, 2), round(duracion_seg, 2)))
    return huecos


def resumen_huecos(huecos: list[tuple[float, float]]) -> str:
    if not huecos:
        return "Sin tramos hablados fuera de la transcripción"
    total = sum(b - a for a, b in huecos)
    cuantos = f"{len(huecos)} tramo" + ("s" if len(huecos) != 1 else "")
    return f"{cuantos} con sonido y sin texto ({total:.0f} s en total)"
