"""Pruebas de la conexión con PPI usando un cliente falso (sin internet)."""

from datetime import datetime

import pytest

from iaseyt.broker.ppi import (
    CONFIRMACION_PLATA_REAL,
    VARIABLE_PLATA_REAL,
    BrokerPPI,
    ErrorPPI,
    LectorPPI,
    conectar,
    estado_orden,
)
from iaseyt.config import ConfigPPI

pytest.importorskip("ppi_client")


class Cuentas:
    def __init__(self, saldo):
        self.saldo = saldo

    def get_available_balance(self, cuenta):
        return self.saldo


class Mercado:
    def __init__(self, precio=1000.0):
        self.precio = precio

    def current(self, ticker, tipo, liquidacion):
        assert tipo == "CEDEARS" and liquidacion == "A-24HS"
        return {"date": "2026-11-25T15:00:00", "price": self.precio}

    def search(self, ticker, tipo, liquidacion, desde, hasta):
        return [
            {"date": "2026-11-21T00:00:00", "price": 102.0, "volume": 10},
            {"date": "2026-11-20T00:00:00", "price": 100.0, "volume": 5},
            {"date": "roto", "price": 1},
            {"date": "2026-11-24T00:00:00", "price": None},
        ]


class Ordenes:
    def __init__(self, estados):
        self.estados = list(estados)  # lo que devuelve cada consulta de detalle
        self.confirmadas = []
        self.canceladas = []
        self.presupuestos = []

    def budget(self, p):
        self.presupuestos.append(p)
        return {"disclaimers": [{"code": "RIESGO", "description": "Operar implica riesgo"}]}

    def confirm(self, p):
        self.confirmadas.append(p)
        return {"id": 7, "status": "Pendiente"}

    def get_order_detail(self, cuenta, id_orden, externo):
        estado = self.estados.pop(0) if self.estados else "Pendiente"
        return {"id": id_orden, "status": estado, "price": 1003.0}

    def cancel_order(self, orden):
        self.canceladas.append(orden)


class Cliente:
    def __init__(self, estados=("Ejecutada",), saldo=None, precio=1000.0):
        self.account = Cuentas(
            saldo
            if saldo is not None
            else [
                {"name": "Pesos", "simbol": "$", "amount": 500_000, "settlement": "A-24HS"},
                {"name": "Pesos", "simbol": "$", "amount": 800_000, "settlement": "INMEDIATA"},
                {"name": "Dólares MEP", "simbol": "US$", "amount": 100, "settlement": "INMEDIATA"},
            ]
        )
        self.marketdata = Mercado(precio)
        self.orders = Ordenes(estados)


class Reloj:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def dormir(self, s):
        self.t += s


def _broker(estados=("Ejecutada",), cfg=None, entorno=None, **kw):
    reloj = Reloj()
    mensajes = []
    cliente = Cliente(estados, **kw)
    cfg = cfg or ConfigPPI()
    b = BrokerPPI(
        LectorPPI(cliente, "123", cfg), cfg, comision=0.005, deslizamiento=0.002,
        entorno=entorno or {}, dormir=reloj.dormir, reloj=reloj, registrar=mensajes.append,
    )
    return b, cliente, mensajes


def test_conectar_pide_las_variables_de_entorno():
    with pytest.raises(ErrorPPI, match="PPI_KEY_PUBLICA"):
        conectar(sandbox=True, entorno={})


def test_no_opera_con_plata_real_sin_confirmacion():
    cfg = ConfigPPI(sandbox=False)
    with pytest.raises(ErrorPPI, match="simulación"):
        _broker(cfg=cfg)
    b, _, _ = _broker(cfg=cfg, entorno={VARIABLE_PLATA_REAL: CONFIRMACION_PLATA_REAL})
    assert b is not None


def test_saldo_toma_el_menor_en_pesos():
    b, _, _ = _broker()
    assert b.efectivo() == 500_000


def test_saldo_sin_pesos_es_error():
    b, _, _ = _broker(saldo=[{"name": "Dólares", "simbol": "US$", "amount": 1, "settlement": "INMEDIATA"}])
    with pytest.raises(ErrorPPI):
        b.efectivo()


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("Ejecutada", "ejecutada"),
        ("COMPLETADA", "ejecutada"),
        ("Pendiente", "viva"),
        ("Parcialmente ejecutada", "viva"),
        ("Cancelada", "muerta"),
        ("Rechazada", "muerta"),
        ("algo raro", "desconocido"),
        ("", "desconocido"),
    ],
)
def test_estado_orden(texto, esperado):
    assert estado_orden({"status": texto}) == esperado


def test_compra_ejecutada_con_orden_limite():
    b, cliente, mensajes = _broker(estados=("Pendiente", "Ejecutada"))
    ej = b.comprar("AAPL", 100_000, datetime(2026, 11, 25))
    assert ej is not None and ej.lado == "compra"
    # 100.000 / (1002 * 1.005) = 99,3 -> 99 unidades
    assert ej.cantidad == 99 and ej.precio == 1003.0
    p = cliente.orders.confirmadas[0]
    assert p.operation == "COMPRA" and p.quantityType == "PAPELES" and p.operationType == "PRECIO-LIMITE"
    assert p.price == 1002.0 and p.externalId.startswith("iaseyt-")
    assert p.disclaimers[0].code == "RIESGO" and p.disclaimers[0].accepted
    assert any("Aviso de PPI" in m for m in mensajes)


def test_compra_no_supera_el_efectivo():
    b, _, _ = _broker()
    ej = b.comprar("AAPL", 10_000_000, datetime(2026, 11, 25))
    assert ej.cantidad * 1002 <= 500_000


def test_compra_sin_ejecutar_se_cancela():
    b, cliente, _ = _broker(estados=["Pendiente"] * 50)
    assert b.comprar("AAPL", 100_000, datetime(2026, 11, 25)) is None
    assert len(cliente.orders.canceladas) == 1


def test_ejecucion_parcial_obliga_a_revisar():
    b, cliente, _ = _broker(estados=["Parcialmente ejecutada"] * 50)
    with pytest.raises(ErrorPPI, match="en parte"):
        b.comprar("AAPL", 100_000, datetime(2026, 11, 25))
    assert len(cliente.orders.canceladas) == 1


def test_estado_desconocido_obliga_a_revisar():
    b, _, _ = _broker(estados=["Estado nuevo de PPI"] * 50)
    with pytest.raises(ErrorPPI, match="no reconoce"):
        b.comprar("AAPL", 100_000, datetime(2026, 11, 25))


def test_venta_sin_ejecutar_es_error():
    b, _, _ = _broker(estados=["Cancelada"])
    with pytest.raises(ErrorPPI):
        b.vender("AAPL", 3, datetime(2026, 11, 25))


def test_compra_de_monto_chico_no_envia_orden():
    b, cliente, _ = _broker()
    assert b.comprar("AAPL", 500, datetime(2026, 11, 25)) is None
    assert not cliente.orders.confirmadas


def test_historico_ordenado_y_sin_filas_rotas():
    lector = LectorPPI(Cliente(), "123", ConfigPPI())
    barras = lector.historico("AAPL", datetime(2026, 11, 1), datetime(2026, 11, 25))
    assert [b["precio"] for b in barras] == [100.0, 102.0]


def test_motor_se_pausa_si_falla_el_broker():
    import numpy as np

    from iaseyt.config import Config
    from iaseyt.estado import Estado, Modo, MotivoPausa
    from iaseyt.historial import Historial
    from iaseyt.motor import Motor

    from .test_motor import EstrategiaFija, Reloj as RelojMotor, _feed

    class BrokerRoto(BrokerPPI):
        def __init__(self):
            pass

        soporta_stops = False

        def efectivo(self):
            return 1_000_000.0

        def comprar(self, *a):
            raise ErrorPPI("se cortó la conexión")

    m = Motor(Config(), BrokerRoto(), _feed([100] * 5), EstrategiaFija(), Historial(), reloj=RelojMotor(), rng=np.random.default_rng(0))
    m.cambiar_modo(Modo.AUTOMATICO)
    m.encender()
    m.paso()
    assert m.control.estado == Estado.PAUSADA and m.control.motivo_pausa == MotivoPausa.FALLA_TECNICA
    assert "se cortó" in m.historial.eventos(tipo="falla")[0]["detalle"]
    assert not m.cartera.posiciones
