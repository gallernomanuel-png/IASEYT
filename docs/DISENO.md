# IASEYT: especificaciones

Versión del 25 de noviembre de 2026. El documento de diseño completo, con
fuentes y detalles, está en Claude: https://claude.ai/artifact/6aLBuPtzLMnzHZdanmtWeB

## Qué es

IASEYT es un asistente de inversión propio. Sigue empresas de EE.UU. a través
de CEDEARs, lee noticias y avisos oficiales, simula escenarios y opera con
reglas de riesgo estrictas. No promete ganancias: mide su acierto real y decide
con esa medida.

**Regla de oro:** solo se opera con plata que se pueda perder. Durante los
primeros meses, todo se hace en simulación.

## Arquitectura

```
 Tu PC / celular              Servidor en la nube (24/7)                 Servicios
 ┌──────────────┐   ┌──────────────────────────────────────┐
 │ Panel        │◄─►│ Recolector de datos ◄─────────────────┼── Finnhub, SEC EDGAR, broker
 │ (botones,    │   │        │                              │
 │  historial)  │   │ Cerebro: filtros, simulaciones ◄──────┼──► Claude API
 └──────────────┘   │        │                              │
 ┌──────────────┐   │ Ejecutor de órdenes ──────────────────┼──► Broker (IOL o PPI)
 │ Celular:     │◄─►│        │                              │
 │ avisos y     │   │ Historial y aprendizaje ──────────────┼──► GitHub + Claude Code
 │ aprobaciones │   └──────────────────────────────────────┘
 └──────────────┘
```

Con la PC suspendida no hay programa que pueda seguir andando. Por eso lo que
tiene que estar siempre activo vive en el servidor.

## Botones y modos

| Botón | Lee datos | Toma decisiones | Qué pasa |
| --- | --- | --- | --- |
| Encender | Sí | Sí | Arranca y se pone al día. |
| Pausar | Sí | No | Junta datos, no abre operaciones. Los stops de protección siguen funcionando. |
| Reanudar | Sí | Sí | Sigue desde el último dato que juntó. |
| Apagar | No | No | Avisa qué posiciones quedan sin stop en el broker. |
| Cerrar todo | - | - | Vende todo y apaga. Pide confirmación. |

- **Modo automático:** decide sola dentro de los topes.
- **Modo asistido:** propone una compra con un monto en pesos y el porcentaje
  de la cuenta entre paréntesis. Vos escribís cuánto poner. Si supera el tope,
  avisa, pero la decisión es tuya. Si no respondés a tiempo, se descarta.
- Opcional: pasar sola a automático tras N minutos sin visitas (apagado por defecto).

## Cómo decide

Compra solo si pasa **todos** los filtros:

1. Sabe por qué se movió (causa identificada).
2. La causa está confirmada por al menos 2 fuentes independientes (noticias).
3. Hay precedentes suficientes (situaciones parecidas del pasado).
4. Confianza **calibrada** de al menos 60%.
5. Ganancia esperada positiva después de costos.
6. En las simulaciones Monte Carlo, perder más de 5% pasa menos del 15% de las veces.
7. Hay liquidez y el mercado está abierto.
8. Entra en los topes de riesgo.

**Cuánto pone:** un cuarto del criterio de Kelly, sin pasar nunca los topes.

| Tope | Valor inicial | Qué pasa si se alcanza |
| --- | --- | --- |
| Máximo por empresa | 10% | No compra más de esa empresa. |
| Máximo por sector | 25% | No compra más de ese sector. |
| Pérdida máxima en un día | 3% | Se pausa. |
| Caída máxima desde el pico | 15% | Se pausa y exige revisión para reanudar. |
| Efectivo mínimo | 20% | Siempre guarda una parte sin invertir. |

**Cuándo vende:** stop (corta la pérdida), objetivo (toma la ganancia), plazo
vencido, o si una noticia rompe la razón de la compra (fase 3). Cuando la acción
ya subió la mitad del objetivo, el stop sube detrás del precio.

**Fallas:** datos que no coinciden entre fuentes, caídas bruscas del mercado o
del CCL, cortes del broker o de Claude: no abre operaciones nuevas.

## Simulaciones

1. Backtest sobre años de datos, sin mirar el futuro.
2. Prueba hacia adelante (walk-forward).
3. Monte Carlo antes de cada operación: la volatilidad sale de la historia de la
   acción y la dirección, de los precedentes.
4. Simulación en vivo durante meses antes de usar plata real.

Todo se compara contra comprar y esperar.

## Historial

Cada operación guarda: empresa, fechas, cuánto puso (pesos y %), resultado,
por qué entró, confianza, qué esperaba, qué pasó, qué no vio y modo. Al abrir
el panel muestra el resumen de lo que cambió desde la última visita.

## Aprendizaje

- **Nivel 1:** recalibra su confianza con cada operación cerrada.
- **Nivel 2:** escribe informes de errores, los publica como issues en GitHub
  mencionando a Claude (Claude Code GitHub Actions) y Claude propone cambios.
  **Ningún cambio se aplica sin tu aprobación.**

## Claude dentro de IASEYT

API con clave propia y un espacio de trabajo con tope de gasto mensual en la
Claude Console. Al alcanzarlo, IASEYT se pausa sola. No se usan varias cuentas
de chat. Haiku filtra noticias; Sonnet analiza las importantes.

## Fuentes de datos

- Broker: API de InvertirOnline o de PPI (CEDEARs).
- Precios y noticias de EE.UU.: Finnhub.
- Avisos oficiales: SEC EDGAR (gratis).
- Práctica: reMarkets de Primary.
- El precio de un CEDEAR depende de la acción en EE.UU., el dólar CCL y el ratio.

## Seguridad

Claves cifradas y fuera del código, sin permiso de retiro cuando se pueda,
servidor con acceso por llave, panel con token (segundo factor en fase 1+),
copias de respaldo y repositorio privado.

## Fases

1. **Base** (esta versión): botones, modos, filtros, topes, Monte Carlo,
   calibración, historial, panel, broker simulado y una estrategia de prueba.
2. Datos reales y backtest con prueba hacia adelante.
3. Noticias, SEC y Claude.
4. Aprendizaje e informes de errores por GitHub.
5. Simulación completa durante al menos 3 meses.
6. Plata real, con monto chico.
