"""Descarga de precios históricos de PPI a un CSV que entiende IASEYT."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

# Lista inicial: CEDEARs con mucho volumen. Se puede cambiar con --tickers.
TICKERS_POR_DEFECTO = {
    "AAPL": "Tecnología", "MSFT": "Tecnología", "NVDA": "Tecnología", "GOOGL": "Tecnología",
    "AMZN": "Consumo", "META": "Tecnología", "TSLA": "Consumo", "KO": "Consumo",
    "WMT": "Consumo", "JPM": "Finanzas", "XOM": "Energía", "MELI": "Consumo",
}


def leer_tickers(texto: str | None) -> dict[str, str]:
    """"AAPL:Tecnología,KO:Consumo" -> {"AAPL": "Tecnología", "KO": "Consumo"}."""
    if not texto:
        return dict(TICKERS_POR_DEFECTO)
    resultado = {}
    for parte in texto.split(","):
        if not parte.strip():
            continue
        ticker, _, sector = parte.partition(":")
        resultado[ticker.strip().upper()] = sector.strip() or "Sin sector"
    return resultado


def descargar(lector, tickers: dict[str, str], desde: datetime, hasta: datetime, salida: str | Path) -> dict[str, int]:
    """Baja el histórico de cada ticker y lo guarda. Devuelve cuántas ruedas bajó de cada uno.

    El volumen se guarda en pesos aproximados (nominales × precio), que es lo que
    usa el filtro de liquidez.
    """
    conteo: dict[str, int] = {}
    filas = []
    for ticker, sector in tickers.items():
        barras = lector.historico(ticker, desde, hasta)
        conteo[ticker] = len(barras)
        for b in barras:
            filas.append(
                {
                    "fecha": b["fecha"].date().isoformat(),
                    "ticker": ticker,
                    "sector": sector,
                    "precio": f"{b['precio']:.4f}",
                    "volumen": f"{b['volumen'] * b['precio']:.0f}",
                }
            )
    with open(salida, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["fecha", "ticker", "sector", "precio", "volumen"])
        w.writeheader()
        w.writerows(sorted(filas, key=lambda f: (f["fecha"], f["ticker"])))
    return conteo
