"""Línea de comandos.

    python -m iaseyt simular              Simulación rápida en modo automático
    python -m iaseyt backtest             Backtest con prueba hacia adelante
    python -m iaseyt panel --demo         Panel web con datos sintéticos
    python -m iaseyt ppi-verificar        Prueba la conexión con PPI (solo lectura)
    python -m iaseyt ppi-descargar        Baja precios históricos de PPI a un CSV
    python -m iaseyt ppi-prueba-orden     Manda una orden de prueba al sandbox de PPI
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from dataclasses import replace
from datetime import datetime, timedelta

from .config import cargar_config
from .data import feed_desde_csv, feed_sintetico


def _feed(args):
    return feed_desde_csv(args.csv) if args.csv else feed_sintetico(semilla=args.semilla)


def _aviso_sinteticos(args) -> None:
    if not args.csv:
        print("Aviso: precios sintéticos (inventados). Sirven para probar el programa, no la estrategia.\n")


def cmd_simular(args) -> int:
    from .simulacion import correr

    _aviso_sinteticos(args)
    _, informe = correr(_feed(args), cargar_config(args.config), semilla=args.semilla)
    print(informe.texto())
    return 0


def cmd_backtest(args) -> int:
    from .backtest import walk_forward

    _aviso_sinteticos(args)
    r = walk_forward(_feed(args), cargar_config(args.config), args.entrenamiento, args.prueba, semilla=args.semilla)
    print(r.texto())
    return 0


def cmd_panel(args) -> int:
    import uvicorn

    from .broker import BrokerSimulado
    from .estrategia import EstrategiaCaidaFuerte
    from .historial import Historial
    from .motor import Motor
    from .panel import crear_app

    cfg = cargar_config(args.config)
    historial = Historial(cfg.ruta_db)
    broker = BrokerSimulado(cfg.capital_inicial, cfg.costos.comision, cfg.costos.deslizamiento)
    motor = Motor(cfg, broker, _feed(args), EstrategiaCaidaFuerte(), historial)
    token = os.environ.get("IASEYT_TOKEN") or secrets.token_urlsafe(16)
    segundos = args.segundos if args.segundos is not None else cfg.segundos_por_ciclo
    app = crear_app(motor, token=token, segundos_por_ciclo=segundos)
    print(f"\nIASEYT listo. Abrí en el navegador:\n  http://{args.host}:{args.puerto}/?token={token}\n")
    print(f"Cada {segundos} segundos avanza una rueda de datos.")
    uvicorn.run(app, host=args.host, port=args.puerto, log_level="warning")
    return 0


def _lector_ppi(args):
    from .broker.ppi import LectorPPI, conectar

    cfg = cargar_config(args.config)
    cfg_ppi = replace(cfg.ppi, sandbox=not args.produccion) if args.produccion else cfg.ppi
    cliente, cuenta = conectar(cfg_ppi.sandbox)
    entorno = "sandbox (prueba)" if cfg_ppi.sandbox else "producción (solo lectura)"
    print(f"Conectado a PPI, entorno {entorno}, cuenta {cuenta}.")
    return cfg, cfg_ppi, LectorPPI(cliente, cuenta, cfg_ppi)


def cmd_ppi_verificar(args) -> int:
    from .broker.ppi import ErrorPPI

    _, _, lector = _lector_ppi(args)
    try:
        print(f"Saldo disponible en pesos: ${lector.saldo_disponible():,.2f}")
    except ErrorPPI as e:
        print(f"No pude leer el saldo: {e}")
    try:
        print(f"Precio actual de {args.ticker}: ${lector.precio_actual(args.ticker):,.2f}")
    except Exception as e:
        print(f"No pude leer el precio de {args.ticker}: {e}")
    if args.crudo:
        print(json.dumps(lector.saldo_y_posiciones(), indent=2, ensure_ascii=False, default=str))
    return 0


def cmd_ppi_descargar(args) -> int:
    from .data.descarga import descargar, leer_tickers

    _, _, lector = _lector_ppi(args)
    hasta = datetime.now()
    desde = datetime.fromisoformat(args.desde) if args.desde else hasta - timedelta(days=365 * 5)
    conteo = descargar(lector, leer_tickers(args.tickers), desde, hasta, args.salida)
    for t, n in conteo.items():
        print(f"  {t}: {n} ruedas")
    print(f"Guardado en {args.salida}. Probalo con: python -m iaseyt backtest --csv {args.salida}")
    return 0


def cmd_ppi_prueba_orden(args) -> int:
    from .broker.ppi import BrokerPPI

    cfg, cfg_ppi, lector = _lector_ppi(args)
    if not cfg_ppi.sandbox:
        print("Las órdenes de prueba solo se mandan al sandbox.")
        return 1
    broker = BrokerPPI(lector, cfg_ppi, cfg.costos.comision, cfg.costos.deslizamiento, registrar=print)
    precio = lector.precio_actual(args.ticker)
    print(f"Precio de {args.ticker}: ${precio:,.2f}. Compro 1 unidad en el sandbox...")
    ej = broker.comprar(args.ticker, precio * 1.05, datetime.now())
    if ej is None:
        print("La orden no se ejecutó a tiempo y se canceló. Revisá los estados de arriba.")
        return 0
    print(f"Compra ejecutada: {ej}")
    print("Vendo esa unidad para dejar la cuenta como estaba...")
    print(f"Venta ejecutada: {broker.vender(args.ticker, ej.cantidad, datetime.now())}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="iaseyt", description="IASEYT (en simulación)")
    sub = p.add_subparsers(dest="comando", required=True)

    def comun(nombre, fn, datos=True):
        s = sub.add_parser(nombre)
        s.add_argument("--config", help="Ruta a config.toml")
        if datos:
            s.add_argument("--csv", help="CSV de precios (fecha, ticker, sector, precio, volumen)")
            s.add_argument("--semilla", type=int, default=7, help="Semilla de los datos sintéticos")
        s.set_defaults(fn=fn)
        return s

    comun("simular", cmd_simular)
    b = comun("backtest", cmd_backtest)
    b.add_argument("--entrenamiento", type=int, default=250, help="Ruedas para entrenar en cada tramo")
    b.add_argument("--prueba", type=int, default=63, help="Ruedas de prueba en cada tramo")
    s = comun("panel", cmd_panel)
    s.add_argument("--demo", action="store_true", help="Usa config.demo.toml y avanza rápido")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--puerto", type=int, default=8000)
    s.add_argument("--segundos", type=float, help="Segundos entre ciclos")

    for nombre, fn in (("ppi-verificar", cmd_ppi_verificar), ("ppi-descargar", cmd_ppi_descargar), ("ppi-prueba-orden", cmd_ppi_prueba_orden)):
        s = comun(nombre, fn, datos=False)
        s.add_argument("--produccion", action="store_true", help="Lee del entorno real (nunca opera)")
        if nombre != "ppi-descargar":
            s.add_argument("--ticker", default="AAPL")
    sub.choices["ppi-verificar"].add_argument("--crudo", action="store_true", help="Muestra la respuesta completa de PPI")
    d = sub.choices["ppi-descargar"]
    d.add_argument("--tickers", help='Ej: "AAPL:Tecnología,KO:Consumo". Por defecto, 12 CEDEARs líquidos')
    d.add_argument("--desde", help="Fecha AAAA-MM-DD (por defecto, 5 años atrás)")
    d.add_argument("--salida", default="precios.csv")

    args = p.parse_args(argv)
    if getattr(args, "demo", False):
        args.config = args.config or "config.demo.toml"
        if args.segundos is None:
            args.segundos = 2
    try:
        return args.fn(args)
    except Exception as e:
        from .broker.ppi import ErrorPPI

        if isinstance(e, ErrorPPI):
            print(f"Error de PPI: {e}")
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
