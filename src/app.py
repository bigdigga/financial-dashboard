import datetime as dt
import pandas as pd
import yfinance as yf
from dash import ctx
import dash
from dash import dcc, html, Input, Output
import plotly.graph_objects as go

# ---------- Dash app ----------
app = dash.Dash(__name__)
app.title = "LumaCharts Pro – Financial Dashboard"
server = app.server  # for gunicorn

# ---------- Custom HTML shell (Tailwind + Feather + CSS) ----------
app.index_string = """
<!DOCTYPE html>
<html lang="en" class="dark">
  <head>
    {%metas%}
    <title>LumaCharts Pro - Financial Dashboard</title>
    {%favicon%}
    {%css%}
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
      tailwind.config = {
        darkMode: 'class',
        theme: { extend: {
          colors: {
            primary: {500:'#6366f1',600:'#4f46e5'},
            secondary:{500:'#10b981',600:'#059669'},
            dark:{800:'#1e293b',900:'#0f172a'}
          }
        }}
      }
    </script>
    <script src="https://cdn.jsdelivr.net/npm/feather-icons/dist/feather.min.js"></script>
    <style>
      .transition-smooth{transition:all .3s ease}

      /* Darken Dash dropdowns in dark mode */
      .dark .Select-control{background:#1e293b;border-color:#334155;color:#e5e7eb}
      .dark .Select-menu-outer{background:#1e293b;border-color:#334155;color:#e5e7eb}
      .dark .Select-placeholder,
      .dark .Select--single > .Select-control .Select-value .Select-value-label{color:#cbd5e1}

      /* Plotly modebar tint */
      .js-plotly-plot .modebar-btn svg path{fill:#94a3b8}
      .js-plotly-plot .modebar-btn:hover svg path{fill:#6366f1}

      /* Hide the unified-hover vertical white guide line */
      .hoverlayer .hoverline { display: none !important; }

      /* --- Dark Dropdown: eliminate focus/flicker color mismatch --- */
      .dark .Select-control,
      .dark .is-open > .Select-control,
      .dark .is-focused > .Select-control {
        background:#1e293b !important;
        border-color:#334155 !important;
        color:#e5e7eb !important;
        box-shadow:none !important;
      }
      .dark .Select--single > .Select-control .Select-value .Select-value-label,
      .dark .Select-placeholder,
      .dark .Select-input > input {
        color:#e5e7eb !important;
      }
      .dark .Select-menu-outer {
        background:#1e293b !important;
        border-color:#334155 !important;
        color:#e5e7eb !important;
      }
      .dark .Select-option { color:#e5e7eb !important; }
      .dark .Select-option.is-focused {
        background:rgba(99,102,241,.12) !important;
      }
      .dark .Select-arrow { border-top-color:#cbd5e1 !important; }
    </style>
  </head>
  <body class="bg-gray-50 dark:bg-dark-900 text-gray-800 dark:text-gray-200 min-h-screen">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <header class="mb-10">
        <div class="flex justify-between items-center">
          <div>
            <h1 class="text-3xl font-bold text-primary-500">LumaCharts Pro</h1>
            <p class="text-gray-500 dark:text-gray-400">Your comprehensive financial dashboard</p>
          </div>
          <button id="theme-toggle"
                  class="p-2 rounded-full bg-gray-200 dark:bg-dark-800 hover:bg-gray-300 dark:hover:bg-dark-700 transition-smooth"
                  onclick="(function(){
                    const el=document.documentElement;
                    el.classList.toggle('dark');
                    localStorage.setItem('theme', el.classList.contains('dark')?'dark':'light');
                    if (window.feather) feather.replace();
                  })();">
            <i data-feather="moon" class="hidden dark:block"></i>
            <i data-feather="sun" class="dark:hidden"></i>
          </button>
        </div>
      </header>
      {%app_entry%}
    </div>
    {%config%}
    {%scripts%}
    {%renderer%}
    <script>
      (function(){
        const saved = localStorage.getItem('theme');
        if (saved==='dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
          document.documentElement.classList.add('dark');
        } else {
          document.documentElement.classList.remove('dark');
        }
      })();
      document.addEventListener('DOMContentLoaded', function(){ if (window.feather) feather.replace(); });
      setTimeout(function(){ if (window.feather) feather.replace(); }, 0);
    </script>
  </body>
</html>
"""

# ------------------------------------------------------------
# Data helpers
# ------------------------------------------------------------
DEFAULT_TICKER = "AAPL"
TODAY = dt.date.today()
ACCENT = "#6366f1"  # indigo-500

def get_last_trading_day(date: dt.date) -> dt.date:
    """Return the most recent weekday (Sat/Sun -> Friday)."""
    if date.weekday() == 5:
        return date - dt.timedelta(days=1)
    if date.weekday() == 6:
        return date - dt.timedelta(days=2)
    return date

def pick_interval(days: int) -> str:
    """
    Use intraday for short/medium windows so hover shows timestamps:
      ≤ 2 days  -> 5m
      ≤ 10 days -> 30m
      ≤ 60 days -> 60m
      else      -> 1d
    """
    if days <= 2:  return "5m"
    if days <= 10: return "30m"
    if days <= 60: return "60m"
    return "1d"

def fetch_history(ticker: str, start: dt.date, end: dt.date) -> pd.Series:
    """
    Fetch Close series with a sensible interval.
    Robust to weekends/holidays and Yahoo intraday quirks by:
      - Using start/end where possible
      - Falling back to period-based pulls
      - For intraday 1D, selecting the last available trading session
    Returns tz-naive DatetimeIndex (minute-floor for intraday).
    """
    import sys
    days = (end - start).days or 1
    interval = pick_interval(days)

    def to_close_series(df: pd.DataFrame) -> pd.Series:
        if df is None or len(df) == 0:
            return pd.Series(dtype="float64")
        if isinstance(df.columns, pd.MultiIndex):
            cols = [c for c in df.columns if isinstance(c, tuple) and c[0] == "Close"]
            s = df[cols[0]] if cols else df.get("Close", pd.Series(dtype="float64"))
        else:
            s = df.get("Close", pd.Series(dtype="float64"))
        if isinstance(s, pd.DataFrame):
            s = s.squeeze("columns")
        s = s.dropna().copy()
        if s.empty:
            return s
        s.index = pd.to_datetime(s.index).tz_localize(None)
        if interval == "1d":
            s.index = s.index.normalize()
        else:
            s.index = s.index.floor("min")
        s.name = "Close"
        return s

    # --- Fast path: intraday 1D -> pull last available session explicitly ---
    if interval != "1d" and days == 1:
        try:
            d0 = yf.download(
                ticker, period="5d", interval=interval,
                progress=False, auto_adjust=False, threads=False,
            )
            s0 = to_close_series(d0)
            if not s0.empty:
                # choose the most recent date that has bars
                last_session = s0.index.normalize().max()
                s0 = s0[s0.index.normalize() == last_session]
                if not s0.empty:
                    return s0
        except Exception as e:
            print(f"[fetch_history] 1D intraday session pull error: {e}", file=sys.stderr)

    # yfinance uses exclusive 'end'; widen by a day for safety
    end_inclusive = end + dt.timedelta(days=1)

    # --- 1) Try straightforward start/end ---
    try:
        d = yf.download(
            ticker, start=start, end=end_inclusive,
            interval=interval, progress=False, auto_adjust=False, threads=False,
        )
        s = to_close_series(d)
        if not s.empty:
            return s
    except Exception as e:
        print(f"[fetch_history] download error: {e}", file=sys.stderr)

    # --- 2) Retry with .history(start/end) ---
    try:
        h = yf.Ticker(ticker).history(
            start=start, end=end_inclusive, interval=interval, auto_adjust=False
        )
        s = to_close_series(h)
        if not s.empty:
            return s
    except Exception as e:
        print(f"[fetch_history] history error: {e}", file=sys.stderr)

    # --- 3) Intraday fallback: period, then slice (and still handle 1D) ---
    try:
        if interval != "1d":
            period = "7d" if days <= 7 else "30d"
            d2 = yf.download(
                ticker, period=period, interval=interval,
                progress=False, auto_adjust=False, threads=False,
            )
            s2 = to_close_series(d2)
            if not s2.empty:
                if days == 1:
                    # same logic: pick last session with data
                    last_session = s2.index.normalize().max()
                    s2 = s2[s2.index.normalize() == last_session]
                    if not s2.empty:
                        return s2
                else:
                    # slice calendar window for multi-day intraday
                    mask = (s2.index >= pd.Timestamp(start)) & (s2.index < pd.Timestamp(end_inclusive))
                    s2 = s2.loc[mask]
                    if not s2.empty:
                        return s2
    except Exception as e:
        print(f"[fetch_history] intraday period fallback error: {e}", file=sys.stderr)

    print(f"[fetch_history] no data for {ticker} {start}→{end} (interval {interval})", file=sys.stderr)
    return pd.Series(dtype="float64")

def make_figure(s: pd.Series, ticker: str) -> go.Figure:
    df = s.to_frame(name="Close").reset_index()
    df.columns = ["Date", "Close"]
    df["Date"] = pd.to_datetime(df["Date"], utc=False)

    # Detect daily vs intraday
    is_daily_like = (df["Date"].dt.floor("D") == df["Date"]).all()
    if is_daily_like:
        df["Date"] = df["Date"].dt.normalize()

    span_days = max(1, int((df["Date"].iloc[-1] - df["Date"].iloc[0]).total_seconds() // 86400))
    has_intraday_time = (df["Date"].dt.floor("D") != df["Date"]).any()

    # Tick/hover formats
    if has_intraday_time:
        x_tickformat = "%b %d, %H:%M"
        hover_fmt = "%b %d, %Y %H:%M"
    else:
        x_tickformat = "%b %d" if span_days <= 120 else "%b %Y"
        hover_fmt = "%b %d, %Y"

    fig = go.Figure([
        go.Scatter(
            x=df["Date"],
            y=df["Close"],
            mode="lines+markers",
            line=dict(width=2.2, color=ACCENT),
            marker=dict(size=3.5, line=dict(width=0), color=ACCENT, opacity=0.9),
            connectgaps=False,
            hovertemplate=f"%{{x|{hover_fmt}}}<br>Close: $%{{y:.2f}}<extra></extra>",
            name=f"{ticker} Close",
        )
    ])

    # Unified hover card (vertical white line hidden via CSS)
    fig.update_layout(
        title=f"{ticker} Price Performance",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        template=None,
        hovermode="x unified",
        hoverdistance=30,
        spikedistance=-1,
        margin=dict(l=56, r=24, t=60, b=56),
        font=dict(color="#a5b4fc"),
        hoverlabel=dict(
            bgcolor="rgba(17,24,39,0.92)",
            bordercolor="rgba(99,102,241,0.35)",
            font=dict(color="#e5e7eb", size=12),
            align="left",
            namelength=-1,
        ),
        uirevision="keep",
    )

    # Axes + weekend-only breaks (safer across time zones)
    fig.update_xaxes(
        type="date",
        tickformat=x_tickformat,
        tickfont=dict(color="#a5b4fc"),
        title_text="Date",
        title_font=dict(color="#a5b4fc"),
        gridcolor="rgba(99,102,241,0.08)",
        zeroline=False,
        showspikes=False,
        rangeslider=dict(visible=span_days > 60),
        rangebreaks=[dict(bounds=["sat", "mon"])],
    )
    fig.update_yaxes(
        tickprefix="$",
        tickformat=".0f",
        tickfont=dict(color="#a5b4fc"),
        title=dict(text="Close", standoff=20),
        title_font=dict(color="#a5b4fc"),
        gridcolor="rgba(99,102,241,0.08)",
        zeroline=False,
        showspikes=False,
    )

    return fig

# Window helpers
RANGE_DAYS = {
    "1d": 1, "1w": 7, "1m": 30, "3m": 90, "6m": 180, "1y": 365, "2y": 730
}
def compute_window_endpoints(range_key: str, end_date: dt.date) -> tuple[dt.date, dt.date]:
    if (range_key or "").lower() == "1d":
        end_date = get_last_trading_day(end_date)
        start_date = end_date - dt.timedelta(days=1)
        return start_date, end_date
    days = RANGE_DAYS.get((range_key or "3m").lower(), 90)
    return end_date - dt.timedelta(days=days), end_date

# ------------------------------------------------------------
# Layout
# ------------------------------------------------------------
graph_config = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["hoverCompareCartesian", "toggleSpikelines"],
    "responsive": True,
}

app.layout = html.Main(children=[
    # Controls card
    html.Div(
        className="bg-white dark:bg-dark-800 rounded-xl shadow-md p-6 mb-8 transition-smooth",
        children=[
            html.H2("Market Data Controls", className="text-xl font-semibold mb-6 text-primary-500"),
            html.Div(className="grid grid-cols-1 md:grid-cols-3 gap-6", children=[
                # Ticker
                html.Div(children=[
                    html.Label("Select Ticker", className="block text-sm font-medium mb-2 text-gray-700 dark:text-gray-300"),
                    dcc.Dropdown(
                        id="ticker",
                        options=[
                            {"label": "Apple (AAPL)", "value": "AAPL"},
                            {"label": "Microsoft (MSFT)", "value": "MSFT"},
                            {"label": "Alphabet (GOOGL)", "value": "GOOGL"},
                            {"label": "Amazon (AMZN)", "value": "AMZN"},
                            {"label": "NVIDIA (NVDA)", "value": "NVDA"},
                            {"label": "Tesla (TSLA)", "value": "TSLA"},
                            {"label": "Meta (META)", "value": "META"},
                            {"label": "S&P 500 (SPY)", "value": "SPY"},
                            {"label": "NASDAQ 100 (QQQ)", "value": "QQQ"},
                        ],
                        value=DEFAULT_TICKER,
                        clearable=False,
                        className="dark:text-gray-900",
                    )
                ]),
                # Range
                html.Div(children=[
                    html.Label("Date Range", className="block text-sm font-medium mb-2 text-gray-700 dark:text-gray-300"),
                    dcc.Dropdown(
                        id="range-select",
                        options=[
                            {"label": "1 Day", "value": "1d"},
                            {"label": "1 Week", "value": "1w"},
                            {"label": "1 Month", "value": "1m"},
                            {"label": "3 Months", "value": "3m"},
                            {"label": "6 Months", "value": "6m"},
                            {"label": "1 Year", "value": "1y"},
                            {"label": "2 Years", "value": "2y"},
                        ],
                        value="3m",
                        clearable=False,
                        className="dark:text-gray-900",
                    )
                ]),
                # Update button
                html.Div(className="flex items-end justify-center md:justify-end gap-3", children=[
                    html.Button(
                        id="update-btn",
                        n_clicks=0,
                        className=(
                            "inline-flex items-center gap-2 px-5 py-2.5 rounded-xl "
                            "bg-primary-500 hover:bg-primary-600 text-white font-semibold "
                            "shadow-md shadow-primary-900/20 transition-smooth"
                        ),
                        children="Update Chart",
                    ),
                    html.Div(id="status", style={"display": "none"}),
                ]),
            ])
        ]
    ),

    # Chart card
    html.Div(
        className="bg-white dark:bg-dark-800 rounded-xl shadow-md p-6 mb-8 transition-smooth",
        children=[
            html.Div(className="flex justify-between items-center mb-6",
                     children=[
                         html.H2("Price Performance", className="text-xl font-semibold text-primary-500"),
                         html.Div(className="flex gap-4 text-primary-300", children=[
                             html.Button("1D", id="btn-1d", n_clicks=0, className="text-sm hover:text-primary-500"),
                             html.Button("1W", id="btn-1w", n_clicks=0, className="text-sm hover:text-primary-500"),
                             html.Button("1M", id="btn-1m", n_clicks=0, className="text-sm hover:text-primary-500"),
                             html.Button("1Y", id="btn-1y", n_clicks=0, className="text-sm hover:text-primary-500"),
                         ])
                     ]),
            dcc.Loading(
                dcc.Graph(id="price-chart", config=graph_config, style={"height": "520px"}),
                type="default"
            ),
        ]
    ),

    # Info card
    html.Div(
        className="bg-white dark:bg-dark-800 rounded-xl shadow-md p-6 transition-smooth mt-8",
        children=[
            html.Div(className="flex items-start gap-3",
                     children=[
                         html.Div("ℹ️", className="text-secondary-500"),
                         html.Div(children=[
                             html.H3("Ready to fetch data", className="text-sm font-medium text-gray-800 dark:text-gray-200"),
                             html.P("Select a ticker and date range above to visualize the price performance.",
                                    className="mt-1 text-sm text-gray-600 dark:text-gray-400")
                         ])
                     ])
        ]
    ),
])

# ------------------------------------------------------------
# Callbacks
# ------------------------------------------------------------
@app.callback(
    Output("range-select", "value"),
    Input("btn-1d", "n_clicks"),
    Input("btn-1w", "n_clicks"),
    Input("btn-1m", "n_clicks"),
    Input("btn-1y", "n_clicks"),
    prevent_initial_call=True,
)
def set_quick_range(n1, n2, n3, n4):
    trigger = ctx.triggered_id
    return {
        "btn-1d": "1d",
        "btn-1w": "1w",
        "btn-1m": "1m",
        "btn-1y": "1y",
    }.get(trigger, dash.no_update)

@app.callback(
    Output("price-chart", "figure"),
    Output("status", "children"),
    Input("ticker", "value"),
    Input("range-select", "value"),
    Input("update-btn", "n_clicks"),
)
def update_chart(ticker, range_key, _n):
    try:
        t = (ticker or "").strip().upper() or DEFAULT_TICKER
        end = get_last_trading_day(dt.date.today())
        start, end = compute_window_endpoints(range_key, end)

        s = fetch_history(t, start, end)
        if s is None or len(s) == 0:
            return go.Figure(layout=dict(
                title=f"No data for '{t}' in {start}→{end}. Try another range."
            )), f"No rows returned for {t}."

        fig = make_figure(s, t)
        msg = f"Showing {t} – {range_key.upper()} window ({len(s)} rows)"
        return fig, msg
    except Exception as e:
        return go.Figure(layout=dict(title="Error")), f"Error: {type(e).__name__}: {e}"

if __name__ == "__main__":
    app.run(debug=True)
