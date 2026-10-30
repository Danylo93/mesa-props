"""Testes dos indicadores e da maquina de estados do Holy Grail."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from holygrail.indicators import add_indicators, adx_di, wilder
from holygrail.setup import HGParams, Setup, find_setups
from holygrail.evaluate import CostModel, pip_size, run_setups
from holygrail.resample import resample


def dente(ciclos=12, subida=40, recuo=12, passo=0.0020, devolve=0.45, sentido=1):
    """
    Serra deterministica: sobe forte, devolve parte do movimento (furando a
    EMA) e sobe de novo. E a forma mais simples que produz exatamente o que
    o Holy Grail procura - tendencia forte com recuos ate o "valor".

    Uma senoide NAO serve: sobre uma tendencia, a onda suave quase nunca
    leva a minima abaixo da EMA, e nenhum setup arma.
    """
    px = [1.0]
    for _ in range(ciclos):
        for _ in range(subida):
            px.append(px[-1] + passo * sentido)
        volta = passo * subida * devolve / recuo
        for _ in range(recuo):
            px.append(px[-1] - volta * sentido)
    return np.array(px)


def mk(close, high=None, low=None):
    c = np.asarray(close, dtype=float)
    o = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame(
        {"open": o,
         "high": c + 0.001 if high is None else np.asarray(high, float),
         "low": c - 0.001 if low is None else np.asarray(low, float),
         "close": c, "volume": np.ones(len(c)) * 1000},
        index=pd.date_range("2025-01-01", periods=len(c), freq="h", tz="UTC"))


# ------------------------------------------------------------ indicadores

def test_wilder_e_media_movel_exponencial_com_alpha_1_sobre_n():
    x = pd.Series([1.0] * 50)
    assert abs(wilder(x, 14).iloc[-1] - 1.0) < 1e-9

def test_adx_alto_em_tendencia_limpa():
    d = add_indicators(mk(np.linspace(1.0, 1.2, 300)))
    assert d["adx"].iloc[-1] > 60

def test_adx_baixo_em_lateral():
    rng = np.random.default_rng(3)
    d = add_indicators(mk(1.0 + rng.normal(0, 0.002, 400).cumsum() * 0.05))
    assert d["adx"].iloc[-1] < 60

def test_di_aponta_a_direcao():
    up = add_indicators(mk(np.linspace(1.0, 1.2, 300)))
    dn = add_indicators(mk(np.linspace(1.2, 1.0, 300)))
    assert up["plus_di"].iloc[-1] > up["minus_di"].iloc[-1]
    assert dn["minus_di"].iloc[-1] > dn["plus_di"].iloc[-1]

def test_adx_fica_na_faixa_0_100():
    rng = np.random.default_rng(11)
    d = add_indicators(mk(1.0 + rng.normal(0, 0.003, 500).cumsum() * 0.1))
    a = d["adx"].dropna()
    assert a.min() >= 0.0 and a.max() <= 100.0


# ------------------------------------------------------------ setup

def test_sem_setup_quando_adx_fraco():
    rng = np.random.default_rng(5)
    d = add_indicators(mk(1.0 + rng.normal(0, 0.0005, 400).cumsum() * 0.02))
    assert find_setups(d, HGParams(adx_min=95.0)) == []

def test_setup_respeita_o_lado_da_tendencia():
    d = add_indicators(mk(dente()))
    s = find_setups(d, HGParams())
    assert s, "esperava ao menos um setup nesta serie"
    assert all(x.side > 0 for x in s)      # tendencia de alta: so compra


def test_setup_acha_vendas_em_tendencia_de_baixa():
    d = add_indicators(mk(dente(sentido=-1)))
    s = find_setups(d, HGParams())
    assert s, "esperava ao menos um setup de venda"
    assert all(x.side < 0 for x in s)

def test_stop_fica_do_lado_certo_da_entrada():
    d = add_indicators(mk(dente()))
    for x in find_setups(d, HGParams()):
        if x.side > 0:
            assert x.stop < x.entry < x.target
        else:
            assert x.target < x.entry < x.stop

def test_min_rr_descarta_alvo_curto():
    d = add_indicators(mk(dente()))
    folgado = find_setups(d, HGParams(min_rr=0.5))
    exigente = find_setups(d, HGParams(min_rr=5.0))
    assert len(exigente) <= len(folgado)
    assert all(x.rr >= 5.0 - 1e-9 for x in exigente)

def test_max_rr_trava_o_alvo():
    d = add_indicators(mk(dente()))
    for x in find_setups(d, HGParams(max_rr=2.0)):
        assert x.rr <= 2.0 + 1e-9

def test_entrada_nunca_antes_da_barra_que_armou():
    d = add_indicators(mk(dente()))
    for x in find_setups(d, HGParams()):
        assert x.i_entry >= x.i_armed   # sem look-ahead

def test_setup_expira_se_nao_romper():
    d = add_indicators(mk(dente()))
    curto = find_setups(d, HGParams(max_wait=1))
    longo = find_setups(d, HGParams(max_wait=20))
    assert len(curto) <= len(longo)


# ------------------------------------------------------------ avaliacao

def test_pip_size():
    assert pip_size("EURUSD") == 0.0001
    assert pip_size("USDJPY") == 0.01

def test_perda_no_stop_fica_perto_de_menos_1R():
    # serie que cai: um setup de compra tem de bater o stop
    d = mk(np.linspace(1.10, 1.00, 200))
    s = [Setup(i_entry=50, side=1, entry=1.0750, stop=1.0700,
               target=1.0900, i_armed=49)]
    o = run_setups(d, s, "EURUSD")[0]
    assert o.reason == "stop"
    assert -1.5 < o.r < -1.0       # -1R mais o custo, nunca melhor que -1

def test_custo_sempre_piora_o_resultado():
    d = mk(np.linspace(1.00, 1.10, 200))
    s = [Setup(i_entry=50, side=1, entry=1.0250, stop=1.0200,
               target=1.0350, i_armed=49)]
    sem = run_setups(d, s, "EURUSD", CostModel(commission_pips=0, slippage_pips=0))[0]
    com = run_setups(d, s, "EURUSD", CostModel())[0]
    assert com.r < sem.r

def test_stop_ganha_do_alvo_na_mesma_barra():
    """Barra que contem stop E alvo tem de resolver como STOP."""
    c = np.full(60, 1.05)
    hi = c + 0.01; lo = c - 0.01          # barra larga: cobre os dois
    d = mk(c, high=hi, low=lo)
    s = [Setup(i_entry=30, side=1, entry=1.0500, stop=1.0450,
               target=1.0550, i_armed=29)]
    assert run_setups(d, s, "EURUSD")[0].reason == "stop"


# ------------------------------------------------------------ reamostragem

def test_resample_h4_agrega_certo():
    d = mk(np.linspace(1.0, 1.1, 400))
    h4 = resample(d, "H4")
    assert len(h4) == 100
    assert h4["high"].iloc[0] == d["high"].iloc[:4].max()
    assert h4["low"].iloc[0] == d["low"].iloc[:4].min()
    assert h4["open"].iloc[0] == d["open"].iloc[0]
    assert h4["close"].iloc[0] == d["close"].iloc[3]

def test_resample_d1_fecha_as_21h_utc():
    d = mk(np.linspace(1.0, 1.1, 24 * 10))
    d1 = resample(d, "D1")
    assert all(ts.hour == 21 for ts in d1.index)
