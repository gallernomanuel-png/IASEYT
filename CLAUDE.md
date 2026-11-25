# Instrucciones para Claude en este repositorio

IASEYT es el asistente de inversión de Manuel. Antes de cambiar algo, leé
`docs/DISENO.md`.

## Reglas que no se rompen

- **Honestidad:** nunca prometer ganancias ni presentar resultados de datos
  sintéticos como evidencia. Si algo no funciona, decirlo.
- **Seguridad de la plata:** ningún cambio puede saltear los filtros de
  `iaseyt/decision.py`, los topes de `iaseyt/riesgo.py` ni los frenos del motor.
  Si un cambio los toca, explicarlo en el PR y agregar pruebas.
- **Sin aprobación no hay cambios:** las propuestas de código van como PR; Manuel
  aprueba.
- **Sin claves en el repo:** claves y contraseñas solo en variables de entorno.
- **Nada de manipulación de mercado:** nunca órdenes que no se piensan ejecutar
  ni operaciones contra sí misma.
- **Sin mirar el futuro:** el feed nunca entrega datos posteriores al momento
  simulado.

## Cómo trabajar

- Todo en español: código, comentarios, mensajes y documentos.
- `python -m pytest -q` tiene que pasar antes de cada commit.
- Cambios chicos y probados. Una fase a la vez (ver `docs/DISENO.md`).

## Estado actual

- Fase 1 terminada: núcleo, broker simulado, historial, panel, pruebas.
- Próximo: fase 2 (datos reales de precios y backtest walk-forward), y conectar
  el broker elegido (IOL o PPI) en modo prueba.
