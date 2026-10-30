#!/usr/bin/env python3
"""Roda o Holy Grail nos majors e compara com o controle aleatorio."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from holygrail.indicators import add_indicators
from holygrail.setup import HGParams, find_setups
from holygrail.evaluate import CostModel, random_control, run_setups

DATA = pathlib.Path("data/h1")


def load(pair):
    d = pd.read_csv(DATA / f"{pair}.csv", index_col=0, parse_dates=True)
    d.index = pd.to_datetime(d.index, utc=True)
    return add_indicators(d)


def stats(outs):
    if not outs:
        return None
    r = np.array([o.r for o in outs])
    w = r > 0
    return {"n": len(r), "win%": round(100 * w.mean(), 1),
            "avgR": round(float(r.mean()), 4),
            "soma_R": round(float(r.sum()), 1),
            "t": round(float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))), 2) if len(r) > 2 else np.nan}


if __name__ == "__main__":
    p = HGParams()
    print(f"Holy Grail: ADX({p.adx_len})>{p.adx_min}, EMA({p.ema_len}), "
          f"espera {p.max_wait} barras, alvo no topo/fundo de {p.swing_lookback}\n")
    print(f"  {'par':8} {'n':>4} {'win%':>6} {'avgR':>8} {'somaR':>8} {'t':>6}   "
          f"| {'ALEATORIO avgR':>14}")
    print("  " + "-" * 72)
    allr, allrand = [], []
    for pair in ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY"):
        d = load(pair)
        s = find_setups(d, p)
        o = run_setups(d, s, pair)
        rc = [x for k in range(3) for x in random_control(d, s, pair, seed=k)]
        st, sr = stats(o), stats(rc)
        if not st:
            continue
        allr += [x.r for x in o]; allrand += [x.r for x in rc]
        print(f"  {pair:8} {st['n']:>4} {st['win%']:>6} {st['avgR']:>8} "
              f"{st['soma_R']:>8} {st['t']:>6}   | {sr['avgR']:>14}")

    a, b = np.array(allr), np.array(allrand)
    t = a.mean() / (a.std(ddof=1) / np.sqrt(len(a)))
    from math import erfc, sqrt
    print("\n  === agregado ===")
    print(f"  setups          {len(a)}")
    print(f"  acerto          {100*(a>0).mean():.1f}%")
    print(f"  avg R           {a.mean():+.4f}")
    print(f"  aleatorio avg R {b.mean():+.4f}")
    print(f"  vantagem        {a.mean()-b.mean():+.4f} R")
    print(f"  t               {t:.2f}   p={erfc(abs(t)/sqrt(2)):.4f}")
    print(f"  soma            {a.sum():+.1f} R")
