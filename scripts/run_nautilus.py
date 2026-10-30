#!/usr/bin/env python3
"""
Roda a estrategia no motor do NAUTILUSTRADER - nao no meu.

NAO VALIDADO: o caminho de saida esta errado (ver nautilus_strategy.py).
close_all_positions() e ordem a mercado, entao o stop nao e respeitado e
o resultado sai otimista demais (+10 000 em todo par, 55-72% de acerto).
Mantido no repo como esqueleto e como demonstracao de quanto a premissa
de saida muda o resultado. Nao tire conclusao daqui.

Eu reportei numeros do backtest proprio (src/the5ers/backtest.py) antes de
rodar isto. Sao coisas diferentes: um motor independente, com sua propria
simulacao de conta, margem e preenchimento, e o teste de que as premissas
do meu motor nao estavam me favorecendo.

Se os dois discordarem muito, o meu motor e que esta errado - o Nautilus e
que tem contabilidade de portfolio, margem e eventos de ordem de verdade.

    python scripts/run_nautilus.py [PAR]        # padrao EURUSD
"""
import sys, pathlib
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.model.data import Bar
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from the5ers.nautilus_strategy import The5ersConfig, The5ersStrategy

PAR = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"
CSV = ROOT / "data" / "h1" / f"{PAR}.csv"


def main() -> None:
    if not CSV.exists():
        print(f"sem dados: {CSV}"); sys.exit(1)

    df = pd.read_csv(CSV, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[["open", "high", "low", "close", "volume"]].copy()
    print(f"{PAR}: {len(df)} barras H1  {df.index[0].date()} -> {df.index[-1].date()}")

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="THE5ERS-001",
        logging=LoggingConfig(log_level="ERROR"),   # o motor e verboso
    ))
    venue = Venue("SIM")
    engine.add_venue(
        venue=venue,
        oms_type=OmsType.NETTING,   # MT5 e netting; em HEDGING as ordens reduce-only
                                    # do bracket sao rejeitadas e a posicao fica SEM stop
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(100_000, USD)],
        default_leverage=Decimal(30),      # alavancagem tipica de mesa FX
    )

    sym = f"{PAR[:3]}/{PAR[3:]}"
    instrument = TestInstrumentProvider.default_fx_ccy(sym, venue=venue)
    engine.add_instrument(instrument)

    # O motor simulado precisa dos DOIS lados do mercado: uma ordem de
    # compra executa no ASK. Os dados da Dukascopy sao BID, entao o ASK e
    # sintetizado somando o spread tipico do par - e assim o proprio
    # Nautilus cobra o custo do spread, em vez de eu descontar na mao.
    from the5ers.data import SPREADS_PIPS
    pip = 0.01 if "JPY" in PAR.upper() else 0.0001
    spread = SPREADS_PIPS.get(PAR, 1.2) * pip
    bar_type = BarType.from_str(f"{instrument.id}-1-HOUR-BID-EXTERNAL")
    ask_type = BarType.from_str(f"{instrument.id}-1-HOUR-ASK-EXTERNAL")
    # Barras montadas a mao em vez do BarDataWrangler: o pandas 3 entrega
    # arrays somente-leitura (copy-on-write) e o wrangler em Cython exige
    # buffer gravavel. Construir os Bar direto evita o problema por inteiro.
    prec = instrument.price_precision
    bars, asks = [], []
    for ts, row in df.iterrows():
        ns = int(ts.value)
        o, h, l, c = (float(row.open), float(row.high), float(row.low), float(row.close))
        vol = Quantity(int(row.volume), 0)
        bars.append(Bar(bar_type, Price(o, prec), Price(h, prec),
                        Price(l, prec), Price(c, prec), vol, ns, ns))
        asks.append(Bar(ask_type, Price(o + spread, prec), Price(h + spread, prec),
                        Price(l + spread, prec), Price(c + spread, prec), vol, ns, ns))
    engine.add_data(bars)
    engine.add_data(asks)
    print(f"carregadas {len(bars)} barras BID + {len(asks)} ASK "
          f"(spread {spread/pip:.1f} pip) no motor Nautilus")

    engine.add_strategy(The5ersStrategy(The5ersConfig(
        instrument_id=instrument.id,
        bar_type=bar_type,
    )))

    engine.run()

    acct = engine.portfolio.account(venue)
    final = float(acct.balance_total(USD).as_double())
    report = engine.trader.generate_order_fills_report()
    positions = engine.trader.generate_positions_report()

    print("\n=== resultado no motor NautilusTrader ===")
    print(f"  saldo inicial   100000.00 USD")
    print(f"  saldo final     {final:,.2f} USD")
    print(f"  resultado       {final - 100_000:+,.2f} USD")
    print(f"  ordens preenchidas {len(report)}")
    print(f"  posicoes           {len(positions)}")
    if len(positions):
        pnl = pd.to_numeric(positions["realized_pnl"].astype(str)
                            .str.replace(" USD", "", regex=False), errors="coerce")
        wins = int((pnl > 0).sum()); n = int(pnl.notna().sum())
        print(f"  vencedoras         {wins}/{n}"
              f"  ({100*wins/n:.1f}%)" if n else "")
    engine.dispose()


if __name__ == "__main__":
    main()
