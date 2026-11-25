"""Historial en SQLite: operaciones, eventos, propuestas, visitas y valores.

Todo lo que IASEYT hace queda registrado con su explicación, para entenderlo
después y para aprender de los errores.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from typing import Any

ESQUEMA = """
CREATE TABLE IF NOT EXISTS operaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    sector TEXT NOT NULL,
    modo TEXT NOT NULL,
    fecha_entrada TEXT NOT NULL,
    precio_entrada REAL NOT NULL,
    cantidad INTEGER NOT NULL,
    monto REAL NOT NULL,
    porcentaje_cuenta REAL NOT NULL,
    monto_propuesto REAL,
    causa TEXT,
    fuentes TEXT,
    prob_bruta REAL,
    prob_calibrada REAL,
    que_esperaba TEXT,
    objetivo REAL,
    stop REAL,
    horizonte_dias INTEGER,
    fecha_salida TEXT,
    precio_salida REAL,
    resultado_pesos REAL,
    resultado_pct REAL,
    motivo_salida TEXT,
    que_paso TEXT,
    que_no_vio TEXT
);
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    tipo TEXT NOT NULL,
    detalle TEXT NOT NULL,
    datos TEXT
);
CREATE TABLE IF NOT EXISTS propuestas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creada TEXT NOT NULL,
    vence TEXT NOT NULL,
    ticker TEXT NOT NULL,
    texto TEXT NOT NULL,
    monto_sugerido REAL NOT NULL,
    porcentaje REAL NOT NULL,
    monto_maximo REAL NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    monto_usuario REAL
);
CREATE TABLE IF NOT EXISTS visitas (fecha TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS valores (fecha TEXT NOT NULL, valor REAL NOT NULL);
CREATE TABLE IF NOT EXISTS calibracion (prob REAL NOT NULL, acerto INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS kv (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
"""


def _iso(f: datetime) -> str:
    return f.isoformat(timespec="seconds")


class Historial:
    def __init__(self, ruta: str = ":memory:"):
        self._db = sqlite3.connect(ruta, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._db.executescript(ESQUEMA)
            self._db.commit()

    def _ejecutar(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._db.execute(sql, params)
            self._db.commit()
            return cur

    def _filas(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, params).fetchall()]

    # Eventos -----------------------------------------------------------------
    def evento(self, fecha: datetime, tipo: str, detalle: str, datos: dict | None = None) -> None:
        self._ejecutar(
            "INSERT INTO eventos (fecha, tipo, detalle, datos) VALUES (?, ?, ?, ?)",
            (_iso(fecha), tipo, detalle, json.dumps(datos, ensure_ascii=False) if datos else None),
        )

    def eventos(self, desde: datetime | None = None, tipo: str | None = None, limite: int = 200) -> list[dict]:
        sql, p = "SELECT * FROM eventos WHERE 1=1", []
        if desde:
            sql += " AND fecha > ?"
            p.append(_iso(desde))
        if tipo:
            sql += " AND tipo = ?"
            p.append(tipo)
        sql += " ORDER BY id DESC LIMIT ?"
        p.append(limite)
        return self._filas(sql, tuple(p))

    # Operaciones -------------------------------------------------------------
    def abrir_operacion(self, **c: Any) -> int:
        c["fecha_entrada"] = _iso(c["fecha_entrada"])
        c["fuentes"] = json.dumps(c.get("fuentes", []), ensure_ascii=False)
        cols = ", ".join(c)
        marcas = ", ".join("?" for _ in c)
        return self._ejecutar(f"INSERT INTO operaciones ({cols}) VALUES ({marcas})", tuple(c.values())).lastrowid

    def cerrar_operacion(
        self, id_op: int, fecha: datetime, precio_salida: float, resultado_pesos: float,
        resultado_pct: float, motivo: str, que_paso: str, que_no_vio: str,
    ) -> None:
        self._ejecutar(
            """UPDATE operaciones SET fecha_salida=?, precio_salida=?, resultado_pesos=?,
               resultado_pct=?, motivo_salida=?, que_paso=?, que_no_vio=? WHERE id=?""",
            (_iso(fecha), precio_salida, resultado_pesos, resultado_pct, motivo, que_paso, que_no_vio, id_op),
        )

    def operaciones(self, abiertas: bool | None = None, desde: datetime | None = None) -> list[dict]:
        sql, p = "SELECT * FROM operaciones WHERE 1=1", []
        if abiertas is True:
            sql += " AND fecha_salida IS NULL"
        elif abiertas is False:
            sql += " AND fecha_salida IS NOT NULL"
        if desde:
            sql += " AND (fecha_entrada > ? OR fecha_salida > ?)"
            p += [_iso(desde), _iso(desde)]
        filas = self._filas(sql + " ORDER BY id DESC", tuple(p))
        for f in filas:
            f["fuentes"] = json.loads(f["fuentes"] or "[]")
        return filas

    # Propuestas (modo asistido) ---------------------------------------------
    def crear_propuesta(
        self, creada: datetime, vence: datetime, ticker: str, texto: str,
        monto_sugerido: float, porcentaje: float, monto_maximo: float,
    ) -> int:
        return self._ejecutar(
            """INSERT INTO propuestas (creada, vence, ticker, texto, monto_sugerido, porcentaje, monto_maximo)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (_iso(creada), _iso(vence), ticker, texto, monto_sugerido, porcentaje, monto_maximo),
        ).lastrowid

    def propuesta(self, id_prop: int) -> dict | None:
        filas = self._filas("SELECT * FROM propuestas WHERE id=?", (id_prop,))
        return filas[0] if filas else None

    def propuestas(self, estado: str | None = None) -> list[dict]:
        if estado:
            return self._filas("SELECT * FROM propuestas WHERE estado=? ORDER BY id DESC", (estado,))
        return self._filas("SELECT * FROM propuestas ORDER BY id DESC")

    def actualizar_propuesta(self, id_prop: int, estado: str, monto_usuario: float | None = None) -> None:
        self._ejecutar("UPDATE propuestas SET estado=?, monto_usuario=? WHERE id=?", (estado, monto_usuario, id_prop))

    # Visitas, valores, calibración, estado ------------------------------------
    def registrar_visita(self, fecha: datetime) -> datetime | None:
        """Guarda esta visita y devuelve la anterior."""
        filas = self._filas("SELECT fecha FROM visitas ORDER BY fecha DESC LIMIT 1")
        self._ejecutar("INSERT INTO visitas (fecha) VALUES (?)", (_iso(fecha),))
        return datetime.fromisoformat(filas[0]["fecha"]) if filas else None

    def ultima_visita(self) -> datetime | None:
        filas = self._filas("SELECT fecha FROM visitas ORDER BY fecha DESC LIMIT 1")
        return datetime.fromisoformat(filas[0]["fecha"]) if filas else None

    def registrar_valor(self, fecha: datetime, valor: float) -> None:
        self._ejecutar("INSERT INTO valores (fecha, valor) VALUES (?, ?)", (_iso(fecha), valor))

    def valor_en(self, fecha: datetime) -> float | None:
        """Último valor de la cuenta registrado hasta esa fecha."""
        filas = self._filas("SELECT valor FROM valores WHERE fecha <= ? ORDER BY fecha DESC LIMIT 1", (_iso(fecha),))
        return filas[0]["valor"] if filas else None

    def valores(self) -> list[dict]:
        return self._filas("SELECT * FROM valores ORDER BY fecha")

    def guardar_calibracion(self, prob: float, acerto: bool) -> None:
        self._ejecutar("INSERT INTO calibracion (prob, acerto) VALUES (?, ?)", (prob, int(acerto)))

    def calibracion(self) -> list[tuple[float, bool]]:
        return [(f["prob"], bool(f["acerto"])) for f in self._filas("SELECT * FROM calibracion")]

    def guardar(self, clave: str, valor: Any) -> None:
        self._ejecutar(
            "INSERT INTO kv (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
            (clave, json.dumps(valor, ensure_ascii=False, default=str)),
        )

    def leer(self, clave: str, default: Any = None) -> Any:
        filas = self._filas("SELECT valor FROM kv WHERE clave=?", (clave,))
        return json.loads(filas[0]["valor"]) if filas else default
