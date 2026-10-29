"""
Monte Carlo do desafio.

Um backtest devolve UM caminho. O desafio The5ers nao pergunta "qual o
retorno medio", pergunta "este caminho especifico chega a +10 000 antes
de furar um piso?". Essa e uma pergunta de distribuicao, nao de media.

Aqui reamostramos os trades do backtest (bootstrap de R-multiplos,
agrupados em dias com a mesma distribuicao de trades/dia observada) e
rodamos cada caminho pelo MESMO motor de regras do backtest. O numero
que sai - P(aprovado) - e a unica estatistica que decide se vale a pena
arriscar a taxa do desafio.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .risk import RiskLimits
from .rules import ProgramRules, RuleEngine, Status

__all__ = ["MCConfig", "MCResult", "simulate"]


@dataclass(frozen=True)
class MCConfig:
    paths: int = 20_000
    max_days: int = 180
    seed: int = 7


@dataclass
class MCResult:
    passed: float
    failed: float
    unresolved: float
    median_days_to_pass: float | None
    p_breach_daily: float
    p_breach_total: float
    median_final_equity: float
    p5_final_equity: float

    def as_dict(self) -> dict:
        return {
            "P(aprovado)": f"{self.passed:.1%}",
            "P(violacao)": f"{self.failed:.1%}",
            "  - diaria": f"{self.p_breach_daily:.1%}",
            "  - total": f"{self.p_breach_total:.1%}",
            "P(sem resolver)": f"{self.unresolved:.1%}",
            "dias ate aprovar (mediana)": self.median_days_to_pass,
            "equity final (mediana)": round(self.median_final_equity, 2),
            "equity final (p5)": round(self.p5_final_equity, 2),
        }


def simulate(r_multiples: np.ndarray, trades_per_day: np.ndarray,
             rules: ProgramRules | None = None, limits: RiskLimits | None = None,
             cfg: MCConfig | None = None) -> MCResult:
    """
    `r_multiples`   R de cada trade fechado no backtest (pnl / risco).
    `trades_per_day` numero de trades em cada dia que teve trade.
    """
    rules = rules or ProgramRules()
    limits = limits or RiskLimits()
    cfg = cfg or MCConfig()
    rng = np.random.default_rng(cfg.seed)

    r_multiples = np.asarray(r_multiples, dtype=float)
    trades_per_day = np.asarray(trades_per_day, dtype=int)
    if r_multiples.size == 0 or trades_per_day.size == 0:
        raise ValueError("sem trades para reamostrar")

    outcomes = np.empty(cfg.paths, dtype=object)
    days_to_pass: list[int] = []
    finals = np.empty(cfg.paths)
    breach_daily = breach_total = 0

    for i in range(cfg.paths):
        eng = RuleEngine(rules)
        day_n = 0
        while day_n < cfg.max_days and eng.status is Status.RUNNING:
            day_n += 1
            eng.open_day(None)  # type: ignore[arg-type]
            k = int(rng.choice(trades_per_day))
            day_start = eng.balance
            hard_floor = day_start - day_start * limits.daily_hard_stop_pct / 100.0
            for _ in range(k):
                if eng.target_hit:
                    break
                risk = eng.equity * limits.risk_per_trade_pct / 100.0
                progress = (eng.equity - rules.initial_balance) / rules.profit_target
                if progress * 100.0 >= limits.derisk_at_target_pct:
                    risk *= limits.derisk_factor
                pnl = float(rng.choice(r_multiples)) * risk
                eng.balance += pnl
                if eng.mark(eng.balance):
                    break
                # o governor zera o dia antes do limite contratual
                if eng.balance <= hard_floor:
                    break
            if eng.breach:
                break
            eng.close_day()
        finals[i] = eng.equity
        st = eng.status
        outcomes[i] = st
        if st is Status.PASSED:
            days_to_pass.append(day_n)
        elif st is Status.FAILED:
            from .rules import Breach
            if eng.breach is Breach.DAILY_LOSS:
                breach_daily += 1
            else:
                breach_total += 1

    n = float(cfg.paths)
    return MCResult(
        passed=sum(1 for o in outcomes if o is Status.PASSED) / n,
        failed=sum(1 for o in outcomes if o is Status.FAILED) / n,
        unresolved=sum(1 for o in outcomes if o is Status.RUNNING) / n,
        median_days_to_pass=float(np.median(days_to_pass)) if days_to_pass else None,
        p_breach_daily=breach_daily / n,
        p_breach_total=breach_total / n,
        median_final_equity=float(np.median(finals)),
        p5_final_equity=float(np.percentile(finals, 5)),
    )
