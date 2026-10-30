"""
Avaliacao dos setups: vira R-multiplo, com custo e premissas pessimistas.

Premissas, todas contra o resultado:
  * entrada no preco do GATILHO mais slippage (e ordem parada: em
    rompimento ela escorrega, nunca a favor);
  * dentro da barra, STOP ganha do alvo - dados H1 nao dizem a ordem;
  * spread cobrado na entrada e na saida, mais comissao por lote;
  * saida por tempo no fechamento, se nada resolveu.

O controle aleatorio usa a MESMA quantidade de trades, o MESMO lado e a
MESMA distancia de stop/alvo, sorteando so a barra de entrada. E o
adversario certo: se o setup nao bate isso, o que ele tem e estrutura de
trade, nao vantagem preditiva.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .setup import Setup

__all__ = ["CostModel", "Outcome", "run_setups", "random_control"]

SPREAD_PIPS = {"EURUSD": 0.8, "GBPUSD": 1.2, "AUDUSD": 1.0,
               "NZDUSD": 1.6, "USDJPY": 0.9, "USDCHF": 1.3, "USDCAD": 1.4}


def pip_size(pair: str) -> float:
    return 0.01 if "JPY" in pair.upper() else 0.0001


@dataclass(frozen=True)
class CostModel:
    commission_pips: float = 0.7   # ~7 USD/lote ida e volta = 0.7 pip
    slippage_pips: float = 0.3     # ordem parada escorrega
    max_bars: int = 96             # saida por tempo

    def cost_pips(self, pair: str) -> float:
        return SPREAD_PIPS.get(pair, 1.3) + self.commission_pips


@dataclass
class Outcome:
    r: float
    reason: str
    bars: int
    i_entry: int = -1      # barra da entrada, para simulacao de carteira
    i_exit: int = -1       # barra da saida
    risk_price: float = 0.0   # distancia do stop em PRECO
    entry_px: float = 0.0
    side: int = 0


def run_setups(df: pd.DataFrame, setups: list[Setup], pair: str,
               cm: CostModel | None = None) -> list[Outcome]:
    cm = cm or CostModel()
    hi, lo, cl = df["high"].values, df["low"].values, df["close"].values
    n = len(df)
    pip = pip_size(pair)
    cost = cm.cost_pips(pair) * pip
    slip = cm.slippage_pips * pip

    out: list[Outcome] = []
    for s in setups:
        side = s.side
        entry = s.entry + side * slip        # escorrega contra
        risk = abs(entry - s.stop)
        if risk <= 0:
            continue
        r_val, why, bars = None, "tempo", 0
        end = min(s.i_entry + cm.max_bars, n)
        j_exit = end - 1
        for j in range(s.i_entry, end):
            bars = j - s.i_entry + 1
            j_exit = j
            if side > 0:
                if lo[j] <= s.stop:
                    r_val, why = -(1.0), "stop"; break
                if hi[j] >= s.target:
                    r_val, why = abs(s.target - entry) / risk, "alvo"; break
            else:
                if hi[j] >= s.stop:
                    r_val, why = -(1.0), "stop"; break
                if lo[j] <= s.target:
                    r_val, why = abs(s.target - entry) / risk, "alvo"; break
        if r_val is None:
            r_val = (cl[end - 1] - entry) * side / risk
            j_exit = end - 1
        out.append(Outcome(r=r_val - cost / risk, reason=why, bars=bars,
                           i_entry=s.i_entry, i_exit=j_exit,
                           risk_price=risk, entry_px=entry, side=side))
    return out


def random_control(df: pd.DataFrame, setups: list[Setup], pair: str,
                   seed: int = 0, cm: CostModel | None = None) -> list[Outcome]:
    """Mesmos lados e mesmas distancias; so a barra de entrada e sorteada."""
    rng = np.random.default_rng(seed)
    n = len(df)
    op = df["open"].values
    fake: list[Setup] = []
    lo_bound = 250
    for s in setups:
        i = int(rng.integers(lo_bound, max(lo_bound + 1, n - 2)))
        entry = float(op[i])
        risk = abs(s.entry - s.stop)
        rew = abs(s.target - s.entry)
        fake.append(Setup(i_entry=i, side=s.side, entry=entry,
                          stop=entry - s.side * risk,
                          target=entry + s.side * rew, i_armed=i))
    return run_setups(df, fake, pair, cm)
