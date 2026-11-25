"""Línea de comandos.

    python -m iaseyt simular              Simulación rápida en modo automático
    python -m iaseyt panel --demo         Panel web con datos sintéticos
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys

from .config import cargar_config
from .data import feed_desde_csv, feed_sintetico


def _feed(args):
    return feed_desde_csv(args.csv) if args.csv else feed_sintetico(semilla=args.semilla)


def cmd_simular(args) -> int:
    from .simulacion import correr

    cfg = cargar_config(args.config)
    _, informe = correr(_feed(args), cfg, semilla=args.semilla)
    print(informe.texto())
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="iaseyt", description="IASEYT, fase 1 (simulación)")
    sub = p.add_subparsers(dest="comando", required=True)
    for nombre, fn in (("simular", cmd_simular), ("panel", cmd_panel)):
        s = sub.add_parser(nombre)
        s.add_argument("--config", help="Ruta a config.toml")
        s.add_argument("--csv", help="CSV de precios (fecha, ticker, sector, precio, volumen)")
        s.add_argument("--semilla", type=int, default=7, help="Semilla de los datos sintéticos")
        s.set_defaults(fn=fn)
        if nombre == "panel":
            s.add_argument("--demo", action="store_true", help="Usa config.demo.toml y avanza rápido")
            s.add_argument("--host", default="127.0.0.1")
            s.add_argument("--puerto", type=int, default=8000)
            s.add_argument("--segundos", type=float, help="Segundos entre ciclos")
    args = p.parse_args(argv)
    if getattr(args, "demo", False):
        args.config = args.config or "config.demo.toml"
        if args.segundos is None:
            args.segundos = 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
