"""Panel de control: los botones, el modo asistido, el historial y el resumen.

Es una página web que sirve el propio servidor. Desde tu PC o tu celular la
abrís en el navegador. En la fase 1 corre todo en una sola máquina.
"""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..estado import Modo, TransicionInvalida
from ..motor import Motor

PAGINA = (Path(__file__).parent / "pagina.html").read_text(encoding="utf-8")


class PedidoMonto(BaseModel):
    monto: float = Field(gt=0, description="Monto en pesos")


class PedidoModo(BaseModel):
    modo: Modo


class PedidoConfirmacion(BaseModel):
    confirmar: bool = False


class Ciclo:
    """Corre motor.paso() cada cierto tiempo en un hilo aparte."""

    def __init__(self, motor: Motor, segundos: float):
        self.motor = motor
        self.segundos = segundos
        self._parar = threading.Event()
        self._hilo = threading.Thread(target=self._correr, daemon=True)

    def iniciar(self) -> None:
        self._hilo.start()

    def detener(self) -> None:
        self._parar.set()

    def _correr(self) -> None:
        while not self._parar.wait(self.segundos):
            try:
                self.motor.paso()
            except Exception as e:  # un error no puede tirar abajo el ciclo
                self.motor.historial.evento(self.motor.reloj(), "falla", f"Error en el ciclo: {e!r}")
                time.sleep(self.segundos)


def crear_app(motor: Motor, token: str | None = None, segundos_por_ciclo: float | None = None) -> FastAPI:
    token = token or secrets.token_urlsafe(16)
    ciclo = Ciclo(motor, segundos_por_ciclo or motor.cfg.segundos_por_ciclo) if segundos_por_ciclo != 0 else None

    @asynccontextmanager
    async def vida(_app: FastAPI):
        if ciclo:
            ciclo.iniciar()
        yield
        if ciclo:
            ciclo.detener()

    app = FastAPI(title="IASEYT", docs_url=None, redoc_url=None, lifespan=vida)
    app.state.token = token
    app.state.ciclo = ciclo

    def autorizar(x_token: str = Header(default="")) -> None:
        if not secrets.compare_digest(x_token, token):
            raise HTTPException(status_code=401, detail="Token incorrecto.")

    def accion(fn, *args):
        try:
            resultado = fn(*args)
        except TransicionInvalida as e:
            raise HTTPException(status_code=409, detail=str(e)) from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        return {"ok": True, "resultado": resultado, "foto": motor.foto()}

    @app.get("/", response_class=HTMLResponse)
    def pagina() -> str:
        return PAGINA

    @app.get("/api/estado", dependencies=[Depends(autorizar)])
    def estado() -> dict:
        return motor.foto()

    @app.post("/api/encender", dependencies=[Depends(autorizar)])
    def encender() -> dict:
        return accion(motor.encender)

    @app.post("/api/pausar", dependencies=[Depends(autorizar)])
    def pausar() -> dict:
        return accion(motor.pausar)

    @app.post("/api/reanudar", dependencies=[Depends(autorizar)])
    def reanudar(p: PedidoConfirmacion) -> dict:
        return accion(motor.reanudar, p.confirmar)

    @app.post("/api/apagar", dependencies=[Depends(autorizar)])
    def apagar() -> dict:
        return accion(motor.apagar)

    @app.post("/api/cerrar-todo", dependencies=[Depends(autorizar)])
    def cerrar_todo(p: PedidoConfirmacion) -> dict:
        if not p.confirmar:
            raise HTTPException(status_code=400, detail="Falta confirmar el cierre de todas las posiciones.")
        return accion(motor.cerrar_todo)

    @app.post("/api/modo", dependencies=[Depends(autorizar)])
    def modo(p: PedidoModo) -> dict:
        return accion(motor.cambiar_modo, p.modo)

    @app.get("/api/resumen", dependencies=[Depends(autorizar)])
    def resumen() -> dict:
        return motor.resumen_desde_ultima_visita()

    @app.get("/api/propuestas", dependencies=[Depends(autorizar)])
    def propuestas() -> list[dict]:
        total = motor.cartera.valor_total
        res = motor.historial.propuestas("pendiente")
        for p in res:
            p["valor_cuenta"] = total
        return res

    @app.post("/api/propuestas/{id_prop}/aceptar", dependencies=[Depends(autorizar)])
    def aceptar(id_prop: int, p: PedidoMonto) -> dict:
        return accion(motor.aceptar_propuesta, id_prop, p.monto)

    @app.post("/api/propuestas/{id_prop}/rechazar", dependencies=[Depends(autorizar)])
    def rechazar(id_prop: int) -> dict:
        return accion(motor.rechazar_propuesta, id_prop)

    @app.get("/api/operaciones", dependencies=[Depends(autorizar)])
    def operaciones() -> list[dict]:
        return motor.historial.operaciones()

    @app.get("/api/eventos", dependencies=[Depends(autorizar)])
    def eventos() -> list[dict]:
        return motor.historial.eventos(limite=100)

    return app
