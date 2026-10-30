#!/usr/bin/env python3
"""
A ideia do AI Hedge Fund aplicada aqui: varios "analistas" independentes
opinam e so se opera quando ha confluencia.

Testo tres formas de combinar:
  voto2   >=2 sinais concordando no mesmo lado
  voto3   >=3 sinais concordando
  unanime todos os que opinam concordam

Expectativa honesta: combinar sinais que individualmente valem ~zero
costuma dar ~zero. Confluencia reduz o numero de trades e sobe a taxa de
acerto, mas se nenhum componente carrega informacao, a media tambem nao
carrega. Vale testar porque e barato e porque e a hipotese certa a eliminar.
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from the5ers.research import EvalCfg, SIGNALS, eval_signal, random_like
from the5ers.strategy import StratParams, add_indicators

DATA = ROOT / "data" / "h1"
SPLIT = 0.6
# bb_fade sai: e identico a meanrev_z, votaria duas vezes a mesma coisa.
MEMBROS = ["meanrev_z", "asia_fade", "rsi_extreme", "london_breakout", "vol_squeeze"]


def ensemble(d: pd.DataFrame, k: int) -> pd.Series:
    votos = sum(SIGNALS[m](d) for m in MEMBROS)
    s = pd.Series(0, index=d.index, dtype=int)
    s[votos >= k] = 1
    s[votos <= -k] = -1
    return s


def _t(x):
    n = len(x)
    if n < 10:
        return np.nan, np.nan
    se = x.std(ddof=1) / np.sqrt(n)
    t = x.mean() / se if se > 0 else np.nan
    from math import erfc, sqrt
    return t, erfc(abs(t) / sqrt(2))


if __name__ == "__main__":
    print(__doc__)
    pares = {}
    for f in sorted(DATA.glob("*.csv")):
        d = pd.read_csv(f, index_col=0, parse_dates=True)
        d.index = pd.to_datetime(d.index, utc=True)
        pares[f.stem] = (add_indicators(d, StratParams()).iloc[250:],
                         0.01 if "JPY" in f.stem.upper() else 0.0001)

    print(f"  membros: {', '.join(MEMBROS)}\n")
    print(f"  {'combinacao':10} {'estrutura':16} {'n':>6} {'avgR':>9} {'rand':>9} "
          f"{'vant':>9} {'t':>6} {'p':>7}")
    print("  " + "-" * 76)
    linhas = []
    for k, nome in ((2, "voto2"), (3, "voto3")):
        for atr_m, rr in ((1.5, 0.5), (2.5, 0.5), (4.0, 0.5), (1.5, 1.0)):
            cfg = EvalCfg(atr_mult_stop=atr_m, rr=rr)
            rs, bs = [], []
            for p, (d, pip) in pares.items():
                cut = int(len(d) * SPLIT)
                te = d.iloc[cut:]
                s = ensemble(d, k).iloc[cut:]
                r = eval_signal(te, s, cfg, pip)
                b = eval_signal(te, random_like(te, s, 1), cfg, pip)
                if len(r): rs.append(r)
                if len(b): bs.append(b)
            if not rs:
                continue
            x = np.concatenate(rs); bb = np.concatenate(bs) if bs else np.array([np.nan])
            t, pv = _t(x)
            print(f"  {nome:10} stop{atr_m}ATR alvo{rr}R {len(x):>6} {x.mean():>+9.4f} "
                  f"{np.nanmean(bb):>+9.4f} {x.mean()-np.nanmean(bb):>+9.4f} "
                  f"{t:>6.2f} {pv:>7.3f}")
            linhas.append({"comb": nome, "stop": atr_m, "alvo": rr, "n": len(x),
                           "avgR": round(float(x.mean()), 4), "t": round(t, 2),
                           "p": round(pv, 3)})

    df = pd.DataFrame(linhas)
    pos = df[(df.avgR > 0) & (df.p < 0.05)]
    print(f"\n  combinacoes com avgR>0 E p<0.05: {len(pos)} de {len(df)}")
    if len(pos):
        print(pos.to_string(index=False))
    else:
        print("  nenhuma. Confluencia nao cria informacao que os componentes nao tem.")
    df.to_csv(ROOT / "reports" / "ensemble.csv", index=False)
