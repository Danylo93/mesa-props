#!/usr/bin/env python3
"""
Quanta amostra faltou? (analise de poder)

O H4 ajustado deu +0.12 R fora da amostra em 53 trades. O numero e
positivo mas nao se distingue de zero. Isso NAO quer dizer "nao funciona"
- quer dizer "este teste nao consegue decidir". Sao coisas diferentes, e
confundi-las e como se perde dinheiro nos dois sentidos.

Aqui calculo quantos trades seriam precisos para detectar essa vantagem,
e quanto tempo de dado isso representa.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from holygrail.indicators import add_indicators
from holygrail.setup import HGParams, find_setups
from holygrail.evaluate import CostModel, run_setups
from holygrail.resample import resample

PARES = ("EURUSD","GBPUSD","AUDUSD","NZDUSD","USDJPY")
CM = CostModel(max_bars=48)
P = HGParams(adx_min=30.0, min_rr=2.0, max_rr=2.0)

rs, meses = [], 0
for par in PARES:
    d = pd.read_csv(f"data/h1/{par}.csv", index_col=0, parse_dates=True)
    d.index = pd.to_datetime(d.index, utc=True)
    d = add_indicators(resample(d, "H4"))
    meses = max(meses, (d.index[-1] - d.index[0]).days / 30.44)
    rs += [o.r for o in run_setups(d, find_setups(d, P), par, CM)]

r = np.array(rs)
n, mu, sd = len(r), r.mean(), r.std(ddof=1)
print(__doc__)
print(f"  dados          {meses:.0f} meses, {len(PARES)} pares, H4")
print(f"  setups totais  {n}  ({n/meses*12:.0f} por ano)")
print(f"  avg R          {mu:+.4f}")
print(f"  desvio         {sd:.3f}")
print(f"  erro padrao    {sd/np.sqrt(n):.4f}")
print(f"  t              {mu/(sd/np.sqrt(n)):.2f}")

print("\n  n necessario para detectar a vantagem (95% conf., 80% poder):")
for alvo in (0.05, 0.10, 0.1199, 0.20, 0.30):
    need = ((1.96 + 0.84) * sd / alvo) ** 2
    anos = need / (n / meses * 12)
    print(f"    vantagem de {alvo:+.3f} R -> {need:>6.0f} trades = {anos:>5.1f} anos de dado")

print(f"\n  Tenho {meses:.0f} meses. Para decidir sobre +0.12 R faltam "
      f"~{((1.96+0.84)*sd/0.1199)**2/(n/meses*12) - meses/12:.1f} anos de dado.")
