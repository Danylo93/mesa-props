"""
Estrategia de referencia: pullback a favor da tendencia, H1, majors FX.

Escolhida por ser a familia mais testada e mais chata que existe em FX.
Num desafio de prop firm o que importa nao e o retorno maximo, e o
CAMINHO: drawdown raso, poucos trades, nenhuma surpresa. Estrategia
exotica com Sharpe bonito no backtest quebra conta no dia 4.

Logica, por par:
  regime    EMA(50) vs EMA(200) define o lado. So compra acima, so vende abaixo.
  gatilho   preco recua ate a EMA(20) e FECHA de volta a favor do regime.
  momento   RSI(14) cruzando de volta (>40 long / <60 short) - evita faca caindo.
  vol       ATR(14)/preco dentro de uma banda - fora dela e noticia ou mercado morto.
  sessao    so entra entre 07:00 e 16:00 UTC (Londres + abertura NY).
  stop      1.5 x ATR(14)
  alvo      2.0 R, breakeven em +1.0 R
  tempo     fecha em 48 barras se nao resolveu

Tudo parametrizado: scripts/run_backtest.py faz varredura e walk-forward.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

__all__ = ["StratParams", "add_indicators", "generate_signals", "DEFAULT"]


@dataclass(frozen=True)
class StratParams:
    ema_fast: int = 50
    ema_slow: int = 200
    ema_pull: int = 20
    rsi_len: int = 14
    rsi_long: float = 40.0
    rsi_short: float = 60.0
    atr_len: int = 14
    atr_mult_stop: float = 1.5
    rr: float = 2.0
    be_at_r: float = 1.0
    max_bars: int = 48
    pull_lookback: int = 3      # em quantas barras o recuo pode ter ocorrido
    rsi_ceiling: float = 72.0   # nao compra exaustao
    rsi_floor: float = 28.0
    # Refinamentos opcionais. A varredura + walk-forward decidem se pagam.
    slope_bars: int = 0         # >0: exige EMA(50) inclinada a favor ha N barras
    shallow_pullback: bool = False   # recuo nao pode furar a EMA(50)
    stop_mode: str = "atr"      # "atr" | "swing"
    swing_bars: int = 10        # janela do swing quando stop_mode="swing"
    swing_buffer_atr: float = 0.25
    session_start: int = 7      # UTC
    session_end: int = 16       # UTC, exclusivo
    atr_pct_min: float = 0.00020
    atr_pct_max: float = 0.00600
    allow_long: bool = True
    allow_short: bool = True

    def with_(self, **kw) -> "StratParams":
        return replace(self, **kw)


DEFAULT = StratParams()


def _rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0.0)
    dn = (-d).clip(lower=0.0)
    # Wilder: EMA com alpha = 1/n
    rs = up.ewm(alpha=1 / n, adjust=False).mean() / dn.ewm(alpha=1 / n, adjust=False).mean()
    return 100.0 - 100.0 / (1.0 + rs)


def _atr(df: pd.DataFrame, n: int) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - pc).abs(),
        (df["low"] - pc).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def add_indicators(df: pd.DataFrame, p: StratParams = DEFAULT) -> pd.DataFrame:
    out = df.copy()
    c = out["close"]
    out["ema_f"] = c.ewm(span=p.ema_fast, adjust=False).mean()
    out["ema_s"] = c.ewm(span=p.ema_slow, adjust=False).mean()
    out["ema_p"] = c.ewm(span=p.ema_pull, adjust=False).mean()
    out["rsi"] = _rsi(c, p.rsi_len)
    out["atr"] = _atr(out, p.atr_len)
    out["atr_pct"] = out["atr"] / c
    return out


def generate_signals(df: pd.DataFrame, p: StratParams = DEFAULT) -> pd.Series:
    """
    +1 compra, -1 venda, 0 nada. O sinal da barra t e executado na
    ABERTURA de t+1 pelo backtest - nunca no fechamento da propria barra.

    O recuo nao precisa ser na barra imediatamente anterior: basta ter
    ocorrido nas ultimas `pull_lookback` barras. Exigir que o toque na
    EMA e a retomada acontecam na mesma barra quase nunca dispara.
    """
    d = df
    k = max(1, p.pull_lookback)
    up_regime = d["ema_f"] > d["ema_s"]
    dn_regime = d["ema_f"] < d["ema_s"]

    # recuo recente ate a EMA(20)
    dipped = d["low"].rolling(k).min().shift(1) <= d["ema_p"].shift(1)
    popped = d["high"].rolling(k).max().shift(1) >= d["ema_p"].shift(1)

    # retomada: fecha de volta do lado certo da EMA(20), com barra a favor
    recl_up = (d["close"] > d["ema_p"]) & (d["close"] > d["open"])
    recl_dn = (d["close"] < d["ema_p"]) & (d["close"] < d["open"])

    # momento de volta, mas sem exaustao
    mom_up = d["rsi"].between(p.rsi_long, p.rsi_ceiling)
    mom_dn = d["rsi"].between(p.rsi_floor, p.rsi_short)

    # inclinacao da EMA(50): tendencia que anda, nao tendencia parada
    if p.slope_bars > 0:
        slope = d["ema_f"] - d["ema_f"].shift(p.slope_bars)
        up_regime = up_regime & (slope > 0)
        dn_regime = dn_regime & (slope < 0)

    # recuo raso: tendencia forte nao devolve tudo
    if p.shallow_pullback:
        dipped = dipped & (d["low"].rolling(k).min().shift(1) > d["ema_f"].shift(1))
        popped = popped & (d["high"].rolling(k).max().shift(1) < d["ema_f"].shift(1))

    vol_ok = d["atr_pct"].between(p.atr_pct_min, p.atr_pct_max)
    hours = d.index.hour
    sess_ok = pd.Series((hours >= p.session_start) & (hours < p.session_end), index=d.index)

    longs = up_regime & dipped & recl_up & mom_up & vol_ok & sess_ok
    shorts = dn_regime & popped & recl_dn & mom_dn & vol_ok & sess_ok
    if not p.allow_long:
        longs = longs & False
    if not p.allow_short:
        shorts = shorts & False

    sig = pd.Series(0, index=d.index, dtype=int)
    sig[longs] = 1
    sig[shorts] = -1
    return sig


def stop_distance(df: pd.DataFrame, i: int, side: int, p: StratParams = DEFAULT) -> float:
    """
    Distancia do stop em PRECO.

    "atr"   -> multiplo fixo do ATR. Simples, agnostico de estrutura.
    "swing" -> abaixo da minima (ou acima da maxima) das ultimas `swing_bars`
               barras, com folga de ATR. Respeita a estrutura do mercado,
               que e onde o stop de verdade pertence.
    """
    atr = float(df["atr"].iloc[i])
    if atr <= 0:
        return 0.0
    if p.stop_mode != "swing":
        return p.atr_mult_stop * atr
    lo = slice(max(0, i - p.swing_bars + 1), i + 1)
    px = float(df["close"].iloc[i])
    if side > 0:
        anchor = float(df["low"].iloc[lo].min()) - p.swing_buffer_atr * atr
        dist = px - anchor
    else:
        anchor = float(df["high"].iloc[lo].max()) + p.swing_buffer_atr * atr
        dist = anchor - px
    # nunca mais apertado que 0.5 ATR nem mais largo que 3 ATR
    return float(min(max(dist, 0.5 * atr), 3.0 * atr))
