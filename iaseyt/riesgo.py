"""Topes de riesgo y tamaño de posición (Kelly fraccionado con límites)."""

from __future__ import annotations

from .cartera import Cartera
from .config import LimitesRiesgo
from .estado import MotivoPausa


def kelly(prob: float, ganancia: float, perdida: float) -> float:
    """Fracción óptima del capital para una apuesta con dos resultados.

    prob: probabilidad de ganar.
    ganancia: cuánto se gana si sale bien, como fracción del monto (0.10 = +10%).
    perdida: cuánto se pierde si sale mal, como fracción del monto (0.05 = -5%).

    Fórmula: f = p / L - (1 - p) / G. Nunca devuelve negativo (no apuesta).
    """
    if not 0.0 <= prob <= 1.0:
        raise ValueError("La probabilidad tiene que estar entre 0 y 1.")
    if ganancia <= 0 or perdida <= 0:
        raise ValueError("Ganancia y pérdida tienen que ser positivas.")
    return max(0.0, prob / perdida - (1.0 - prob) / ganancia)


def monto_maximo_permitido(cartera: Cartera, ticker: str, sector: str, lim: LimitesRiesgo) -> float:
    """Lo máximo que se puede comprar de una empresa sin romper ningún tope."""
    total = cartera.valor_total
    if total <= 0:
        return 0.0
    por_empresa = lim.max_por_empresa * total - cartera.exposicion_empresa(ticker)
    por_sector = lim.max_por_sector * total - cartera.exposicion_sector(sector)
    por_efectivo = cartera.efectivo - lim.efectivo_minimo * total
    return max(0.0, min(por_empresa, por_sector, por_efectivo))


def tamano_posicion(
    cartera: Cartera,
    prob: float,
    ganancia: float,
    perdida: float,
    ticker: str,
    sector: str,
    lim: LimitesRiesgo,
    fraccion_kelly: float,
) -> float:
    """Monto sugerido en pesos: un cuarto de Kelly, sin pasar ningún tope."""
    f = fraccion_kelly * kelly(prob, ganancia, perdida)
    sugerido = f * cartera.valor_total
    return max(0.0, min(sugerido, monto_maximo_permitido(cartera, ticker, sector, lim)))


def verificar_frenos(
    valor_actual: float, valor_inicio_dia: float, valor_pico: float, lim: LimitesRiesgo
) -> MotivoPausa | None:
    """Devuelve el motivo de pausa si se alcanzó algún freno, o None."""
    if valor_pico > 0 and (valor_pico - valor_actual) / valor_pico >= lim.caida_max_desde_pico:
        return MotivoPausa.CAIDA_DESDE_PICO
    if valor_inicio_dia > 0 and (valor_inicio_dia - valor_actual) / valor_inicio_dia >= lim.perdida_max_diaria:
        return MotivoPausa.PERDIDA_DIARIA
    return None
