"""
Diario de Trading estilo Tradezella — Streamlit
Ejecutar:  streamlit run app.py
"""
from __future__ import annotations

import calendar
import hmac
import os
import re
from datetime import date, datetime
from math import pi

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import core

st.set_page_config(page_title="Diario de Trading", page_icon="📈", layout="wide")

GREEN, RED, PURPLE, GRAY = "#16a34a", "#dc2626", "#6d4aff", "#9ca3af"
GREEN_BG, RED_BG = "#e8f7ee", "#fdecec"

# ----------------------------------------------------------------------------
# Estilos
# ----------------------------------------------------------------------------
st.markdown(
    """
<style>
.block-container {padding-top: 4rem !important;}
/* Pestañas: más grandes, oscuras y legibles */
.stTabs [data-baseweb="tab-list"] {gap: 1.2rem;}
.stTabs [data-baseweb="tab"] p {font-size: 1.05rem !important; font-weight: 600 !important; color: #1f1f1f !important;}
/* Barra lateral: textos más oscuros */
[data-testid="stSidebar"] p, [data-testid="stSidebar"] small,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {color: #2b2b2b !important;}
.kpi {background:#fff;border:1px solid #ececf3;border-radius:14px;padding:14px 16px;
      display:flex;justify-content:space-between;align-items:center;min-height:104px;
      box-shadow:0 1px 2px rgba(16,24,40,.04);}
.kpi-label {color:#6b7280;font-size:.80rem;font-weight:500;}
.kpi-value {font-size:1.55rem;font-weight:700;line-height:1.3;}
.kpi-sub {color:#6b7280;font-size:.75rem;}
.badge {display:inline-block;border-radius:6px;padding:0 6px;font-size:.72rem;font-weight:600;margin-left:4px;}
.b-g {background:#dcfce7;color:#15803d;} .b-r {background:#fee2e2;color:#b91c1c;} .b-n {background:#eef0f4;color:#4b5563;}
.ratio-bar {display:flex;height:7px;border-radius:4px;overflow:hidden;width:120px;margin-top:6px;}
.panel-title {font-weight:600;font-size:.95rem;margin:2px 0 6px 2px;}

table.cal {width:100%;border-collapse:separate;border-spacing:6px;table-layout:fixed;}
table.cal th {color:#6b7280;font-weight:600;font-size:.8rem;text-align:center;padding:4px;
              background:#f3f4f8;border-radius:8px;}
table.cal td {height:96px;vertical-align:top;border-radius:10px;padding:6px 8px;
              border:1px solid #ececf3;background:#fafafc;font-size:.78rem;}
table.cal.compact td {height:74px;}
table.cal td.out {background:transparent;border:1px dashed #eceef3;color:#c4c7d0;}
table.cal td.win {background:#e8f7ee;border-color:#9fdcb7;}
table.cal td.loss {background:#fdecec;border-color:#f3b0b0;}
table.cal td.flat {background:#f1f2f6;border-color:#d7d9e0;}
table.cal td.week {background:#f5f3ff;border-color:#ddd6fe;}
table.cal .dnum {text-align:right;color:#6b7280;font-weight:600;}
table.cal .pnl {font-weight:700;font-size:1.0rem;text-align:center;margin-top:6px;}
table.cal .meta {text-align:center;color:#4b5563;}
.cal-head {display:flex;justify-content:space-between;align-items:baseline;margin:4px 2px 2px;}
.cal-title {font-weight:700;font-size:1.15rem;}
</style>
""",
    unsafe_allow_html=True,
)


# ----------------------------------------------------------------------------
# Helpers de formato
# ----------------------------------------------------------------------------
def money(v: float | None, signo: bool = False) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    s = "-" if v < 0 else ("+" if signo and v > 0 else "")
    return f"{s}${abs(v):,.2f}"


def short_money(v: float) -> str:
    a, s = abs(v), "-" if v < 0 else ""
    if a >= 1_000_000:
        return f"{s}${a / 1_000_000:.2f}M"
    if a >= 10_000:
        return f"{s}${a / 1000:.1f}K"
    return f"{s}${a:,.0f}" if a >= 1000 else f"{s}${a:,.2f}"


def ratio(v: float) -> str:
    return "∞" if np.isinf(v) else f"{v:.2f}"


def color_of(v: float) -> str:
    return GREEN if v > 0 else RED if v < 0 else "#374151"


def color_pnl(v):
    if isinstance(v, (int, float)) and not pd.isna(v):
        return f"color: {GREEN}" if v > 0 else f"color: {RED}" if v < 0 else ""
    return ""


def donut_svg(win: int, loss: int) -> str:
    r, c = 24, 2 * pi * 24
    tot = win + loss
    if tot == 0:
        return f'<svg width="64" height="64" viewBox="0 0 64 64"><circle cx="32" cy="32" r="{r}" fill="none" stroke="{GRAY}" stroke-width="8"/></svg>'
    g = c * win / tot
    return (
        f'<svg width="64" height="64" viewBox="0 0 64 64">'
        f'<circle cx="32" cy="32" r="{r}" fill="none" stroke="{RED}" stroke-width="8"/>'
        f'<circle cx="32" cy="32" r="{r}" fill="none" stroke="{GREEN}" stroke-width="8" '
        f'stroke-dasharray="{g:.2f} {c:.2f}" transform="rotate(-90 32 32)"/></svg>'
    )


def gauge_svg(frac: float) -> str:
    L = pi * 28
    return (
        f'<svg width="76" height="46" viewBox="0 0 72 44">'
        f'<path d="M8 40 A28 28 0 0 1 64 40" fill="none" stroke="{RED}" stroke-width="7" stroke-linecap="round"/>'
        f'<path d="M8 40 A28 28 0 0 1 64 40" fill="none" stroke="{GREEN}" stroke-width="7" stroke-linecap="round" '
        f'stroke-dasharray="{frac * L:.2f} {L:.2f}"/></svg>'
    )


def kpi(label: str, value: str, sub: str = "", color: str | None = None, extra: str = "") -> str:
    return (
        f'<div class="kpi"><div><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value" style="color:{color or "#111827"}">{value}</div>'
        f'<div class="kpi-sub">{sub}</div></div><div>{extra}</div></div>'
    )


# ----------------------------------------------------------------------------
# Gráficos
# ----------------------------------------------------------------------------
def _crossings(x: np.ndarray, y: np.ndarray, base: float):
    """Inserta los puntos donde la curva cruza la línea base, para colorear verde/rojo prolijo."""
    xs, ys = [x[0]], [y[0]]
    for i in range(1, len(y)):
        a, b = y[i - 1] - base, y[i] - base
        if a * b < 0:
            t = a / (a - b)
            xs.append(x[i - 1] + t * (x[i] - x[i - 1]))
            ys.append(base)
        xs.append(x[i])
        ys.append(y[i])
    return np.array(xs, dtype=float), np.array(ys, dtype=float)


def equity_fig(curve: pd.DataFrame, base: float, por: str, con_drawdown: bool = True, height: int = 420):
    is_date = por == "dia"
    x = curve["x"]
    if is_date:
        epoch = pd.Timestamp("1970-01-01")
        xn = ((pd.to_datetime(x) - epoch) / pd.Timedelta(seconds=1)).to_numpy(dtype=float)
    else:
        xn = x.to_numpy(dtype=float)
    xs, ys = _crossings(xn, curve["equity"].to_numpy(dtype=float), base)
    xs_plot = (pd.Timestamp("1970-01-01") + pd.to_timedelta(xs, unit="s")) if is_date else xs

    rows = 2 if con_drawdown else 1
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.06,
                        row_heights=[0.72, 0.28] if con_drawdown else [1.0])
    for fill_y, col in [(np.maximum(ys, base), "rgba(22,163,74,0.22)"), (np.minimum(ys, base), "rgba(220,38,38,0.22)")]:
        fig.add_trace(go.Scatter(x=xs_plot, y=np.full(len(ys), base), line=dict(width=0),
                                 hoverinfo="skip", showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=xs_plot, y=fill_y, fill="tonexty", fillcolor=col, line=dict(width=0),
                                 hoverinfo="skip", showlegend=False), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=x, y=curve["equity"], mode="lines", line=dict(color=PURPLE, width=2.2), name="Equity",
        hovertemplate=("%{x|%d/%m/%Y}" if is_date else "Trade #%{x}") + "<br>Equity: $%{y:,.2f}<extra></extra>",
    ), row=1, col=1)
    fig.add_hline(y=base, line=dict(color=GRAY, width=1, dash="dot"), row=1, col=1)
    if con_drawdown:
        fig.add_trace(go.Scatter(
            x=x, y=curve["drawdown"], fill="tozeroy", mode="lines", line=dict(color=RED, width=1.2),
            fillcolor="rgba(220,38,38,0.18)", name="Drawdown",
            hovertemplate="Drawdown: $%{y:,.2f}<extra></extra>",
        ), row=2, col=1)
        fig.update_yaxes(title_text="Drawdown", row=2, col=1)
    fig.update_yaxes(tickprefix="$", separatethousands=True, gridcolor="#eef0f4")
    fig.update_xaxes(gridcolor="#f3f4f6", title_text=None if is_date else "N° de trade", row=rows, col=1)
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=10, b=10), showlegend=False,
                      plot_bgcolor="white", paper_bgcolor="white", hovermode="x unified")
    return fig


def daily_bar_fig(daily: pd.DataFrame, height: int = 300):
    fig = go.Figure(go.Bar(
        x=daily["fecha"], y=daily["pnl_neto"],
        marker_color=[GREEN if v >= 0 else RED for v in daily["pnl_neto"]],
        customdata=daily["trades"],
        hovertemplate="%{x|%d/%m/%Y}<br>P&L: $%{y:,.2f}<br>Trades: %{customdata}<extra></extra>",
    ))
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="white",
                      paper_bgcolor="white", bargap=0.25)
    fig.update_yaxes(tickprefix="$", gridcolor="#eef0f4", zerolinecolor="#cbd5e1")
    return fig


def score_fig(m: dict, height: int = 300):
    win_s = m["pct_ganadores"] * 100
    pf = m["profit_factor"]
    pf_s = 100 if np.isinf(pf) else min(pf / 2.5, 1) * 100
    r = m["ratio_media"]
    r_s = 100 if np.isinf(r) else min(r / 2.5, 1) * 100
    score = (win_s + pf_s + r_s) / 3
    cats = ["% ganadores", "Profit factor", "Gan./Pérd. media"]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=[100, 100, 100, 100], theta=cats + [cats[0]], fill="toself",
                                  fillcolor="rgba(109,74,255,0.05)", line=dict(color="#d9d3ff"),
                                  hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatterpolar(r=[win_s, pf_s, r_s, win_s], theta=cats + [cats[0]], fill="toself",
                                  fillcolor="rgba(109,74,255,0.30)", line=dict(color=PURPLE, width=2),
                                  hovertemplate="%{theta}: %{r:.0f}/100<extra></extra>", showlegend=False))
    fig.update_layout(height=height, margin=dict(l=40, r=40, t=20, b=20), paper_bgcolor="white",
                      polar=dict(radialaxis=dict(visible=False, range=[0, 100]), bgcolor="white"))
    return fig, score


def group_figs(g: pd.DataFrame, key: str, titulo: str):
    h = max(260, 34 * len(g) + 80)
    f1 = go.Figure(go.Bar(y=g[key].astype(str), x=g["trades"], orientation="h", marker_color=PURPLE,
                          hovertemplate="%{y}: %{x} trades<extra></extra>"))
    f1.update_layout(title=f"Cantidad de trades por {titulo}", height=h, margin=dict(l=10, r=10, t=40, b=10),
                     plot_bgcolor="white", paper_bgcolor="white", yaxis=dict(autorange="reversed"))
    f2 = go.Figure(go.Bar(y=g[key].astype(str), x=g["pnl_neto"], orientation="h",
                          marker_color=[GREEN if v >= 0 else RED for v in g["pnl_neto"]],
                          hovertemplate="%{y}: $%{x:,.2f}<extra></extra>"))
    f2.update_layout(title=f"P&L neto por {titulo}", height=h, margin=dict(l=10, r=10, t=40, b=10),
                     plot_bgcolor="white", paper_bgcolor="white", yaxis=dict(autorange="reversed"),
                     xaxis=dict(tickprefix="$", zerolinecolor="#94a3b8"))
    return f1, f2


# ----------------------------------------------------------------------------
# Calendario
# ----------------------------------------------------------------------------
def shift_month(delta: int):
    y, m = st.session_state.cal_ym
    m += delta
    while m > 12:
        y, m = y + 1, m - 12
    while m < 1:
        y, m = y - 1, m + 12
    st.session_state.cal_ym = (y, m)


def go_today():
    t = date.today()
    st.session_state.cal_ym = (t.year, t.month)


def calendar_nav(key: str):
    y, m = st.session_state.cal_ym
    c1, c2, c3, c4 = st.columns([1, 1, 1, 6])
    c1.button("◀", key=f"{key}_prev", on_click=shift_month, args=(-1,), help="Mes anterior")
    c2.button("Hoy", key=f"{key}_today", on_click=go_today)
    c3.button("▶", key=f"{key}_next", on_click=shift_month, args=(1,), help="Mes siguiente")
    return y, m


def calendar_html(df: pd.DataFrame, year: int, month: int, compact: bool = False) -> str:
    daily = core.daily_summary(df)
    by_day = {d.date(): row for d, row in zip(daily["fecha"], daily.itertuples())} if len(daily) else {}
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)

    month_rows = daily[(daily["fecha"].dt.year == year) & (daily["fecha"].dt.month == month)] if len(daily) else daily
    m_pnl = month_rows["pnl_neto"].sum() if len(month_rows) else 0.0
    m_days = len(month_rows)
    m_trades = int(month_rows["trades"].sum()) if len(month_rows) else 0

    head = (
        f'<div class="cal-head"><div class="cal-title">{core.MESES_ES[month - 1]} {year}</div>'
        f'<div>Resultado del mes: <b style="color:{color_of(m_pnl)}">{money(m_pnl)}</b>'
        f' · {m_days} días operados · {m_trades} trades</div></div>'
    )
    dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    html = [head, f'<table class="cal{" compact" if compact else ""}"><tr>']
    html += [f"<th>{d}</th>" for d in dias] + ["<th>Semana</th></tr>"]

    for n_w, week in enumerate(weeks, 1):
        html.append("<tr>")
        w_pnl, w_days, w_trades = 0.0, 0, 0
        for d in week:
            if d.month != month:
                html.append(f'<td class="out"><div class="dnum">{d.day}</div></td>')
                continue
            r = by_day.get(d)
            if r is None:
                html.append(f'<td><div class="dnum">{d.day}</div></td>')
                continue
            pnl, nt = r.pnl_neto, int(r.trades)
            w_pnl += pnl
            w_days += 1
            w_trades += nt
            cls = "win" if pnl > 0 else "loss" if pnl < 0 else "flat"
            wr = r.ganadores / nt * 100 if nt else 0
            meta = f"{nt} trade{'s' if nt != 1 else ''}"
            if not compact:
                meta += f"<br>{wr:.0f}% ganadores"
            html.append(
                f'<td class="{cls}"><div class="dnum">{d.day}</div>'
                f'<div class="pnl" style="color:{color_of(pnl)}">{short_money(pnl)}</div>'
                f'<div class="meta">{meta}</div></td>'
            )
        html.append(
            f'<td class="week"><div class="dnum">Semana {n_w}</div>'
            f'<div class="pnl" style="color:{color_of(w_pnl)}">{short_money(w_pnl) if w_days else "—"}</div>'
            f'<div class="meta">{w_days} días · {w_trades} trades</div></td></tr>'
        )
    html.append("</table>")
    return "".join(html)


# ----------------------------------------------------------------------------
# Configuración: base de datos y contraseña (desde st.secrets o variables de entorno)
# ----------------------------------------------------------------------------
def _secret(section: str, key: str, env: str) -> str | None:
    try:
        v = st.secrets.get(section, {}).get(key)
        if v:
            return str(v)
    except Exception:
        pass
    return os.environ.get(env)


core.configure(_secret("db", "url", "DATABASE_URL"))
APP_PASSWORD = _secret("auth", "password", "APP_PASSWORD")

if APP_PASSWORD and not st.session_state.get("auth_ok"):
    st.markdown("## 🔒 Diario de Trading")
    pw = st.text_input("Contraseña", type="password")
    if pw:
        if hmac.compare_digest(pw, APP_PASSWORD):
            st.session_state.auth_ok = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta.")
    st.stop()

MULT_OPC = 100.0  # cada contrato de opciones = 100 acciones
COMISION_CONTRATO = 0.65  # USD por contrato, se cobra al comprar y al vender


TAG_SALIDA = re.compile(r"^\s*\[Salida (\d{1,2}:\d{2})\]\s*")


def separar_salida(notas) -> tuple[str | None, str | None]:
    """La hora de salida se guarda al principio de las notas como "[Salida HH:MM]".
    Devuelve (hora_salida, notas_sin_la_etiqueta)."""
    if notas is None or (isinstance(notas, float) and np.isnan(notas)):
        return None, None
    txt = str(notas)
    mt = TAG_SALIDA.match(txt)
    if not mt:
        return None, txt or None
    resto = txt[mt.end():].strip()
    return mt.group(1).zfill(5), resto or None


def unir_salida(hora_salida, notas) -> str | None:
    hs = str(hora_salida).strip() if hora_salida is not None and not (isinstance(hora_salida, float) and np.isnan(hora_salida)) else ""
    nt = str(notas).strip() if notas is not None and not (isinstance(notas, float) and np.isnan(notas)) else ""
    if hs:
        return f"[Salida {hs}] {nt}".strip()
    return nt or None


def _minutos(h) -> float:
    try:
        hh, mm = str(h).split(":")[:2]
        return int(hh) * 60 + int(mm)
    except Exception:
        return np.nan


def fmt_duracion(mins) -> str:
    if mins is None or pd.isna(mins) or mins < 0:
        return ""
    mins = int(mins)
    return f"{mins // 60} h {mins % 60:02d} min" if mins >= 60 else f"{mins} min"


def aplicar_formula(d: pd.DataFrame) -> pd.DataFrame:
    """Opciones: P&L = (salida*100 - entrada*100) * contratos - 0,65 * 2 * contratos.
    Siempre igual, sea Call o Put. Las comisiones se calculan solas."""
    if not len(d):
        return d
    d = d.copy()
    d["lado"] = d["lado"].replace({"Long": "Call", "Short": "Put"})
    cant = pd.to_numeric(d["cantidad"], errors="coerce").fillna(1)
    bruto = (pd.to_numeric(d["salida"], errors="coerce") - pd.to_numeric(d["entrada"], errors="coerce")) * MULT_OPC * cant
    for col in ("pnl_bruto", "pnl"):
        if col in d.columns:
            d[col] = bruto
    d["costo"] = COMISION_CONTRATO * 2 * cant
    d["pnl_neto"] = bruto - d["costo"]
    sep = d["notas"].map(separar_salida)
    d["hora_salida"] = sep.map(lambda x: x[0])
    d["notas_txt"] = sep.map(lambda x: x[1])
    dur = d["hora_salida"].map(_minutos) - d["hora"].map(_minutos)
    d["duracion"] = dur.map(fmt_duracion)
    return d


try:
    df_all = aplicar_formula(core.load_trades())
except Exception as e:
    st.error(
        "No me pude conectar a la base de datos. Revisá la URL en *Settings → Secrets* "
        f"(sección `[db]`, clave `url`).\n\nDetalle: `{type(e).__name__}: {e}`"
    )
    st.stop()

# ----------------------------------------------------------------------------
# Filtros (sidebar)
# ----------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 📈 Diario de Trading")
    if core.is_remote():
        st.caption(f"☁️ Guardado permanente en {core.storage_label()}")
    else:
        st.warning("💾 Guardando en SQLite local. En Streamlit Cloud estos datos se borran al reiniciar: "
                   "configurá la base en *Settings → Secrets*.", icon="⚠️")
    capital = st.number_input("Capital inicial ($)", min_value=0.0, value=0.0, step=1000.0,
                              help="Opcional. Si lo cargás, la curva de equity arranca desde acá y se calculan % de retorno y drawdown %.")
    st.markdown("### Filtros")
    if len(df_all):
        dmin, dmax = df_all["dt"].min().date(), df_all["dt"].max().date()
        rango = st.date_input("Rango de fechas", value=(dmin, dmax), format="DD/MM/YYYY")
        simbolos = st.multiselect("Símbolos", sorted(df_all["simbolo"].unique()))
        lados = st.multiselect("Tipo", ["Call", "Put"])
        setups_disp = sorted(df_all["setup"].dropna().astype(str).unique())
        setups = st.multiselect("Setup", setups_disp) if setups_disp else []
    else:
        rango, simbolos, lados, setups = (), [], [], []
        st.caption("Todavía no hay trades cargados.")

    st.divider()
    if st.button("🧪 Cargar datos de ejemplo"):
        core.add_many(core.demo_trades())
        st.rerun()
    with st.expander("🗑️ Borrar todos los trades"):
        ok = st.checkbox("Sí, quiero borrar todo")
        if st.button("Borrar todo", disabled=not ok, type="primary"):
            core.delete_all()
            st.rerun()

df = df_all
if len(df):
    if isinstance(rango, (tuple, list)) and len(rango) == 2:
        df = df[(df["dt"].dt.date >= rango[0]) & (df["dt"].dt.date <= rango[1])]
    elif isinstance(rango, (tuple, list)) and len(rango) == 1:
        df = df[df["dt"].dt.date >= rango[0]]
    if simbolos:
        df = df[df["simbolo"].isin(simbolos)]
    if lados:
        df = df[df["lado"].isin(lados)]
    if setups:
        df = df[df["setup"].isin(setups)]
    df = df.reset_index(drop=True)

if "cal_ym" not in st.session_state:
    last = df_all["dt"].max() if len(df_all) else pd.Timestamp.today()
    st.session_state.cal_ym = (last.year, last.month)

m = core.compute_metrics(df, capital)
hay_datos = m["total_trades"] > 0

tabs = st.tabs(["📊 Dashboard", "➕ Cargar trades", "📅 Calendario", "📈 Curva de equity",
                "📑 Reportes", "📋 Trades", "⬇️ Exportar"])

# ----------------------------------------------------------------------------
# 1) DASHBOARD
# ----------------------------------------------------------------------------
with tabs[0]:
    hora = datetime.now().hour
    saludo = "Buen día" if hora < 13 else "Buenas tardes" if hora < 20 else "Buenas noches"
    st.markdown(f"#### {saludo} 👋")

    if not hay_datos:
        st.info("No hay trades para mostrar. Cargá tus órdenes en **➕ Cargar trades**, importá un CSV/Excel, "
                "o probá con **🧪 Cargar datos de ejemplo** en la barra lateral.")
    else:
        c = st.columns(5)
        c[0].markdown(kpi("P&L neto", money(m["pnl_neto"]),
                          f'{m["total_trades"]} trades · comisiones {money(m["costos"])}', color_of(m["pnl_neto"])),
                      unsafe_allow_html=True)
        c[1].markdown(kpi("Esperanza matemática", money(m["esperanza"]), "por trade",
                          color_of(m["esperanza"])), unsafe_allow_html=True)
        pf = m["profit_factor"]
        c[2].markdown(kpi("Profit factor", ratio(pf), "ganancia bruta / pérdida bruta",
                          extra=gauge_svg(1.0 if np.isinf(pf) else pf / (pf + 1))), unsafe_allow_html=True)
        c[3].markdown(kpi(
            "% trades ganadores", f'{m["pct_ganadores"] * 100:.1f}%',
            f'<span class="badge b-g">{m["ganadores"]}</span><span class="badge b-n">{m["break_even"]}</span>'
            f'<span class="badge b-r">{m["perdedores"]}</span>',
            extra=donut_svg(m["ganadores"], m["perdedores"])), unsafe_allow_html=True)
        aw, al = m["ganancia_media"], m["perdida_media"]
        frac = aw / (aw + al) * 100 if (aw + al) else 50
        bar = (f'<div class="ratio-bar"><div style="width:{frac:.0f}%;background:{GREEN}"></div>'
               f'<div style="width:{100 - frac:.0f}%;background:{RED}"></div></div>'
               f'<div class="kpi-sub"><span style="color:{GREEN}">{money(aw)}</span> &nbsp; '
               f'<span style="color:{RED}">-{money(al)}</span></div>')
        c[4].markdown(kpi("Gan. media / Pérd. media", ratio(m["ratio_media"]), bar), unsafe_allow_html=True)

        st.write("")
        c2 = st.columns(4)
        c2[0].markdown(kpi("Ratio ganadores vs perdedores", ratio(m["ratio_gan_perd"]),
                           f'{m["ganadores"]} ganadores / {m["perdedores"]} perdedores'), unsafe_allow_html=True)
        c2[1].markdown(kpi("Máximo drawdown", money(m["max_drawdown"]),
                           f'{m["max_drawdown_pct"] * 100:.2f}% del pico' if m["max_drawdown_pct"] is not None else "desde el pico de equity",
                           RED if m["max_drawdown"] < 0 else None), unsafe_allow_html=True)
        c2[2].markdown(kpi("Días verdes", f'{m["pct_dias_verdes"] * 100:.0f}%',
                           f'{m["dias_verdes"]} verdes · {m["dias_rojos"]} rojos · {m["dias_operados"]} operados',
                           extra=donut_svg(m["dias_verdes"], m["dias_rojos"])), unsafe_allow_html=True)
        c2[3].markdown(kpi("Mejor / peor trade", money(m["mejor_trade"]),
                           f'Peor: <span style="color:{RED}">{money(m["peor_trade"])}</span> · '
                           f'rachas {m["max_racha_ganadora"]}G / {m["max_racha_perdedora"]}P', GREEN),
                       unsafe_allow_html=True)

        with st.expander("¿Cómo se calcula la esperanza matemática?"):
            st.markdown(
                f"""
**Esperanza = %ganadores × ganancia media − %perdedores × pérdida media**

= {m['pct_ganadores'] * 100:.1f}% × {money(m['ganancia_media'])} − {m['pct_perdedores'] * 100:.1f}% × {money(m['perdida_media'])}
= **{money(m['esperanza'])} por trade**

Es lo que en promedio esperás ganar (o perder) cada vez que tomás un trade con este sistema.
Si es positiva, el sistema tiene ventaja. Los trades en break-even cuentan en el total pero no suman ni restan.
"""
            )

        st.write("")
        g1, g2, g3 = st.columns([1, 1.4, 1.4])
        with g1:
            st.markdown('<div class="panel-title">Score</div>', unsafe_allow_html=True)
            fig, score = score_fig(m, 280)
            st.plotly_chart(fig, key="dash_score")
            st.markdown(f"<div style='text-align:center'>Tu score: <b style='font-size:1.3rem'>{score:.1f}</b></div>",
                        unsafe_allow_html=True)
        with g2:
            st.markdown('<div class="panel-title">P&L neto acumulado diario</div>', unsafe_allow_html=True)
            st.plotly_chart(equity_fig(core.equity_curve(df, 0, "dia"), 0, "dia", False, 310), key="dash_eq")
        with g3:
            st.markdown('<div class="panel-title">P&L neto diario</div>', unsafe_allow_html=True)
            st.plotly_chart(daily_bar_fig(core.daily_summary(df), 310), key="dash_bar")

        st.write("")
        l, r = st.columns([1, 2.2])
        with l:
            st.markdown('<div class="panel-title">Últimos trades</div>', unsafe_allow_html=True)
            ult = df.sort_values(["dt", "hora", "id"], ascending=False).head(12)
            ult = ult[["fecha", "simbolo", "lado", "pnl_neto"]].rename(
                columns={"fecha": "Fecha", "simbolo": "Símbolo", "lado": "Lado", "pnl_neto": "P&L neto"})
            st.dataframe(ult.style.map(color_pnl, subset=["P&L neto"]).format({"P&L neto": "${:,.2f}"}),
                         hide_index=True, height=440)
        with r:
            calendar_nav("dash")
            y, mo = st.session_state.cal_ym
            st.markdown(calendar_html(df, y, mo, compact=True), unsafe_allow_html=True)

# ----------------------------------------------------------------------------
# 2) CARGAR TRADES
# ----------------------------------------------------------------------------
with tabs[1]:
    st.subheader("Cargar una orden")

    if "f_sym" not in st.session_state:
        st.session_state.f_sym = ""
    st.caption("P&L = (precio de salida × 100 − precio de entrada × 100) × contratos − comisiones "
               "(USD 0,65 por contrato al comprar + USD 0,65 al vender, se calculan solas)")

    with st.form("nuevo_trade"):
        a1, a2, a2b, a3, a4 = st.columns([1.1, 1, 1, 1, 1])
        f_fecha = a1.date_input("Fecha", value=date.today(), format="DD/MM/YYYY")
        f_hora = a2.time_input("Hora de entrada", value=None, step=60)
        f_hora_sal = a2b.time_input("Hora de salida", value=None, step=60)
        f_sym = a3.text_input("Símbolo", key="f_sym", placeholder="QQQ, SPY, AAPL…")
        f_lado = a4.radio("Tipo", ["Call", "Put"], horizontal=True)

        b1, b2, b3 = st.columns(3)
        f_ent = b1.number_input("Precio de entrada", min_value=0.0, value=0.0, step=0.25, format="%.4f")
        f_sal = b2.number_input("Precio de salida", min_value=0.0, value=0.0, step=0.25, format="%.4f")
        f_qty = b3.number_input("Cantidad de contratos", min_value=0.0, value=1.0, step=1.0)

        c1, c2 = st.columns([1, 2])
        f_setup = c1.text_input("Setup / estrategia (opcional)")
        f_notas = c2.text_input("Notas (opcional)")
        enviado = st.form_submit_button("💾 Guardar trade", type="primary")

    if enviado:
        if not f_sym.strip():
            st.error("Falta el símbolo.")
        elif f_ent <= 0 or f_sal <= 0 or f_qty <= 0:
            st.error("Entrada, salida y cantidad tienen que ser mayores a 0.")
        else:
            f_cost = COMISION_CONTRATO * 2 * f_qty
            t = {
                "fecha": f_fecha.strftime("%Y-%m-%d"),
                "hora": f_hora.strftime("%H:%M") if f_hora else None,
                "simbolo": f_sym.strip().upper(), "lado": f_lado,
                "entrada": f_ent, "salida": f_sal, "cantidad": f_qty,
                "multiplicador": MULT_OPC, "costo": f_cost,
                "setup": f_setup.strip() or None,
                "notas": unir_salida(f_hora_sal.strftime("%H:%M") if f_hora_sal else None, f_notas),
            }
            core.add_trade(t)
            pnl = (f_sal - f_ent) * MULT_OPC * f_qty - f_cost
            dur_txt = ""
            if f_hora and f_hora_sal:
                dur_txt = fmt_duracion((f_hora_sal.hour * 60 + f_hora_sal.minute) - (f_hora.hour * 60 + f_hora.minute))
                dur_txt = f" · duración {dur_txt}" if dur_txt else ""
            st.session_state.msg_ok = (f"Trade guardado: {t['simbolo']} {f_lado} — P&L neto **{money(pnl)}** "
                                       f"(comisiones {money(f_cost)}){dur_txt}")
            st.rerun()

    if st.session_state.get("msg_ok"):
        st.success(st.session_state.pop("msg_ok"))

    st.divider()
    st.subheader("Importar desde CSV o Excel")
    st.caption("Columnas: **fecha, simbolo, entrada, salida, cantidad** (obligatorias) y opcionales "
               "**hora, lado (Call/Put), setup, notas**. Las comisiones se calculan solas. También acepta nombres en inglés "
               "(date, symbol, side, entry, exit, qty, fees…).")
    st.download_button("📄 Descargar plantilla CSV", core.template_csv(), "plantilla_trades.csv", "text/csv")
    up = st.file_uploader("Archivo", type=["csv", "xlsx", "xls"])
    if up is not None:
        try:
            raw = pd.read_csv(up, sep=None, engine="python") if up.name.lower().endswith(".csv") else pd.read_excel(up)
            prev = aplicar_formula(core.enrich(core.normalize_import(raw).assign(id=range(len(raw))))) if len(raw) else raw
            st.write(f"Se detectaron **{len(prev)}** trades válidos:")
            st.dataframe(prev.drop(columns=["id", "dt", "mes", "dia_semana"], errors="ignore").head(50), hide_index=True)
            if st.button("✅ Importar estos trades", type="primary"):
                n = core.add_many(raw)
                st.success(f"Se importaron {n} trades.")
                st.rerun()
        except Exception as e:
            st.error(f"No pude leer el archivo: {e}")

# ----------------------------------------------------------------------------
# 3) CALENDARIO
# ----------------------------------------------------------------------------
with tabs[2]:
    calendar_nav("cal")
    y, mo = st.session_state.cal_ym
    st.markdown(calendar_html(df, y, mo), unsafe_allow_html=True)

    mes_df = df[(df["dt"].dt.year == y) & (df["dt"].dt.month == mo)] if hay_datos else df
    if len(mes_df):
        st.write("")
        dias_op = sorted(mes_df["dt"].dt.date.unique(), reverse=True)
        dsel = st.selectbox("Ver detalle del día", dias_op, format_func=lambda d: f"{core.DIAS_ES[d.weekday()]} {d:%d/%m/%Y}")
        dd = mes_df[mes_df["dt"].dt.date == dsel].reset_index(drop=True)
        md = core.compute_metrics(dd)
        k = st.columns(4)
        k[0].markdown(kpi("P&L neto del día", money(md["pnl_neto"]), f'{md["total_trades"]} trades',
                          color_of(md["pnl_neto"])), unsafe_allow_html=True)
        k[1].markdown(kpi("% ganadores", f'{md["pct_ganadores"] * 100:.0f}%',
                          f'{md["ganadores"]}G / {md["perdedores"]}P'), unsafe_allow_html=True)
        k[2].markdown(kpi("Profit factor", ratio(md["profit_factor"])), unsafe_allow_html=True)
        k[3].markdown(kpi("Comisiones", money(md["costos"])), unsafe_allow_html=True)
        cc1, cc2 = st.columns([1.3, 1])
        with cc1:
            cols = ["hora", "hora_salida", "duracion", "simbolo", "lado", "entrada", "salida", "cantidad", "costo",
                    "pnl_neto", "setup", "notas_txt"]
            st.dataframe(dd[cols].style.map(color_pnl, subset=["pnl_neto"])
                         .format({"pnl_neto": "${:,.2f}", "costo": "${:,.2f}", "entrada": "{:,.2f}", "salida": "{:,.2f}"}),
                         hide_index=True,
                         column_config={"hora": "Entrada (hora)", "hora_salida": "Salida (hora)", "duracion": "Duración",
                                        "simbolo": "Símbolo", "lado": "Tipo", "entrada": "Entrada",
                                        "salida": "Salida", "cantidad": "Contratos", "costo": "Comisiones",
                                        "pnl_neto": "P&L neto", "setup": "Setup", "notas_txt": "Notas"})
        with cc2:
            st.plotly_chart(equity_fig(core.equity_curve(dd, 0, "trade"), 0, "trade", False, 260), key="day_eq")

# ----------------------------------------------------------------------------
# 4) CURVA DE EQUITY
# ----------------------------------------------------------------------------
with tabs[3]:
    if not hay_datos:
        st.info("Cargá trades para ver la curva de equity.")
    else:
        por = st.radio("Eje X", ["Por día", "Por trade"], horizontal=True)
        por_k = "dia" if por == "Por día" else "trade"
        curve = core.equity_curve(df, capital, por_k)
        k = st.columns(4)
        k[0].markdown(kpi("Capital final" if capital else "P&L acumulado", money(m["capital_final"]),
                          f'Retorno {m["retorno_pct"] * 100:.2f}%' if m["retorno_pct"] is not None else "",
                          color_of(m["pnl_neto"])), unsafe_allow_html=True)
        k[1].markdown(kpi("Máximo drawdown", money(m["max_drawdown"]),
                          f'{m["max_drawdown_pct"] * 100:.2f}%' if m["max_drawdown_pct"] is not None else "",
                          RED), unsafe_allow_html=True)
        k[2].markdown(kpi("Mejor día", money(m["mejor_dia"]), color=GREEN), unsafe_allow_html=True)
        k[3].markdown(kpi("Peor día", money(m["peor_dia"]), color=RED), unsafe_allow_html=True)
        st.plotly_chart(equity_fig(curve, capital, por_k, True, 560), key="eq_main")

        st.markdown('<div class="panel-title">Resultado mensual</div>', unsafe_allow_html=True)
        mm = core.monthly_summary(df)
        st.dataframe(
            mm.rename(columns={"mes": "Mes", "trades": "Trades", "ganadores": "Ganadores", "perdedores": "Perdedores",
                               "ganancia_bruta": "Ganancia bruta", "perdida_bruta": "Pérdida bruta",
                               "pnl_neto": "P&L neto", "pct_ganadores": "% ganadores", "esperanza": "Esperanza",
                               "pnl_acumulado": "Acumulado"})
            .style.map(color_pnl, subset=["P&L neto", "Esperanza", "Acumulado"])
            .format({"Ganancia bruta": "${:,.2f}", "Pérdida bruta": "${:,.2f}", "P&L neto": "${:,.2f}",
                     "% ganadores": "{:.1%}", "Esperanza": "${:,.2f}", "Acumulado": "${:,.2f}"}),
            hide_index=True,
        )

# ----------------------------------------------------------------------------
# 5) REPORTES
# ----------------------------------------------------------------------------
with tabs[4]:
    if not hay_datos:
        st.info("Cargá trades para ver los reportes.")
    else:
        opciones = {"Día de la semana": ("dia_semana", "día"), "Símbolo": ("simbolo", "símbolo"),
                    "Setup": ("setup", "setup"), "Hora": ("hora_bloque", "hora"), "Tipo (Call/Put)": ("lado", "tipo"),
                    "Mes": ("mes", "mes")}
        sel = st.radio("Agrupar por", list(opciones), horizontal=True)
        key, titulo = opciones[sel]
        dfr = df.copy()
        dfr["setup"] = dfr["setup"].fillna("(sin setup)")
        dfr["hora_bloque"] = dfr["hora"].fillna("").astype(str).str[:2].map(lambda h: f"{h}:00" if h.strip() else "(sin hora)")
        g = core.group_summary(dfr, key)
        if key in ("hora_bloque", "mes"):
            g = g.sort_values(key).reset_index(drop=True)
        f1, f2 = group_figs(g, key, titulo)
        a, b = st.columns(2)
        a.plotly_chart(f1, key="rep_cnt")
        b.plotly_chart(f2, key="rep_pnl")
        st.dataframe(
            g.rename(columns={key: sel, "trades": "Trades", "ganadores": "Ganadores", "perdedores": "Perdedores",
                              "ganancia_bruta": "Ganancia bruta", "perdida_bruta": "Pérdida bruta",
                              "pnl_neto": "P&L neto", "pct_ganadores": "% ganadores", "esperanza": "Esperanza"})
            .style.map(color_pnl, subset=["P&L neto", "Esperanza"])
            .format({"Ganancia bruta": "${:,.2f}", "Pérdida bruta": "${:,.2f}", "P&L neto": "${:,.2f}",
                     "% ganadores": "{:.1%}", "Esperanza": "${:,.2f}"}),
            hide_index=True,
        )

        st.divider()
        st.markdown('<div class="panel-title">Ganadores vs perdedores</div>', unsafe_allow_html=True)
        w, l = df[df["pnl_neto"] > 0], df[df["pnl_neto"] < 0]
        comp = pd.DataFrame({
            "Métrica": ["Cantidad", "P&L total", "P&L medio", "Mayor", "Cantidad media de contratos", "Comisión media"],
            "Ganadores": [len(w), money(w["pnl_neto"].sum()), money(w["pnl_neto"].mean() if len(w) else 0),
                          money(w["pnl_neto"].max() if len(w) else 0), f'{w["cantidad"].mean() if len(w) else 0:.2f}',
                          money(w["costo"].mean() if len(w) else 0)],
            "Perdedores": [len(l), money(l["pnl_neto"].sum()), money(l["pnl_neto"].mean() if len(l) else 0),
                           money(l["pnl_neto"].min() if len(l) else 0), f'{l["cantidad"].mean() if len(l) else 0:.2f}',
                           money(l["costo"].mean() if len(l) else 0)],
        })
        c1, c2 = st.columns([1, 1.3])
        c1.dataframe(comp.astype(str), hide_index=True)
        hist = go.Figure(go.Histogram(x=df["pnl_neto"], nbinsx=30, marker_color=PURPLE,
                                      hovertemplate="P&L: %{x}<br>Trades: %{y}<extra></extra>"))
        hist.add_vline(x=0, line=dict(color=GRAY, dash="dot"))
        hist.update_layout(title="Distribución de P&L por trade", height=300, margin=dict(l=10, r=10, t=40, b=10),
                           plot_bgcolor="white", paper_bgcolor="white", xaxis=dict(tickprefix="$"))
        c2.plotly_chart(hist, key="rep_hist")

# ----------------------------------------------------------------------------
# 6) TRADES (editar / borrar)
# ----------------------------------------------------------------------------
with tabs[5]:
    if not hay_datos:
        st.info("No hay trades (o los filtros no dejan ninguno).")
    else:
        st.caption("Editá cualquier celda, agregá filas abajo o seleccioná filas y borralas con la papelera. "
                   "Después tocá **Guardar cambios**. El P&L se recalcula al guardar.")
        edit = df[core.COLUMNS + ["pnl_neto"]].copy()
        edit["fecha"] = pd.to_datetime(edit["fecha"]).dt.date
        # La hora de salida va en su propia columna (por dentro se guarda en las notas)
        edit["notas"] = df["notas_txt"].values
        edit.insert(list(edit.columns).index("hora") + 1, "hora_salida", df["hora_salida"].values)
        edited = st.data_editor(
            edit, num_rows="dynamic", hide_index=True, key="editor",
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "fecha": st.column_config.DateColumn("Fecha", format="DD/MM/YYYY", required=True),
                "hora": st.column_config.TextColumn("Hora entrada", help="HH:MM"),
                "hora_salida": st.column_config.TextColumn("Hora salida", help="HH:MM"),
                "simbolo": st.column_config.TextColumn("Símbolo", required=True),
                "lado": st.column_config.SelectboxColumn("Tipo", options=["Call", "Put"], required=True),
                "entrada": st.column_config.NumberColumn("Entrada", format="%.2f", required=True),
                "salida": st.column_config.NumberColumn("Salida", format="%.2f", required=True),
                "cantidad": st.column_config.NumberColumn("Contratos", required=True),
                "multiplicador": None,  # siempre 100 (opciones)
                "costo": st.column_config.NumberColumn("Comisiones", format="$%.2f", disabled=True),
                "setup": st.column_config.TextColumn("Setup"),
                "notas": st.column_config.TextColumn("Notas", width="large"),
                "pnl_neto": st.column_config.NumberColumn("P&L neto", format="$%.2f", disabled=True),
            },
        )
        if st.button("💾 Guardar cambios", type="primary"):
            try:
                guardar = edited.copy()
                guardar["notas"] = [unir_salida(hs, nt) for hs, nt in zip(guardar["hora_salida"], guardar["notas"])]
                guardar = guardar.drop(columns=["pnl_neto", "hora_salida"])
                n_upd, n_new, n_del = core.save_edits(df["id"].tolist(), guardar)
                st.success(f"Listo: {n_upd} actualizados, {n_new} nuevos, {n_del} borrados.")
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo guardar: {e}")

# ----------------------------------------------------------------------------
# 7) EXPORTAR
# ----------------------------------------------------------------------------
with tabs[6]:
    st.subheader("Exportar resultados")
    if not hay_datos:
        st.info("No hay datos para exportar.")
    else:
        st.markdown(
            f"Se exportan los **{len(df)} trades** que pasan los filtros actuales, en un Excel con las hojas: "
            "**Resumen** (todas las métricas), **Trades**, **Diario** (con gráfico de equity y P&L diario), "
            "**Mensual**, **Por símbolo**, **Por día de semana** y **Por setup**."
        )
        nombre = f"diario_trading_{date.today():%Y%m%d}"
        c1, c2 = st.columns(2)
        c1.download_button("📥 Descargar Excel", core.build_excel(df, capital), f"{nombre}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
        csv = df.drop(columns=["dt", "notas_txt"], errors="ignore").to_csv(index=False).encode("utf-8")
        c2.download_button("📄 Descargar CSV de trades", csv, f"{nombre}.csv", "text/csv")
