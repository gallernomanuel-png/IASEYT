"""Broker de mentira: opera con precios reales o sintéticos y plata ficticia."""

from __future__ import annotations

import math
from datetime import datetime

from .base import Broker, Ejecucion


class BrokerSimulado(Broker):
    soporta_stops = False  # los stops los vigila el motor

    def __init__(self, efectivo_inicial: float, comision: float, deslizamiento: float):
        if efectivo_inicial < 0:
            raise ValueError("El efectivo inicial no puede ser negativo.")
        self._efectivo = float(efectivo_inicial)
        self.comision = comision
        self.deslizamiento = deslizamiento
        self._precios: dict[str, float] = {}
        self._tenencias: dict[str, int] = {}

    def actualizar_precios(self, precios: dict[str, float]) -> None:
        self._precios.update(precios)

    def efectivo(self) -> float:
        return self._efectivo

    def tenencia(self, ticker: str) -> int:
        return self._tenencias.get(ticker, 0)

    def _precio(self, ticker: str) -> float:
        try:
            return self._precios[ticker]
        except KeyError:
            raise ValueError(f"No hay precio para {ticker}.") from None

    def comprar(self, ticker: str, monto: float, fecha: datetime) -> Ejecucion | None:
        monto = min(monto, self._efectivo)
        precio = self._precio(ticker) * (1 + self.deslizamiento)
        cantidad = math.floor(monto / (precio * (1 + self.comision)))
        if cantidad < 1:
            return None
        bruto = cantidad * precio
        comision = bruto * self.comision
        self._efectivo -= bruto + comision
        self._tenencias[ticker] = self.tenencia(ticker) + cantidad
        return Ejecucion(ticker, "compra", cantidad, precio, comision, fecha)

    def vender(self, ticker: str, cantidad: int, fecha: datetime) -> Ejecucion:
        if cantidad < 1 or cantidad > self.tenencia(ticker):
            raise ValueError(f"No hay {cantidad} unidades de {ticker} para vender.")
        precio = self._precio(ticker) * (1 - self.deslizamiento)
        bruto = cantidad * precio
        comision = bruto * self.comision
        self._efectivo += bruto - comision
        self._tenencias[ticker] -= cantidad
        if self._tenencias[ticker] == 0:
            del self._tenencias[ticker]
        return Ejecucion(ticker, "venta", cantidad, precio, comision, fecha)
