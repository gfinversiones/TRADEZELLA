"""
Lógica del diario de trading: base de datos, cálculos de P&L, métricas y exportación a Excel.
No depende de Streamlit, así que se puede testear o reutilizar por separado.
"""
from __future__ import annotations

import io
import sqlite3
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

DB_PATH = Path(__file__).parent / "trades.db"

COLUMNS = [
    "id", "fecha", "hora", "simbolo", "lado", "entrada", "salida",
    "cantidad", "multiplicador", "costo", "setup", "notas",
]

DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES_ES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
            "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

# Valor por punto de algunos contratos comunes (para ayudar en la carga)
MULTIPLICADORES = {
    "ES": 50, "MES": 5, "NQ": 20, "MNQ": 2, "YM": 5, "MYM": 0.5,
    "RTY": 50, "M2K": 5, "CL": 1000, "MCL": 100, "GC": 100, "MGC": 10,
    "Acciones / CEDEARs": 1,
}


# ----------------------------------------------------------------------------
# Base de datos: PostgreSQL (Supabase u otro) si hay URL configurada; si no, SQLite local
# ----------------------------------------------------------------------------
_DB_URL: str | None = None
_schema_ready: set = set()
_COLS_NO_ID = [c for c in COLUMNS if c != "id"]

_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha         TEXT NOT NULL,
    hora          TEXT,
    simbolo       TEXT NOT NULL,
    lado          TEXT NOT NULL,
    entrada       REAL NOT NULL,
    salida        REAL NOT NULL,
    cantidad      REAL NOT NULL,
    multiplicador REAL NOT NULL DEFAULT 1,
    costo         REAL NOT NULL DEFAULT 0,
    setup         TEXT,
    notas         TEXT
)"""

_SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS trades (
    id            BIGSERIAL PRIMARY KEY,
    fecha         TEXT NOT NULL,
    hora          TEXT,
    simbolo       TEXT NOT NULL,
    lado          TEXT NOT NULL,
    entrada       DOUBLE PRECISION NOT NULL,
    salida        DOUBLE PRECISION NOT NULL,
    cantidad      DOUBLE PRECISION NOT NULL,
    multiplicador DOUBLE PRECISION NOT NULL DEFAULT 1,
    costo         DOUBLE PRECISION NOT NULL DEFAULT 0,
    setup         TEXT,
    notas         TEXT
)"""


def configure(db_url: str | None) -> None:
    """Definí la URL de PostgreSQL (ej. Supabase). None o vacío = SQLite local."""
    global _DB_URL
    _DB_URL = (db_url or "").strip() or None


def storage_label() -> str:
    if _DB_URL:
        host = _DB_URL.split("@")[-1].split("/")[0].split(":")[0]
        return f"PostgreSQL ({host})"
    return f"SQLite local ({DB_PATH.name})"


def is_remote() -> bool:
    return _DB_URL is not None


class _DB:
    """Context manager que abre la conexión, crea la tabla si hace falta y hace commit."""

    def __enter__(self):
        if _DB_URL:
            import psycopg2
            kw = {} if "sslmode=" in _DB_URL else {"sslmode": "require"}
            self.con = psycopg2.connect(_DB_URL, connect_timeout=15, **kw)
            self.ph, schema, key = "%s", _SCHEMA_PG, _DB_URL
        else:
            self.con = sqlite3.connect(DB_PATH)
            self.ph, schema, key = "?", _SCHEMA_SQLITE, str(DB_PATH)
        self.cur = self.con.cursor()
        if key not in _schema_ready:
            self.cur.execute(schema)
            _schema_ready.add(key)
        return self

    def __exit__(self, exc_type, *a):
        try:
            if exc_type is None:
                self.con.commit()
            else:
                self.con.rollback()
        finally:
            self.con.close()
        return False

    def ph_list(self, n: int) -> str:
        return ", ".join([self.ph] * n)


def _py(v):
    """Convierte tipos numpy/pandas a tipos Python (psycopg2 no acepta numpy)."""
    if v is None:
        return None
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and np.isnan(v):
        return None
    if v is pd.NaT or (not isinstance(v, (str, bytes)) and pd.isna(v)):
        return None
    return v


def _rows(df: pd.DataFrame, cols: list[str]) -> list[list]:
    return [[_py(v) for v in row] for row in df[cols].astype(object).itertuples(index=False, name=None)]


def load_trades() -> pd.DataFrame:
    with _DB() as db:
        db.cur.execute(f"SELECT {', '.join(COLUMNS)} FROM trades ORDER BY fecha, hora, id")
        data = db.cur.fetchall()
    df = pd.DataFrame(data, columns=COLUMNS)
    for c in ["entrada", "salida", "cantidad", "multiplicador", "costo"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["id"] = pd.to_numeric(df["id"], errors="coerce").astype("Int64") if len(df) else df["id"]
    return enrich(df)


def add_trade(trade: dict) -> None:
    with _DB() as db:
        db.cur.execute(
            f"INSERT INTO trades ({', '.join(_COLS_NO_ID)}) VALUES ({db.ph_list(len(_COLS_NO_ID))})",
            [_py(trade.get(c)) for c in _COLS_NO_ID],
        )


def add_many(df: pd.DataFrame) -> int:
    df = normalize_import(df)
    rows = _rows(df, _COLS_NO_ID)
    if not rows:
        return 0
    with _DB() as db:
        db.cur.executemany(
            f"INSERT INTO trades ({', '.join(_COLS_NO_ID)}) VALUES ({db.ph_list(len(_COLS_NO_ID))})",
            rows,
        )
    return len(rows)


def save_edits(original_ids: list[int], edited: pd.DataFrame) -> tuple[int, int, int]:
    """Guarda lo editado en la grilla: actualiza por id, inserta filas nuevas y
    borra las que se quitaron. Solo toca los ids que estaban visibles."""
    edited = edited.copy()
    if "id" not in edited.columns:
        edited["id"] = np.nan
    ids_num = pd.to_numeric(edited["id"], errors="coerce")
    keep = set(ids_num.dropna().astype(int))
    to_delete = [int(i) for i in original_ids if int(i) not in keep]
    delete_ids(to_delete)

    existing = edited[ids_num.notna()]
    new = edited[ids_num.isna()]
    n_upd = n_new = 0
    if len(existing):
        upd = normalize_import(existing)
        rows = [r[:-1] + [int(r[-1])] for r in _rows(upd, _COLS_NO_ID + ["id"])]
        with _DB() as db:
            db.cur.executemany(
                f"UPDATE trades SET {', '.join(f'{c} = {db.ph}' for c in _COLS_NO_ID)} WHERE id = {db.ph}",
                rows,
            )
        n_upd = len(rows)
    if len(new):
        n_new = add_many(new)
    return n_upd, n_new, len(to_delete)


def delete_ids(ids: list[int]) -> None:
    if not ids:
        return
    with _DB() as db:
        db.cur.executemany(f"DELETE FROM trades WHERE id = {db.ph}", [(int(i),) for i in ids])


def delete_all() -> None:
    with _DB() as db:
        db.cur.execute("DELETE FROM trades")


# ----------------------------------------------------------------------------
# Importación / normalización
# ----------------------------------------------------------------------------
_ALIASES = {
    "fecha": ["fecha", "date", "dia", "día", "fecha_entrada"],
    "hora": ["hora", "time", "hora_entrada"],
    "simbolo": ["simbolo", "símbolo", "symbol", "ticker", "instrumento"],
    "lado": ["lado", "side", "direccion", "dirección", "tipo"],
    "entrada": ["entrada", "precio_entrada", "entry", "entry_price", "precio entrada"],
    "salida": ["salida", "precio_salida", "exit", "exit_price", "precio salida"],
    "cantidad": ["cantidad", "contratos", "qty", "quantity", "size"],
    "multiplicador": ["multiplicador", "multiplier", "valor_punto", "point_value"],
    "costo": ["costo", "costos", "comision", "comisión", "comisiones", "fees", "commission"],
    "setup": ["setup", "estrategia", "strategy"],
    "notas": ["notas", "nota", "notes", "comentarios"],
}


def normalize_import(df: pd.DataFrame) -> pd.DataFrame:
    """Acepta columnas con nombres en español/inglés y deja el formato interno."""
    df = df.copy()
    rename = {}
    lower = {str(c).strip().lower(): c for c in df.columns}
    for target, aliases in _ALIASES.items():
        for a in aliases:
            if a in lower:
                rename[lower[a]] = target
                break
    df = df.rename(columns=rename)

    missing = [c for c in ["fecha", "simbolo", "entrada", "salida", "cantidad"] if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas obligatorias: {', '.join(missing)}")

    if "lado" not in df.columns:
        df["lado"] = "Long"
    if "multiplicador" not in df.columns:
        df["multiplicador"] = 1.0
    if "costo" not in df.columns:
        df["costo"] = 0.0
    for c in ["hora", "setup", "notas"]:
        if c not in df.columns:
            df[c] = None

    # Primero formato ISO (AAAA-MM-DD); lo que no matchee se interpreta como DD/MM/AAAA
    iso = pd.to_datetime(df["fecha"].astype(str).str[:10], format="%Y-%m-%d", errors="coerce")
    otros = pd.to_datetime(df["fecha"], format="mixed", dayfirst=True, errors="coerce")
    df["fecha"] = iso.fillna(otros).dt.strftime("%Y-%m-%d")
    df = df[df["fecha"].notna()]

    def _hora(v):
        if v is None or (isinstance(v, float) and np.isnan(v)) or str(v).strip() in ("", "nan", "NaT", "None"):
            return None
        try:
            return pd.to_datetime(str(v)).strftime("%H:%M")
        except Exception:
            return str(v)[:5]

    df["hora"] = df["hora"].map(_hora)

    lado = df["lado"].astype(str).str.strip().str.lower()
    df["lado"] = np.where(lado.isin(["short", "s", "sell", "venta", "corto", "v"]), "Short", "Long")

    for c in ["entrada", "salida", "cantidad", "multiplicador", "costo"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["multiplicador"] = df["multiplicador"].fillna(1.0)
    df["costo"] = df["costo"].fillna(0.0)
    df = df.dropna(subset=["entrada", "salida", "cantidad"])
    df["simbolo"] = df["simbolo"].astype(str).str.strip().str.upper()
    return df.reset_index(drop=True)


def template_csv() -> bytes:
    ejemplo = pd.DataFrame([
        {"fecha": "2026-11-03", "hora": "10:15", "simbolo": "MES", "lado": "Long",
         "entrada": 5980.25, "salida": 5992.50, "cantidad": 2, "multiplicador": 5,
         "costo": 2.48, "setup": "Breakout", "notas": ""},
        {"fecha": "2026-11-03", "hora": "11:40", "simbolo": "MES", "lado": "Short",
         "entrada": 5995.00, "salida": 6001.75, "cantidad": 2, "multiplicador": 5,
         "costo": 2.48, "setup": "Reversión", "notas": "Entré tarde"},
    ])
    return ejemplo.to_csv(index=False).encode("utf-8")


# ----------------------------------------------------------------------------
# Cálculos
# ----------------------------------------------------------------------------
def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega P&L bruto, neto, resultado y campos de fecha."""
    df = df.copy()
    if df.empty:
        for c in ["pnl_bruto", "pnl_neto", "puntos", "resultado", "dt"]:
            df[c] = pd.Series(dtype=float)
        return df
    sign = np.where(df["lado"] == "Short", -1.0, 1.0)
    df["puntos"] = (df["salida"] - df["entrada"]) * sign
    df["pnl_bruto"] = df["puntos"] * df["cantidad"] * df["multiplicador"]
    df["pnl_neto"] = df["pnl_bruto"] - df["costo"]
    df["resultado"] = np.select(
        [df["pnl_neto"] > 0, df["pnl_neto"] < 0], ["Ganador", "Perdedor"], "Break-even"
    )
    df["dt"] = pd.to_datetime(df["fecha"])
    df["dia_semana"] = df["dt"].dt.dayofweek.map(lambda i: DIAS_ES[i])
    df["mes"] = df["dt"].dt.strftime("%Y-%m")
    return df.sort_values(["dt", "hora", "id"], na_position="first").reset_index(drop=True)


def _max_streak(mask: pd.Series) -> int:
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def compute_metrics(df: pd.DataFrame, capital_inicial: float = 0.0) -> dict:
    n = len(df)
    if n == 0:
        return {"total_trades": 0}

    pnl = df["pnl_neto"]
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    n_w, n_l = len(wins), len(losses)
    n_be = n - n_w - n_l

    pct_win = n_w / n
    pct_loss = n_l / n
    avg_win = wins.mean() if n_w else 0.0
    avg_loss = abs(losses.mean()) if n_l else 0.0
    gross_profit = wins.sum()
    gross_loss = abs(losses.sum())

    # Esperanza matemática = %ganadores * ganancia media - %perdedores * pérdida media
    expectancy = pct_win * avg_win - pct_loss * avg_loss

    equity = capital_inicial + pnl.cumsum()
    peak = np.maximum.accumulate(np.concatenate([[capital_inicial], equity.values]))[1:]
    dd = equity.values - peak
    max_dd = dd.min() if len(dd) else 0.0
    max_dd_pct = None
    if capital_inicial > 0:
        max_dd_pct = (dd / peak).min()

    daily = daily_summary(df)
    green_days = int((daily["pnl_neto"] > 0).sum())
    red_days = int((daily["pnl_neto"] < 0).sum())

    return {
        "total_trades": n,
        "ganadores": n_w,
        "perdedores": n_l,
        "break_even": n_be,
        "pct_ganadores": pct_win,
        "pct_perdedores": pct_loss,
        "ratio_gan_perd": (n_w / n_l) if n_l else np.inf,
        "ganancia_media": avg_win,
        "perdida_media": avg_loss,
        "ratio_media": (avg_win / avg_loss) if avg_loss else np.inf,
        "esperanza": expectancy,
        "pnl_bruto": df["pnl_bruto"].sum(),
        "costos": df["costo"].sum(),
        "pnl_neto": pnl.sum(),
        "ganancia_bruta": gross_profit,
        "perdida_bruta": gross_loss,
        "profit_factor": (gross_profit / gross_loss) if gross_loss else np.inf,
        "mejor_trade": pnl.max(),
        "peor_trade": pnl.min(),
        "max_racha_ganadora": _max_streak(pnl > 0),
        "max_racha_perdedora": _max_streak(pnl < 0),
        "max_drawdown": max_dd,
        "max_drawdown_pct": max_dd_pct,
        "dias_operados": len(daily),
        "dias_verdes": green_days,
        "dias_rojos": red_days,
        "pct_dias_verdes": green_days / len(daily) if len(daily) else 0,
        "mejor_dia": daily["pnl_neto"].max() if len(daily) else 0,
        "peor_dia": daily["pnl_neto"].min() if len(daily) else 0,
        "retorno_pct": (pnl.sum() / capital_inicial) if capital_inicial > 0 else None,
        "capital_final": capital_inicial + pnl.sum(),
    }


def daily_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["fecha", "trades", "ganadores", "perdedores", "pnl_bruto",
                                     "costos", "pnl_neto", "pnl_acumulado"])
    g = df.groupby("dt").agg(
        trades=("pnl_neto", "size"),
        ganadores=("pnl_neto", lambda s: int((s > 0).sum())),
        perdedores=("pnl_neto", lambda s: int((s < 0).sum())),
        pnl_bruto=("pnl_bruto", "sum"),
        costos=("costo", "sum"),
        pnl_neto=("pnl_neto", "sum"),
    ).reset_index().rename(columns={"dt": "fecha"})
    g["pnl_acumulado"] = g["pnl_neto"].cumsum()
    return g


def group_summary(df: pd.DataFrame, by: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    g = df.groupby(by).agg(
        trades=("pnl_neto", "size"),
        ganadores=("pnl_neto", lambda s: int((s > 0).sum())),
        perdedores=("pnl_neto", lambda s: int((s < 0).sum())),
        ganancia_bruta=("pnl_neto", lambda s: s[s > 0].sum()),
        perdida_bruta=("pnl_neto", lambda s: s[s < 0].sum()),
        pnl_neto=("pnl_neto", "sum"),
    ).reset_index()
    g["pct_ganadores"] = g["ganadores"] / g["trades"]
    g["esperanza"] = g["pnl_neto"] / g["trades"]  # equivale a %G*G.media - %P*P.media
    if by == "dia_semana":
        g["_o"] = g["dia_semana"].map({d: i for i, d in enumerate(DIAS_ES)})
        g = g.sort_values("_o").drop(columns="_o")
    return g.reset_index(drop=True)


def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    g = group_summary(df, "mes")
    if not g.empty:
        g["pnl_acumulado"] = g["pnl_neto"].cumsum()
    return g


def equity_curve(df: pd.DataFrame, capital_inicial: float = 0.0, por: str = "trade") -> pd.DataFrame:
    """Devuelve la curva de equity con drawdown, por trade o por día."""
    if df.empty:
        return pd.DataFrame(columns=["x", "equity", "drawdown"])
    if por == "dia":
        d = daily_summary(df)
        x, pnl = d["fecha"], d["pnl_neto"]
    else:
        x, pnl = pd.Series(range(1, len(df) + 1)), df["pnl_neto"].reset_index(drop=True)
    eq = capital_inicial + pnl.cumsum().values
    peak = np.maximum.accumulate(np.concatenate([[capital_inicial], eq]))[1:]
    out = pd.DataFrame({"x": x.values, "equity": eq, "drawdown": eq - peak})
    # punto inicial
    start_x = (x.iloc[0] - pd.Timedelta(days=1)) if por == "dia" else 0
    out = pd.concat([pd.DataFrame({"x": [start_x], "equity": [capital_inicial], "drawdown": [0.0]}), out],
                    ignore_index=True)
    return out


def demo_trades(n_days: int = 60, seed: int = 7) -> pd.DataFrame:
    """Genera trades de ejemplo para probar la app."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n_days)
    rows = []
    price = 5900.0
    for d in days:
        if rng.random() < 0.15:
            continue
        for _ in range(rng.integers(1, 6)):
            sym = rng.choice(["MES", "MNQ", "ES"], p=[0.6, 0.3, 0.1])
            mult = MULTIPLICADORES[sym]
            lado = rng.choice(["Long", "Short"])
            price += rng.normal(0, 8)
            move = rng.normal(1.2, 6)  # leve ventaja
            exit_ = price + move if lado == "Long" else price - move
            qty = int(rng.integers(1, 4)) if sym != "ES" else 1
            hh = int(rng.integers(9, 16))
            mm = int(rng.integers(0, 60)) if hh > 9 else int(rng.integers(30, 60))
            rows.append({
                "fecha": d.strftime("%Y-%m-%d"), "hora": f"{hh:02d}:{mm:02d}",
                "simbolo": sym, "lado": lado, "entrada": round(price * 4) / 4,
                "salida": round(exit_ * 4) / 4, "cantidad": qty, "multiplicador": mult,
                "costo": round(1.24 * qty * (1 if sym != "ES" else 3.5), 2),
                "setup": rng.choice(["Breakout", "Pullback", "Reversión", "Apertura"]),
                "notas": "",
            })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# Exportación a Excel
# ----------------------------------------------------------------------------
def build_excel(df: pd.DataFrame, capital_inicial: float = 0.0) -> bytes:
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.utils import get_column_letter

    m = compute_metrics(df, capital_inicial)
    daily = daily_summary(df)
    monthly = monthly_summary(df)
    by_sym = group_summary(df, "simbolo")
    by_dow = group_summary(df, "dia_semana")
    by_setup = group_summary(df.assign(setup=df["setup"].fillna("(sin setup)")), "setup") if len(df) else pd.DataFrame()

    money = '"$"#,##0.00;[Red]-"$"#,##0.00'
    pct = "0.00%"

    def fmt_inf(v):
        return "∞" if isinstance(v, float) and np.isinf(v) else v

    resumen = [
        ("Total de trades", m.get("total_trades", 0), "0"),
        ("Trades ganadores", m.get("ganadores", 0), "0"),
        ("Trades perdedores", m.get("perdedores", 0), "0"),
        ("Break-even", m.get("break_even", 0), "0"),
        ("% ganadores", m.get("pct_ganadores", 0), pct),
        ("% perdedores", m.get("pct_perdedores", 0), pct),
        ("Ratio ganadores / perdedores", fmt_inf(m.get("ratio_gan_perd", 0)), "0.00"),
        ("Ganancia media", m.get("ganancia_media", 0), money),
        ("Pérdida media", m.get("perdida_media", 0), money),
        ("Ratio ganancia media / pérdida media", fmt_inf(m.get("ratio_media", 0)), "0.00"),
        ("Esperanza matemática por trade", m.get("esperanza", 0), money),
        ("Profit factor", fmt_inf(m.get("profit_factor", 0)), "0.00"),
        ("P&L bruto", m.get("pnl_bruto", 0), money),
        ("Costos totales", m.get("costos", 0), money),
        ("P&L neto", m.get("pnl_neto", 0), money),
        ("Mejor trade", m.get("mejor_trade", 0), money),
        ("Peor trade", m.get("peor_trade", 0), money),
        ("Máx. racha ganadora", m.get("max_racha_ganadora", 0), "0"),
        ("Máx. racha perdedora", m.get("max_racha_perdedora", 0), "0"),
        ("Máximo drawdown", m.get("max_drawdown", 0), money),
        ("Días operados", m.get("dias_operados", 0), "0"),
        ("Días verdes", m.get("dias_verdes", 0), "0"),
        ("Días rojos", m.get("dias_rojos", 0), "0"),
        ("% días verdes", m.get("pct_dias_verdes", 0), pct),
        ("Mejor día", m.get("mejor_dia", 0), money),
        ("Peor día", m.get("peor_dia", 0), money),
    ]
    if capital_inicial > 0:
        resumen += [
            ("Capital inicial", capital_inicial, money),
            ("Capital final", m.get("capital_final", 0), money),
            ("Retorno %", m.get("retorno_pct", 0) or 0, pct),
            ("Máximo drawdown %", m.get("max_drawdown_pct", 0) or 0, pct),
        ]

    trades_out = df[["fecha", "hora", "simbolo", "lado", "entrada", "salida", "cantidad",
                     "multiplicador", "puntos", "pnl_bruto", "costo", "pnl_neto", "resultado",
                     "setup", "notas"]].copy() if len(df) else pd.DataFrame()
    if len(trades_out):
        trades_out["pnl_acumulado"] = trades_out["pnl_neto"].cumsum()
        trades_out["fecha"] = pd.to_datetime(trades_out["fecha"])

    header_fill = PatternFill("solid", start_color="5B3FD6")
    header_font = Font(bold=True, color="FFFFFF", name="Arial")
    body_font = Font(name="Arial")
    thin = Side(style="thin", color="DDDDDD")
    green_font = Font(name="Arial", color="0F9D58")
    red_font = Font(name="Arial", color="D93025")

    money_cols = {"entrada", "salida", "pnl_bruto", "costo", "costos", "pnl_neto", "pnl_acumulado",
                  "ganancia_bruta", "perdida_bruta", "esperanza"}
    pct_cols = {"pct_ganadores"}
    pnl_cols = {"pnl_bruto", "pnl_neto", "pnl_acumulado", "esperanza", "puntos"}

    nice = {
        "fecha": "Fecha", "hora": "Hora", "simbolo": "Símbolo", "lado": "Lado", "entrada": "Entrada",
        "salida": "Salida", "cantidad": "Cantidad", "multiplicador": "Multiplicador", "puntos": "Puntos",
        "pnl_bruto": "P&L bruto", "costo": "Costo", "costos": "Costos", "pnl_neto": "P&L neto",
        "resultado": "Resultado", "setup": "Setup", "notas": "Notas", "pnl_acumulado": "P&L acumulado",
        "trades": "Trades", "ganadores": "Ganadores", "perdedores": "Perdedores",
        "ganancia_bruta": "Ganancia bruta", "perdida_bruta": "Pérdida bruta",
        "pct_ganadores": "% ganadores", "esperanza": "Esperanza / trade", "mes": "Mes",
        "dia_semana": "Día", "x": "",
    }

    def write_table(ws, data: pd.DataFrame, start_row: int = 1):
        if data.empty:
            ws.cell(row=start_row, column=1, value="Sin datos").font = body_font
            return
        cols = list(data.columns)
        for j, c in enumerate(cols, 1):
            cell = ws.cell(row=start_row, column=j, value=nice.get(c, c))
            cell.fill, cell.font = header_fill, header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for i, row in enumerate(data.itertuples(index=False), start_row + 1):
            for j, (c, v) in enumerate(zip(cols, row), 1):
                if isinstance(v, (np.floating, np.integer)):
                    v = v.item()
                if isinstance(v, float) and np.isnan(v):
                    v = None
                if isinstance(v, pd.Timestamp):
                    v = v.to_pydatetime()
                cell = ws.cell(row=i, column=j, value=v)
                cell.font = body_font
                cell.border = Border(bottom=thin)
                if c in money_cols:
                    cell.number_format = money
                elif c in pct_cols:
                    cell.number_format = pct
                elif c == "fecha":
                    cell.number_format = "dd/mm/yyyy"
                elif c == "puntos":
                    cell.number_format = "#,##0.00;[Red]-#,##0.00"
        last = start_row + len(data)
        for j, c in enumerate(cols, 1):
            col = get_column_letter(j)
            if c in pnl_cols and len(data):
                rng = f"{col}{start_row + 1}:{col}{last}"
                ws.conditional_formatting.add(rng, CellIsRule(operator="greaterThan", formula=["0"], font=green_font))
                ws.conditional_formatting.add(rng, CellIsRule(operator="lessThan", formula=["0"], font=red_font))
            width = max(len(str(nice.get(c, c))), *(len(str(v)) for v in data[c].astype(str).head(200))) + 3
            ws.column_dimensions[col].width = min(max(width, 10), 45)
        ws.freeze_panes = ws.cell(row=start_row + 1, column=1)
        ws.auto_filter.ref = f"A{start_row}:{get_column_letter(len(cols))}{last}"

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        wb = xw.book
        # --- Resumen
        ws = wb.create_sheet("Resumen")
        ws["A1"] = "Diario de trading — Resumen"
        ws["A1"].font = Font(name="Arial", bold=True, size=14, color="5B3FD6")
        if len(df):
            ws["A2"] = f"Período: {df['dt'].min():%d/%m/%Y} al {df['dt'].max():%d/%m/%Y}"
        ws["A2"].font = Font(name="Arial", italic=True, color="666666")
        ws["A4"], ws["B4"] = "Métrica", "Valor"
        for c in ("A4", "B4"):
            ws[c].fill, ws[c].font = header_fill, header_font
        for i, (k, v, f) in enumerate(resumen, 5):
            ws.cell(row=i, column=1, value=k).font = body_font
            cell = ws.cell(row=i, column=2, value=float(v) if isinstance(v, (np.floating, np.integer)) else v)
            cell.font = Font(name="Arial", bold=k in ("P&L neto", "Esperanza matemática por trade"))
            cell.number_format = f
            cell.alignment = Alignment(horizontal="right")
            ws.cell(row=i, column=1).border = ws.cell(row=i, column=2).border = Border(bottom=thin)
        r = 5 + len(resumen) + 1
        ws.cell(row=r, column=1, value="Esperanza = %ganadores × ganancia media − %perdedores × pérdida media").font = \
            Font(name="Arial", italic=True, size=9, color="666666")
        ws.column_dimensions["A"].width = 40
        ws.column_dimensions["B"].width = 18

        # --- Trades
        ws_t = wb.create_sheet("Trades")
        write_table(ws_t, trades_out)

        # --- Diario + gráfico de equity
        ws_d = wb.create_sheet("Diario")
        write_table(ws_d, daily)
        if len(daily) > 1:
            n = len(daily) + 1
            pnl_col = list(daily.columns).index("pnl_neto") + 1
            acc_col = list(daily.columns).index("pnl_acumulado") + 1
            cats = Reference(ws_d, min_col=1, min_row=2, max_row=n)

            lc = LineChart()
            lc.title, lc.y_axis.title, lc.height, lc.width = "Curva de equity (P&L acumulado)", "$", 9, 22
            lc.add_data(Reference(ws_d, min_col=acc_col, min_row=1, max_row=n), titles_from_data=True)
            lc.set_categories(cats)
            lc.x_axis.number_format = "dd/mm"
            lc.series[0].graphicalProperties.line.solidFill = "5B3FD6"
            lc.series[0].graphicalProperties.line.width = 22000
            lc.legend = None
            ws_d.add_chart(lc, f"{get_column_letter(len(daily.columns) + 2)}2")

            bc = BarChart()
            bc.title, bc.height, bc.width = "P&L neto diario", 9, 22
            bc.add_data(Reference(ws_d, min_col=pnl_col, min_row=1, max_row=n), titles_from_data=True)
            bc.set_categories(cats)
            bc.series[0].graphicalProperties.solidFill = "5B3FD6"
            bc.series[0].invertIfNegative = False
            bc.legend = None
            ws_d.add_chart(bc, f"{get_column_letter(len(daily.columns) + 2)}21")

        # --- Mensual, por símbolo, por día, por setup
        for name, data in [("Mensual", monthly), ("Por símbolo", by_sym),
                           ("Por día de semana", by_dow), ("Por setup", by_setup)]:
            write_table(wb.create_sheet(name), data)

        if "Sheet" in wb.sheetnames and len(wb.sheetnames) > 1:
            del wb["Sheet"]
    return buf.getvalue()
