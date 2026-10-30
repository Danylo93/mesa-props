"""
Regras da conta The5ers $100K High Stakes 10% e dimensionamento.

Valores lidos da API da The5ers (the5ers_program/rules e
the5ers_consistency/list) na conta "meta-trader-5 . ...6821":

    alvo de lucro      10 000 USD
    perda diaria maxima     4 %
    perda total maxima  8 000 USD
    dias lucrativos         3 dias
    SEM regra de expiracao e SEM minimo de dias de negociacao.

Dois pontos onde a API nao expoe a base de calculo. Nos dois usamos o
lado mais apertado - errar para o frouxo custa a conta:

  1. A perda total ARRASTA pelo high-water mark de fim de dia:
         piso = max(saldo_inicial, maior_fechamento_diario) - 8 000
     Ou seja: ganhar aperta o seu piso. Nenhum dashboard mostra isso.
  2. "4 percent" sem base -> o MENOR entre 4% do saldo inicial e 4% do
     saldo de abertura do dia.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

__all__ = ["Breach", "Status", "Rules", "Account", "Limits", "size_lots",
           "pip_size", "pip_value_usd"]


class Breach(str, Enum):
    NONE = "none"
    DAILY = "daily_loss"
    TOTAL = "total_loss"

    def __bool__(self) -> bool:
        return self is not Breach.NONE


class Status(str, Enum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True)
class Rules:
    initial: float = 100_000.0
    target: float = 10_000.0
    daily_pct: float = 4.0
    total_loss: float = 8_000.0
    min_profit_days: int = 3
    trailing: bool = True

    @property
    def target_equity(self) -> float:
        return self.initial + self.target


@dataclass(frozen=True)
class Limits:
    """Travas operacionais, sempre mais apertadas que as contratuais."""
    risk_pct: float = 0.35
    daily_soft_pct: float = 1.50     # para de abrir
    daily_hard_pct: float = 2.50     # zera tudo (regra e 4%)
    max_concurrent: int = 2
    floor_buffer_pct: float = 1.00


@dataclass
class Account:
    rules: Rules = field(default_factory=Rules)
    limits: Limits = field(default_factory=Limits)

    def __post_init__(self) -> None:
        self.balance = self.rules.initial
        self.eod_hwm = self.rules.initial
        self.day_start = self.rules.initial
        self.breach = Breach.NONE
        self.day: date | None = None
        self.profit_days = 0
        self.days = 0
        self.min_equity = self.rules.initial

    # ---- pisos -------------------------------------------------------
    @property
    def total_floor(self) -> float:
        base = max(self.rules.initial, self.eod_hwm) if self.rules.trailing \
            else self.rules.initial
        return base - self.rules.total_loss

    @property
    def daily_limit(self) -> float:
        p = self.rules.daily_pct / 100.0
        return min(self.rules.initial * p, self.day_start * p)

    @property
    def daily_floor(self) -> float:
        return self.day_start - self.daily_limit

    @property
    def soft_floor(self) -> float:
        return self.day_start * (1 - self.limits.daily_soft_pct / 100.0)

    @property
    def hard_floor(self) -> float:
        return self.day_start * (1 - self.limits.daily_hard_pct / 100.0)

    @property
    def guarded_floor(self) -> float:
        return self.total_floor + self.rules.initial * self.limits.floor_buffer_pct / 100.0

    # ---- estado ------------------------------------------------------
    @property
    def target_hit(self) -> bool:
        return self.balance >= self.rules.target_equity

    @property
    def status(self) -> Status:
        if self.breach:
            return Status.FAILED
        if self.target_hit and self.profit_days >= self.rules.min_profit_days:
            return Status.PASSED
        return Status.RUNNING

    def risk_usd(self) -> float:
        r = self.balance * self.limits.risk_pct / 100.0
        room = min(self.balance - self.hard_floor, self.balance - self.guarded_floor)
        return max(0.0, min(r, room))

    def can_open(self, n_open: int) -> bool:
        return (not self.breach and not self.target_hit
                and self.balance > self.soft_floor
                and self.balance > self.guarded_floor
                and n_open < self.limits.max_concurrent)

    # ---- ciclo -------------------------------------------------------
    def open_day(self, d: date) -> None:
        self.day = d
        self.day_start = self.balance

    def mark(self, equity: float) -> Breach:
        self.min_equity = min(self.min_equity, equity)
        if self.breach:
            return self.breach
        if equity <= self.total_floor:
            self.breach = Breach.TOTAL
        elif equity <= self.daily_floor:
            self.breach = Breach.DAILY
        return self.breach

    def close_day(self) -> None:
        if self.balance > self.day_start:
            self.profit_days += 1
        self.eod_hwm = max(self.eod_hwm, self.balance)   # so sobe no fechamento
        self.days += 1


# ---- dimensionamento --------------------------------------------------

def pip_size(pair: str) -> float:
    return 0.01 if "JPY" in pair.upper() else 0.0001


def pip_value_usd(pair: str, price: float, lots: float = 1.0) -> float:
    s = pair.upper()
    base, quote = s[:3], s[3:6]
    units = 100_000.0 * lots
    p = pip_size(pair)
    if quote == "USD":
        return p * units
    if base == "USD":
        return (p / price) * units
    raise ValueError(f"par sem USD: {pair}")


def size_lots(pair: str, price: float, stop_dist: float, risk_usd: float,
              min_lots: float = 0.01, max_lots: float = 50.0) -> float:
    if stop_dist <= 0 or risk_usd <= 0:
        return 0.0
    pips = stop_dist / pip_size(pair)
    loss_1lot = pips * pip_value_usd(pair, price, 1.0)
    if loss_1lot <= 0:
        return 0.0
    lots = round(risk_usd / loss_1lot, 2)
    return 0.0 if lots < min_lots else min(lots, max_lots)
