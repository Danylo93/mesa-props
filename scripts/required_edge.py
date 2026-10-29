#!/usr/bin/env python3
"""
Qual vantagem e preciso ter para aprovar na The5ers 100K?

Responder "a estrategia X nao funciona" e metade da resposta. A outra
metade e a barra a ser batida. Aqui fixamos o resto (risco 0.35%, RR 2:1,
travas do governor, regras reais da conta) e variamos SO a taxa de acerto,
rodando 20 000 caminhos de Monte Carlo em cada ponto.

Leia a tabela de baixo para cima: ache a linha onde P(aprovado) deixa de
ser constrangedor e veja que taxa de acerto ela exige. Essa e a sua meta.
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
from the5ers.montecarlo import MCConfig, simulate
from the5ers.risk import RiskLimits
from the5ers.rules import ProgramRules

RR = 2.0
COST_R = 0.07          # spread + comissao, medido no backtest
TRADES_DIA = np.array([1, 1, 2, 2, 3])   # frequencia observada

print(__doc__)
print(f"  RR fixo {RR}:1   custo embutido {COST_R} R/trade   risco 0.35%/trade\n")
print(f"  {'acerto':>7} {'avgR bruto':>11} {'avgR liq':>9} "
      f"{'P(aprova)':>10} {'P(perde)':>9} {'P(aberto)':>10} {'dias':>6}")
print("  " + "-" * 68)

for w in (0.30, 0.3333, 0.35, 0.3667, 0.38, 0.40, 0.42, 0.45, 0.50):
    bruto = w * RR - (1 - w)
    liq = bruto - COST_R
    n = 1000
    k = int(round(w * n))
    rs = np.array([RR - COST_R] * k + [-1.0 - COST_R] * (n - k))
    res = simulate(rs, TRADES_DIA, ProgramRules(), RiskLimits(),
                   MCConfig(paths=20_000, max_days=180))
    dias = res.median_days_to_pass
    print(f"  {w:>6.1%} {bruto:>11.3f} {liq:>9.3f} "
          f"{res.passed:>9.1%} {res.failed:>8.1%} {res.unresolved:>9.1%} "
          f"{(f'{dias:.0f}' if dias else '-'):>6}")

print("\n  referencia: a estrategia deste repo entrega ~22.9% de acerto a RR 2:1")
print("              (avgR liquido -0.156) -> P(aprovado) 2.2%")
