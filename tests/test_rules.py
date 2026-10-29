"""
Testes do motor de regras e da camada de risco.

Estes testes sao o produto. Se o motor de regras estiver errado, um
backtest bonito so significa que a conta quebra mais devagar.
"""
import datetime as dt
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from the5ers.rules import Breach, ProgramRules, RuleEngine, Status
from the5ers.risk import RiskGovernor, RiskLimits, pip_value_usd, size_position

D = dt.date(2026, 1, 5)
def eng(**kw): return RuleEngine(ProgramRules(**kw))


# ----------------------------------------------------------- pisos

def test_piso_total_inicial():
    assert eng().total_loss_floor == 92_000.0          # 100k - 8k

def test_piso_total_arrasta_com_lucro():
    e = eng(); e.open_day(D); e.close_day(103_000)
    assert e.total_loss_floor == 95_000.0              # ganhar APERTA o piso

def test_piso_total_nao_afrouxa_com_prejuizo():
    e = eng()
    e.open_day(D); e.close_day(104_000)
    e.open_day(D); e.close_day(99_000)                 # dia ruim depois
    assert e.eod_high_water == 104_000.0
    assert e.total_loss_floor == 96_000.0              # continua preso ao topo

def test_piso_total_estatico_quando_desligado():
    e = eng(trailing_total_loss=False)
    e.open_day(D); e.close_day(110_000)
    assert e.total_loss_floor == 92_000.0

def test_hwm_so_sobe_no_fechamento_do_dia():
    e = eng(); e.open_day(D)
    e.mark(107_000)                                     # pico intradiario
    assert e.total_loss_floor == 92_000.0               # nao arrastou ainda
    e.close_day(101_000)
    assert e.total_loss_floor == 93_000.0               # arrasta pelo FECHAMENTO


# ----------------------------------------------------------- limite diario

def test_limite_diario_usa_o_menor_dos_dois():
    e = eng(); e.open_day(D, balance=90_000)
    assert e.daily_loss_limit == 3_600.0                # 4% de 90k < 4% de 100k
    e.open_day(D, balance=120_000)
    assert e.daily_loss_limit == 4_000.0                # 4% de 100k < 4% de 120k

def test_piso_diario():
    e = eng(); e.open_day(D, balance=102_000)
    assert e.daily_loss_floor == 98_000.0               # 102k - 4k


# ----------------------------------------------------------- violacoes

def test_violacao_diaria():
    e = eng(); e.open_day(D)
    assert e.mark(96_500) is Breach.NONE
    assert e.mark(95_900) is Breach.DAILY_LOSS
    assert e.status is Status.FAILED

def test_violacao_total():
    e = eng(); e.open_day(D, balance=94_000)
    assert e.mark(91_900) is Breach.TOTAL_LOSS         # abaixo de 92k

def test_total_tem_prioridade_sobre_diaria():
    """Equity que fura os dois pisos deve reportar perda TOTAL."""
    e = eng(); e.open_day(D, balance=93_000)           # piso diario 89.8k, total 92k
    assert e.mark(88_000) is Breach.TOTAL_LOSS

def test_violacao_e_permanente():
    e = eng(); e.open_day(D); e.mark(95_000)
    assert e.mark(105_000) is Breach.DAILY_LOSS        # recuperar nao desfaz

def test_breach_none_e_falsy():
    assert not Breach.NONE and Breach.DAILY_LOSS


# ----------------------------------------------------------- consistencia / aprovacao

def test_dias_lucrativos():
    e = eng()
    # saldos de FECHAMENTO acumulados, nao pnl diario:
    #   100.0k -> 100.5k (+)  -> 101.2k (+)  -> 99.0k (-)  -> 101.0k (+)
    for b in (100_500, 101_200, 99_000, 101_000):
        e.open_day(D); e.close_day(b)
    assert e.profitable_days == 3
    assert [round(d.pnl) for d in e.days] == [500, 700, -2200, 2000]

def test_alvo_sem_dias_lucrativos_nao_aprova():
    e = eng(); e.open_day(D); e.close_day(110_000)
    assert e.target_hit and e.profitable_days == 1
    assert e.status is Status.RUNNING                  # falta consistencia

def test_aprovado_exige_alvo_e_dias():
    e = eng()
    for b in (103_000, 106_000, 110_000):
        e.open_day(D); e.close_day(b)
    assert e.status is Status.PASSED


# ----------------------------------------------------------- dimensionamento

def test_pip_value_xxxusd():
    assert pip_value_usd("EURUSD", 1.08) == 10.0       # independe do preco

def test_pip_value_usdxxx_depende_do_preco():
    assert round(pip_value_usd("USDJPY", 100.0), 2) == 10.0
    assert round(pip_value_usd("USDJPY", 200.0), 2) == 5.0

def test_size_bate_o_risco():
    lots = size_position("EURUSD", 1.08, 0.0025, 350.0)   # stop 25 pips
    assert lots == 1.4                                     # 350 / (25*10)
    assert abs(lots * 25 * 10.0 - 350.0) < 1.0

def test_size_zero_quando_nao_cabe():
    assert size_position("EURUSD", 1.08, 0.50, 1.0) == 0.0  # stop gigante, risco minusculo

def test_size_rejeita_stop_invalido():
    assert size_position("EURUSD", 1.08, 0.0, 350.0) == 0.0


# ----------------------------------------------------------- governor

def gov(**kw):
    e = eng(); e.open_day(D); g = RiskGovernor(e, RiskLimits(**kw)); g.on_day_open(); return e, g

def test_governor_para_mais_cedo_que_a_regra():
    e, g = gov()
    assert g.daily_soft_floor == 98_500.0               # 1.5% vs 4% contratual
    assert g.daily_hard_floor == 97_500.0
    assert g.guarded_total_floor == 93_000.0            # 92k + 1% de folga

def test_governor_veta_apos_soft_stop():
    e, g = gov()
    assert g.can_open("EURUSD", 99_000).allowed
    assert not g.can_open("EURUSD", 98_400).allowed

def test_governor_manda_zerar():
    e, g = gov()
    assert not g.must_flatten(98_000)
    assert g.must_flatten(97_400)

def test_governor_limita_simultaneas():
    e, g = gov(max_concurrent=2, max_per_currency=9)
    g.register_open("EURUSD"); g.register_open("AUDJPY")
    assert not g.can_open("GBPUSD", 100_000).allowed

def test_governor_bloqueia_moeda_repetida():
    e, g = gov()
    g.register_open("EURUSD")
    assert not g.can_open("GBPUSD", 100_000).allowed   # USD nos dois
    assert g.can_open("AUDJPY", 100_000).allowed

def test_governor_para_no_alvo():
    e, g = gov()
    e.mark(110_000)
    assert not g.can_open("EURUSD", 110_000).allowed

def test_risco_cai_perto_do_alvo():
    e, g = gov()
    cheio = g.risk_usd(100_000)
    perto = g.risk_usd(108_500)                        # 85% do alvo
    assert perto < cheio * 0.6

def test_risco_nunca_passa_da_folga_ate_o_piso():
    e, g = gov()
    r = g.risk_usd(97_600)                             # quase no hard stop
    assert r <= 97_600 - g.daily_hard_floor + 1e-9

def test_governor_veta_conta_violada():
    e, g = gov(); e.mark(95_000)
    assert not g.can_open("EURUSD", 95_000).allowed
