"""Estados y modos de IASEYT: los botones Encender, Pausar, Reanudar y Apagar."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Estado(str, Enum):
    APAGADA = "apagada"
    ENCENDIDA = "encendida"
    PAUSADA = "pausada"


class Modo(str, Enum):
    AUTOMATICO = "automatico"
    ASISTIDO = "asistido"


class MotivoPausa(str, Enum):
    MANUAL = "manual"
    PERDIDA_DIARIA = "perdida_diaria"
    CAIDA_DESDE_PICO = "caida_desde_pico"
    SIN_SALDO_CLAUDE = "sin_saldo_claude"
    FALLA_TECNICA = "falla_tecnica"


# Pausas que exigen que la revises antes de seguir.
PAUSAS_QUE_REQUIEREN_REVISION = {MotivoPausa.CAIDA_DESDE_PICO, MotivoPausa.FALLA_TECNICA}


class TransicionInvalida(Exception):
    pass


@dataclass
class ControlEstado:
    estado: Estado = Estado.APAGADA
    modo: Modo = Modo.ASISTIDO
    motivo_pausa: MotivoPausa | None = None

    @property
    def lee_datos(self) -> bool:
        return self.estado in (Estado.ENCENDIDA, Estado.PAUSADA)

    @property
    def toma_decisiones(self) -> bool:
        return self.estado == Estado.ENCENDIDA

    def encender(self) -> None:
        if self.estado != Estado.APAGADA:
            raise TransicionInvalida(f"No se puede encender: ya está {self.estado.value}.")
        self.estado = Estado.ENCENDIDA
        self.motivo_pausa = None

    def pausar(self, motivo: MotivoPausa = MotivoPausa.MANUAL) -> None:
        if self.estado == Estado.APAGADA:
            raise TransicionInvalida("No se puede pausar: está apagada.")
        if self.estado == Estado.PAUSADA:
            # Un freno más grave reemplaza a una pausa manual.
            if motivo in PAUSAS_QUE_REQUIEREN_REVISION:
                self.motivo_pausa = motivo
            return
        self.estado = Estado.PAUSADA
        self.motivo_pausa = motivo

    def reanudar(self, confirmo_revision: bool = False) -> None:
        if self.estado != Estado.PAUSADA:
            raise TransicionInvalida(f"No se puede reanudar: está {self.estado.value}.")
        if self.motivo_pausa in PAUSAS_QUE_REQUIEREN_REVISION and not confirmo_revision:
            raise TransicionInvalida(
                f"Se pausó por {self.motivo_pausa.value.replace('_', ' ')}. "
                "Revisá el historial y confirmá la revisión para reanudar."
            )
        self.estado = Estado.ENCENDIDA
        self.motivo_pausa = None

    def apagar(self) -> None:
        self.estado = Estado.APAGADA
        self.motivo_pausa = None

    def cambiar_modo(self, modo: Modo) -> None:
        self.modo = modo
