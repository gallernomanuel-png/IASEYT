# IASEYT

Asistente de inversión con reglas de riesgo estrictas. **Fase 1: todo en
simulación, con plata de mentira.** Las especificaciones están en
[docs/DISENO.md](docs/DISENO.md).

> **Fase 2 (en curso):** conexión con PPI en su entorno de prueba, descarga de
> precios históricos reales y backtest con prueba hacia adelante.

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

**Backtest con prueba hacia adelante** (entrena en un período y prueba en el
siguiente, que nunca vio; solo cuentan los períodos de prueba):

```bash
python -m iaseyt backtest                     # con precios sintéticos
python -m iaseyt backtest --csv precios.csv   # con precios reales
```

## PPI

IASEYT se conecta a PPI con la librería oficial. **Por defecto usa el sandbox**,
el entorno de prueba, donde las órdenes no usan plata real. Operar con plata
real está bloqueado hasta la fase 6.

1. Abrí tu cuenta en PPI y pedí las claves de la API (pública y privada).
2. Guardá las claves como variables de entorno. **Nunca** en archivos del repo.

   Windows (PowerShell), solo para la ventana actual:

   ```powershell
   $env:PPI_KEY_PUBLICA = "tu clave pública"
   $env:PPI_KEY_PRIVADA = "tu clave privada"
   $env:PPI_CUENTA = "tu número de cuenta comitente"
   ```

3. Probá la conexión (solo lectura: saldo y un precio):

   ```bash
   python -m iaseyt ppi-verificar
   ```

4. Bajá precios históricos reales y corré el backtest con ellos:

   ```bash
   python -m iaseyt ppi-descargar --produccion --salida precios.csv
   python -m iaseyt backtest --csv precios.csv
   ```

   `--produccion` lee del entorno real porque el sandbox puede tener precios de
   mentira. Solo lee: con `--produccion` IASEYT no puede mandar órdenes.

5. Mandá una orden de prueba al sandbox (compra 1 unidad y la vende):

   ```bash
   python -m iaseyt ppi-prueba-orden --ticker AAPL
   ```

   Muestra cada respuesta de PPI. Sirve para confirmar cómo nombra PPI los
   estados de las órdenes, que su documentación no detalla.

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
