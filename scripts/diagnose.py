#!/usr/bin/env python3
"""
Diagnostico: a estrategia perde por falta de vantagem ou por BUG?

Tres rodadas sobre os mesmos dados, mesmos stops, mesmos custos:

  normal     o sinal como projetado
  invertido  o mesmo sinal com o lado trocado
  aleatorio  entradas sorteadas na mesma frequencia

Como ler:
  * invertido MUITO positivo  -> o sinal esta com o lado trocado (BUG)
  * normal ~= aleatorio       -> o sinal nao carrega informacao nenhuma
  * normal < aleatorio        -> o sinal e pior que sorteio (informacao negativa)
  * aleatorio ~= -custos      -> o motor de custos esta coerente
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from the5ers import strategy as S
from the5ers.backtest import BacktestConfig, run_backtest
from the5ers.risk import RiskLimits
from the5ers.rules import ProgramRules

DATA = ROOT / "data" / "h1"
_orig = S.generate_signals


def load():
    out = {}
    for f in sorted(DATA.glob("*.csv")):
        d = pd.read_csv(f, index_col=0, parse_dates=True)
        d.index = pd.to_datetime(d.index, utc=True)
        if len(d) > 400:
            out[f.stem] = d
    return out


def run(label: str, patch) -> dict:
    import the5ers.backtest as BT
    S.generate_signals = patch
    BT.generate_signals = patch
    try:
        st = run_backtest(load(), S.StratParams(), RiskLimits(),
                          ProgramRules(), BacktestConfig()).stats()
    finally:
        S.generate_signals = _orig
        BT.generate_signals = _orig
    print(f"  {label:11} trades={st['trades']:>4}  win={st['win_rate']:>5.1f}%  "
          f"avgR={st['avg_R']:>7.3f}  lucro={st['profit']:>9.2f}  pf={st['profit_factor']}")
    return st


if __name__ == "__main__":
    print(__doc__)
    base = run("normal", _orig)

    run("invertido", lambda df, p=None: -_orig(df, p or S.DEFAULT))

    # aleatorio: mesma taxa de sinais do original, lado sorteado
    def rnd(df, p=None):
        p = p or S.DEFAULT
        s = _orig(df, p)
        rate = max(1e-6, float((s != 0).mean()))
        rng = np.random.default_rng(42)
        draw = rng.random(len(df)) < rate
        side = rng.choice([-1, 1], size=len(df))
        return pd.Series(np.where(draw, side, 0), index=df.index, dtype=int)

    rs = [run(f"aleatorio{i}", lambda df, p=None, i=i: rnd(df, p)) for i in range(1)]

    print("\nleitura:")
    print(f"  custo embutido por trade ~ spread/2 x2 + comissao")
    print(f"  normal avgR    = {base['avg_R']}")
    print(f"  aleatorio avgR = {rs[0]['avg_R']}")
    d = base["avg_R"] - rs[0]["avg_R"]
    print(f"  diferenca      = {d:+.3f} R  ->", 
          "sinal agrega" if d > 0.03 else ("sinal NAO agrega" if abs(d) <= 0.03 else "sinal PIOR que sorteio"))
