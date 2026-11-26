"""Fuentes de precios.

En la fase 1 los datos vienen de un archivo CSV o de precios sintéticos.
En la fase 2 se suman Finnhub y el broker; en la fase 3, noticias y la SEC.

El feed avanza de a un paso (una barra). Solo avanza mientras IASEYT lee
datos, así al reanudar sigue desde lo último que recopiló, sin huecos.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Barra:
    ticker: str
    fecha: datetime
    precio: float
    volumen: float  # monto operado en pesos


class FeedHistorico:
    """Serie de precios ya conocida que se recorre paso a paso, sin mirar el futuro."""

    def __init__(
        self,
        fechas: list[datetime],
        precios: dict[str, np.ndarray],
        volumenes: dict[str, np.ndarray],
        sectores: dict[str, str],
    ):
        n = len(fechas)
        for t in precios:
            if len(precios[t]) != n or len(volumenes[t]) != n:
                raise ValueError(f"La serie de {t} no tiene el mismo largo que las fechas.")
            if np.any(precios[t] <= 0):
                raise ValueError(f"La serie de {t} tiene precios no positivos.")
        self.fechas = fechas
        self.precios = precios
        self.volumenes = volumenes
        self.sectores = sectores
        self.indice = -1  # todavía no se leyó nada
        self.inicio = 0  # primera barra que se lee (antes de esa, es historia)

    def ventana(self, inicio: int, fin: int) -> "FeedHistorico":
        """Copia que empieza a leer en la barra `inicio` y termina antes de `fin`.

        Todo lo anterior a `inicio` queda como historia visible (es pasado).
        Desde `fin` en adelante no existe: así es imposible mirar el futuro.
        """
        if not 0 <= inicio < fin <= len(self.fechas):
            raise ValueError(f"Ventana inválida: {inicio} a {fin} con {len(self.fechas)} barras.")
        f = FeedHistorico(
            self.fechas[:fin],
            {t: p[:fin] for t, p in self.precios.items()},
            {t: v[:fin] for t, v in self.volumenes.items()},
            self.sectores,
        )
        f.indice = inicio - 1
        f.inicio = inicio
        return f

    @property
    def tickers(self) -> list[str]:
        return sorted(self.precios)

    @property
    def fecha_actual(self) -> datetime | None:
        return self.fechas[self.indice] if self.indice >= 0 else None

    @property
    def terminado(self) -> bool:
        return self.indice >= len(self.fechas) - 1

    def avanzar(self) -> dict[str, Barra] | None:
        """Lee la barra siguiente. None si no hay datos nuevos."""
        if self.terminado:
            return None
        self.indice += 1
        f = self.fechas[self.indice]
        return {
            t: Barra(t, f, float(self.precios[t][self.indice]), float(self.volumenes[t][self.indice]))
            for t in self.tickers
        }

    def historia(self, ticker: str) -> np.ndarray:
        """Precios hasta hoy inclusive. Nunca incluye el futuro."""
        return self.precios[ticker][: self.indice + 1]

    def mercado_abierto(self) -> bool:
        return self.indice >= 0


def feed_sintetico(
    tickers: dict[str, str] | None = None,
    dias: int = 750,
    semilla: int = 7,
    inicio: datetime = datetime(2023, 1, 2),
) -> FeedHistorico:
    """Precios inventados para probar sin internet. No sirven para sacar conclusiones."""
    tickers = tickers or {
        "NVDA": "Tecnología", "AMD": "Tecnología", "MSFT": "Tecnología",
        "AAPL": "Tecnología", "KO": "Consumo", "WMT": "Consumo",
        "JPM": "Finanzas", "XOM": "Energía",
    }
    rng = np.random.default_rng(semilla)
    fechas, f = [], inicio
    while len(fechas) < dias:
        if f.weekday() < 5:
            fechas.append(f)
        f += timedelta(days=1)
    mercado = rng.normal(0.0007, 0.009, dias)
    precios, volumenes = {}, {}
    for i, t in enumerate(sorted(tickers)):
        beta = rng.uniform(0.6, 1.5)
        propio = rng.standard_t(4, dias) * rng.uniform(0.008, 0.02) / np.sqrt(2)
        # Algo de reversión de corto plazo, para que la estrategia de prueba tenga con qué trabajar.
        r = beta * mercado + propio
        for d in range(5, dias):
            r[d] -= 0.08 * r[d - 5 : d].sum()
        precios[t] = 1000.0 * (1 + i * 0.3) * np.cumprod(1 + r)
        volumenes[t] = rng.lognormal(np.log(3e8), 0.5, dias)
    return FeedHistorico(fechas, precios, volumenes, dict(tickers))


def feed_desde_csv(ruta: str | Path) -> FeedHistorico:
    """CSV con columnas: fecha (AAAA-MM-DD), ticker, sector, precio, volumen."""
    filas: dict[str, dict[datetime, tuple[float, float]]] = {}
    sectores: dict[str, str] = {}
    with open(ruta, newline="", encoding="utf-8") as fh:
        for fila in csv.DictReader(fh):
            t = fila["ticker"].strip().upper()
            fecha = datetime.fromisoformat(fila["fecha"].strip())
            filas.setdefault(t, {})[fecha] = (float(fila["precio"]), float(fila["volumen"]))
            sectores[t] = fila["sector"].strip()
    if not filas:
        raise ValueError("El CSV está vacío.")
    # Solo fechas en las que hay precio de todos los tickers.
    comunes = sorted(set.intersection(*(set(d) for d in filas.values())))
    if not comunes:
        raise ValueError("No hay fechas en común entre los tickers del CSV.")
    precios = {t: np.array([d[f][0] for f in comunes]) for t, d in filas.items()}
    volumenes = {t: np.array([d[f][1] for f in comunes]) for t, d in filas.items()}
    return FeedHistorico(comunes, precios, volumenes, sectores)
