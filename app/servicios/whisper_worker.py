"""Worker de transcripción Whisper — se ejecuta en un PROCESO SEPARADO.

Este script NO corre dentro del venv de la aplicación: lo lanza el servicio de
transcripción con un Python que tenga instalado openai-whisper + torch (por
ejemplo el Python del sistema). Por eso solo usa la biblioteca estándar además
de whisper, y no importa nada de `app`.

Protocolo:
    python whisper_worker.py --modelo RUTA.pt --ffmpeg DIR [--idioma es]

    stdin:  una ruta de archivo de audio por línea (UTF-8).
    stdout: una línea JSON por audio procesado:
        {"archivo": "...", "ok": true,  "texto": "...", "idioma": "es",
         "duracion": 33.4,
         "segmentos": [{"inicio": 0.0, "fin": 4.2, "texto": "..."}, ...]}
        {"archivo": "...", "ok": false, "error": "..."}
      y al final una línea {"fin": true, "procesados": N}.
    stderr: progreso legible (una línea por audio) para logs.

El modelo se carga UNA sola vez por proceso: transcribir 50 audios cuesta una
carga de modelo, no cincuenta.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# En Windows el proceso hijo escribe con la codificación del sistema (cp1252),
# no UTF-8: los acentos de la transcripción llegarían corruptos. Forzamos UTF-8
# en stdout/stderr para que "cómo estás" no se convierta en "c�mo est�s".
for _flujo in (sys.stdout, sys.stderr):
    try:
        _flujo.reconfigure(encoding="utf-8")  # Python 3.7+
    except (AttributeError, ValueError):
        pass


def _normalizar(texto: str) -> str:
    """Minúsculas y espacios colapsados, para comparar sin depender del formato."""
    return " ".join((texto or "").lower().split())


def _es_eco_del_prompt(segmento: dict, prompt: str) -> bool:
    """True si el segmento es el prompt repetido en vez de audio transcripto."""
    if not prompt:
        return False
    texto = _normalizar(segmento.get("text") or "")
    return bool(texto) and texto in _normalizar(prompt)


def _sin_eco_del_prompt(texto: str, prompt: str) -> str:
    """Saca del texto el arranque que sea una copia literal del prompt."""
    if not prompt or not texto:
        return texto
    limpio, referencia = _normalizar(texto), _normalizar(prompt)
    # Se recorta la fracción más larga del prompt con la que arranque el texto.
    for corte in range(len(referencia), 20, -1):
        pedazo = referencia[:corte]
        if limpio.startswith(pedazo):
            return texto[len(pedazo):].lstrip(" .,-–—").strip()
    return texto


class _ErrorDeCarga(RuntimeError):
    """No se pudo dejar el modelo listo; el worker termina avisando por qué."""


def _validar_modelo(args) -> None:
    """Chequeo barato de que el modelo está donde se dijo.

    Va antes que todo lo demás —incluso antes de mirar ffmpeg— porque una ruta
    de modelo equivocada es el error de configuración más común y no tiene
    sentido pagar diez segundos de carga para descubrirlo.
    """
    if args.motor == "faster":
        # Un nombre pelado ("small") es válido: lo resuelve la caché local.
        if os.path.sep in args.modelo and not os.path.isdir(args.modelo):
            raise _ErrorDeCarga(f"No existe la carpeta del modelo: {args.modelo}")
    elif not os.path.isfile(args.modelo):
        raise _ErrorDeCarga(f"No existe el modelo: {args.modelo}")


def _cargar_modelo(args):
    """Carga el modelo del motor pedido. Se hace UNA vez por proceso.

    Transcribir cincuenta audios cuesta una carga de modelo, no cincuenta.
    """
    if args.motor == "faster":
        try:
            from faster_whisper import WhisperModel  # noqa: PLC0415
        except ImportError as exc:
            raise _ErrorDeCarga(
                f"El motor 'faster' necesita faster-whisper instalado: {exc}"
            ) from exc
        # Acepta una carpeta CTranslate2 o un nombre a resolver desde la caché.
        origen = args.modelo
        print(f"Cargando faster-whisper ({origen})...", file=sys.stderr, flush=True)
        try:
            return WhisperModel(origen, device="cpu", compute_type="int8")
        except Exception as exc:  # noqa: BLE001
            raise _ErrorDeCarga(f"No se pudo cargar el modelo: {exc}") from exc

    try:
        import whisper  # noqa: PLC0415 — import diferido a propósito
    except ImportError as exc:
        raise _ErrorDeCarga(
            f"whisper no está instalado en este Python: {exc}"
        ) from exc
    print("Cargando modelo Whisper...", file=sys.stderr, flush=True)
    try:
        return whisper.load_model(args.modelo)
    except Exception as exc:  # noqa: BLE001
        raise _ErrorDeCarga(f"No se pudo cargar el modelo: {exc}") from exc


# Parámetros de control de alucinaciones, comunes a los dos motores. Sin ellos
# Whisper arrastra su propia salida como contexto y ante un silencio —que en
# una comunicación telefónica es la mitad del audio— entra en bucle repitiendo
# la última frase.
_ANTIALUCINACION = {
    "condition_on_previous_text": False,
    "temperature": (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
    "compression_ratio_threshold": 2.4,
    "no_speech_threshold": 0.6,
}


def _transcribir_openai(modelo, ruta: str, args) -> dict:
    """Motor openai-whisper. Normaliza la salida al formato común del worker."""
    respuesta = modelo.transcribe(
        ruta,
        language=args.idioma or None,
        fp16=False,
        initial_prompt=args.prompt or None,
        logprob_threshold=-1.0,
        **_ANTIALUCINACION,
    )
    return {
        "text": respuesta.get("text") or "",
        "language": respuesta.get("language") or "",
        "segments": [
            {"start": s.get("start", 0.0), "end": s.get("end", 0.0),
             "text": s.get("text") or ""}
            for s in (respuesta.get("segments") or [])
        ],
    }


def _transcribir_faster(modelo, ruta: str, args) -> dict:
    """Motor faster-whisper. La diferencia que importa es el filtro VAD.

    Recorta los tramos sin voz ANTES de transcribir, que es de donde salen las
    alucinaciones al final de una comunicación telefónica. El motor openai no
    lo tiene.
    """
    parametros = dict(_ANTIALUCINACION)
    parametros["temperature"] = list(parametros["temperature"])
    segmentos_iter, info = modelo.transcribe(
        ruta,
        language=args.idioma or None,
        initial_prompt=args.prompt or None,
        log_prob_threshold=-1.0,   # faster-whisper lo llama distinto
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        **parametros,
    )
    segmentos = [
        {"start": s.start, "end": s.end, "text": s.text or ""}
        for s in segmentos_iter
    ]
    return {
        "text": " ".join(s["text"].strip() for s in segmentos).strip(),
        "language": getattr(info, "language", "") or "",
        "segments": segmentos,
    }


def _emitir(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="Worker de transcripción Whisper")
    parser.add_argument(
        "--modelo", required=True,
        help="Motor openai: ruta al .pt. Motor faster: carpeta del modelo "
             "CTranslate2, o el nombre a resolver desde la caché local.",
    )
    parser.add_argument(
        "--motor", default="openai", choices=("openai", "faster"),
        help="openai = openai-whisper (.pt) | faster = faster-whisper (con VAD)",
    )
    parser.add_argument("--ffmpeg", required=True, help="Carpeta que contiene ffmpeg.exe")
    parser.add_argument("--idioma", default="es")
    parser.add_argument(
        "--prompt", default="",
        help="Contexto (initial_prompt) que orienta el vocabulario del modelo",
    )
    args = parser.parse_args()

    try:
        _validar_modelo(args)
    except _ErrorDeCarga as exc:
        _emitir({"fin": True, "procesados": 0, "error": str(exc)})
        return 2

    ffmpeg_exe = os.path.join(args.ffmpeg, "ffmpeg.exe")
    if not os.path.isfile(ffmpeg_exe):
        _emitir({"fin": True, "procesados": 0,
                 "error": f"No se encontró ffmpeg.exe en: {args.ffmpeg}"})
        return 2
    os.environ["PATH"] = args.ffmpeg + os.pathsep + os.environ.get("PATH", "")

    try:
        modelo = _cargar_modelo(args)
    except _ErrorDeCarga as exc:
        _emitir({"fin": True, "procesados": 0, "error": str(exc)})
        return 2
    print("Modelo cargado.", file=sys.stderr, flush=True)

    procesados = 0
    for linea in sys.stdin:
        # PowerShell agrega BOM (U+FEFF) al pipear texto a stdin.
        ruta = linea.strip().lstrip("﻿").strip()
        if not ruta:
            continue
        print(f"Transcribiendo: {ruta}", file=sys.stderr, flush=True)

        if not os.path.isfile(ruta):
            _emitir({"archivo": ruta, "ok": False,
                     "error": "El archivo no existe."})
            continue

        try:
            if args.motor == "faster":
                respuesta = _transcribir_faster(modelo, ruta, args)
            else:
                respuesta = _transcribir_openai(modelo, ruta, args)
        except Exception as exc:  # noqa: BLE001
            _emitir({"archivo": ruta, "ok": False, "error": str(exc)})
            continue

        texto = (respuesta.get("text") or "").strip()
        segmentos = respuesta.get("segments") or []
        # El modelo a veces devuelve el propio prompt como si fuera lo primero
        # que se escucha. En un informe judicial eso es inaceptable, así que se
        # descarta antes de que salga del worker.
        segmentos = [s for s in segmentos if not _es_eco_del_prompt(s, args.prompt)]
        texto = _sin_eco_del_prompt(texto, args.prompt)
        duracion = float(segmentos[-1]["end"]) if segmentos else 0.0
        # Whisper ya sabe en qué segundo dijo cada frase. Antes se usaba ese
        # dato solo para calcular la duración y se descartaba el resto; ahora
        # viaja entero, que es lo que permite navegar el audio por texto.
        _emitir({
            "archivo": ruta,
            "ok": True,
            "texto": texto,
            "idioma": (respuesta.get("language") or "").strip(),
            "duracion": round(duracion, 2),
            "segmentos": [
                {
                    "inicio": round(float(s.get("start", 0.0)), 2),
                    "fin": round(float(s.get("end", 0.0)), 2),
                    "texto": (s.get("text") or "").strip(),
                }
                for s in segmentos
            ],
        })
        procesados += 1

    _emitir({"fin": True, "procesados": procesados})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
