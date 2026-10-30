#!/usr/bin/env python3
"""
Varre as hipoteses de sinal e mostra quais sobrevivem.

Regra de sobrevivencia (todas, nao alguma):
  * vantagem positiva FORA da amostra (avgR_te > avgR_rand)
  * positiva em pelo menos 3 dos 5 pares - vantagem real nao e de um par so
  * amostra >= 30 trades fora da amostra

Nada disso prova vantagem. Testar 9 hipoteses em 5 pares sao 45 testes;
com 45 testes algo PARECE bom por acaso. Por isso o relatorio imprime a
contagem - quem le precisa descontar isso.
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd
from the5ers.research import EvalCfg, SIGNALS, scan_all

pd.set_option("display.width", 200)
DATA = ROOT / "data" / "h1"


def load():
    out = {}
    for f in sorted(DATA.glob("*.csv")):
        d = pd.read_csv(f, index_col=0, parse_dates=True)
        d.index = pd.to_datetime(d.index, utc=True)
        if len(d) > 1000:
            out[f.stem] = d
    return out


if __name__ == "__main__":
    data = load()
    print(f"{len(data)} pares | {len(SIGNALS)} sinais | "
          f"{len(data)*len(SIGNALS)} testes no total\n")
    df = scan_all(data, EvalCfg())

    agg = (df.groupby("signal")
             .agg(n_te=("n_te", "sum"),
                  avgR_te=("avgR_te", "mean"),
                  avgR_rand=("avgR_rand", "mean"),
                  edge=("edge_te", "mean"),
                  pares_pos=("edge_te", lambda x: int((x > 0).sum())))
             .sort_values("edge", ascending=False))
    print("=== fora da amostra, media dos 5 pares ===")
    print(agg.round(4).to_string())

    ok = agg[(agg.edge > 0) & (agg.pares_pos >= 3) & (agg.n_te >= 150)]
    print(f"\n=== sobreviventes: {len(ok)} de {len(SIGNALS)} ===")
    if len(ok):
        print(ok.round(4).to_string())
    else:
        print("nenhum sinal bateu o sorteio de forma consistente.")

    df.to_csv(ROOT / "reports" / "scan_sinais.csv", index=False)
    print(f"\ndetalhe por par -> reports/scan_sinais.csv")
