from datetime import datetime, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient

from iaseyt.broker import BrokerSimulado
from iaseyt.config import Config
from iaseyt.data.feed import FeedHistorico, feed_sintetico
from iaseyt.decision import Senal, TipoSenal
from iaseyt.estado import Estado, Modo, MotivoPausa, TransicionInvalida
from iaseyt.historial import Historial
from iaseyt.motor import Motor
from iaseyt.panel import crear_app
from iaseyt.simulacion import correr


class Reloj:
    def __init__(self):
        self.ahora = datetime(2026, 1, 5, 12, 0)

    def __call__(self):
        return self.ahora

    def avanzar(self, **kw):
        self.ahora += timedelta(**kw)


class EstrategiaFija:
    """Propone comprar NVDA una sola vez, con una señal que pasa todos los filtros."""

    def __init__(self):
        self.usada = False

    def generar(self, feed, cartera):
        if self.usada or "NVDA" in cartera.posiciones:
            return []
        self.usada = True
        return [
            Senal(
                ticker="NVDA", sector="Tec", tipo=TipoSenal.NOTICIA, causa="Aviso a la SEC",
                fuentes=["sec", "finnhub"], precedentes=[0.05] * 10, prob_bruta=0.75,
                objetivo=0.08, stop=0.03, horizonte_dias=5, volumen_diario=1e9, mercado_abierto=True,
                retornos_historicos=np.random.default_rng(3).normal(0.0, 0.004, 400),
                precio=float(feed.historia("NVDA")[-1]),
            )
        ]


def _feed(precios_nvda):
    n = len(precios_nvda)
    fechas = [datetime(2026, 1, 5) + timedelta(days=i) for i in range(n)]
    return FeedHistorico(
        fechas,
        {"NVDA": np.array(precios_nvda, dtype=float), "KO": np.full(n, 500.0)},
        {"NVDA": np.full(n, 1e9), "KO": np.full(n, 1e9)},
        {"NVDA": "Tec", "KO": "Consumo"},
    )


def _motor(precios, modo=Modo.AUTOMATICO, cfg=None):
    cfg = cfg or Config()
    reloj = Reloj()
    feed = _feed(precios)
    broker = BrokerSimulado(cfg.capital_inicial, cfg.costos.comision, cfg.costos.deslizamiento)
    m = Motor(cfg, broker, feed, EstrategiaFija(), Historial(":memory:"), reloj=reloj, rng=np.random.default_rng(0))
    m.cambiar_modo(modo)
    return m, reloj


def test_feed_no_mira_el_futuro():
    f = feed_sintetico(dias=50)
    f.avanzar()
    f.avanzar()
    assert len(f.historia("NVDA")) == 2
    while f.avanzar():
        pass
    assert f.terminado and f.avanzar() is None


def test_apagada_no_lee_datos():
    m, _ = _motor([100] * 5)
    m.paso()
    assert m.feed.indice == -1


def test_automatico_compra_y_vende_por_objetivo():
    m, _ = _motor([100, 100, 120, 120, 120])
    m.encender()
    m.paso()  # compra
    assert "NVDA" in m.cartera.posiciones
    op = m.historial.operaciones(abiertas=True)[0]
    assert op["modo"] == "automatico" and op["causa"] == "Aviso a la SEC"
    assert op["monto"] <= 0.10 * Config().capital_inicial + 1
    m.paso()
    m.paso()  # sube 20%: vende por objetivo
    assert "NVDA" not in m.cartera.posiciones
    cerrada = m.historial.operaciones(abiertas=False)[0]
    assert cerrada["motivo_salida"] == "objetivo" and cerrada["resultado_pesos"] > 0
    assert len(m.calibrador.observaciones) == 1


def test_en_pausa_no_compra_pero_el_stop_funciona():
    m, _ = _motor([100, 80, 80, 80, 80])
    m.encender()
    m.paso()
    assert "NVDA" in m.cartera.posiciones
    m.pausar()
    m.paso()  # cae 20%: el stop vende aunque esté en pausa
    assert "NVDA" not in m.cartera.posiciones
    assert m.historial.operaciones(abiertas=False)[0]["motivo_salida"] == "stop"
    assert m.historial.operaciones(abiertas=False)[0]["que_no_vio"].startswith("Pendiente")


def test_vende_por_plazo():
    m, _ = _motor([100] * 10)
    m.encender()
    for _ in range(8):
        m.paso()
    assert m.historial.operaciones(abiertas=False)[0]["motivo_salida"] == "plazo"


def test_reanudar_sigue_desde_el_ultimo_dato():
    m, _ = _motor([100] * 6)
    m.encender()
    m.paso()
    m.apagar()
    m.paso()
    assert m.feed.indice == 0
    m.encender()
    m.paso()
    assert m.feed.indice == 1


def test_freno_de_perdida_diaria_pausa():
    cfg = Config()
    m, _ = _motor([100, 1, 1, 1], cfg=cfg)
    m.encender()
    m.paso()
    # Simula una caída enorme de la cartera.
    m.cartera.posiciones["NVDA"].stop = 0.0
    m.paso()
    assert m.control.estado == Estado.PAUSADA
    assert m.control.motivo_pausa in (MotivoPausa.PERDIDA_DIARIA, MotivoPausa.CAIDA_DESDE_PICO)
    assert m.historial.eventos(tipo="freno")


def test_asistido_propone_y_acepta_con_monto_en_pesos():
    m, reloj = _motor([100] * 6, modo=Modo.ASISTIDO)
    m.encender()
    m.paso()
    assert "NVDA" not in m.cartera.posiciones
    props = m.historial.propuestas("pendiente")
    assert len(props) == 1 and props[0]["monto_sugerido"] > 0
    r = m.aceptar_propuesta(props[0]["id"], 150_000)  # más que el tope de 100.000
    assert r["aviso"] and "tope" in r["aviso"]
    op = m.historial.operaciones(abiertas=True)[0]
    assert op["modo"] == "asistido"
    assert op["monto_propuesto"] == pytest.approx(props[0]["monto_sugerido"])
    with pytest.raises(TransicionInvalida):
        m.aceptar_propuesta(props[0]["id"], 1000)


def test_asistido_propuesta_vence():
    m, reloj = _motor([100] * 6, modo=Modo.ASISTIDO)
    m.encender()
    m.paso()
    pid = m.historial.propuestas("pendiente")[0]["id"]
    reloj.avanzar(minutes=31)
    with pytest.raises(TransicionInvalida):
        m.aceptar_propuesta(pid, 1000)
    assert m.historial.propuesta(pid)["estado"] == "vencida"


def test_asistido_no_acepta_mas_que_el_efectivo():
    m, _ = _motor([100] * 6, modo=Modo.ASISTIDO)
    m.encender()
    m.paso()
    pid = m.historial.propuestas("pendiente")[0]["id"]
    with pytest.raises(ValueError):
        m.aceptar_propuesta(pid, 10_000_000)


def test_apagar_avisa_posiciones_sin_stop_y_cerrar_todo_vende():
    m, _ = _motor([100] * 6)
    m.encender()
    m.paso()
    assert m.apagar() == ["NVDA"]
    m.encender()
    m.cerrar_todo()
    assert not m.cartera.posiciones and m.control.estado == Estado.APAGADA
    assert m.historial.operaciones(abiertas=False)[0]["motivo_salida"] == "cierre de emergencia"


def test_resumen_desde_ultima_visita():
    m, reloj = _motor([100, 120, 120, 120, 120])
    assert m.resumen_desde_ultima_visita()["primera_visita"]
    m.encender()
    reloj.avanzar(hours=12)
    m.paso()
    reloj.avanzar(hours=12)
    m.paso()
    reloj.avanzar(hours=12)
    r = m.resumen_desde_ultima_visita()
    assert r["horas"] == 36.0
    assert len(r["compras"]) == 1 and len(r["ventas"]) == 1
    assert r["variacion_pesos"] > 0


def test_pasa_sola_a_automatico_si_se_configura():
    from dataclasses import replace

    cfg = replace(Config(), pasar_a_auto_tras_minutos=60)
    m, reloj = _motor([100] * 6, modo=Modo.ASISTIDO, cfg=cfg)
    m.resumen_desde_ultima_visita()
    m.encender()
    reloj.avanzar(minutes=61)
    m.paso()
    assert m.control.modo == Modo.AUTOMATICO


def test_simulacion_completa_respeta_topes():
    from iaseyt.config import cargar_config

    motor, inf = correr(feed_sintetico(semilla=11), cargar_config("config.demo.toml"), semilla=0)
    assert inf.operaciones > 0
    for op in motor.historial.operaciones():
        assert op["porcentaje_cuenta"] <= 0.10 + 1e-9


# Panel ---------------------------------------------------------------------------------
def test_panel_requiere_token_y_funcionan_los_botones():
    m, _ = _motor([100] * 6, modo=Modo.ASISTIDO)
    app = crear_app(m, token="secreto", segundos_por_ciclo=0)
    with TestClient(app) as c:
        assert c.get("/").status_code == 200
        assert c.get("/api/estado").status_code == 401
        h = {"X-Token": "secreto"}
        assert c.post("/api/encender", headers=h).json()["foto"]["estado"] == "encendida"
        assert c.post("/api/encender", headers=h).status_code == 409
        m.paso()
        props = c.get("/api/propuestas", headers=h).json()
        assert props and props[0]["valor_cuenta"] > 0
        r = c.post(f"/api/propuestas/{props[0]['id']}/aceptar", headers=h, json={"monto": 50_000})
        assert r.status_code == 200
        assert c.get("/api/operaciones", headers=h).json()[0]["modo"] == "asistido"
        assert c.post("/api/cerrar-todo", headers=h, json={}).status_code == 400
        assert c.post("/api/cerrar-todo", headers=h, json={"confirmar": True}).json()["foto"]["estado"] == "apagada"
        assert c.get("/api/resumen", headers=h).status_code == 200
