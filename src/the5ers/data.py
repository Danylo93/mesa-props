"""
Carregador de dados FX (Yahoo Finance, H1).

Limitacoes conhecidas, declaradas de proposito - elas mudam como o
backtest deve ser lido:
  * Yahoo devolve mid OHLC, SEM spread. O spread e modelado no backtest.
  * Barras H1 nao dizem a ORDEM dentro da barra. O backtest assume
    sempre o pior caso (stop antes do alvo).
  * Fins de semana/feriados aparecem como lacunas, nao como barras.

Para validacao final, use tick data do proprio broker The5ers (MT5
History Center). Isto aqui serve para pesquisa e dimensionamento.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pandas as pd

__all__ = ["YF_SYMBOLS", "SPREADS_PIPS", "fetch", "load", "load_all"]

# Mapa par -> simbolo Yahoo. Yahoo usa "JPY=X" para USD/JPY.
YF_SYMBOLS: dict[str, str] = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "AUDUSD": "AUDUSD=X",
    "NZDUSD": "NZDUSD=X",
    "USDJPY": "JPY=X",
    "USDCHF": "CHF=X",
    "USDCAD": "CAD=X",
}

# Spread tipico em pips numa conta raw de prop firm, ja com folga.
# Usado como custo de ida e volta no backtest.
SPREADS_PIPS: dict[str, float] = {
    "EURUSD": 0.8, "GBPUSD": 1.2, "AUDUSD": 1.0, "NZDUSD": 1.6,
    "USDJPY": 0.9, "USDCHF": 1.3, "USDCAD": 1.4,
}

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"
_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval={iv}"


def fetch(pair: str, rng: str = "730d", interval: str = "1h",
          cache_dir: str | Path = "data/raw", refresh: bool = False) -> pd.DataFrame:
    """Baixa (ou le do cache) OHLC de um par. Index UTC, colunas o/h/l/c."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"{pair}_{interval}.csv"
    if cache.exists() and not refresh:
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        return df

    sym = YF_SYMBOLS.get(pair, f"{pair}=X")
    url = _BASE.format(sym=sym, rng=rng, iv=interval)
    # curl em vez de urllib: neste ambiente o proxy HTTPS so deixa passar
    # o curl limpo - urllib leva 429 do Yahoo em todas as tentativas.
    payload = None
    last = ""
    for attempt in range(6):
        proc = subprocess.run(
            ["curl", "-sS", "--compressed", "--max-time", "45", "-H", f"User-Agent: {_UA}", url],
            capture_output=True, text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip().startswith("{"):
            try:
                payload = json.loads(proc.stdout)
                break
            except json.JSONDecodeError as e:
                last = str(e)
        else:
            last = (proc.stderr or proc.stdout)[:200]
        time.sleep(2.0 * (attempt + 1))
    if payload is None:
        raise RuntimeError(f"{pair}: falhou apos 6 tentativas ({last})")

    chart = payload["chart"]
    if chart.get("error"):
        raise RuntimeError(f"{pair}: {chart['error']}")
    res = chart["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame(
        {"open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"]},
        index=pd.to_datetime(res["timestamp"], unit="s", utc=True),
    )
    df = df.dropna()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.to_csv(cache)
    return df


def load(pair: str, **kw) -> pd.DataFrame:
    return fetch(pair, **kw)


def load_all(pairs: list[str] | None = None, pause: float = 0.6, **kw) -> dict[str, pd.DataFrame]:
    """Carrega varios pares. Pausa entre requests para nao irritar o Yahoo."""
    pairs = pairs or list(YF_SYMBOLS)
    out: dict[str, pd.DataFrame] = {}
    for i, p in enumerate(pairs):
        try:
            out[p] = fetch(p, **kw)
        except Exception as e:  # um par faltando nao invalida o estudo
            print(f"  ! {p}: {e}")
            continue
        if i < len(pairs) - 1:
            time.sleep(pause)
    return out
