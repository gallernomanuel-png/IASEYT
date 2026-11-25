"""Filtros para comprar. Si falla uno, no opera.

Ver docs/DISENO.md, sección "Cómo decide".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from .calibracion import Calibrador
from .cartera import Cartera
from .config import Config
from .montecarlo import ResultadoMC, simular_operacion
from .riesgo import monto_maximo_permitido, tamano_posicion


class TipoSenal(str, Enum):
    NOTICIA = "noticia"  # fase 3: noticias y avisos a la SEC analizados por Claude
    TECNICA = "tecnica"  # fase 1: patrón de precio, sin noticias


@dataclass
class Senal:
    ticker: str
    sector: str
    tipo: TipoSenal
    causa: str | None
    fuentes: list[str]
    # Retornos que tuvieron situaciones parecidas del pasado, en el mismo plazo.
    precedentes: list[float]
    prob_bruta: float
    objetivo: float  # +10% = 0.10
    stop: float  # -5% = 0.05
    horizonte_dias: int
    volumen_diario: float  # en pesos
    mercado_abierto: bool
    retornos_historicos: np.ndarray = field(repr=False)
    precio: float = 0.0


@dataclass
class Evaluacion:
    senal: Senal
    aprobada: bool
    rechazos: list[str]
    prob_calibrada: float
    valor_esperado: float
    montecarlo: ResultadoMC | None
    monto_sugerido: float
    porcentaje_cuenta: float
    monto_maximo: float

    def resumen(self) -> str:
        s = self.senal
        if self.aprobada:
            return (
                f"{s.ticker}: {s.causa}. Confianza {self.prob_calibrada:.0%}. "
                f"Recomiendo ${self.monto_sugerido:,.0f} ({self.porcentaje_cuenta:.1%} de la cuenta)."
            )
        return f"{s.ticker}: descartada. " + " ".join(self.rechazos)


def evaluar(
    senal: Senal,
    cartera: Cartera,
    cfg: Config,
    calibrador: Calibrador,
    rng: np.random.Generator | None = None,
) -> Evaluacion:
    f = cfg.filtros
    costo = 2 * (cfg.costos.comision + cfg.costos.deslizamiento)
    rechazos: list[str] = []

    # 1. Sabe por qué se movió.
    if not senal.causa:
        rechazos.append("No tiene identificada la causa del movimiento.")

    # 2. La causa está confirmada por fuentes independientes.
    minimo = f.min_fuentes_noticia if senal.tipo == TipoSenal.NOTICIA else f.min_fuentes_tecnica
    if len(set(senal.fuentes)) < minimo:
        rechazos.append(f"Solo {len(set(senal.fuentes))} fuente(s); necesita {minimo}.")

    # 3. Hay precedentes suficientes.
    if len(senal.precedentes) < f.min_precedentes:
        rechazos.append(f"Solo {len(senal.precedentes)} precedentes; necesita {f.min_precedentes}.")

    # 4. La confianza calibrada supera el mínimo.
    prob = calibrador.calibrar(senal.prob_bruta)
    if prob < f.prob_minima:
        rechazos.append(f"Confianza calibrada {prob:.0%}, por debajo de {f.prob_minima:.0%}.")

    # 5. Gana después de costos.
    ve = prob * senal.objetivo - (1 - prob) * senal.stop - costo
    if ve <= 0:
        rechazos.append(f"Ganancia esperada después de costos negativa ({ve:+.2%}).")

    # 6. Pasa las simulaciones.
    mc: ResultadoMC | None = None
    deriva = None
    if senal.precedentes:
        medio = float(np.mean(senal.precedentes))
        deriva = (1 + medio) ** (1 / senal.horizonte_dias) - 1 if medio > -1 else None
    try:
        mc = simular_operacion(
            senal.retornos_historicos,
            objetivo=senal.objetivo,
            stop=senal.stop,
            dias=senal.horizonte_dias,
            costo_ida_vuelta=costo,
            umbral_perdida=f.umbral_perdida,
            caminos=f.caminos_montecarlo,
            rng=rng,
            deriva_diaria=deriva,
        )
        if mc.prob_perdida_mayor_umbral >= f.max_prob_perdida:
            rechazos.append(
                f"En las simulaciones pierde más de {f.umbral_perdida:.0%} el "
                f"{mc.prob_perdida_mayor_umbral:.0%} de las veces (máximo {f.max_prob_perdida:.0%})."
            )
        if mc.retorno_esperado <= 0:
            rechazos.append(f"En las simulaciones el resultado promedio es negativo ({mc.retorno_esperado:+.2%}).")
    except ValueError as e:
        rechazos.append(f"No se pudo simular: {e}")

    # 7. Hay liquidez y el mercado está abierto.
    if senal.volumen_diario < f.volumen_minimo_diario:
        rechazos.append("Poco volumen operado: difícil entrar y salir sin mover el precio.")
    if not senal.mercado_abierto:
        rechazos.append("El mercado está cerrado.")

    # 8. Entra en los topes de riesgo.
    maximo = monto_maximo_permitido(cartera, senal.ticker, senal.sector, cfg.limites)
    monto = 0.0
    if not rechazos:
        monto = tamano_posicion(
            cartera, prob, senal.objetivo, senal.stop, senal.ticker, senal.sector,
            cfg.limites, f.fraccion_kelly,
        )
        if senal.precio > 0 and monto < senal.precio:
            rechazos.append("No queda margen en los topes de riesgo para comprar ni una unidad.")
            monto = 0.0

    total = cartera.valor_total
    return Evaluacion(
        senal=senal,
        aprobada=not rechazos,
        rechazos=rechazos,
        prob_calibrada=prob,
        valor_esperado=ve,
        montecarlo=mc,
        monto_sugerido=monto,
        porcentaje_cuenta=monto / total if total > 0 else 0.0,
        monto_maximo=maximo,
    )
