"""Simulación rápida: corre el motor sobre toda una serie de precios en modo automático."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from .broker import BrokerSimulado
from .config import Config
from .data.feed import FeedHistorico
from .estado import Estado, Modo
from .estrategia import EstrategiaCaidaFuerte
from .historial import Historial
from .motor import Motor


@dataclass
class Informe:
    valor_inicial: float
    valor_final: float
    retorno: float
    retorno_comprar_y_esperar: float
    peor_caida: float
    operaciones: int
    aciertos: float
    ganancia_promedio: float
    perdida_promedio: float
    frenos: int
    brier: float | None

    def texto(self) -> str:
        return "\n".join(
            [
                "Resultado de la simulación",
                f"  Valor inicial:          ${self.valor_inicial:,.0f}",
                f"  Valor final:            ${self.valor_final:,.0f}",
                f"  Retorno IASEYT:         {self.retorno:+.2%}",
                f"  Comprar y esperar:      {self.retorno_comprar_y_esperar:+.2%}  (todas las empresas, partes iguales)",
                f"  Peor caída desde pico:  {self.peor_caida:.2%}",
                f"  Operaciones cerradas:   {self.operaciones}",
                f"  Porcentaje de aciertos: {self.aciertos:.0%}",
                f"  Ganancia promedio:      {self.ganancia_promedio:+.2%}",
                f"  Pérdida promedio:       {self.perdida_promedio:+.2%}",
                f"  Frenos activados:       {self.frenos}",
                f"  Error de calibración:   {self.brier:.3f}" if self.brier is not None else "  Error de calibración:   sin datos",
                "",
                "Aviso: la estrategia de la fase 1 es de prueba y los precios",
                "sintéticos son inventados. Esto prueba que el circuito funciona,",
                "no que la estrategia gane plata.",
            ]
        )


def correr(feed: FeedHistorico, cfg: Config, semilla: int = 0, historial: Historial | None = None) -> tuple[Motor, Informe]:
    historial = historial or Historial(":memory:")
    broker = BrokerSimulado(cfg.capital_inicial, cfg.costos.comision, cfg.costos.deslizamiento)

    def reloj() -> datetime:
        return feed.fecha_actual or feed.fechas[0]

    motor = Motor(cfg, broker, feed, EstrategiaCaidaFuerte(), historial, reloj=reloj, rng=np.random.default_rng(semilla))
    motor.cambiar_modo(Modo.AUTOMATICO)
    motor.encender()
    while not feed.terminado:
        motor.paso()
        # En la simulación, un freno de pérdida diaria se levanta al día siguiente.
        # La caída desde el pico, en cambio, exige revisión: la simulación la acepta
        # automáticamente y lo deja anotado.
        if motor.control.estado == Estado.PAUSADA:
            motor.reanudar(confirmo_revision=True)
    for t in list(motor.cartera.posiciones):
        motor._vender(t, "fin de la simulación")

    valores = np.array([v["valor"] for v in historial.valores()] or [cfg.capital_inicial])
    picos = np.maximum.accumulate(valores)
    cerradas = historial.operaciones(abiertas=False)
    res = [o["resultado_pct"] for o in cerradas]
    ganadas = [r for r in res if r > 0]
    perdidas = [r for r in res if r <= 0]
    inicio = {t: feed.precios[t][0] for t in feed.tickers}
    fin = {t: feed.precios[t][-1] for t in feed.tickers}
    byh = float(np.mean([fin[t] / inicio[t] - 1 for t in feed.tickers]))
    final = motor.cartera.valor_total
    informe = Informe(
        valor_inicial=cfg.capital_inicial,
        valor_final=final,
        retorno=final / cfg.capital_inicial - 1,
        retorno_comprar_y_esperar=byh,
        peor_caida=float(((picos - valores) / picos).max()),
        operaciones=len(res),
        aciertos=len(ganadas) / len(res) if res else 0.0,
        ganancia_promedio=float(np.mean(ganadas)) if ganadas else 0.0,
        perdida_promedio=float(np.mean(perdidas)) if perdidas else 0.0,
        frenos=len(historial.eventos(tipo="freno", limite=100_000)),
        brier=motor.calibrador.brier(),
    )
    return motor, informe
