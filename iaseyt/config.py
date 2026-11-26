"""Configuración de IASEYT.

Todos los valores tienen un default seguro. Se pueden cambiar con un archivo
config.toml (ver config.example.toml). Nunca pongas claves en este archivo:
las claves van en variables de entorno (ver README).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LimitesRiesgo:
    """Topes de riesgo. Todos son fracciones del valor total de la cuenta."""

    max_por_empresa: float = 0.10
    max_por_sector: float = 0.25
    perdida_max_diaria: float = 0.03
    caida_max_desde_pico: float = 0.15
    efectivo_minimo: float = 0.20


@dataclass(frozen=True)
class FiltrosDecision:
    """Umbrales de los filtros para comprar (sección "Cómo decide")."""

    prob_minima: float = 0.60
    # Fuentes independientes que confirman la causa. Para señales de noticias.
    min_fuentes_noticia: int = 2
    # Para señales técnicas (fase 1) alcanza con el dato de precio.
    min_fuentes_tecnica: int = 1
    min_precedentes: int = 8
    umbral_perdida: float = 0.05
    max_prob_perdida: float = 0.15
    volumen_minimo_diario: float = 50_000_000.0  # en pesos
    fraccion_kelly: float = 0.25
    caminos_montecarlo: int = 10_000


@dataclass(frozen=True)
class Costos:
    """Costos de operar, como fracción del monto de cada operación."""

    comision: float = 0.005
    deslizamiento: float = 0.002


@dataclass(frozen=True)
class ConfigPPI:
    """Conexión con PPI. Las claves NO van acá: van en variables de entorno
    (PPI_KEY_PUBLICA, PPI_KEY_PRIVADA y PPI_CUENTA)."""

    sandbox: bool = True
    tipo_instrumento: str = "CEDEARS"
    # Los CEDEARs se liquidan a 24 horas (T+1).
    liquidacion: str = "A-24HS"
    # Cuánto espera a que se ejecute una orden límite antes de cancelarla.
    segundos_espera_orden: float = 30.0


@dataclass(frozen=True)
class Config:
    limites: LimitesRiesgo = field(default_factory=LimitesRiesgo)
    filtros: FiltrosDecision = field(default_factory=FiltrosDecision)
    costos: Costos = field(default_factory=Costos)
    ppi: ConfigPPI = field(default_factory=ConfigPPI)
    capital_inicial: float = 1_000_000.0
    ruta_db: str = "iaseyt.db"
    # Modo asistido: minutos para responder una propuesta antes de descartarla.
    minutos_para_responder: int = 30
    # Si no abrís el panel en este tiempo, pasa sola a automático.
    # None = nunca pasa sola (default seguro).
    pasar_a_auto_tras_minutos: int | None = None
    # Segundos entre cada ciclo del motor cuando corre en vivo.
    segundos_por_ciclo: int = 60


def _construir(clase: type, datos: dict[str, Any] | None):
    if not datos:
        return clase()
    validos = {f.name for f in fields(clase)}
    desconocidos = set(datos) - validos
    if desconocidos:
        raise ValueError(f"Claves desconocidas en [{clase.__name__}]: {sorted(desconocidos)}")
    return clase(**datos)


def cargar_config(ruta: str | Path | None = None) -> Config:
    """Lee config.toml. Si no hay archivo, usa los valores por defecto."""
    if ruta is None or not Path(ruta).exists():
        return Config()
    with open(ruta, "rb") as f:
        datos = tomllib.load(f)
    base = Config(
        limites=_construir(LimitesRiesgo, datos.pop("limites", None)),
        filtros=_construir(FiltrosDecision, datos.pop("filtros", None)),
        costos=_construir(Costos, datos.pop("costos", None)),
        ppi=_construir(ConfigPPI, datos.pop("ppi", None)),
    )
    general = datos.pop("general", {})
    if datos:
        raise ValueError(f"Secciones desconocidas en la configuración: {sorted(datos)}")
    return replace(base, **general) if general else base
