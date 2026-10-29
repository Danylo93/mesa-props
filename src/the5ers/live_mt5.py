"""
Guarda-regras para a conta real no MetaTrader 5.

Nenhum dos oito repos da lista fala com MT5 - nem o NautilusTrader, que
e o melhor deles para pesquisa. Entao a execucao na conta The5ers passa
por aqui: um watchdog que le a conta pelo pacote oficial `MetaTrader5`,
calcula os MESMOS pisos de rules.py e fecha tudo antes de furar um.

    pip install MetaTrader5        # so funciona em Windows
    python -m the5ers.live_mt5 --watch

IMPORTANTE - o que isto e e o que nao e:
  * E uma rede de seguranca que FECHA posicoes e BLOQUEIA novas.
  * NAO abre posicoes sozinho. A decisao de entrar continua sendo sua
    (ou de um EA que voce rode), e isso e de proposito.
  * Os pisos sao os da LEITURA CONSERVADORA (ver config/the5ers_100k.yaml).
    O numero oficial e o do Hub da The5ers; este aqui e sempre igual ou
    mais apertado, nunca mais frouxo.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from .risk import RiskGovernor, RiskLimits
from .rules import ProgramRules, RuleEngine

__all__ = ["MT5Guard", "main"]


def _mt5():
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError as e:
        raise SystemExit(
            "pacote MetaTrader5 nao instalado (ou voce nao esta no Windows).\n"
            "  pip install MetaTrader5"
        ) from e
    return mt5


@dataclass
class MT5Guard:
    rules: ProgramRules
    limits: RiskLimits
    rollover_utc_hour: int = 21
    dry_run: bool = True

    def __post_init__(self) -> None:
        self.engine = RuleEngine(self.rules)
        self.gov = RiskGovernor(self.engine, self.limits)
        self._day = None

    # ------------------------------------------------------------ conexao

    def connect(self) -> None:
        mt5 = _mt5()
        if not mt5.initialize():
            raise SystemExit(f"MT5 initialize falhou: {mt5.last_error()}")
        info = mt5.account_info()
        if info is None:
            raise SystemExit("sem account_info - o terminal esta logado?")
        print(f"conectado: {info.server} | moeda {info.currency} | "
              f"saldo {info.balance:,.2f}")
        self.engine.balance = float(info.balance)
        self._roll(float(info.balance))

    def _broker_day(self):
        ts = datetime.now(timezone.utc)
        h = (ts.hour + (24 - self.rollover_utc_hour)) % 24
        d = ts.date()
        if ts.hour >= self.rollover_utc_hour:
            from datetime import timedelta
            d = (ts + timedelta(days=1)).date()
        return d

    def _roll(self, balance: float) -> None:
        day = self._broker_day()
        if self._day != day:
            if self._day is not None:
                self.engine.close_day(balance)
            self._day = day
            self.engine.open_day(day, balance)
            self.gov.on_day_open()
            print(f"  novo dia {day}: piso diario {self.engine.daily_loss_floor:,.2f} | "
                  f"piso total {self.engine.total_loss_floor:,.2f}")

    # ------------------------------------------------------------ acao

    def flatten(self) -> None:
        mt5 = _mt5()
        positions = mt5.positions_get() or []
        if not positions:
            return
        print(f"  !! fechando {len(positions)} posicoes")
        if self.dry_run:
            print("     (dry-run: nada foi enviado)")
            return
        for p in positions:
            tick = mt5.symbol_info_tick(p.symbol)
            if tick is None:
                continue
            is_buy = p.type == mt5.ORDER_TYPE_BUY
            req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": p.symbol,
                "volume": p.volume,
                "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                "position": p.ticket,
                "price": tick.bid if is_buy else tick.ask,
                "deviation": 20,
                "comment": "the5ers-guard",
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            r = mt5.order_send(req)
            print(f"     {p.symbol} {p.volume} -> retcode={getattr(r,'retcode','?')}")

    # ------------------------------------------------------------ loop

    def poll(self) -> dict:
        mt5 = _mt5()
        info = mt5.account_info()
        if info is None:
            return {"erro": "sem account_info"}
        equity, balance = float(info.equity), float(info.balance)
        self._roll(balance)
        self.engine.balance = balance

        breach = self.engine.mark(equity)
        snap = self.engine.snapshot()
        snap["equity_mt5"] = equity

        if breach:
            print(f"  VIOLACAO JA OCORRIDA: {breach.value}. Fechando tudo.")
            self.flatten()
        elif self.gov.must_flatten(equity):
            print(f"  trava dura: equity {equity:,.2f} <= "
                  f"{max(self.gov.daily_hard_floor, self.gov.guarded_total_floor):,.2f}")
            self.flatten()
            self.gov.flattened_today = True
        return snap

    def watch(self, every: float = 5.0) -> None:
        print(f"vigiando a cada {every}s (Ctrl-C para sair)"
              f"{'  [DRY-RUN]' if self.dry_run else '  [ARMADO]'}")
        while True:
            s = self.poll()
            print(f"  {datetime.now():%H:%M:%S} equity={s.get('equity_mt5',0):,.2f} "
                  f"piso_dia={s.get('daily_loss_floor',0):,.2f} "
                  f"piso_total={s.get('total_loss_floor',0):,.2f} "
                  f"lucro={s.get('profit',0):,.2f} dias_lucro={s.get('profitable_days',0)}",
                  flush=True)
            if s.get("breach") not in (None, "none"):
                print("  encerrado.")
                return
            time.sleep(every)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Guarda-regras The5ers para MT5")
    ap.add_argument("--watch", action="store_true", help="loop continuo")
    ap.add_argument("--every", type=float, default=5.0)
    ap.add_argument("--arm", action="store_true",
                    help="ARMA o fechamento real (sem isto e dry-run)")
    ap.add_argument("--rollover", type=int, default=21,
                    help="hora UTC da virada do dia no servidor MT5")
    a = ap.parse_args(argv)

    g = MT5Guard(ProgramRules(), RiskLimits(), rollover_utc_hour=a.rollover,
                 dry_run=not a.arm)
    g.connect()
    if a.watch:
        g.watch(a.every)
    else:
        for k, v in g.poll().items():
            print(f"  {k:20} {v}")


if __name__ == "__main__":
    main()
