"""Backtest con prueba hacia adelante (walk-forward).

Divide la historia en tramos. En cada tramo:

1. **Entrena** con el período anterior: prueba varias configuraciones de la
   estrategia y se queda con la mejor. De ese período también saca la
   calibración de la confianza.
2. **Prueba** la elegida en el período siguiente, que nunca vio.

Después corre la ventana y repite. Solo cuentan los resultados de los
períodos de prueba. Si la estrategia "memorizó" el pasado, acá se nota.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import product

import numpy as np

from .config import Config
from .data.feed import FeedHistorico
from .estrategia import EstrategiaCaidaFuerte
from .historial import Historial
from .simulacion import Informe, correr

GRILLA_POR_DEFECTO = {
    "caida_minima": [0.05, 0.07, 0.10],
    "objetivo": [0.04, 0.06],
}


@dataclass
class Tramo:
    entrenamiento: str
    prueba: str
    parametros: dict
    puntaje_entrenamiento: float
    prueba_informe: Informe


@dataclass
class ResultadoWalkForward:
    tramos: list[Tramo] = field(default_factory=list)

    @property
    def retorno(self) -> float:
        return float(np.prod([1 + t.prueba_informe.retorno for t in self.tramos]) - 1) if self.tramos else 0.0

    @property
    def retorno_comprar_y_esperar(self) -> float:
        if not self.tramos:
            return 0.0
        return float(np.prod([1 + t.prueba_informe.retorno_comprar_y_esperar for t in self.tramos]) - 1)

    @property
    def operaciones(self) -> int:
        return sum(t.prueba_informe.operaciones for t in self.tramos)

    @property
    def peor_caida(self) -> float:
        return max((t.prueba_informe.peor_caida for t in self.tramos), default=0.0)

    def texto(self) -> str:
        lineas = ["Backtest con prueba hacia adelante", ""]
        lineas.append(f"{'Período de prueba':<26}{'IASEYT':>9}{'Esperar':>9}{'Ops':>5}  Parámetros elegidos")
        for t in self.tramos:
            i = t.prueba_informe
            params = ", ".join(f"{k}={v}" for k, v in t.parametros.items())
            lineas.append(f"{t.prueba:<26}{i.retorno:>+9.2%}{i.retorno_comprar_y_esperar:>+9.2%}{i.operaciones:>5}  {params}")
        lineas += [
            "",
            f"Total en períodos de prueba:  IASEYT {self.retorno:+.2%}  ·  comprar y esperar {self.retorno_comprar_y_esperar:+.2%}",
            f"Operaciones: {self.operaciones}  ·  peor caída en un tramo: {self.peor_caida:.2%}",
        ]
        if self.retorno <= self.retorno_comprar_y_esperar:
            lineas.append("Resultado: no le gana a comprar y esperar. Con estos datos, no conviene usarla.")
        else:
            lineas.append(
                "Resultado: le gana a comprar y esperar en estos datos. Falta confirmarlo con más "
                "historia y en simulación en vivo antes de confiar."
            )
        return "\n".join(lineas)


def _puntaje(inf: Informe) -> float:
    """Ganancia, castigando la caída: prefiere ganar algo menos con menos riesgo."""
    return inf.retorno - 0.5 * inf.peor_caida


def walk_forward(
    feed: FeedHistorico,
    cfg: Config,
    barras_entrenamiento: int = 250,
    barras_prueba: int = 63,
    grilla: dict[str, list] | None = None,
    semilla: int = 0,
) -> ResultadoWalkForward:
    grilla = grilla or GRILLA_POR_DEFECTO
    n = len(feed.fechas)
    if n < barras_entrenamiento + barras_prueba:
        raise ValueError(
            f"Hacen falta al menos {barras_entrenamiento + barras_prueba} ruedas de datos; hay {n}."
        )
    claves = sorted(grilla)
    combinaciones = [dict(zip(claves, valores)) for valores in product(*(grilla[k] for k in claves))]
    resultado = ResultadoWalkForward()
    fmt = lambda i: feed.fechas[i].strftime("%Y-%m-%d")  # noqa: E731

    inicio_prueba = barras_entrenamiento
    while inicio_prueba + barras_prueba <= n:
        ini_ent, fin_prueba = inicio_prueba - barras_entrenamiento, inicio_prueba + barras_prueba
        mejor: tuple[float, dict, list] | None = None
        for params in combinaciones:
            hist = Historial(":memory:")
            _, inf = correr(feed.ventana(ini_ent, inicio_prueba), cfg, semilla, hist, EstrategiaCaidaFuerte(**params))
            puntaje = _puntaje(inf)
            if mejor is None or puntaje > mejor[0]:
                mejor = (puntaje, params, hist.calibracion())
        assert mejor is not None
        puntaje, params, calibracion = mejor
        _, inf_prueba = correr(
            feed.ventana(inicio_prueba, fin_prueba), cfg, semilla, None,
            EstrategiaCaidaFuerte(**params), calibracion_previa=calibracion,
        )
        resultado.tramos.append(
            Tramo(
                entrenamiento=f"{fmt(ini_ent)} a {fmt(inicio_prueba - 1)}",
                prueba=f"{fmt(inicio_prueba)} a {fmt(fin_prueba - 1)}",
                parametros=params,
                puntaje_entrenamiento=puntaje,
                prueba_informe=inf_prueba,
            )
        )
        inicio_prueba += barras_prueba
    return resultado


def como_dict(r: ResultadoWalkForward) -> dict:
    return {
        "retorno": r.retorno,
        "retorno_comprar_y_esperar": r.retorno_comprar_y_esperar,
        "operaciones": r.operaciones,
        "tramos": [
            {"prueba": t.prueba, "parametros": t.parametros, "informe": asdict(t.prueba_informe)} for t in r.tramos
        ],
    }
