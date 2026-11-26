"""Conexión con PPI (Portfolio Personal Inversiones).

Usa la librería oficial `ppi-client`. Por defecto se conecta al **sandbox**,
el entorno de prueba de PPI, donde las órdenes no usan plata real.

Las claves se leen de variables de entorno, nunca del código ni del repo:

    PPI_KEY_PUBLICA    clave pública de la API
    PPI_KEY_PRIVADA    clave privada de la API
    PPI_CUENTA         número de cuenta comitente

Cosas que todavía hay que confirmar en el sandbox (la documentación de PPI no
las detalla): los textos exactos del estado de una orden y cómo responde el
saldo disponible. Por eso el código los interpreta con cuidado y, ante la duda,
no opera. El comando `python -m iaseyt ppi-prueba-orden` muestra las respuestas
crudas para ajustarlo.
"""

from __future__ import annotations

import math
import os
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Mapping

from ..config import ConfigPPI
from .base import Broker, Ejecucion

VARIABLE_PLATA_REAL = "IASEYT_PLATA_REAL"
CONFIRMACION_PLATA_REAL = "si-entiendo-el-riesgo"


class ErrorPPI(Exception):
    pass


def conectar(sandbox: bool, entorno: Mapping[str, str] = os.environ) -> tuple[Any, str]:
    """Inicia sesión en PPI y devuelve (cliente, número de cuenta)."""
    publica = entorno.get("PPI_KEY_PUBLICA", "").strip()
    privada = entorno.get("PPI_KEY_PRIVADA", "").strip()
    cuenta = entorno.get("PPI_CUENTA", "").strip()
    faltan = [n for n, v in (("PPI_KEY_PUBLICA", publica), ("PPI_KEY_PRIVADA", privada), ("PPI_CUENTA", cuenta)) if not v]
    if faltan:
        raise ErrorPPI("Faltan variables de entorno: " + ", ".join(faltan) + ". Ver README, sección PPI.")
    try:
        from ppi_client.ppi import PPI
    except ImportError as e:
        raise ErrorPPI("Falta la librería de PPI: pip install ppi-client") from e
    cliente = PPI(sandbox=sandbox)
    try:
        cliente.account.login_api(publica, privada)
    except Exception as e:
        raise ErrorPPI(f"PPI rechazó el inicio de sesión: {e}") from e
    return cliente, cuenta


def _numero(valor: Any) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        raise ErrorPPI(f"PPI devolvió un número inválido: {valor!r}") from None


def _es_pesos(item: Mapping[str, Any]) -> bool:
    texto = " ".join(str(item.get(k, "")) for k in ("name", "currency", "simbol", "symbol")).lower()
    if "dolar" in texto or "dólar" in texto or "usd" in texto or "us$" in texto:
        return False
    return "peso" in texto or "ars" in texto or texto.strip() == "$" or " $" in f" {texto}"


def estado_orden(detalle: Mapping[str, Any] | None) -> str:
    """Clasifica el estado que devuelve PPI en: ejecutada, viva, muerta o desconocido."""
    if not detalle:
        return "desconocido"
    estado = str(detalle.get("status", "")).strip().lower()
    if not estado:
        return "desconocido"
    if "parcial" in estado or "partial" in estado:
        return "viva"
    if any(p in estado for p in ("cancel", "rechaz", "anulad", "vencid", "error", "reject", "expir")):
        return "muerta"
    if any(p in estado for p in ("ejecutad", "complet", "filled", "operad", "cumplid", "terminad")):
        return "ejecutada"
    if any(p in estado for p in ("pend", "activ", "ofert", "envi", "recib", "nueva", "new", "open", "abiert")):
        return "viva"
    return "desconocido"


class LectorPPI:
    """Solo lectura: precios, históricos, saldo y posiciones. No puede operar."""

    def __init__(self, cliente: Any, cuenta: str, cfg: ConfigPPI):
        self.cliente = cliente
        self.cuenta = cuenta
        self.cfg = cfg

    def precio_actual(self, ticker: str) -> float:
        datos = self.cliente.marketdata.current(ticker, self.cfg.tipo_instrumento, self.cfg.liquidacion)
        precio = _numero((datos or {}).get("price"))
        if precio <= 0:
            raise ErrorPPI(f"PPI devolvió un precio no positivo para {ticker}: {precio}")
        return precio

    def historico(self, ticker: str, desde: datetime, hasta: datetime) -> list[dict]:
        """Barras diarias: fecha, precio de cierre y volumen (en nominales)."""
        datos = self.cliente.marketdata.search(ticker, self.cfg.tipo_instrumento, self.cfg.liquidacion, desde, hasta)
        barras = []
        for d in datos or []:
            try:
                fecha = datetime.fromisoformat(str(d["date"])[:19])
                precio = float(d["price"])
                volumen = float(d.get("volume") or 0.0)
            except (KeyError, TypeError, ValueError):
                continue  # una fila rota no frena la descarga
            if precio > 0:
                barras.append({"fecha": fecha, "precio": precio, "volumen": volumen})
        barras.sort(key=lambda b: b["fecha"])
        return barras

    def saldo_disponible(self) -> float:
        """Pesos disponibles para operar. Si hay varios plazos, toma el menor (lo más prudente)."""
        datos = self.cliente.account.get_available_balance(self.cuenta) or []
        montos = [
            _numero(item.get("amount"))
            for item in datos
            if _es_pesos(item) and str(item.get("settlement", "")).upper() in (self.cfg.liquidacion, "INMEDIATA")
        ]
        if not montos:
            raise ErrorPPI(f"No encontré el saldo en pesos en la respuesta de PPI: {datos!r}")
        return max(0.0, min(montos))

    def saldo_y_posiciones(self) -> Any:
        return self.cliente.account.get_balance_and_positions(self.cuenta)


class BrokerPPI(Broker):
    """Opera en PPI con órdenes límite. Por defecto, solo en el sandbox."""

    soporta_stops = False  # hasta confirmar las órdenes de stop en el sandbox, las vigila el motor

    def __init__(
        self,
        lector: LectorPPI,
        cfg: ConfigPPI,
        comision: float,
        deslizamiento: float,
        entorno: Mapping[str, str] = os.environ,
        dormir: Callable[[float], None] = time.sleep,
        reloj: Callable[[], float] = time.monotonic,
        registrar: Callable[[str], None] | None = None,
    ):
        if not cfg.sandbox and entorno.get(VARIABLE_PLATA_REAL) != CONFIRMACION_PLATA_REAL:
            raise ErrorPPI(
                "IASEYT está en simulación: no opera con plata real. "
                "Eso se habilita recién en la fase 6, después de meses de prueba."
            )
        self.lector = lector
        self.cliente = lector.cliente
        self.cuenta = lector.cuenta
        self.cfg = cfg
        self.comision = comision
        self.deslizamiento = deslizamiento
        self.dormir = dormir
        self.reloj = reloj
        self.registrar = registrar or (lambda texto: None)
        self._efectivo_cache: tuple[float, float] | None = None

    def actualizar_precios(self, precios: dict[str, float]) -> None:
        # Los precios para operar se piden a PPI en el momento de la orden.
        pass

    def efectivo(self) -> float:
        ahora = self.reloj()
        if self._efectivo_cache and ahora - self._efectivo_cache[0] < 10:
            return self._efectivo_cache[1]
        saldo = self.lector.saldo_disponible()
        self._efectivo_cache = (ahora, saldo)
        return saldo

    def comprar(self, ticker: str, monto: float, fecha: datetime) -> Ejecucion | None:
        precio = round(self.lector.precio_actual(ticker) * (1 + self.deslizamiento), 2)
        cantidad = math.floor(min(monto, self.efectivo()) / (precio * (1 + self.comision)))
        if cantidad < 1:
            return None
        return self._operar(ticker, "COMPRA", cantidad, precio, fecha)

    def vender(self, ticker: str, cantidad: int, fecha: datetime) -> Ejecucion:
        if cantidad < 1:
            raise ValueError("La cantidad a vender tiene que ser al menos 1.")
        precio = round(self.lector.precio_actual(ticker) * (1 - self.deslizamiento), 2)
        ej = self._operar(ticker, "VENTA", cantidad, precio, fecha)
        if ej is None:
            raise ErrorPPI(f"La venta de {ticker} no se ejecutó a tiempo y se canceló.")
        return ej

    def _operar(self, ticker: str, operacion: str, cantidad: int, precio: float, fecha: datetime) -> Ejecucion | None:
        from ppi_client.models.disclaimer import Disclaimer
        from ppi_client.models.order import Order
        from ppi_client.models.order_budget import OrderBudget
        from ppi_client.models.order_confirm import OrderConfirm

        comunes = dict(
            accountNumber=self.cuenta, quantity=cantidad, price=precio, ticker=ticker,
            instrumentType=self.cfg.tipo_instrumento, quantityType="PAPELES",
            operationType="PRECIO-LIMITE", operationTerm="POR-EL-DÍA", operationMaxDate=None,
            operation=operacion, settlement=self.cfg.liquidacion,
        )
        presupuesto = self.cliente.orders.budget(OrderBudget(**comunes)) or {}
        avisos = presupuesto.get("disclaimers") or []
        for a in avisos:
            self.registrar(f"Aviso de PPI aceptado ({a.get('code')}): {a.get('description', a.get('text', ''))}")
        aceptados = [Disclaimer(a["code"], True) for a in avisos if "code" in a]
        id_externo = f"iaseyt-{uuid.uuid4().hex[:16]}"
        confirmacion = self.cliente.orders.confirm(
            OrderConfirm(**comunes, disclaimers=aceptados, externalId=id_externo)
        ) or {}
        id_orden = confirmacion.get("id")
        self._efectivo_cache = None
        self.registrar(f"Orden enviada a PPI: {operacion} {cantidad} {ticker} a ${precio:,.2f} (id {id_orden}).")

        limite = self.reloj() + self.cfg.segundos_espera_orden
        estado = estado_orden(confirmacion)
        detalle: Mapping[str, Any] = confirmacion
        while estado in ("viva", "desconocido") and self.reloj() < limite:
            self.dormir(2.0)
            detalle = self.cliente.orders.get_order_detail(self.cuenta, id_orden, id_externo) or {}
            estado = estado_orden(detalle)

        if estado == "ejecutada":
            precio_real = detalle.get("price") or precio
            ej_precio = _numero(precio_real)
            return Ejecucion(ticker, operacion.lower(), cantidad, ej_precio, cantidad * ej_precio * self.comision, fecha)

        parcial = "parcial" in str(detalle.get("status", "")).lower() or "partial" in str(detalle.get("status", "")).lower()
        if estado != "muerta":
            try:
                self.cliente.orders.cancel_order(Order(id=id_orden, account_number=self.cuenta, externalId=id_externo))
            except Exception as e:  # informar, pero no ocultar el problema de fondo
                self.registrar(f"No se pudo cancelar la orden {id_orden}: {e}")
        if parcial:
            raise ErrorPPI(
                f"La orden {id_orden} de {ticker} se ejecutó en parte y se canceló el resto. "
                "Revisá la cuenta: puede haber una posición que IASEYT no tiene registrada."
            )
        if estado == "desconocido":
            raise ErrorPPI(
                f"PPI devolvió un estado de orden que IASEYT no reconoce: {detalle.get('status')!r}. "
                "Revisá la cuenta antes de seguir."
            )
        self.registrar(f"Orden {id_orden} sin ejecutar ({detalle.get('status')}): cancelada.")
        return None
