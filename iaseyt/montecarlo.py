"""Simulación Monte Carlo de una operación.

Genera miles de caminos posibles del precio remuestreando retornos diarios
reales de la acción (bootstrap por bloques, para respetar rachas), y aplica
el stop, el objetivo y el plazo de la operación a cada camino.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ResultadoMC:
    caminos: int
    retorno_esperado: float
    prob_ganar: float
    prob_perdida_mayor_umbral: float
    percentil_5: float
    percentil_95: float
    umbral: float


def simular_operacion(
    retornos_historicos: np.ndarray,
    objetivo: float,
    stop: float,
    dias: int,
    costo_ida_vuelta: float,
    umbral_perdida: float = 0.05,
    caminos: int = 10_000,
    bloque: int = 5,
    rng: np.random.Generator | None = None,
    deriva_diaria: float | None = None,
) -> ResultadoMC:
    """Simula una compra.

    retornos_historicos: retornos diarios simples (0.01 = +1%).
    objetivo: ganancia a la que vende (0.10 = +10%).
    stop: pérdida a la que corta (0.05 = -5%).
    dias: plazo máximo de la operación.
    costo_ida_vuelta: comisiones + deslizamiento de comprar y vender.
    deriva_diaria: movimiento promedio esperado por día según los precedentes.
        Si se da, los retornos históricos se centran en cero y se les suma
        esta deriva: la volatilidad sale de la historia de la acción, y la
        dirección, de lo que pasó en situaciones parecidas.
    """
    r = np.asarray(retornos_historicos, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 2 * bloque:
        raise ValueError("Faltan datos históricos para simular (mínimo 2 bloques).")
    if dias < 1:
        raise ValueError("El plazo tiene que ser de al menos 1 día.")
    if deriva_diaria is not None:
        r = r - r.mean() + deriva_diaria
    rng = rng or np.random.default_rng()

    # Bootstrap por bloques: elige inicios al azar y toma bloques seguidos.
    n_bloques = -(-dias // bloque)
    inicios = rng.integers(0, len(r) - bloque + 1, size=(caminos, n_bloques))
    idx = (inicios[:, :, None] + np.arange(bloque)[None, None, :]).reshape(caminos, -1)[:, :dias]
    trayectorias = np.cumprod(1.0 + r[idx], axis=1)  # precio relativo a la entrada

    nivel_stop = 1.0 - stop
    nivel_obj = 1.0 + objetivo
    toca_stop = trayectorias <= nivel_stop
    toca_obj = trayectorias >= nivel_obj
    INF = dias + 1
    dia_stop = np.where(toca_stop.any(axis=1), toca_stop.argmax(axis=1), INF)
    dia_obj = np.where(toca_obj.any(axis=1), toca_obj.argmax(axis=1), INF)

    final = trayectorias[:, -1] - 1.0
    # Si el stop llega antes (o el mismo día), sale por stop: el peor caso.
    # Un salto puede pasar de largo el stop: se vende al precio de ese día.
    precio_stop = trayectorias[np.arange(caminos), np.minimum(dia_stop, dias - 1)]
    resultado = np.where(
        (dia_stop <= dia_obj) & (dia_stop < INF),
        np.minimum(precio_stop, nivel_stop) - 1.0,
        np.where(dia_obj < INF, objetivo, final),
    )
    resultado = resultado - costo_ida_vuelta

    return ResultadoMC(
        caminos=caminos,
        retorno_esperado=float(resultado.mean()),
        prob_ganar=float((resultado > 0).mean()),
        prob_perdida_mayor_umbral=float((resultado < -umbral_perdida).mean()),
        percentil_5=float(np.percentile(resultado, 5)),
        percentil_95=float(np.percentile(resultado, 95)),
        umbral=umbral_perdida,
    )
