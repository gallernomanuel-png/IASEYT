"""Pruebas de la fase 2: ventanas del feed, backtest hacia adelante y descarga de precios."""

import csv
from datetime import datetime, timedelta

import pytest

from iaseyt.__main__ import main
from iaseyt.backtest import walk_forward
from iaseyt.config import cargar_config
from iaseyt.data import feed_desde_csv, feed_sintetico
from iaseyt.data.descarga import descargar, leer_tickers


def test_ventana_no_ve_el_futuro():
    f = feed_sintetico(dias=100)
    v = f.ventana(40, 60)
    assert v.inicio == 40 and v.indice == 39
    assert len(v.historia("NVDA")) == 40  # ve el pasado...
    v.avanzar()
    assert len(v.historia("NVDA")) == 41
    while v.avanzar():
        pass
    assert len(v.precios["NVDA"]) == 60  # ...y nada desde el fin
    with pytest.raises(ValueError):
        f.ventana(60, 40)


def test_walk_forward_solo_cuenta_periodos_de_prueba():
    feed = feed_sintetico(dias=400, semilla=11)
    r = walk_forward(feed, cargar_config("config.demo.toml"), 200, 50, grilla={"caida_minima": [0.05, 0.07]})
    assert len(r.tramos) == 4  # (400 - 200) / 50
    for t in r.tramos:
        assert t.parametros["caida_minima"] in (0.05, 0.07)
        # El período de prueba empieza después de que termina el de entrenamiento.
        assert t.prueba.split(" a ")[0] > t.entrenamiento.split(" a ")[1]
    assert "comprar y esperar" in r.texto()


def test_walk_forward_pide_datos_suficientes():
    with pytest.raises(ValueError, match="al menos"):
        walk_forward(feed_sintetico(dias=100), cargar_config(None), 250, 63)


class LectorFalso:
    def historico(self, ticker, desde, hasta):
        base = datetime(2026, 1, 5)
        return [{"fecha": base + timedelta(days=i), "precio": 100.0 + i, "volumen": 1000.0} for i in range(3)]


def test_descarga_genera_un_csv_que_el_feed_entiende(tmp_path):
    salida = tmp_path / "precios.csv"
    conteo = descargar(LectorFalso(), {"AAPL": "Tecnología", "KO": "Consumo"}, datetime(2026, 1, 1), datetime(2026, 2, 1), salida)
    assert conteo == {"AAPL": 3, "KO": 3}
    filas = list(csv.DictReader(open(salida, encoding="utf-8")))
    assert filas[0]["volumen"] == "100000"  # nominales × precio
    feed = feed_desde_csv(salida)
    assert feed.tickers == ["AAPL", "KO"] and len(feed.fechas) == 3


def test_leer_tickers():
    assert leer_tickers("aapl:Tecnología, KO") == {"AAPL": "Tecnología", "KO": "Sin sector"}
    assert "NVDA" in leer_tickers(None)


def test_cli_backtest_y_simular(capsys):
    assert main(["backtest", "--config", "config.demo.toml", "--entrenamiento", "200", "--prueba", "100"]) == 0
    salida = capsys.readouterr().out
    assert "sintéticos" in salida and "Total en períodos de prueba" in salida
    assert main(["simular"]) == 0


def test_cli_ppi_sin_claves_da_un_error_claro(capsys, monkeypatch):
    for v in ("PPI_KEY_PUBLICA", "PPI_KEY_PRIVADA", "PPI_CUENTA"):
        monkeypatch.delenv(v, raising=False)
    assert main(["ppi-verificar"]) == 2
    assert "PPI_KEY_PUBLICA" in capsys.readouterr().out
