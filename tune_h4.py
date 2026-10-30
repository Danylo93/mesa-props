#!/usr/bin/env python3
"""
Ultimo teste justo do Holy Grail em H4.

O diagnostico mostrou acerto 30.1% contra 31.4% de equilibrio - falta 1.3
ponto, e o custo vale 0.09 R por trade. Ou seja: no BRUTO o setup empata;
o pedagio derruba. Entao a pergunta certa nao e "que parametro deixa o
backtest bonito", e "existe estrutura de trade que paga o pedagio?".

Tres alavancas, todas com justificativa, nenhuma inventada:
  adx_min  quao forte a tendencia precisa estar
  min_rr   recusa setup cujo alvo nem paga N vezes o risco
  max_rr   trava alvo muito distante (alvo longe quase nunca e atingido)

DISCIPLINA: a escolha sai SO do treino (60% iniciais). O teste e olhado
UMA vez. Sao 27 combinacoes - o p do vencedor precisa ser lido com isso
em mente, e a amostra de H4 e pequena (~190 setups no total).
"""
import sys, pathlib
from itertools import product
from math import erfc, sqrt
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import numpy as np, pandas as pd

from holygrail.indicators import add_indicators
from holygrail.setup import HGParams, find_setups
from holygrail.evaluate import CostModel, random_control, run_setups
from holygrail.resample import resample

PARES = ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY")
SPLIT = 0.6
CM = CostModel(max_bars=48)

DADOS = {}
for par in PARES:
    d = pd.read_csv(f"data/h1/{par}.csv", index_col=0, parse_dates=True)
    d.index = pd.to_datetime(d.index, utc=True)
    DADOS[par] = add_indicators(resample(d, "H4"))


def medir(p: HGParams, parte: str):
    rs, bs = [], []
    for par, d in DADOS.items():
        cut = int(len(d) * SPLIT)
        seg = d.iloc[:cut] if parte == "tr" else d.iloc[cut:]
        s = find_setups(seg, p)
        if not s:
            continue
        rs += [o.r for o in run_setups(seg, s, par, CM)]
        bs += [o.r for o in random_control(seg, s, par, seed=1, cm=CM)]
    return np.array(rs), np.array(bs)


grid = list(product((25.0, 30.0, 35.0), (1.0, 1.5, 2.0), (None, 2.0, 3.0)))
print(__doc__)
print(f"  {len(grid)} combinacoes\n")
print(f"  {'adx':>5} {'minRR':>6} {'maxRR':>6} | {'n_tr':>5} {'avgR_tr':>9} {'vant_tr':>9}")
print("  " + "-" * 58)
melhor, mcfg = -9e9, None
for adx, mn, mx in grid:
    p = HGParams(adx_min=adx, min_rr=mn, max_rr=mx)
    r, b = medir(p, "tr")
    if len(r) < 40:
        continue
    v = r.mean() - b.mean()
    mark = ""
    if r.mean() > melhor:
        melhor, mcfg, mark = r.mean(), p, "  <-"
    print(f"  {adx:>5.0f} {mn:>6.1f} {str(mx):>6} | {len(r):>5} "
          f"{r.mean():>+9.3f} {v:>+9.3f}{mark}")

print(f"\n  escolhido no treino: ADX>{mcfg.adx_min:.0f}, minRR={mcfg.min_rr}, maxRR={mcfg.max_rr}")
r, b = medir(mcfg, "te")
t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if len(r) > 2 else float("nan")
pv = erfc(abs(t) / sqrt(2))
print("\n  === TESTE (fora da amostra, olhado uma vez) ===")
print(f"  setups            {len(r)}")
print(f"  acerto            {100*(r>0).mean():.1f}%")
print(f"  avg R             {r.mean():+.4f}")
print(f"  aleatorio avg R   {b.mean():+.4f}")
print(f"  vantagem          {r.mean()-b.mean():+.4f} R")
print(f"  t                 {t:.2f}    p bruto = {pv:.4f}")
print(f"  p apos Bonferroni ({len(grid)} testes) = {min(1.0, pv*len(grid)):.4f}")
print(f"  soma              {r.sum():+.1f} R")
