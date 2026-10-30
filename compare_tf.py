#!/usr/bin/env python3
"""Holy Grail em H1, H4 e D1 - o setup foi publicado para grafico diario."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from math import erfc, sqrt
from holygrail.indicators import add_indicators
from holygrail.setup import HGParams, find_setups
from holygrail.evaluate import CostModel, random_control, run_setups
from holygrail.resample import resample

PARES = ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY")
# saida por tempo proporcional ao timeframe
MAXB = {"H1": 96, "H4": 48, "D1": 20}

print("  tf    setups  acerto    avgR   aleat   vantagem      t       p    somaR")
print("  " + "-" * 74)
for tf in ("H1", "H4", "D1"):
    allr, allb = [], []
    for par in PARES:
        d = pd.read_csv(f"data/h1/{par}.csv", index_col=0, parse_dates=True)
        d.index = pd.to_datetime(d.index, utc=True)
        d = add_indicators(resample(d, tf))
        if len(d) < 300:
            continue
        cm = CostModel(max_bars=MAXB[tf])
        s = find_setups(d, HGParams())
        if not s:
            continue
        allr += [o.r for o in run_setups(d, s, par, cm)]
        allb += [o.r for k in range(3) for o in random_control(d, s, par, seed=k, cm=cm)]
    if len(allr) < 20:
        print(f"  {tf:5} {len(allr):>6}  (amostra insuficiente)")
        continue
    a, b = np.array(allr), np.array(allb)
    t = a.mean() / (a.std(ddof=1) / np.sqrt(len(a)))
    print(f"  {tf:5} {len(a):>6} {100*(a>0).mean():>7.1f}% {a.mean():>+7.3f} "
          f"{b.mean():>+7.3f} {a.mean()-b.mean():>+10.3f} {t:>6.2f} {erfc(abs(t)/sqrt(2)):>7.4f} {a.sum():>+8.1f}")
