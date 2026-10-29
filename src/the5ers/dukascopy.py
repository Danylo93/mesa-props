"""
Carregador Dukascopy (candles H1, BID) - fonte principal de dados.

Por que nao Yahoo: Yahoo devolve mid sintetico, com lacunas e sujeito a
429 agressivo. Dukascopy publica o book real do proprio broker, em
arquivos mensais comprimidos, e e o que se usa para backtest FX serio.

Formato do .bi5, confirmado empiricamente neste repo:
  LZMA (FORMAT_ALONE), registros de 24 bytes big-endian:
      >I  offset em segundos desde o inicio do mes (UTC)
      >I  open      (em pontos inteiros)
      >I  close     <-- ATENCAO: close vem ANTES de low/high
      >I  low
      >I  high
      >f  volume
  Escala: pares com JPY /1000, o resto /100000.

A ordem (open, close, low, high) foi verificada contra 744 registros:
0 violacoes de low<=min(o,c) e high>=max(o,c); a leitura OHLC classica
produziu 527 violacoes nos mesmos dados.
"""

from __future__ import annotations

import lzma
import struct
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

__all__ = ["PAIRS", "fetch_month", "fetch_pair", "load_all"]

PAIRS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD"]

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "Chrome/120 Safari/537.36")
_URL = "https://datafeed.dukascopy.com/datafeed/{pair}/{y}/{m:02d}/BID_candles_hour_1.bi5"
_REC = struct.Struct(">5If")


def _scale(pair: str) -> float:
    return 1000.0 if "JPY" in pair.upper() else 100000.0


def _download(url: str, cache: Path, tries: int = 2) -> bytes | None:
    """
    Baixa com cache em disco e recuo CURTO.

    O servidor devolve 503 em rajada quando se pede rapido demais, mas se
    recupera em segundos. Recuo curto repetido em varias passadas rende
    muito mais que recuo longo numa passada so.
    """
    if cache.exists() and cache.stat().st_size > 200:
        return cache.read_bytes()
    for a in range(tries):
        p = subprocess.run(
            ["curl", "-sS", "--max-time", "15", "--connect-timeout", "8",
             "-H", f"User-Agent: {_UA}", url],
            capture_output=True,
        )
        body = p.stdout
        if p.returncode == 0 and len(body) > 200 and not body[:20].lstrip().startswith(b"<"):
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(body)
            return body
        # 404 = mes sem arquivo (futuro). Nao insiste.
        if b"404" in body[:60] or b"Not Found" in body[:80]:
            return None
        time.sleep(0.8 * (a + 1))
    return None


def fetch_month(pair: str, year: int, month: int, cache_dir: Path) -> pd.DataFrame | None:
    """Um mes de candles H1. `month` e 1-12 (a URL usa 0-11)."""
    url = _URL.format(pair=pair, y=year, m=month - 1)
    blob = _download(url, cache_dir / pair / f"{year}-{month:02d}.bi5")
    if not blob:
        return None
    try:
        dec = lzma.decompress(blob, format=lzma.FORMAT_ALONE)
    except lzma.LZMAError:
        return None
    if len(dec) < _REC.size:
        return None

    base = datetime(year, month, 1, tzinfo=timezone.utc)
    sc = _scale(pair)
    rows, idx = [], []
    for i in range(len(dec) // _REC.size):
        off, o, c, lo, hi, vol = _REC.unpack_from(dec, i * _REC.size)
        if vol <= 0:            # hora sem negocio (fim de semana/feriado)
            continue
        rows.append((o / sc, hi / sc, lo / sc, c / sc, vol))
        idx.append(base + timedelta(seconds=off))
    if not rows:
        return None
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"],
                        index=pd.DatetimeIndex(idx, tz="UTC"))


def fetch_pair(pair: str, months: int = 24, cache_dir: str | Path = "data/raw/duka",
               end: datetime | None = None) -> pd.DataFrame:
    """Concatena os ultimos `months` meses de candles H1 de um par."""
    cache_dir = Path(cache_dir)
    end = end or datetime.now(timezone.utc)
    parts: list[pd.DataFrame] = []
    y, m = end.year, end.month
    for _ in range(months):
        df = fetch_month(pair, y, m, cache_dir)
        if df is not None:
            parts.append(df)
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    if not parts:
        raise RuntimeError(f"{pair}: nenhum mes baixado")
    out = pd.concat(parts).sort_index()
    return out[~out.index.duplicated(keep="last")]


def load_all(pairs: list[str] | None = None, months: int = 24,
             cache_dir: str | Path = "data/raw/duka") -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for p in (pairs or PAIRS):
        try:
            out[p] = fetch_pair(p, months=months, cache_dir=cache_dir)
            print(f"  {p:8} {len(out[p]):6} barras  "
                  f"{out[p].index[0].date()} -> {out[p].index[-1].date()}", flush=True)
        except Exception as e:
            print(f"  ! {p}: {e}", flush=True)
    return out
