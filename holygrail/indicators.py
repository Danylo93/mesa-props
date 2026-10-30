"""
Indicadores do Holy Grail, no metodo de Wilder.

ADX e DI sao o coracao do setup, entao sao calculados pela definicao
original de Wilder (suavizacao com alpha = 1/n, nao SMA nem EMA comum).
Usar a suavizacao errada muda o nivel do ADX e o filtro de 30 passa a
significar outra coisa.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["wilder", "true_range", "atr", "adx_di", "ema", "add_indicators"]


def wilder(x: pd.Series, n: int) -> pd.Series:
    """Suavizacao de Wilder: media exponencial com alpha = 1/n."""
    return x.ewm(alpha=1.0 / n, adjust=False).mean()


def ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat([
        df["high"] - df["low"],
        (df["high"] - pc).abs(),
        (df["low"] - pc).abs(),
    ], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return wilder(true_range(df), n)


def adx_di(df: pd.DataFrame, n: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Devolve (adx, plus_di, minus_di).

    +DM so conta quando a alta de hoje supera a de ontem MAIS do que a
    minima de ontem supera a de hoje - e vice-versa. Quando as duas sobem
    igual, nenhuma conta: e isso que separa tendencia de alargamento.
    """
    up = df["high"].diff()
    dn = -df["low"].diff()

    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)

    tr_n = wilder(true_range(df), n)
    plus_di = 100.0 * wilder(plus_dm, n) / tr_n.replace(0.0, np.nan)
    minus_di = 100.0 * wilder(minus_dm, n) / tr_n.replace(0.0, np.nan)

    denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denom
    return wilder(dx.fillna(0.0), n), plus_di, minus_di


def add_indicators(df: pd.DataFrame, ema_len: int = 20, adx_len: int = 14,
                   atr_len: int = 14) -> pd.DataFrame:
    out = df.copy()
    out["ema"] = ema(out["close"], ema_len)
    a, p, m = adx_di(out, adx_len)
    out["adx"], out["plus_di"], out["minus_di"] = a, p, m
    out["atr"] = atr(out, atr_len)
    return out
