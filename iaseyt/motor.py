"""El motor de IASEYT: une datos, estrategia, filtros, riesgo, broker e historial.

Cada llamada a `paso()` es un ciclo: lee datos nuevos, vigila las posiciones
abiertas, revisa los frenos y, si está encendida, busca oportunidades.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Callable, Protocol

import numpy as np

from .broker.base import Broker
from .calibracion import Calibrador
from .cartera import Cartera, Posicion
from .config import Config
from .data.feed import FeedHistorico
from .decision import Evaluacion, Senal, evaluar
from .estado import ControlEstado, Estado, Modo, MotivoPausa, TransicionInvalida
from .historial import Historial
from .riesgo import verificar_frenos


class Estrategia(Protocol):
    def generar(self, feed: FeedHistorico, cartera: Cartera) -> list[Senal]: ...


class Motor:
    def __init__(
        self,
        cfg: Config,
        broker: Broker,
        feed: FeedHistorico,
        estrategia: Estrategia,
        historial: Historial,
        reloj: Callable[[], datetime] = datetime.now,
        rng: np.random.Generator | None = None,
    ):
        self.cfg = cfg
        self.broker = broker
        self.feed = feed
        self.estrategia = estrategia
        self.historial = historial
        self.reloj = reloj
        self.rng = rng or np.random.default_rng()
        self.control = ControlEstado()
        self.cartera = Cartera(efectivo=broker.efectivo())
        self.calibrador = Calibrador(observaciones=historial.calibracion())
        self.valor_pico = self.cartera.valor_total
        self.valor_inicio_dia = self.cartera.valor_total
        self._dia: datetime | None = None
        self._evaluaciones: dict[int, Evaluacion] = {}
        # El panel y el ciclo automático pueden llamar al mismo tiempo.
        self.lock = threading.RLock()

    # Botones ------------------------------------------------------------------
    def _registrar_estado(self, detalle: str) -> None:
        self.historial.evento(self.reloj(), "estado", detalle)
        self.historial.guardar("estado", {"estado": self.control.estado.value, "modo": self.control.modo.value})

    def encender(self) -> None:
        with self.lock:
            self.control.encender()
            self._registrar_estado("Encendida: lee datos y toma decisiones.")

    def pausar(self) -> None:
        with self.lock:
            self.control.pausar(MotivoPausa.MANUAL)
            self._registrar_estado("Pausada: sigue leyendo datos, no abre operaciones nuevas.")

    def reanudar(self, confirmo_revision: bool = False) -> None:
        with self.lock:
            self.control.reanudar(confirmo_revision)
            self._registrar_estado("Reanudada desde el último dato recopilado.")

    def apagar(self) -> list[str]:
        """Apaga y devuelve las posiciones que quedan sin vigilancia de stop."""
        with self.lock:
            self.control.apagar()
            sin_vigilancia = [] if self.broker.soporta_stops else sorted(self.cartera.posiciones)
            detalle = "Apagada: deja de leer datos."
            if sin_vigilancia:
                detalle += " Sin stop en el broker: " + ", ".join(sin_vigilancia) + "."
            self._registrar_estado(detalle)
            return sin_vigilancia

    def cerrar_todo(self) -> None:
        """Botón de emergencia: vende todo y apaga."""
        with self.lock:
            for t in list(self.cartera.posiciones):
                self._vender(t, "cierre de emergencia")
            self.control.apagar()
            self._registrar_estado("Cerrar todo: vendió todas las posiciones y se apagó.")

    def cambiar_modo(self, modo: Modo) -> None:
        with self.lock:
            self.control.cambiar_modo(modo)
            self._registrar_estado(f"Modo {modo.value}.")

    # Ciclo ----------------------------------------------------------------------
    def paso(self) -> None:
        with self.lock:
            if not self.control.lee_datos:
                return
            barras = self.feed.avanzar()
            if barras is None:
                return
            fecha_mercado = next(iter(barras.values())).fecha
            # Valor al cierre anterior = inicio del día para el freno diario.
            if self._dia is None or fecha_mercado.date() != self._dia.date():
                self.valor_inicio_dia = self.cartera.valor_total
                self._dia = fecha_mercado
            precios = {t: b.precio for t, b in barras.items()}
            self.broker.actualizar_precios(precios)
            for t, pos in self.cartera.posiciones.items():
                if t in precios:
                    pos.actualizar_precio(precios[t])

            # Las salidas de protección (stop, objetivo, plazo) corren aunque esté en pausa.
            self._vigilar_posiciones()
            self.cartera.efectivo = self.broker.efectivo()

            valor = self.cartera.valor_total
            self.historial.registrar_valor(self.reloj(), valor)
            self.valor_pico = max(self.valor_pico, valor)
            motivo = verificar_frenos(valor, self.valor_inicio_dia, self.valor_pico, self.cfg.limites)
            if motivo and not (self.control.estado == Estado.PAUSADA and self.control.motivo_pausa == motivo):
                self.control.pausar(motivo)
                self.historial.evento(self.reloj(), "freno", f"Se activó el freno: {motivo.value}. Quedó en pausa.")

            self._vencer_propuestas()
            self._quizas_pasar_a_automatico()

            if self.control.toma_decisiones:
                self._buscar_oportunidades()

    def _vigilar_posiciones(self) -> None:
        for t, pos in list(self.cartera.posiciones.items()):
            if pos.precio_actual <= pos.stop:
                motivo = "stop"
            elif pos.precio_actual >= pos.objetivo:
                motivo = "objetivo"
            elif self.feed.indice >= pos.vence_en_barra:
                motivo = "plazo"
            else:
                continue
            self._vender(t, motivo)

    def _buscar_oportunidades(self) -> None:
        pendientes = {p["ticker"] for p in self.historial.propuestas("pendiente")}
        for senal in self.estrategia.generar(self.feed, self.cartera):
            if senal.ticker in pendientes:
                continue
            ev = evaluar(senal, self.cartera, self.cfg, self.calibrador, self.rng)
            if not ev.aprobada:
                self.historial.evento(self.reloj(), "descarte", ev.resumen())
                continue
            if self.control.modo == Modo.AUTOMATICO:
                self._comprar(ev, ev.monto_sugerido, Modo.AUTOMATICO, monto_propuesto=ev.monto_sugerido)
            else:
                self._proponer(ev)

    # Modo asistido ----------------------------------------------------------------
    def _proponer(self, ev: Evaluacion) -> None:
        ahora = self.reloj()
        id_prop = self.historial.crear_propuesta(
            ahora, ahora + timedelta(minutes=self.cfg.minutos_para_responder), ev.senal.ticker,
            ev.resumen(), ev.monto_sugerido, ev.porcentaje_cuenta, ev.monto_maximo,
        )
        self._evaluaciones[id_prop] = ev
        self.historial.evento(ahora, "propuesta", ev.resumen(), {"propuesta": id_prop})

    def aceptar_propuesta(self, id_prop: int, monto: float) -> dict:
        """Ejecuta una propuesta con el monto en pesos que elegiste."""
        with self.lock:
            prop = self.historial.propuesta(id_prop)
            if not prop or prop["estado"] != "pendiente":
                raise TransicionInvalida("La propuesta no existe o ya no está pendiente.")
            if datetime.fromisoformat(prop["vence"]) < self.reloj():
                self.historial.actualizar_propuesta(id_prop, "vencida")
                raise TransicionInvalida("La propuesta venció.")
            ev = self._evaluaciones.get(id_prop)
            if ev is None:
                raise TransicionInvalida("La propuesta se perdió al reiniciar; esperá una nueva.")
            if monto <= 0:
                raise ValueError("El monto tiene que ser positivo.")
            if monto > self.cartera.efectivo:
                raise ValueError(f"No alcanza el efectivo: hay ${self.cartera.efectivo:,.0f}.")
            aviso = None
            if monto > ev.monto_maximo:
                aviso = f"Supera el tope de riesgo (${ev.monto_maximo:,.0f}). Se ejecuta porque lo decidiste vos."
            self._comprar(ev, monto, Modo.ASISTIDO, monto_propuesto=ev.monto_sugerido)
            self.historial.actualizar_propuesta(id_prop, "aceptada", monto)
            return {"ok": True, "aviso": aviso}

    def rechazar_propuesta(self, id_prop: int) -> None:
        with self.lock:
            self.historial.actualizar_propuesta(id_prop, "rechazada")
            self._evaluaciones.pop(id_prop, None)

    def _vencer_propuestas(self) -> None:
        ahora = self.reloj()
        for p in self.historial.propuestas("pendiente"):
            if datetime.fromisoformat(p["vence"]) < ahora:
                self.historial.actualizar_propuesta(p["id"], "vencida")
                self._evaluaciones.pop(p["id"], None)
                self.historial.evento(ahora, "descarte", f"{p['ticker']}: propuesta vencida sin respuesta.")

    def _quizas_pasar_a_automatico(self) -> None:
        minutos = self.cfg.pasar_a_auto_tras_minutos
        if minutos is None or self.control.modo == Modo.AUTOMATICO:
            return
        ultima = self.historial.ultima_visita()
        if ultima and self.reloj() - ultima > timedelta(minutes=minutos):
            self.control.cambiar_modo(Modo.AUTOMATICO)
            self._registrar_estado(f"Pasó sola a modo automático: {minutos} minutos sin visitas.")

    # Compra y venta ---------------------------------------------------------------
    def _comprar(self, ev: Evaluacion, monto: float, modo: Modo, monto_propuesto: float) -> None:
        s = ev.senal
        ahora = self.reloj()
        ej = self.broker.comprar(s.ticker, monto, ahora)
        if ej is None:
            self.historial.evento(ahora, "descarte", f"{s.ticker}: el monto no alcanza para una unidad.")
            return
        total_antes = self.cartera.valor_total
        self.cartera.efectivo = self.broker.efectivo()
        id_op = self.historial.abrir_operacion(
            ticker=s.ticker, sector=s.sector, modo=modo.value, fecha_entrada=ahora,
            precio_entrada=ej.precio, cantidad=ej.cantidad, monto=ej.monto + ej.comision,
            porcentaje_cuenta=(ej.monto + ej.comision) / total_antes if total_antes else 0.0,
            monto_propuesto=monto_propuesto, causa=s.causa, fuentes=s.fuentes,
            prob_bruta=s.prob_bruta, prob_calibrada=ev.prob_calibrada,
            que_esperaba=f"Subir {s.objetivo:.0%} en {s.horizonte_dias} ruedas; stop en -{s.stop:.0%}.",
            objetivo=s.objetivo, stop=s.stop, horizonte_dias=s.horizonte_dias,
        )
        self.cartera.posiciones[s.ticker] = Posicion(
            ticker=s.ticker, sector=s.sector, cantidad=ej.cantidad, precio_entrada=ej.precio,
            precio_actual=s.precio, stop=ej.precio * (1 - s.stop), objetivo=ej.precio * (1 + s.objetivo),
            vence_en_barra=self.feed.indice + s.horizonte_dias, prob_bruta=s.prob_bruta, id_operacion=id_op,
            costo_total=ej.monto + ej.comision,
        )
        self.historial.evento(
            ahora, "compra",
            f"Compró {ej.cantidad} {s.ticker} a ${ej.precio:,.2f} ({modo.value}). {s.causa}.",
            {"operacion": id_op},
        )

    def _vender(self, ticker: str, motivo: str) -> None:
        pos = self.cartera.posiciones.pop(ticker)
        ahora = self.reloj()
        ej = self.broker.vender(ticker, pos.cantidad, ahora)
        self.cartera.efectivo = self.broker.efectivo()
        costo = pos.costo_total or pos.cantidad * pos.precio_entrada
        resultado = ej.monto - ej.comision - costo
        pct = resultado / costo if costo else 0.0
        if pos.id_operacion is not None:
            gano = resultado > 0
            self.calibrador.registrar(pos.prob_bruta, gano)
            self.historial.guardar_calibracion(pos.prob_bruta, gano)
            self.historial.cerrar_operacion(
                pos.id_operacion, ahora, ej.precio, resultado, pct, motivo,
                que_paso=f"Salió por {motivo}: {pct:+.1%} (${resultado:+,.0f}).",
                que_no_vio=(
                    "Pendiente: desde la fase 3, Claude revisa las noticias del período."
                    if resultado < 0 else "-"
                ),
            )
        self.historial.evento(
            ahora, "venta",
            f"Vendió {pos.cantidad} {ticker} a ${ej.precio:,.2f} por {motivo}: {pct:+.1%} (${resultado:+,.0f}).",
            {"operacion": pos.id_operacion},
        )

    # Para el panel ---------------------------------------------------------------
    def foto(self) -> dict:
        with self.lock:
            total = self.cartera.valor_total
            return {
                "estado": self.control.estado.value,
                "modo": self.control.modo.value,
                "motivo_pausa": self.control.motivo_pausa.value if self.control.motivo_pausa else None,
                "valor_total": total,
                "efectivo": self.cartera.efectivo,
                "valor_pico": self.valor_pico,
                "fecha_datos": self.feed.fecha_actual.isoformat() if self.feed.fecha_actual else None,
                "stops_en_broker": self.broker.soporta_stops,
                "posiciones": [
                    {
                        "ticker": p.ticker, "sector": p.sector, "cantidad": p.cantidad,
                        "precio_entrada": p.precio_entrada, "precio_actual": p.precio_actual,
                        "valor": p.valor, "porcentaje": p.valor / total if total else 0.0,
                        "resultado_pct": p.precio_actual / p.precio_entrada - 1,
                        "stop": p.stop, "objetivo": p.objetivo,
                    }
                    for p in self.cartera.posiciones.values()
                ],
                "calibracion": self.calibrador.tabla(),
            }

    def resumen_desde_ultima_visita(self) -> dict:
        """Registra la visita y cuenta qué cambió desde la anterior."""
        with self.lock:
            ahora = self.reloj()
            anterior = self.historial.registrar_visita(ahora)
            valor_ahora = self.cartera.valor_total
            if anterior is None:
                return {"primera_visita": True, "valor_ahora": valor_ahora}
            valor_antes = self.historial.valor_en(anterior) or self.cfg.capital_inicial
            eventos = self.historial.eventos(desde=anterior, limite=500)
            por_tipo: dict[str, list[str]] = {}
            for e in reversed(eventos):
                por_tipo.setdefault(e["tipo"], []).append(e["detalle"])
            horas = (ahora - anterior).total_seconds() / 3600
            return {
                "primera_visita": False,
                "desde": anterior.isoformat(timespec="minutes"),
                "horas": round(horas, 1),
                "valor_antes": valor_antes,
                "valor_ahora": valor_ahora,
                "variacion_pesos": valor_ahora - valor_antes,
                "variacion_pct": valor_ahora / valor_antes - 1 if valor_antes else 0.0,
                "compras": por_tipo.get("compra", []),
                "ventas": por_tipo.get("venta", []),
                "descartes": por_tipo.get("descarte", [])[-20:],
                "frenos": por_tipo.get("freno", []),
                "cambios_de_estado": por_tipo.get("estado", []),
                "propuestas_pendientes": len(self.historial.propuestas("pendiente")),
            }
