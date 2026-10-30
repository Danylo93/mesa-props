#!/usr/bin/env python3
"""
Para os sinais que bateram o sorteio: qual ESTRUTURA de trade os salva?

O custo por trade em R e  custo_pips / stop_pips. Com stop de 1.5 ATR
(~20-25 pips) e 1.5 pip de custo, isso e ~0.07 R - maior que a vantagem
medida (~0.016 R). Stop mais largo dilui o custo.

Reversao a media quer exatamente isso: stop largo (o preco pode esticar
mais antes de voltar) e alvo curto (na media). Muito acerto, R pequeno.

DISCIPLINA: a estrutura e escolhida SO no treino. O teste e olhado uma vez,
no fim, e e o numero reportado. Sem isso, escolher entre 12 estruturas x 4
sinais garante encontrar lixo que parece ouro.
"""
import sys, pathlib
from itertools import product

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from the5ers.research import EvalCfg, SIGNALS, eval_signal, random_like
from the5ers.strategy import StratParams, add_indicators

DATA = ROOT / "data" / "h1"
# bb_fade e identico a meanrev_z (mesma formula); fica so um.
CANDIDATOS = ["asia_fade", "meanrev_z", "london_breakout"]
SPLIT = 0.6


def load():
    out = {}
    for f in sorted(DATA.glob("*.csv")):
        d = pd.read_csv(f, index_col=0, parse_dates=True)
        d.index = pd.to_datetime(d.index, utc=True)
        if len(d) > 1000:
            out[f.stem] = d
    return out


def prep(data):
    out = {}
    for p, df in data.items():
        d = add_indicators(df, StratParams()).iloc[250:]
        out[p] = (d, 0.01 if "JPY" in p.upper() else 0.0001)
    return out


def measure(prepped, name, cfg, part):
    """avg R agregado nos 5 pares, mais o baseline aleatorio."""
    rs, bs, n = [], [], 0
    for p, (d, pip) in prepped.items():
        cut = int(len(d) * SPLIT)
        seg = d.iloc[:cut] if part == "tr" else d.iloc[cut:]
        s = SIGNALS[name](d)
        s = s.iloc[:cut] if part == "tr" else s.iloc[cut:]
        r = eval_signal(seg, s, cfg, pip)
        if len(r):
            rs.append(r); n += len(r)
        b = eval_signal(seg, random_like(seg, s, 1), cfg, pip)
        if len(b):
            bs.append(b)
    if not rs:
        return np.nan, np.nan, 0
    allr = np.concatenate(rs)
    allb = np.concatenate(bs) if bs else np.array([np.nan])
    return float(allr.mean()), float(np.nanmean(allb)), n


if __name__ == "__main__":
    print(__doc__)
    prepped = prep(load())
    grid = list(product([1.5, 2.5, 4.0], [0.5, 0.75, 1.0, 1.5]))
    print(f"  {len(CANDIDATOS)} sinais x {len(grid)} estruturas, "
          f"escolhidas no treino\n")

    final = []
    for name in CANDIDATOS:
        print(f"--- {name} (treino) ---")
        best, bestcfg = -9e9, None
        for atr_m, rr in grid:
            cfg = EvalCfg(atr_mult_stop=atr_m, rr=rr)
            r, b, n = measure(prepped, name, cfg, "tr")
            if n < 100:
                continue
            edge = r - b
            flag = ""
            if edge > best:
                best, bestcfg, flag = edge, cfg, "  <-"
            print(f"   stop={atr_m}ATR alvo={rr}R  n={n:>5}  "
                  f"avgR={r:>7.4f}  rand={b:>7.4f}  vant={edge:>+7.4f}{flag}")
        if bestcfg is None:
            continue
        r, b, n = measure(prepped, name, bestcfg, "te")
        final.append({"sinal": name, "stop_ATR": bestcfg.atr_mult_stop,
                      "alvo_R": bestcfg.rr, "n_teste": n,
                      "avgR_teste": round(r, 4), "rand_teste": round(b, 4),
                      "vantagem": round(r - b, 4)})
        print(f"   escolhido: stop={bestcfg.atr_mult_stop}ATR alvo={bestcfg.rr}R\n")

    print("=== TESTE (fora da amostra, olhado uma vez) ===")
    t = pd.DataFrame(final).sort_values("avgR_teste", ascending=False)
    print(t.to_string(index=False))
    pos = t[t.avgR_teste > 0]
    print(f"\n  sinais com avgR LIQUIDO positivo fora da amostra: {len(pos)} de {len(t)}")
    t.to_csv(ROOT / "reports" / "estrutura.csv", index=False)
