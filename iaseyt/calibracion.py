"""Calibración de la confianza.

Si cuando IASEYT dice "70% seguro" acierta solo el 55% de las veces, el
calibrador corrige ese número. Agrupa las predicciones por tramos y mezcla
la probabilidad que dijo con la frecuencia real de aciertos. Con pocos datos
confía más en lo que dijo; con muchos, en lo que pasó de verdad.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Calibrador:
    tramos: int = 10
    # Peso de la predicción original, medido en "observaciones ficticias".
    peso_previo: float = 20.0
    observaciones: list[tuple[float, bool]] = field(default_factory=list)

    def registrar(self, prob_dicha: float, acerto: bool) -> None:
        if not 0.0 <= prob_dicha <= 1.0:
            raise ValueError("La probabilidad tiene que estar entre 0 y 1.")
        self.observaciones.append((prob_dicha, bool(acerto)))

    def _tramo(self, p: float) -> int:
        return min(int(p * self.tramos), self.tramos - 1)

    def calibrar(self, prob: float) -> float:
        t = self._tramo(prob)
        del_tramo = [a for p, a in self.observaciones if self._tramo(p) == t]
        n = len(del_tramo)
        aciertos = sum(del_tramo)
        return (aciertos + prob * self.peso_previo) / (n + self.peso_previo)

    def brier(self) -> float | None:
        """Error cuadrático medio de las probabilidades (0 = perfecto)."""
        if not self.observaciones:
            return None
        return sum((p - a) ** 2 for p, a in self.observaciones) / len(self.observaciones)

    def tabla(self) -> list[dict]:
        """Para el panel: cuánto decía y cuánto acertó en cada tramo."""
        filas = []
        for t in range(self.tramos):
            obs = [(p, a) for p, a in self.observaciones if self._tramo(p) == t]
            if obs:
                filas.append(
                    {
                        "tramo": f"{t * 100 // self.tramos}-{(t + 1) * 100 // self.tramos}%",
                        "cantidad": len(obs),
                        "decia": sum(p for p, _ in obs) / len(obs),
                        "acerto": sum(a for _, a in obs) / len(obs),
                    }
                )
        return filas
