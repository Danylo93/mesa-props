#!/usr/bin/env python3
"""
O london_breakout realmente tem vantagem, ou e o melhor de 36 sorteios?

Quando se testa 36 combinacoes e se reporta a melhor, a melhor PARECE boa
por construcao. Tres perguntas antes de acreditar:

  1. a vantagem se distingue de zero? (teste t sobre os R-multiplos)
  2. ela sobrevive a correcao por multiplos testes? (Bonferroni, 36 testes)
  3. ela aparece em varios pares, ou um par carrega tudo?

E, se passar das tres: ela e GRANDE o bastante para aprovar a mesa?
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from the5ers.research import EvalCfg, SIGNALS, eval_signal, random_like
from the5ers.strategy import StratParams, add_indicators

DATA = ROOT / "data" / "h1"
SPLIT, N_TESTES = 0.6, 36
CFG = EvalCfg(atr_mult_stop=4.0, rr=0.5)
SINAL = "london_breakout"


def _t_test(x: np.ndarray):
    """t de Student para media != 0, e p bilateral por normal (n grande)."""
    n = len(x)
    if n < 10:
        return np.nan, np.nan, np.nan
    se = x.std(ddof=1) / np.sqrt(n)
    t = x.mean() / se if se > 0 else np.nan
    from math import erfc, sqrt
    p = erfc(abs(t) / sqrt(2))
    return t, p, se


if __name__ == "__main__":
    print(__doc__)
    por_par, todos = [], []
    for f in sorted(DATA.glob("*.csv")):
        pair = f.stem
        d = pd.read_csv(f, index_col=0, parse_dates=True)
        d.index = pd.to_datetime(d.index, utc=True)
        d = add_indicators(d, StratParams()).iloc[250:]
        pip = 0.01 if "JPY" in pair.upper() else 0.0001
        cut = int(len(d) * SPLIT)
        te = d.iloc[cut:]
        s = SINAL and SIGNALS[SINAL](d).iloc[cut:]
        r = eval_signal(te, s, CFG, pip)
        b = eval_signal(te, random_like(te, s, 1), CFG, pip)
        if len(r):
            t, p, se = _t_test(r)
            por_par.append({"par": pair, "n": len(r), "avgR": round(float(r.mean()), 4),
                            "rand": round(float(b.mean()), 4) if len(b) else np.nan,
                            "t": round(t, 2), "p": round(p, 3)})
            todos.append(r)

    print(f"--- {SINAL}, stop {CFG.atr_mult_stop} ATR, alvo {CFG.rr} R, fora da amostra ---")
    print(pd.DataFrame(por_par).to_string(index=False))

    x = np.concatenate(todos)
    t, p, se = _t_test(x)
    print(f"\n--- agregado ---")
    print(f"  n              {len(x)}")
    print(f"  avg R          {x.mean():+.4f}")
    print(f"  erro padrao    {se:.4f}")
    print(f"  t              {t:.2f}")
    print(f"  p (bruto)      {p:.4f}")
    p_corr = min(1.0, p * N_TESTES)
    print(f"  p (Bonferroni, {N_TESTES} testes)  {p_corr:.4f}")
    pares_pos = sum(1 for r in por_par if r["avgR"] > 0)
    print(f"  pares positivos {pares_pos}/{len(por_par)}")

    print("\n--- veredito ---")
    sig = p_corr < 0.05
    print(f"  1. distingue de zero?            {'sim' if p < 0.05 else 'NAO'} (p={p:.3f})")
    print(f"  2. sobrevive a multiplos testes? {'sim' if sig else 'NAO'} (p={p_corr:.3f})")
    print(f"  3. consistente entre pares?      {'sim' if pares_pos >= 4 else 'NAO'} ({pares_pos}/5)")

    # 4: mesmo se fosse real, serve para a mesa?
    from the5ers.montecarlo import MCConfig, simulate
    from the5ers.risk import RiskLimits
    from the5ers.rules import ProgramRules
    tpd = np.array([1, 1, 2])
    res = simulate(x, tpd, ProgramRules(), RiskLimits(), MCConfig(paths=10_000))
    print(f"  4. aprova a mesa?                P(aprovado)={res.passed:.1%}  "
          f"P(perde)={res.failed:.1%}")
