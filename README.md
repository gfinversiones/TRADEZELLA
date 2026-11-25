# Diario de Trading (estilo Tradezella) — Streamlit

## Cómo correrlo
```bash
pip install -r requirements.txt
streamlit run app.py
```
Se abre en http://localhost:8501.

## Dónde se guardan los trades
- **Sin configurar nada**: en `trades.db` (SQLite) en esta carpeta. Sirve para usarla en tu PC.
  En Streamlit Cloud ese archivo **se borra** cada vez que la app se reinicia.
- **Con una base PostgreSQL (Supabase, gratis)**: el guardado es permanente. La tabla se crea sola.

### Configurar Supabase
1. Creá una cuenta en https://supabase.com y un proyecto nuevo (guardá la contraseña de la base).
2. En el proyecto: botón **Connect** → pestaña de connection string → elegí **Session pooler** y copiá la URI.
   (Usá el pooler: la conexión directa es solo IPv6 y Streamlit Cloud no la soporta.)
3. Reemplazá `[YOUR-PASSWORD]` por tu contraseña. Si tiene caracteres como `@ # / :` cambiala por una solo con letras y números.
4. En Streamlit Cloud: **Manage app → Settings → Secrets** y pegá (ver `.streamlit/secrets.toml.example`):
   ```toml
   [db]
   url = "postgresql://postgres.xxxx:TU_PASSWORD@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"

   [auth]
   password = "contraseña-para-entrar-a-la-app"   # opcional
   ```
5. Guardá. La barra lateral tiene que mostrar "☁️ Guardado permanente en PostgreSQL".

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
