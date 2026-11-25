# IASEYT

Asistente de inversión con reglas de riesgo estrictas. **Fase 1: todo en
simulación, con plata de mentira.** Las especificaciones están en
[docs/DISENO.md](docs/DISENO.md).

> La estrategia incluida es de prueba: no lee noticias y no hay evidencia de que
> gane plata. Sirve para probar que el circuito completo funciona.

## Qué hace esta versión

- Botones **Encender, Pausar, Reanudar, Apagar** y **Cerrar todo**.
- **Modo automático** (decide solo, con topes) y **modo asistido** (te propone
  un monto en pesos con el % de tu cuenta y vos elegís cuánto poner).
- Los **8 filtros para comprar**, incluido **Monte Carlo** con 10.000 caminos.
- **Topes de riesgo** y **frenos** (pérdida diaria y caída desde el pico).
- Tamaño de posición con **un cuarto de Kelly**.
- **Calibración** de la confianza según los aciertos reales.
- **Historial** en SQLite y **resumen desde tu última visita**.
- **Panel web** que se abre desde la PC o el celular.

## Instalación

Necesitás Python 3.11 o más nuevo.

```bash
git clone https://github.com/gallernomanuel-png/IASEYT-Beta-Propio.git
cd IASEYT-Beta-Propio
python -m venv .venv
# Windows: .venv\Scripts\activate     Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

**Simulación rápida** (corre años de datos sintéticos en segundos):

```bash
python -m iaseyt simular
```

Con la configuración normal la estrategia de prueba casi no opera, porque sus
simulaciones muestran demasiado riesgo. Es el comportamiento buscado: IASEYT
prefiere no operar antes que operar mal.

**Panel de demostración** (filtros aflojados para ver operaciones):

```bash
python -m iaseyt panel --demo
```

Abrí el enlace que aparece en la consola (incluye el token de acceso). Cada 2
segundos avanza un día de datos.

**Con tus propios precios:** un CSV con columnas `fecha,ticker,sector,precio,volumen`:

```bash
python -m iaseyt simular --csv precios.csv
```

## Configuración

Copiá `config.example.toml` como `config.toml` y cambiá los valores. Usalo con
`--config config.toml`. Las claves nunca van en ese archivo, sino en variables
de entorno (`IASEYT_TOKEN` para el panel; las del broker y Claude, desde la
fase 2).

## Pruebas

```bash
python -m pytest -q
```

## Estructura

```
iaseyt/
  config.py        valores y topes
  estado.py        botones y modos
  riesgo.py        topes, Kelly y frenos
  montecarlo.py    simulación de cada operación
  calibracion.py   corrige la confianza con los aciertos reales
  decision.py      los 8 filtros para comprar
  motor.py         une todo: datos, decisiones, órdenes e historial
  historial.py     base de datos SQLite
  broker/          broker simulado (después: IOL o PPI)
  data/            precios (CSV o sintéticos)
  estrategia/      estrategia de prueba
  panel/           panel web
tests/             pruebas automáticas
docs/DISENO.md     especificaciones
```

## Aviso

Esto no es asesoramiento financiero. Operar en bolsa implica riesgo de perder
plata. Antes de usar plata real, IASEYT tiene que pasar meses de simulación.
