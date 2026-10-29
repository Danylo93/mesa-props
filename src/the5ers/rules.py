"""
Motor de regras The5ers - "$100K High Stakes 10%".

As regras aqui vem da API da The5ers (the5ers_program/rules), nao de memoria:

    profit_target   10 000 USD   (unit: currency)
    max_daily_loss  4 %          (unit: percent)
    max_total_loss   8 000 USD   (unit: currency)
    profitable_days  3 dias      (regra de consistencia)

Dois pontos onde a API NAO expoe a base de calculo. Nos dois assumimos o
lado mais restritivo, porque errar para o lado apertado custa lucro e errar
para o lado largo custa a conta:

1. `max_total_loss` arrasta a partir do high-water mark de FIM DE DIA.
   Piso = max(saldo_inicial, maior_saldo_de_fechamento) - 8 000.
   A leitura estatica (sempre 92 000) e mais frouxa; nao usamos.

2. `max_daily_loss` e "4 percent" sem base. Aplicamos o MENOR entre
   4 % do saldo inicial e 4 % do saldo de abertura do dia.

Este modulo nao fala com a corretora e nao depende de nada externo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

__all__ = ["Breach", "Status", "ProgramRules", "DayRecord", "RuleEngine", "THE5ERS_100K_HIGH_STAKES"]


class Breach(str, Enum):
    """Violacao que encerra a conta."""

    NONE = "none"
    DAILY_LOSS = "daily_loss"
    TOTAL_LOSS = "total_loss"

    def __bool__(self) -> bool:  # `if breach:` le como "houve violacao"
        return self is not Breach.NONE


class Status(str, Enum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True)
class ProgramRules:
    """Limiares contratuais. Valores, nunca o quanto ja foi gasto deles."""

    name: str = "$100K High Stakes 10%"
    initial_balance: float = 100_000.0
    profit_target: float = 10_000.0          # USD
    max_daily_loss_pct: float = 4.0          # percent
    max_total_loss: float = 8_000.0          # USD
    min_profitable_days: int = 3
    profitable_day_min_profit: float = 0.0
    trailing_total_loss: bool = True

    @property
    def target_equity(self) -> float:
        return self.initial_balance + self.profit_target


THE5ERS_100K_HIGH_STAKES = ProgramRules()


@dataclass
class DayRecord:
    day: date
    start_balance: float
    end_balance: float

    @property
    def pnl(self) -> float:
        return self.end_balance - self.start_balance


@dataclass
class RuleEngine:
    """
    Acompanha uma conta contra as regras do programa.

    Uso:
        eng = RuleEngine(THE5ERS_100K_HIGH_STAKES)
        eng.open_day(dia, saldo)
        breach = eng.mark(equity_corrente)   # a cada tick/barra
        eng.close_day(saldo_final)
    """

    rules: ProgramRules = field(default_factory=ProgramRules)
    balance: float = field(init=False)
    equity: float = field(init=False)
    eod_high_water: float = field(init=False)
    day_start_balance: float = field(init=False)
    current_day: Optional[date] = field(default=None, init=False)
    days: list[DayRecord] = field(default_factory=list, init=False)
    breach: Breach = field(default=Breach.NONE, init=False)
    min_equity_seen: float = field(init=False)

    def __post_init__(self) -> None:
        b = self.rules.initial_balance
        self.balance = b
        self.equity = b
        self.eod_high_water = b
        self.day_start_balance = b
        self.min_equity_seen = b

    # ----------------------------------------------------------- pisos

    @property
    def total_loss_floor(self) -> float:
        """Equity abaixo disto = conta perdida (regra de perda total)."""
        base = max(self.rules.initial_balance, self.eod_high_water) \
            if self.rules.trailing_total_loss else self.rules.initial_balance
        return base - self.rules.max_total_loss

    @property
    def daily_loss_limit(self) -> float:
        """Quanto se pode perder HOJE, em USD. O menor dos dois 4 %."""
        pct = self.rules.max_daily_loss_pct / 100.0
        return min(self.rules.initial_balance * pct, self.day_start_balance * pct)

    @property
    def daily_loss_floor(self) -> float:
        """Equity abaixo disto = conta perdida (regra de perda diaria)."""
        return self.day_start_balance - self.daily_loss_limit

    @property
    def hard_floor(self) -> float:
        """O piso que realmente morde agora: o mais alto dos dois."""
        return max(self.total_loss_floor, self.daily_loss_floor)

    # --------------------------------------------------------- consistencia

    @property
    def profitable_days(self) -> int:
        return sum(1 for d in self.days if d.pnl > self.rules.profitable_day_min_profit)

    @property
    def profit(self) -> float:
        return self.equity - self.rules.initial_balance

    @property
    def target_hit(self) -> bool:
        return self.equity >= self.rules.target_equity

    @property
    def status(self) -> Status:
        if self.breach:
            return Status.FAILED
        if self.target_hit and self.profitable_days >= self.rules.min_profitable_days:
            return Status.PASSED
        return Status.RUNNING

    # ------------------------------------------------------------ ciclo

    def open_day(self, day: date, balance: Optional[float] = None) -> None:
        if balance is not None:
            self.balance = balance
        self.day_start_balance = self.balance
        self.current_day = day

    def mark(self, equity: float) -> Breach:
        """Marca a equity corrente. Deve ser chamado no pior ponto da barra."""
        self.equity = equity
        self.min_equity_seen = min(self.min_equity_seen, equity)
        if self.breach:
            return self.breach
        # Perda total e verificada primeiro: e a que mata a conta de vez.
        if equity <= self.total_loss_floor:
            self.breach = Breach.TOTAL_LOSS
        elif equity <= self.daily_loss_floor:
            self.breach = Breach.DAILY_LOSS
        return self.breach

    def close_day(self, balance: Optional[float] = None) -> DayRecord:
        if balance is not None:
            self.balance = balance
        self.equity = self.balance
        rec = DayRecord(
            day=self.current_day or date.min,
            start_balance=self.day_start_balance,
            end_balance=self.balance,
        )
        self.days.append(rec)
        # O HWM so sobe no fechamento do dia - e dai que o piso arrasta.
        self.eod_high_water = max(self.eod_high_water, self.balance)
        return rec

    # ------------------------------------------------------------ relato

    def snapshot(self) -> dict:
        return {
            "status": self.status.value,
            "breach": self.breach.value,
            "equity": round(self.equity, 2),
            "profit": round(self.profit, 2),
            "target_equity": self.rules.target_equity,
            "total_loss_floor": round(self.total_loss_floor, 2),
            "daily_loss_floor": round(self.daily_loss_floor, 2),
            "daily_loss_limit": round(self.daily_loss_limit, 2),
            "eod_high_water": round(self.eod_high_water, 2),
            "profitable_days": self.profitable_days,
            "min_profitable_days": self.rules.min_profitable_days,
            "days_traded": len(self.days),
            "min_equity_seen": round(self.min_equity_seen, 2),
        }
