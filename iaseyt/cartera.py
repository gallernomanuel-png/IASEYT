"""Cartera: efectivo y posiciones abiertas."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Posicion:
    ticker: str
    sector: str
    cantidad: int
    precio_entrada: float
    precio_actual: float
    stop: float  # precio al que corta la pérdida
    objetivo: float  # precio al que toma la ganancia
    vence_en_barra: int  # número de barra del feed en que vence el plazo
    prob_bruta: float = 0.0
    id_operacion: int | None = None
    # El stop sube cuando la acción sube fuerte (asegura ganancia).
    precio_maximo: float = 0.0
    distancia_stop: float = 0.0
    costo_total: float = 0.0  # lo que costó comprar, comisiones incluidas

    def __post_init__(self) -> None:
        if self.precio_maximo == 0.0:
            self.precio_maximo = self.precio_entrada
        if self.distancia_stop == 0.0:
            self.distancia_stop = self.precio_entrada - self.stop

    def actualizar_precio(self, precio: float) -> None:
        """Actualiza el precio y, si ya subió la mitad del objetivo, sube el stop."""
        self.precio_actual = precio
        self.precio_maximo = max(self.precio_maximo, precio)
        mitad = self.precio_entrada + (self.objetivo - self.precio_entrada) / 2
        if self.precio_maximo >= mitad:
            self.stop = max(self.stop, self.precio_maximo - self.distancia_stop)

    @property
    def valor(self) -> float:
        return self.cantidad * self.precio_actual


@dataclass
class Cartera:
    efectivo: float
    posiciones: dict[str, Posicion] = field(default_factory=dict)

    @property
    def valor_total(self) -> float:
        return self.efectivo + sum(p.valor for p in self.posiciones.values())

    def exposicion_empresa(self, ticker: str) -> float:
        p = self.posiciones.get(ticker)
        return p.valor if p else 0.0

    def exposicion_sector(self, sector: str) -> float:
        return sum(p.valor for p in self.posiciones.values() if p.sector == sector)
