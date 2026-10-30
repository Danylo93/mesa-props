#!/usr/bin/env python3
"""
Quanto tempo levaria para aprovar? (Monte Carlo)

Um backtest da UM caminho. "Quanto tempo leva" e pergunta de
distribuicao: a mesma estrategia aprova em 4 meses num caminho, quebra no
segundo mes em outro e fica andando de lado no terceiro.

Reamostra os R-multiplos medidos do Holy Grail em H4 e roda cada caminho
pelas regras reais da conta - alvo 10 000, perda diaria 4%, perda total
8 000 ARRASTANDO pelo fechamento, 3 dias lucrativos.

Tres desfechos, nao dois:
  APROVOU   bateu os 10 000 com 3 dias lucrativos
  QUEBROU   violou uma regra
  TRANCOU   nao violou, mas o piso que arrasta + a folga do governor
            deixaram a conta sem espaco para arriscar. Na pratica acabou.
"""
from __future__ import annotations

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import numpy as np

from holygrail.setup import HGParams
from holygrail.the5ers import Account, Breach, Limits, Rules, Status, size_lots
import simulate as S

TRADES_ANO = 73          # medido: 102 trades em 1.4 anos, 5 pares, H4
DIAS_ANO = 252


def amostra_R(tuned: bool = True) -> np.ndarray:
    p = HGParams(adx_min=30.0, min_rr=2.0, max_rr=2.0) if tuned else HGParams()
    return np.array([t["r"] for t in S.build_trades(p)])


def um_caminho(rs: np.ndarray, limits: Limits, rng, max_dias: int) -> tuple[str, int]:
    acc = Account(Rules(), limits)
    p_trade = TRADES_ANO / DIAS_ANO          # prob. de ter trade no dia
    for dia in range(1, max_dias + 1):
        acc.day_start = acc.balance
        n = rng.poisson(p_trade)
        for _ in range(int(n)):
            if acc.target_hit or acc.breach:
                break
            if acc.balance <= acc.guarded_floor:
                return "TRANCOU", dia
            risk = acc.risk_usd()
            if risk <= 0:
                return "TRANCOU", dia
            acc.balance += float(rng.choice(rs)) * risk
            if acc.mark(acc.balance):
                return "QUEBROU", dia
            if acc.balance <= acc.hard_floor:
                break                         # trava dura do dia
        acc.close_day()
        if acc.status is Status.PASSED:
            return "APROVOU", dia
    return "SEM RESOLVER", max_dias


def rodar(rs: np.ndarray, risco: float, caminhos: int = 20_000,
          anos: int = 5, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    lim = Limits(risk_pct=risco)
    max_dias = anos * DIAS_ANO
    cont, dias_ok = {}, []
    for _ in range(caminhos):
        res, d = um_caminho(rs, lim, rng, max_dias)
        cont[res] = cont.get(res, 0) + 1
        if res == "APROVOU":
            dias_ok.append(d)
    n = float(caminhos)
    return {
        "aprovou": cont.get("APROVOU", 0) / n,
        "quebrou": cont.get("QUEBROU", 0) / n,
        "trancou": cont.get("TRANCOU", 0) / n,
        "aberto": cont.get("SEM RESOLVER", 0) / n,
        "mediana_dias": float(np.median(dias_ok)) if dias_ok else None,
        "p25": float(np.percentile(dias_ok, 25)) if dias_ok else None,
        "p75": float(np.percentile(dias_ok, 75)) if dias_ok else None,
    }


def sensibilidade(rs: np.ndarray, risco: float = 0.5, caminhos: int = 8000):
    """
    E SE a vantagem existisse? Desloca a distribuicao medida para varias
    medias e refaz o Monte Carlo. Mesma frequencia, mesma variancia, mesmas
    regras - muda so a vantagem por trade.
    """
    print(f"  === e se houvesse vantagem? (risco {risco}%/trade) ===")
    print(f"  {'avgR':>8} {'aprovou':>9} {'trancou':>9} {'quebrou':>9} | "
          f"{'mediana':>11} {'p25-p75':>15}")
    print("  " + "-" * 70)
    base = rs - rs.mean()           # centraliza, depois injeta a media
    for alvo in (0.0, 0.05, 0.10, 0.15, 0.20, 0.30):
        r = rodar(base + alvo, risco, caminhos=caminhos)
        med = f"{r['mediana_dias']/21:.1f} meses" if r["mediana_dias"] else "-"
        faixa = f"{r['p25']/21:.0f}-{r['p75']/21:.0f} meses" if r["p25"] else "-"
        print(f"  {alvo:>+8.2f} {r['aprovou']:>8.1%} {r['trancou']:>9.1%} "
              f"{r['quebrou']:>9.1%} | {med:>11} {faixa:>15}")


if __name__ == "__main__":
    print(__doc__)
    for nome, tuned in (("DO LIVRO", False), ("AJUSTADA", True)):
        rs = amostra_R(tuned)
        print(f"  === config {nome} === (avg R medido {rs.mean():+.4f}, n={len(rs)})")
        print(f"  {'risco':>6} {'aprovou':>9} {'quebrou':>9} {'trancou':>9} "
              f"{'aberto':>8} | {'mediana':>9} {'p25-p75':>14}")
        print("  " + "-" * 74)
        for risco in (0.25, 0.35, 0.50, 1.00):
            r = rodar(rs, risco, caminhos=8000)
            med = f"{r['mediana_dias']/21:.1f} meses" if r["mediana_dias"] else "-"
            faixa = (f"{r['p25']/21:.0f}-{r['p75']/21:.0f} meses"
                     if r["p25"] else "-")
            print(f"  {risco:>5.2f}% {r['aprovou']:>8.1%} {r['quebrou']:>9.1%} "
                  f"{r['trancou']:>9.1%} {r['aberto']:>8.1%} | {med:>9} {faixa:>14}")
        print()
    sensibilidade(amostra_R(True))


