"""Errores comunes a los exportadores."""

from __future__ import annotations


class InformeVacio(ValueError):
    """No hay material que incluir en el informe.

    No es una falla del programa sino una decisión que le corresponde al
    analista: marcar comunicaciones de interés antes de generar el informe.
    """
