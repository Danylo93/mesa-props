"""
Bancada de pesquisa de sinais.

A estrategia de pullback do repo foi medida como ruido (avg R identico a
entradas aleatorias). A resposta certa para isso NAO e mexer em parametro
ate o backtest ficar bonito - isso e p-hacking, e produz um sistema que
perde dinheiro de verdade.

A resposta certa e testar HIPOTESES DIFERENTES, cada uma com justificativa
economica, e submeter todas ao mesmo tribunal:

  1. separacao treino/teste por TEMPO (nunca aleatoria, em serie temporal)
  2. baseline aleatorio na mesma frequencia - bater o sorteio ou morrer
  3. consistencia entre pares - vantagem real nao aparece num par so
  4. contagem de hipoteses testadas - testar 10 ideias garante que uma
     parece boa por acaso; isso precisa estar no relatorio

Avaliacao de sinal e SEPARADA do backtest de proposito: aqui todo sinal
vira trade (sem limite de posicoes), para medir a qualidade do sinal com a
maior amostra possivel. O backtest depois aplica as travas de risco.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from .strategy import StratParams, add_indicators, generate_signals

__all__ = ["SIGNALS", "eval_signal", "scan_pair", "scan_all", "random_like"]

Signal = Callable[[pd.DataFrame], pd.Series]


# ------------------------------------------------------------------ helpers

def _z(x: pd.Series, n: int) -> pd.Series:
    m = x.rolling(n).mean()
    s = x.rolling(n).std()
    return (x - m) / s.replace(0.0, np.nan)


def _blank(df: pd.DataFrame) -> pd.Series:
    return pd.Series(0, index=df.index, dtype=int)


def _hours(df: pd.DataFrame) -> np.ndarray:
    return df.index.hour.values


# ------------------------------------------------------------------ sinais
# Cada um com a razao economica. Sem razao, e mineracao de ruido.

def sig_trend_pullback(df: pd.DataFrame) -> pd.Series:
    """Linha de base: o sinal que ja foi medido como ruido."""
    return generate_signals(df, StratParams())


def sig_meanrev_z(df: pd.DataFrame, n: int = 20, k: float = 2.0) -> pd.Series:
    """
    Reversao a media. FX major em H1 e mais reversivo que tendencial:
    o fluxo de market maker empurra o preco de volta ao valor justo.
    Compra o desvio negativo extremo, vende o positivo.
    """
    z = _z(df["close"], n)
    s = _blank(df)
    s[z <= -k] = 1
    s[z >= k] = -1
    return s


def sig_rsi_extreme(df: pd.DataFrame, lo: float = 25, hi: float = 75) -> pd.Series:
    """RSI em extremo = exaustao de curto prazo. Mesma logica, outro estimador."""
    r = df["rsi"]
    s = _blank(df)
    s[r <= lo] = 1
    s[r >= hi] = -1
    return s


def sig_bb_fade(df: pd.DataFrame, n: int = 20, k: float = 2.0) -> pd.Series:
    """Fecha fora da banda de Bollinger -> volta. Reversao com filtro de vol."""
    m = df["close"].rolling(n).mean()
    sd = df["close"].rolling(n).std()
    s = _blank(df)
    s[df["close"] < m - k * sd] = 1
    s[df["close"] > m + k * sd] = -1
    return s


def sig_london_breakout(df: pd.DataFrame) -> pd.Series:
    """
    Rompimento da faixa asiatica na abertura de Londres.
    Razao: liquidez entra as 07:00 UTC e resolve o acumulo da madrugada.
    """
    h = _hours(df)
    asia = (h >= 0) & (h < 7)
    day = df.index.normalize()
    hi = df["high"].where(asia).groupby(day).transform("max")
    lo = df["low"].where(asia).groupby(day).transform("min")
    # so usa a faixa JA fechada: vale a partir das 07:00
    window = (h >= 7) & (h < 11)
    s = _blank(df)
    s[window & (df["close"] > hi)] = 1
    s[window & (df["close"] < lo)] = -1
    return s


def sig_momentum(df: pd.DataFrame, n: int = 24) -> pd.Series:
    """Continuacao pura: o que subiu nas ultimas n barras continua."""
    ret = df["close"] - df["close"].shift(n)
    s = _blank(df)
    s[(ret > 0) & (df["close"] > df["ema_s"])] = 1
    s[(ret < 0) & (df["close"] < df["ema_s"])] = -1
    return s


def sig_vol_squeeze_break(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """
    ATR comprimido e depois rompimento. Razao: volatilidade agrupa -
    periodo calmo tende a ser seguido de movimento direcional.
    """
    atr_rank = df["atr"].rolling(n * 5).rank(pct=True)
    hh = df["high"].rolling(n).max().shift(1)
    ll = df["low"].rolling(n).min().shift(1)
    quiet = atr_rank < 0.3
    s = _blank(df)
    s[quiet & (df["close"] > hh)] = 1
    s[quiet & (df["close"] < ll)] = -1
    return s


def sig_asia_fade(df: pd.DataFrame, n: int = 20, k: float = 1.5) -> pd.Series:
    """
    Reversao SO na sessao asiatica (00-06 UTC), onde o fluxo e fino e o
    preco oscila em faixa. Mesma ideia do meanrev, com janela de horario.
    """
    z = _z(df["close"], n)
    h = _hours(df)
    asia = (h >= 0) & (h < 7)
    s = _blank(df)
    s[asia & (z <= -k)] = 1
    s[asia & (z >= k)] = -1
    return s


def sig_inside_break(df: pd.DataFrame) -> pd.Series:
    """Barra interna e depois rompimento: compressao seguida de expansao."""
    inside = (df["high"] < df["high"].shift(1)) & (df["low"] > df["low"].shift(1))
    s = _blank(df)
    s[inside.shift(1).fillna(False) & (df["close"] > df["high"].shift(1))] = 1
    s[inside.shift(1).fillna(False) & (df["close"] < df["low"].shift(1))] = -1
    return s


SIGNALS: dict[str, Signal] = {
    "trend_pullback": sig_trend_pullback,
    "meanrev_z": sig_meanrev_z,
    "rsi_extreme": sig_rsi_extreme,
    "bb_fade": sig_bb_fade,
    "london_breakout": sig_london_breakout,
    "momentum": sig_momentum,
    "vol_squeeze": sig_vol_squeeze_break,
    "asia_fade": sig_asia_fade,
    "inside_break": sig_inside_break,
}


# ------------------------------------------------------------------ avaliador

@dataclass
class EvalCfg:
    atr_mult_stop: float = 1.5
    rr: float = 2.0
    max_bars: int = 48
    cost_pips: float = 1.5      # spread tipico + ~0.7 pip de comissao
    min_trades: int = 30


def eval_signal(df: pd.DataFrame, sig: pd.Series, cfg: EvalCfg | None = None,
                pip: float = 0.0001) -> np.ndarray:
    """
    R-multiplos de cada entrada. Entrada na ABERTURA de t+1; dentro da
    barra o stop ganha do alvo (pessimista); custo descontado em R.
    """
    cfg = cfg or EvalCfg()
    o = df["open"].values; hi = df["high"].values
    lo = df["low"].values; cl = df["close"].values
    atr = df["atr"].values
    s = sig.values.astype(int)
    n = len(df)
    out: list[float] = []
    for i in np.nonzero(s)[0]:
        e = i + 1
        if e >= n:
            break
        side = s[i]
        sd = cfg.atr_mult_stop * atr[i]
        if not np.isfinite(sd) or sd <= 0:
            continue
        entry = o[e]
        stop = entry - side * sd
        tgt = entry + side * sd * cfg.rr
        r = None
        end = min(e + cfg.max_bars, n)
        for j in range(e, end):
            if side > 0:
                if lo[j] <= stop:
                    r = -1.0; break
                if hi[j] >= tgt:
                    r = cfg.rr; break
            else:
                if hi[j] >= stop:
                    r = -1.0; break
                if lo[j] <= tgt:
                    r = cfg.rr; break
        if r is None:
            r = (cl[end - 1] - entry) * side / sd
        out.append(r - cfg.cost_pips * pip / sd)
    return np.array(out)


def random_like(df: pd.DataFrame, sig: pd.Series, seed: int = 0) -> pd.Series:
    """Entradas sorteadas na MESMA frequencia do sinal - o adversario a bater."""
    rng = np.random.default_rng(seed)
    rate = float((sig != 0).mean())
    draw = rng.random(len(df)) < rate
    side = rng.choice([-1, 1], size=len(df))
    return pd.Series(np.where(draw, side, 0), index=df.index, dtype=int)


def scan_pair(df: pd.DataFrame, pair: str, split: float = 0.6,
              cfg: EvalCfg | None = None) -> list[dict]:
    """Avalia todos os sinais num par, com corte treino/teste no TEMPO."""
    cfg = cfg or EvalCfg()
    pip = 0.01 if "JPY" in pair.upper() else 0.0001
    d = add_indicators(df, StratParams()).iloc[250:]
    cut = int(len(d) * split)
    tr, te = d.iloc[:cut], d.iloc[cut:]
    rows = []
    for name, fn in SIGNALS.items():
        s = fn(d)
        r_tr = eval_signal(tr, s.iloc[:cut], cfg, pip)
        r_te = eval_signal(te, s.iloc[cut:], cfg, pip)
        # baseline: media de 3 sorteios, para o acaso de um seed nao enganar
        base = [eval_signal(te, random_like(te, s.iloc[cut:], k), cfg, pip) for k in range(3)]
        base_r = float(np.mean([b.mean() for b in base if len(b)])) if any(len(b) for b in base) else np.nan
        rows.append({
            "pair": pair, "signal": name,
            "n_tr": len(r_tr), "avgR_tr": round(float(r_tr.mean()), 4) if len(r_tr) else np.nan,
            "n_te": len(r_te), "avgR_te": round(float(r_te.mean()), 4) if len(r_te) else np.nan,
            "avgR_rand": round(base_r, 4),
            "edge_te": round(float(r_te.mean()) - base_r, 4) if len(r_te) else np.nan,
        })
    return rows


def scan_all(data: dict[str, pd.DataFrame], cfg: EvalCfg | None = None) -> pd.DataFrame:
    rows: list[dict] = []
    for pair, df in sorted(data.items()):
        rows += scan_pair(df, pair, cfg=cfg)
    return pd.DataFrame(rows)
