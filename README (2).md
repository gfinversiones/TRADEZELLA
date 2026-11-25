# Diario de Trading (estilo Tradezella) — Streamlit

## Cómo correrlo
```bash
pip install -r requirements.txt
streamlit run app.py
```
Se abre en http://localhost:8501. Los trades se guardan en `trades.db` (SQLite) en esta misma carpeta.

## Qué tiene
- **Dashboard**: P&L neto, esperanza matemática, profit factor, % ganadores, ganancia media / pérdida media,
  ratio ganadores vs perdedores, drawdown, días verdes, score radar, P&L acumulado, P&L diario, últimos trades y calendario.
- **Cargar trades**: formulario (fecha, hora, símbolo, Long/Short, entrada, salida, contratos, multiplicador, costo, setup, notas)
  e importación desde CSV/Excel (hay plantilla para descargar).
- **Calendario**: resultado de cada día (verde/rojo), cantidad de trades, % ganadores, total semanal y mensual, y detalle por día.
- **Curva de equity**: por día o por trade, con drawdown y resumen mensual.
- **Reportes**: por día de semana, símbolo, setup, hora, lado y mes; ganadores vs perdedores; distribución de P&L.
- **Trades**: grilla editable (editar, agregar, borrar).
- **Exportar**: Excel con hojas Resumen, Trades, Diario (con gráficos), Mensual, Por símbolo, Por día de semana y Por setup.

## Cálculos
- P&L bruto = (salida − entrada) × contratos × multiplicador   (en Short se invierte el signo)
- P&L neto = P&L bruto − costo
- Esperanza = %ganadores × ganancia media − %perdedores × pérdida media
- Profit factor = ganancia bruta / pérdida bruta

El **multiplicador** es el valor en $ de un punto por contrato (ES=50, MES=5, NQ=20, MNQ=2; acciones=1).
Todos los cálculos usan los filtros de la barra lateral.
