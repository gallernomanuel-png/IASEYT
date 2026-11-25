import numpy as np
import pytest

from iaseyt.calibracion import Calibrador
from iaseyt.cartera import Cartera, Posicion
from iaseyt.config import Config, FiltrosDecision, LimitesRiesgo, cargar_config
from iaseyt.decision import Senal, TipoSenal, evaluar
from iaseyt.estado import ControlEstado, Estado, MotivoPausa, TransicionInvalida
from iaseyt.montecarlo import simular_operacion
from iaseyt.riesgo import kelly, monto_maximo_permitido, tamano_posicion, verificar_frenos


# Estados ----------------------------------------------------------------------
def test_ciclo_de_botones():
    c = ControlEstado()
    assert not c.lee_datos and not c.toma_decisiones
    c.encender()
    assert c.lee_datos and c.toma_decisiones
    c.pausar()
    assert c.lee_datos and not c.toma_decisiones
    c.reanudar()
    assert c.estado == Estado.ENCENDIDA
    c.apagar()
    assert not c.lee_datos


def test_transiciones_invalidas():
    c = ControlEstado()
    with pytest.raises(TransicionInvalida):
        c.pausar()
    with pytest.raises(TransicionInvalida):
        c.reanudar()
    c.encender()
    with pytest.raises(TransicionInvalida):
        c.encender()


def test_caida_desde_pico_exige_revision():
    c = ControlEstado()
    c.encender()
    c.pausar(MotivoPausa.CAIDA_DESDE_PICO)
    with pytest.raises(TransicionInvalida):
        c.reanudar()
    c.reanudar(confirmo_revision=True)
    assert c.toma_decisiones


def test_freno_grave_reemplaza_pausa_manual():
    c = ControlEstado()
    c.encender()
    c.pausar()
    c.pausar(MotivoPausa.CAIDA_DESDE_PICO)
    assert c.motivo_pausa == MotivoPausa.CAIDA_DESDE_PICO


# Riesgo -----------------------------------------------------------------------
def test_kelly():
    assert kelly(0.5, 0.10, 0.10) == pytest.approx(0.0)
    assert kelly(0.6, 0.10, 0.05) == pytest.approx(0.6 / 0.05 - 0.4 / 0.10)
    assert kelly(0.2, 0.05, 0.05) == 0.0  # nunca negativo


def _cartera_con(efectivo, posiciones=()):
    c = Cartera(efectivo=efectivo)
    for t, sector, valor in posiciones:
        c.posiciones[t] = Posicion(t, sector, 1, valor, valor, valor * 0.9, valor * 1.1, 10)
    return c


def test_topes_por_empresa_sector_y_efectivo():
    lim = LimitesRiesgo()
    c = _cartera_con(800_000, [("NVDA", "Tec", 80_000), ("AMD", "Tec", 100_000), ("KO", "Consumo", 20_000)])
    # total 1.000.000: empresa 10% = 100k, sector 25% = 250k (ya hay 180k), efectivo libre 600k
    assert monto_maximo_permitido(c, "NVDA", "Tec", lim) == pytest.approx(20_000)
    assert monto_maximo_permitido(c, "MSFT", "Tec", lim) == pytest.approx(70_000)
    assert monto_maximo_permitido(c, "WMT", "Consumo", lim) == pytest.approx(100_000)
    pobre = _cartera_con(210_000, [("KO", "Consumo", 790_000)])
    assert monto_maximo_permitido(pobre, "XOM", "Energía", lim) == pytest.approx(10_000)


def test_tamano_nunca_pasa_los_topes():
    lim = LimitesRiesgo()
    c = _cartera_con(1_000_000)
    monto = tamano_posicion(c, 0.95, 0.20, 0.02, "NVDA", "Tec", lim, 0.25)
    assert monto == pytest.approx(100_000)  # Kelly pide más, el tope manda


def test_frenos():
    lim = LimitesRiesgo()
    assert verificar_frenos(1000, 1000, 1000, lim) is None
    assert verificar_frenos(969, 1000, 1000, lim) == MotivoPausa.PERDIDA_DIARIA
    assert verificar_frenos(850, 860, 1000, lim) == MotivoPausa.CAIDA_DESDE_PICO


# Monte Carlo --------------------------------------------------------------------
def test_montecarlo_respeta_stop_y_objetivo():
    rng = np.random.default_rng(1)
    r = rng.normal(0, 0.001, 500)  # casi sin volatilidad: nunca toca stop ni objetivo
    res = simular_operacion(r, objetivo=0.10, stop=0.05, dias=5, costo_ida_vuelta=0.01, caminos=2000, rng=rng)
    assert res.prob_perdida_mayor_umbral == 0.0
    assert res.retorno_esperado == pytest.approx(-0.01, abs=0.005)
    assert res.percentil_95 <= 0.10


def test_montecarlo_con_deriva_y_semilla():
    r = np.random.default_rng(2).normal(0, 0.02, 500)
    a = simular_operacion(r, 0.06, 0.035, 10, 0.0, caminos=3000, rng=np.random.default_rng(5), deriva_diaria=0.004)
    b = simular_operacion(r, 0.06, 0.035, 10, 0.0, caminos=3000, rng=np.random.default_rng(5), deriva_diaria=0.004)
    c = simular_operacion(r, 0.06, 0.035, 10, 0.0, caminos=3000, rng=np.random.default_rng(5), deriva_diaria=-0.004)
    assert a == b
    assert a.retorno_esperado > c.retorno_esperado


def test_montecarlo_pocos_datos():
    with pytest.raises(ValueError):
        simular_operacion(np.array([0.01, 0.02]), 0.1, 0.05, 5, 0.0)


# Calibración ----------------------------------------------------------------------
def test_calibrador_corrige_exceso_de_confianza():
    cal = Calibrador()
    assert cal.calibrar(0.7) == pytest.approx(0.7)  # sin datos, confía en lo que dijo
    for i in range(200):
        cal.registrar(0.72, i % 2 == 0)  # decía 72%, acertaba 50%
    assert cal.calibrar(0.72) < 0.55
    assert cal.brier() is not None


# Decisión -------------------------------------------------------------------------------
def _senal(**cambios):
    base = dict(
        ticker="NVDA", sector="Tec", tipo=TipoSenal.NOTICIA, causa="Renunció el CEO",
        fuentes=["sec", "finnhub"], precedentes=[0.05] * 10, prob_bruta=0.75,
        objetivo=0.08, stop=0.03, horizonte_dias=10, volumen_diario=1e9,
        mercado_abierto=True, retornos_historicos=np.random.default_rng(3).normal(0.0, 0.004, 400),
        precio=1000.0,
    )
    base.update(cambios)
    return Senal(**base)


def test_senal_buena_se_aprueba_con_monto():
    ev = evaluar(_senal(), _cartera_con(1_000_000), Config(), Calibrador(), np.random.default_rng(0))
    assert ev.aprobada, ev.rechazos
    assert 0 < ev.monto_sugerido <= 100_000
    assert ev.porcentaje_cuenta == pytest.approx(ev.monto_sugerido / 1_000_000)


@pytest.mark.parametrize(
    "cambio, texto",
    [
        ({"causa": None}, "causa"),
        ({"fuentes": ["sec"]}, "fuente"),
        ({"precedentes": [0.05] * 3}, "precedentes"),
        ({"prob_bruta": 0.4}, "Confianza"),
        ({"volumen_diario": 1.0}, "volumen"),
        ({"mercado_abierto": False}, "cerrado"),
    ],
)
def test_cada_filtro_rechaza(cambio, texto):
    ev = evaluar(_senal(**cambio), _cartera_con(1_000_000), Config(), Calibrador(), np.random.default_rng(0))
    assert not ev.aprobada
    assert any(texto in r for r in ev.rechazos)


def test_rechaza_si_simulaciones_muestran_mucho_riesgo():
    volatil = np.random.default_rng(4).normal(0, 0.05, 400)
    ev = evaluar(_senal(retornos_historicos=volatil), _cartera_con(1_000_000), Config(), Calibrador(), np.random.default_rng(0))
    assert any("simulaciones" in r for r in ev.rechazos)


def test_rechaza_sin_margen_en_topes():
    llena = _cartera_con(200_000, [("NVDA", "Tec", 100_000), ("X", "Otro", 700_000)])
    ev = evaluar(_senal(), llena, Config(), Calibrador(), np.random.default_rng(0))
    assert not ev.aprobada


# Configuración -------------------------------------------------------------------------
def test_config_por_defecto_y_archivo(tmp_path):
    assert cargar_config(None) == Config()
    ruta = tmp_path / "c.toml"
    ruta.write_text("[general]\ncapital_inicial = 5.0\n[filtros]\nprob_minima = 0.7\n", encoding="utf-8")
    cfg = cargar_config(ruta)
    assert cfg.capital_inicial == 5.0
    assert cfg.filtros == FiltrosDecision(prob_minima=0.7)


def test_config_rechaza_claves_desconocidas(tmp_path):
    ruta = tmp_path / "c.toml"
    ruta.write_text("[limites]\nmax_por_empresaa = 0.5\n", encoding="utf-8")
    with pytest.raises(ValueError):
        cargar_config(ruta)


def test_config_ejemplo_y_demo_son_validos():
    assert cargar_config("config.example.toml") == Config()
    assert cargar_config("config.demo.toml").filtros.prob_minima == 0.55
