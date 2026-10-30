# mesa-props — estratégia para aprovação The5ers 100K

Avaliação dos 8 repositórios da lista e implementação da estratégia + camada de
risco para a conta **$100K High Stakes 10%**.

---

## 1. Qual dos 8 repos serve — e por quê

**A The5ers é forex/CFD rodando em MetaTrader 5.** Esse único fato elimina a
maior parte da lista antes de qualquer discussão sobre qualidade de código:

| # | Repo | Classe de ativo | Serve para The5ers? |
|---|------|-----------------|---------------------|
| 1 | AI Hedge Fund | Ações US + agentes LLM | Não — classe errada, sem backtest rigoroso |
| 2 | **Freqtrade** | Cripto (12 exchanges, via CCXT) | **Não** — README não cita forex/CFD/MT5 |
| 3 | CCXT | Cripto — camada de API de exchange | Não — não existe adaptador MT5 |
| 4 | **NautilusTrader** | **Agnóstico: FX, ações, futuros, cripto** | **Sim — a escolha** |
| 5 | Hummingbot | Cripto — market making | Não |
| 6 | Eliza | Agentes cripto / carteiras on-chain | Não |
| 7 | FinRL | Pesquisa em RL | Não — overfit crônico, não é infra de execução |
| 8 | Jesse | Cripto | Não |

**NautilusTrader é o único viável**, e por motivos concretos verificados no
README oficial do projeto:

- explicitamente *asset-class-agnostic*, com **FX** entre os mercados cobertos;
- backtest orientado a eventos em resolução de **nanossegundos**, com tick,
  quote, bar e order book;
- **o mesmo código de estratégia roda em backtest e em live** — é isso que
  impede o clássico "no backtest funcionava".

### A limitação que define a arquitetura

**NautilusTrader não tem adaptador MetaTrader 5.** Confirmei no README: a lista
de 21 integrações não menciona MetaTrader em nenhum lugar. Nenhum dos 8 repos
fala com MT5. Então a arquitetura honesta é:

```
NautilusTrader ──► pesquisa, backtest, validação independente
MetaTrader 5   ──► execução real na conta The5ers  (src/the5ers/live_mt5.py)
```

Quem prometer "plugue o Freqtrade na The5ers" está vendendo ilusão: o Freqtrade
fala CCXT, e CCXT fala com exchange de cripto, não com broker de FX.

---

## 2. As regras reais da sua conta

Lidas da **API da The5ers**, não da documentação pública nem de memória
(`the5ers_program/rules` + `the5ers_consistency/list`, em 29/10/2026):

| Regra | Valor | Unidade |
|---|---|---|
| Programa | `$100K High Stakes 10%` | — |
| Alvo de lucro | **10 000** | USD |
| Perda máxima diária | **4** | **percent** |
| Perda máxima total | **8 000** | USD |
| Dias lucrativos (consistência) | **3** | dias |
| Etapa | 1 de 2 da fase de avaliação | — |
| Etapa seguinte | `$100K High Stakes - 2`, alvo 5 000 USD | — |

Valores em **USD**. Conta: `meta-trader-5 · …6821`, plataforma MetaTrader 5.

**Não há regra de expiração nem de mínimo de dias de negociação configurada** —
a API não retornou nenhuma das duas. Na prática: *não há relógio correndo contra
você*. Isso favorece operar devagar e bem, não rápido e torto.

### As duas armadilhas

A API **não expõe a base de cálculo** de duas regras. Onde havia ambiguidade,
este repo escolhe sempre o lado mais apertado — errar para o lado frouxo custa a
conta, errar para o apertado custa um pouco de lucro.

**1. A perda total arrasta pelo fechamento do dia.** O piso não é fixo em
92 000. Ele sobe junto com seu maior saldo de *fim de dia*:

```
piso = max(saldo_inicial, maior_saldo_de_fechamento) − 8 000
```

Ou seja: **ganhar aperta o seu piso.** Fechou um dia em 103 000? Seu piso virou
95 000, não 92 000 — e nenhum dashboard mostra isso. É a causa número um de
conta perdida "do nada" depois de uma semana boa.

**2. "4 percent" sem base declarada.** Aplicamos o **menor** entre 4% do saldo
inicial e 4% do saldo de abertura do dia.

> O número oficial é sempre o do Hub da The5ers. Os pisos daqui são iguais ou
> mais conservadores — nunca mais frouxos.

---

## 3. A estratégia

Pullback a favor da tendência, H1, majors FX. Escolhida por ser a família mais
testada e mais **chata** que existe em FX. Num desafio de prop firm o que decide
não é o retorno máximo, é o **caminho**: drawdown raso e nenhuma surpresa.
Estratégia exótica com Sharpe bonito quebra conta no dia 4.

| Componente | Regra |
|---|---|
| Regime | EMA(50) vs EMA(200) — só compra acima, só vende abaixo |
| Gatilho | recuo até a EMA(20) nas últimas 3 barras, depois fecha de volta a favor |
| Momento | RSI(14) entre 40 e 72 (long) / 28 e 60 (short) — sem pegar faca caindo |
| Volatilidade | ATR(14)/preço dentro de banda — fora disso é notícia ou mercado morto |
| Sessão | 07:00–16:00 UTC (Londres + abertura NY) |
| Stop | 1.5 × ATR(14) |
| Alvo | 2.0 R, breakeven em +1.0 R |
| Tempo | fecha em 48 barras se não resolveu |

### A camada que realmente importa

**A maioria das contas não quebra por estratégia ruim. Quebra por violação de
regra.** Por isso o `RiskGovernor` tem poder de veto sobre qualquer sinal, e
todos os limites são mais apertados que os contratuais:

| Trava | Operacional | Contratual |
|---|---|---|
| Para de **abrir** | −1,5% no dia | — |
| **Zera** tudo | −2,5% no dia | −4% (perda da conta) |
| Piso de perda total | +1% de folga | 8 000 USD |
| Risco por trade | 0,35% da equity | — |
| Posições simultâneas | 2, nunca 2 na mesma moeda | — |
| Perto do alvo | risco cai pela metade a partir de 80% | — |

A folga de 1,5% entre o hard stop e a regra existe para gap de fim de semana e
slippage — exatamente o cenário em que contas morrem.

---

## 4. Estrutura

```
config/the5ers_100k.yaml     regras reais + interpretações conservadoras
src/the5ers/
  rules.py                   motor de regras — onde a conta MORRE
  risk.py                    dimensionamento + governor (poder de veto)
  strategy.py                sinais (EMA/RSI/ATR), agnóstico de framework
  backtest.py                backtest orientado a eventos, premissas pessimistas
  montecarlo.py              P(aprovado) por bootstrap dos trades
  dukascopy.py               candles H1 reais (formato .bi5 decodificado aqui)
  research.py                bancada de pesquisa de sinais (sem motor)
  nautilus_strategy.py       adaptador NautilusTrader -- NAO VALIDADO
  live_mt5.py                guarda-regras para a conta real no MT5
scripts/fetch_data.py        baixa os dados (Dukascopy, multi-passada)
scripts/build_csv.py         reconstroi os CSVs do cache ja baixado
scripts/run_backtest.py      backtest + varredura + walk-forward + Monte Carlo
scripts/diagnose.py          normal vs invertido vs aleatorio  <- o teste decisivo
scripts/required_edge.py     que taxa de acerto aprova, por Monte Carlo
scripts/sync_rules.py        documenta as chamadas de API que geraram o YAML
scripts/scan_signals.py      varre as 8 hipoteses de sinal
scripts/scan_structure.py    que estrutura de trade salva cada sinal
scripts/verify_edge.py       teste t + Bonferroni no candidato
scripts/test_ensemble.py     confluencia multi-sinal
scripts/run_nautilus.py      motor Nautilus -- NAO VALIDADO (secao 7)
tests/test_rules.py          29 testes do motor de regras
```

### Premissas pessimistas do backtest

Um backtest de desafio que erra para o otimista não vale nada:

- sinal da barra `t` executa na **abertura de `t+1`** — nunca no fechamento da
  própria barra que gerou o sinal;
- se stop **e** alvo cabem na mesma barra, assume-se **stop** (dados H1 não
  dizem a ordem dentro da barra);
- spread cobrado meio a meio na entrada e na saída, mais slippage, mais comissão;
- a equity que vai ao motor de regras é a **pior da barra**, não o fechamento —
  é assim que a corretora mede;
- virada do dia no horário do servidor MT5 (padrão 21:00 UTC), não em UTC 00:00.

---

## 5. Resultados — leia isto antes de operar qualquer coisa

Dados: **5 majors, 44 208 barras H1, 2025-05 a 2026-09** (Dukascopy, bid real).

### A estratégia de referência não tem vantagem. Não opere.

| Métrica | Valor |
|---|---|
| Trades | 136 |
| Taxa de acerto | 22,8% |
| Profit factor | 0,78 |
| **avg R** | **−0,120** |
| Lucro | **−5 715 USD** |
| Drawdown máximo | 7 150 USD |

Varri **24 configurações** (RR 1.0/1.5/2.0 × stop ATR/swing × filtro de
inclinação × recuo raso). **Nenhuma teve vantagem positiva.** A melhor ficou em
avg R −0,108. O walk-forward confirmou: as 3 janelas out-of-sample deram −0,292,
−0,273 e −0,187.

### O teste que fecha a questão

Rodei o mesmo motor três vezes — sinal normal, sinal **invertido**, e entradas
**aleatórias** na mesma frequência:

| Rodada | Trades | Acerto | avg R |
|---|---|---|---|
| normal | 136 | 22,8% | **−0,120** |
| invertido | 158 | 23,4% | **−0,124** |
| aleatório | 167 | 22,2% | **−0,119** |

Os três são **estatisticamente idênticos**. Diferença entre a estratégia e jogar
dados: **−0,001 R**.

Isso não é parâmetro ruim nem bug — se fosse sinal invertido, a linha "invertido"
seria positiva. É a assinatura de um sinal com **zero conteúdo informativo**: os
−0,12 R são puro custo de transação (spread + comissão).

### O que isso significa para a conta de 100K

Monte Carlo, 20 000 caminhos, com as regras reais da sua conta:

| | |
|---|---|
| **P(aprovado)** | **0,8%** |
| **P(perde a conta)** | **90,1%** |
| — por regra diária | 0,0% |
| — por perda total | 90,1% |
| Equity final (mediana) | 93 171 USD |

**Operar isto na sua conta tem 0,8% de chance de aprovar e 90% de perder os 100K.**

### Dois achados que sobrevivem ao fracasso da estratégia

**1. A camada de risco funciona.** Mesmo com um sistema perdedor rodando 379 dias,
a equity mínima foi 94 285 — **nunca chegou perto do piso de 92 000**, e a taxa de
violação da regra *diária* foi **0,0%**. O hard stop de 2,5% dispara antes dos 4%
contratuais, sempre. Você não morre de regra diária; você sangra devagar contra o
piso que arrasta.

**2. A barra real é mais alta do que parece.** Veja `scripts/required_edge.py`:

| Acerto (RR 2:1) | avg R líquido | P(aprovado) | P(perde) |
|---|---|---|---|
| 33,3% (empate bruto) | −0,070 | 6,5% | 85,1% |
| 36,7% | +0,030 | 34,7% | 47,9% |
| 38,0% | +0,070 | 51,2% | 32,7% |
| **40,0%** | **+0,130** | **75,7%** | **15,2%** |
| 42,0% | +0,190 | 90,4% | 5,9% |
| 45,0% | +0,280 | 98,5% | 1,1% |

Repare na primeira linha: **empatar no bruto ainda perde a conta em 85% dos
caminhos**, porque o custo te empurra contra o piso que arrasta. A meta prática é
**~40% de acerto a 2:1** — não 33%.

---

## 6. Busca por vantagem: 8 hipóteses, nenhuma sobreviveu

Depois de medir que o pullback era ruído, a resposta certa não é mexer em
parâmetro até o backtest ficar bonito — isso é p-hacking e produz sistema que
perde dinheiro de verdade. Testei **hipóteses diferentes**, cada uma com razão
econômica, no mesmo tribunal: corte treino/teste **no tempo**, baseline
aleatório na mesma frequência, consistência entre pares.

Resultado fora da amostra, média dos 5 pares (`scripts/scan_signals.py`):

| Sinal | avg R | vs aleatório | pares + |
|---|---|---|---|
| asia_fade | −0,0148 | **+0,0161** | 3/5 |
| bb_fade / meanrev_z | −0,0379 | +0,0157 | 3/5 |
| london_breakout | −0,0471 | +0,0049 | 4/5 |
| rsi_extreme | −0,0869 | −0,0454 | 3/5 |
| trend_pullback | −0,1303 | −0,0529 | 1/5 |
| momentum | −0,1801 | −0,0758 | 1/5 |
| vol_squeeze | −0,1204 | −0,0907 | 0/5 |
| inside_break | −0,1977 | −0,1396 | 1/5 |

A família de **reversão à média bate o sorteio** — confirma que FX H1 é
reversivo, não tendencial. Mas **todos continuam negativos em absoluto**: a
vantagem (~+0,016 R) é menor que o custo (~0,07 R). `bb_fade` e `meanrev_z` deram
números idênticos porque são a mesma fórmula; foram 8 hipóteses, não 9.

### O candidato que quase passou

Varrendo estrutura de trade (stop 1,5–4 ATR × alvo 0,5–1,5 R, escolhida **só no
treino**), o `london_breakout` com stop 4 ATR e alvo 0,5 R deu **avg R +0,0292
fora da amostra** — positivo líquido. Submetido ao teste estatístico
(`scripts/verify_edge.py`):

| | |
|---|---|
| n | 1 086 |
| avg R | +0,0292 |
| t | 1,49 |
| p bruto | 0,137 |
| **p após Bonferroni (36 testes)** | **1,000** |
| pares positivos | 3/5 |

**Reprovado nos três critérios.** Era o melhor de 36 sorteios, não uma vantagem.

### Combinar os sinais (a ideia do AI Hedge Fund) não resolve

Vários "analistas" votando, operando só na confluência — `scripts/test_ensemble.py`:
**0 de 8 combinações** com avg R positivo. `voto3` (3+ concordando) chega a
−0,34 R. Confluência não cria informação que os componentes não têm.

---

## 7. O estado do NautilusTrader neste repo

Preciso ser exato aqui, porque é fácil dar a impressão errada.

**O NautilusTrader é a escolha de framework** e o adaptador existe
(`src/the5ers/nautilus_strategy.py`): instala, instancia, submete ordens e
preenche. **Mas o caminho de saída está errado e os números dele não prestam.**

Duas tentativas, as duas furadas:

1. **Bracket** (`sl_trigger_price`/`tp_price`) — o motor rejeita as ordens
   reduce-only em vários casos e a posição fica **sem proteção**. Uma ficou
   aberta 16 meses e "ganhou" 8 192 USD.
2. **Saída gerida na barra** com `close_all_positions()` — é ordem **a mercado**.
   Quando a barra toca o stop, a posição não fecha *no stop*, fecha no preço da
   barra seguinte. Em mercado reversivo, tocar o stop e voltar vira **vitória**:
   acerto sobe para 55–72% e **todo par "bate" os +10 000**.

O certo é ordens `STOP_MARKET` e `LIMIT` reduce-only descansando na venue,
submetidas depois do preenchimento da entrada. **Não está feito.**

### O contraste vale como lição

A **mesma** estratégia, nos **mesmos** dados:

| Premissa de saída | Resultado |
|---|---|
| pessimista (`backtest.py`: stop ganha do alvo, spread, slippage) | **−5 715 USD** |
| ingênua (`run_nautilus.py`: fecha a mercado na barra seguinte) | **+10 000 USD** |

A diferença entre "funciona" e "não funciona" estava **inteira na premissa de
saída**. É por isso que backtest otimista não vale nada.

### Por que a conclusão não depende disso

A bancada de pesquisa (`src/the5ers/research.py`) avalia sinais **direto sobre
OHLC**, varrendo stop e alvo barra a barra — sem motor, sem ordens, sem estado de
posição. O resultado de "sem vantagem" vem de lá e é **independente dos dois
backtests**.

---

## 8. Uso

```bash
pip install -r requirements.txt
python scripts/fetch_data.py 18        # candles H1 (Dukascopy)
python scripts/run_backtest.py         # backtest + varredura + WF + Monte Carlo
python scripts/diagnose.py             # normal vs invertido vs aleatorio
python scripts/required_edge.py        # que vantagem e preciso ter
python scripts/scan_signals.py         # varre 8 hipoteses de sinal
python scripts/scan_structure.py       # que estrutura de trade salva cada uma
python scripts/verify_edge.py          # teste t + Bonferroni no candidato
python scripts/test_ensemble.py        # confluencia (ideia do AI Hedge Fund)
python scripts/run_nautilus.py EURUSD  # motor Nautilus -- NAO VALIDADO
python -m pytest tests/ -q             # 29 testes do motor de regras
```

Na conta real, em Windows com o terminal MT5 aberto:

```bash
pip install MetaTrader5
python -m the5ers.live_mt5 --watch              # dry-run, só observa
python -m the5ers.live_mt5 --watch --arm        # ARMADO: fecha de verdade
```

O guarda **não abre posições** — só fecha e bloqueia. A decisão de entrar
continua sendo sua, de propósito.

---

## 9. O que isto não é

- **A estratégia de referência não funciona** — medido, não suposto (seção 5).
  Ela está aqui como alvo de teste e exemplo de como ligar sinal + risco + regras,
  não como sistema para operar. O valor entregue é a infraestrutura: motor de
  regras, governor, backtest pessimista e o arnês de diagnóstico que **rejeita uma
  ideia ruim antes de ela custar 100K**.
- **Não é garantia de aprovação.** Nenhum backtest é. O número que importa é o
  `P(aprovado)` do Monte Carlo, e ele vem de uma reamostragem dos trades
  históricos — assume que a distribuição se mantém, o que nem sempre acontece.
- **17 meses é pouco.** Cobre um regime de mercado, não vários. Uma estratégia
  aprovada aqui ainda precisa de dados mais longos antes de ir para conta real.
- **Os parâmetros da varredura não são "os melhores".** São os melhores *nesse
  período*. Por isso o walk-forward: se o out-of-sample desaba, o parâmetro era
  ruído.
- **Perdas em sequência se agrupam** na vida real mais do que no bootstrap.
  Trate o `P(aprovado)` como teto, não como previsão.
- **Rode em conta demo antes.** O custo de descobrir um bug de execução na conta
  de 100K é a conta de 100K.
