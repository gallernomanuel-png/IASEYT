"""Interfaz común de brokers. El simulado y los reales (IOL, PPI) la cumplen."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Ejecucion:
    ticker: str
    lado: str  # "compra" o "venta"
    cantidad: int
    precio: float  # precio por unidad, con deslizamiento incluido
    comision: float
    fecha: datetime

    @property
    def monto(self) -> float:
        return self.cantidad * self.precio


class Broker(ABC):
    # True si el broker acepta órdenes de stop que funcionan aunque IASEYT esté apagada.
    soporta_stops: bool = False

    @abstractmethod
    def actualizar_precios(self, precios: dict[str, float]) -> None: ...

    @abstractmethod
    def efectivo(self) -> float: ...

    @abstractmethod
    def comprar(self, ticker: str, monto: float, fecha: datetime) -> Ejecucion | None:
        """Compra por hasta `monto` pesos, comisiones incluidas. None si no alcanza para 1 unidad."""

    @abstractmethod
    def vender(self, ticker: str, cantidad: int, fecha: datetime) -> Ejecucion: ...
