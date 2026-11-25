"""Estrategia técnica de prueba para la fase 1.

AVISO: es un ejemplo para probar todo el circuito (filtros, simulaciones,
topes, historial). No lee noticias y no hay evidencia de que gane plata.
En la fase 3 la reemplazan las señales de noticias analizadas por Claude.

Idea: cuando una acción cae fuerte en pocos días, busca en su propio pasado
las veces que pasó lo mismo y mira qué hizo el precio después. Esos casos
son los "precedentes" que alimentan la probabilidad.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..cartera import Cartera
from ..data.feed import FeedHistorico
from ..decision import Senal, TipoSenal


@dataclass
class EstrategiaCaidaFuerte:
    dias_caida: int = 5
    caida_minima: float = 0.07
    horizonte: int = 10
    objetivo: float = 0.06
    stop: float = 0.035

    def _precedentes(self, precios: np.ndarray) -> list[float]:
        """Retornos a `horizonte` días de caídas parecidas del pasado, sin solaparse."""
        n, d, h = len(precios), self.dias_caida, self.horizonte
        resultado: list[float] = []
        ultimo = -h
        # j + h tiene que ser un día ya conocido y anterior a hoy.
        for j in range(d, n - 1 - h):
            caida = precios[j] / precios[j - d] - 1
            if caida <= -self.caida_minima and j - ultimo >= h:
                resultado.append(float(precios[j + h] / precios[j] - 1))
                ultimo = j
        return resultado

    def generar(self, feed: FeedHistorico, cartera: Cartera) -> list[Senal]:
        senales = []
        for t in feed.tickers:
            if t in cartera.posiciones:
                continue
            p = feed.historia(t)
            if len(p) < 60 + self.dias_caida:
                continue
            caida = p[-1] / p[-1 - self.dias_caida] - 1
            if caida > -self.caida_minima:
                continue
            prec = self._precedentes(p)
            prob = sum(r > 0 for r in prec) / len(prec) if prec else 0.0
            senales.append(
                Senal(
                    ticker=t,
                    sector=feed.sectores[t],
                    tipo=TipoSenal.TECNICA,
                    causa=(
                        f"Cayó {abs(caida):.1%} en {self.dias_caida} días "
                        "(patrón técnico de prueba, sin análisis de noticias)"
                    ),
                    fuentes=["precio"],
                    precedentes=prec,
                    prob_bruta=prob,
                    objetivo=self.objetivo,
                    stop=self.stop,
                    horizonte_dias=self.horizonte,
                    volumen_diario=float(feed.volumenes[t][feed.indice]),
                    mercado_abierto=feed.mercado_abierto(),
                    retornos_historicos=np.diff(p) / p[:-1],
                    precio=float(p[-1]),
                )
            )
        return senales
