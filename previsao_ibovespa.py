"""Previsão do IBOVESPA com visualização no estilo Google Finanças.

Mostra o gráfico intradiário do pregão, marca em cima dele a previsão para o
horário escolhido (com faixas de incerteza) e, depois do gráfico, mostra no
output o resultado (previsão e faixa de 80%) e o embasamento de cada etapa.

Alvos aceitos (--alvo, ou escolha no menu interativo):
    fechamento            fechamento do pregão atual (ou do próximo, se já fechou)
    abertura              abertura do próximo pregão (preço após os primeiros 5 min)
    fechamento-amanha     fechamento do próximo pregão
    HH:MM                 horário do pregão atual (ou do próximo, se já passou)
    amanha HH:MM          horário do próximo pregão
    DD/MM HH:MM           horário de um pregão específico

Uso:
    python previsao_ibovespa.py
    python previsao_ibovespa.py --alvo fechamento-amanha
    python previsao_ibovespa.py --alvo "amanha 11:30" --sem-janela
"""

import argparse
import math
import re
import sys
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

TZ = ZoneInfo("America/Sao_Paulo")
BARRA_MIN = 5
ATRASO = timedelta(minutes=16)       # atraso do Yahoo nas cotações do IBOV
FOLGA_FECH = timedelta(minutes=30)   # espera após o fechamento para confiar no valor oficial
MIN_HISTORICO = 15      # dias de histórico antes de começar a prever no backtest
MIN_TREINO = 10         # amostras mínimas para treinar um modelo de tendência

VERMELHO, VERDE, AZUL, CINZA, GRADE = "#d93025", "#188038", "#1a73e8", "#5f6368", "#e8eaed"
MESES = ["jan.", "fev.", "mar.", "abr.", "mai.", "jun.",
         "jul.", "ago.", "set.", "out.", "nov.", "dez."]
DIAS_SEMANA = ["seg.", "ter.", "qua.", "qui.", "sex.", "sáb.", "dom."]


# ----------------------------------------------------------------------------
# Formatação
# ----------------------------------------------------------------------------

def br(x: float, casas: int = 2) -> str:
    """164405.38 -> '164.405,38'."""
    return f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x: float, casas: int = 2, sinal: bool = True) -> str:
    return (f"{x:+.{casas}%}" if sinal else f"{x:.{casas}%}").replace(".", ",")


def data_curta(d: date) -> str:
    return f"{DIAS_SEMANA[d.weekday()]} {d.day:02d}/{d.month:02d}"


# ----------------------------------------------------------------------------
# Calendário da B3
# ----------------------------------------------------------------------------

def pascoa(ano: int) -> date:
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


def feriados_b3(ano: int) -> set[date]:
    p = pascoa(ano)
    fixos = [(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2),
             (11, 15), (12, 24), (12, 25), (12, 31)] + ([(11, 20)] if ano >= 2024 else [])
    moveis = [p - timedelta(48), p - timedelta(47),   # Carnaval
              p - timedelta(2), p + timedelta(60)]    # Sexta-feira Santa, Corpus Christi
    return {date(ano, m, d) for m, d in fixos} | set(moveis)


def eh_pregao(d: date) -> bool:
    return d.weekday() < 5 and d not in feriados_b3(d.year)


def proximo_pregao(d: date) -> date:
    d += timedelta(1)
    while not eh_pregao(d):
        d += timedelta(1)
    return d


def pregoes_entre(inicio: date, fim: date) -> list[date]:
    """Pregões no intervalo (inicio, fim]."""
    dias, d = [], inicio
    while True:
        d = proximo_pregao(d)
        if d > fim:
            return dias
        dias.append(d)


def fechamento_b3(d: date) -> datetime:
    """Fim do pregão: 16h de Nova York (17h de Brasília no verão dos EUA, 18h no inverno)."""
    return datetime(d.year, d.month, d.day, 16, tzinfo=ZoneInfo("America/New_York")).astimezone(TZ)


# ----------------------------------------------------------------------------
# Dados
# ----------------------------------------------------------------------------

def _limpar(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna(subset=["Close"])


def baixar(ticker: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    intra = yf.download(ticker, period="60d", interval="5m", auto_adjust=True, progress=False)
    diario = yf.download(ticker, period="1y", interval="1d", auto_adjust=True, progress=False)
    if intra.empty or diario.empty:
        raise SystemExit(f"Sem dados do Yahoo Finance para {ticker}.")
    intra, diario = _limpar(intra), _limpar(diario)
    intra.index = intra.index.tz_convert(TZ)
    return intra, diario


@dataclass
class Grade:
    """Preços de 5 min organizados em pregão × barra do dia.

    A última coluna ("FECH") é o fechamento OFICIAL: as barras do Yahoo param às 17:00,
    mas no inverno dos EUA a B3 só fecha às 18:00.
    """
    dias: list[date]
    rotulos: list[str]     # início de cada barra ("10:00" … "16:55") e, no fim, "FECH"
    P: np.ndarray          # preço de fechamento de cada barra (D × B)
    b_agora: int           # última barra disponível do último pregão

    @property
    def B(self) -> int:
        return len(self.rotulos)

    @property
    def abertura(self) -> time:
        return datetime.strptime(self.rotulos[0], "%H:%M").time()

    def hora_barra(self, b: int, d: date | None = None) -> time:
        """Horário em que o preço da barra b é conhecido (fim da barra)."""
        if self.rotulos[b] == "FECH":
            return fechamento_b3(d or self.dias[-1]).time()
        return (datetime.strptime(self.rotulos[b], "%H:%M") + timedelta(minutes=BARRA_MIN)).time()

    @property
    def ultima_barra(self) -> time:
        return self.hora_barra(self.B - 2)


def montar_grade(intra: pd.DataFrame, diario: pd.DataFrame, agora: datetime) -> Grade:
    fim = intra.index + pd.Timedelta(minutes=BARRA_MIN)
    # o Yahoo atrasa ~15 min: uma barra só está completa depois desse atraso. Sem isto, o preço
    # da última barra mudaria de uma execução para outra.
    intra = intra[fim + ATRASO <= pd.Timestamp(agora)]
    rot = intra.index.strftime("%H:%M")
    tab = intra["Close"].groupby([intra.index.date, rot]).last().unstack()
    tab = tab.loc[:, tab.notna().mean() > 0.5].sort_index(axis=1)   # só o pregão regular

    P = tab.to_numpy(float)
    b_agora = int(np.where(~np.isnan(P[-1]))[0].max())
    P = pd.DataFrame(P).ffill(axis=1).to_numpy(copy=True)
    dias = list(tab.index)
    oficial = {t.date(): float(c) for t, c in diario["Close"].items()}
    # só vale como fechamento oficial depois que o pregão terminou de verdade
    fech = np.array([oficial.get(d, np.nan) if agora >= fechamento_b3(d) + FOLGA_FECH else np.nan for d in dias])
    P[-1, b_agora + 1:] = np.nan                  # o futuro de hoje continua desconhecido
    P = np.column_stack([P, fech])
    if not np.isnan(fech[-1]):
        b_agora = P.shape[1] - 1
    return Grade(dias, list(tab.columns) + ["FECH"], P, b_agora)


# ----------------------------------------------------------------------------
# Alvo da previsão
# ----------------------------------------------------------------------------

@dataclass
class Alvo:
    dia: date
    barra: int
    descricao: str
    hora: time | None = None   # só quando o horário não coincide com o fim da barra


def _barra_do_horario(g: Grade, h: time) -> int:
    minutos = (h.hour * 60 + h.minute) - (g.abertura.hour * 60 + g.abertura.minute)
    return int(np.clip(round(minutos / BARRA_MIN) - 1, 0, g.B - 2))


def _primeiro_pregao_com(agora: datetime, h: time) -> date:
    d = agora.date()
    if not (eh_pregao(d) and datetime.combine(d, h, TZ) > agora):
        d = proximo_pregao(d)
    return d


def resolver_alvo(texto: str, g: Grade, agora: datetime) -> Alvo:
    t = texto.strip().lower().replace("ã", "a")
    if t == "fechamento":
        d = agora.date()
        if not (eh_pregao(d) and agora < fechamento_b3(d)):
            d = proximo_pregao(d)
        return Alvo(d, g.B - 1, f"Fechamento {data_curta(d)} · {fechamento_b3(d):%H:%M}")
    if t == "abertura":
        d = _primeiro_pregao_com(agora, g.abertura)
        return Alvo(d, 0, f"Abertura {data_curta(d)} · {g.hora_barra(0):%H:%M}")
    if t in ("fechamento-amanha", "fechamento amanha"):
        d = proximo_pregao(agora.date())
        return Alvo(d, g.B - 1, f"Fechamento {data_curta(d)} · {fechamento_b3(d):%H:%M}")

    m = re.fullmatch(r"(?:(amanha)|(\d{1,2})/(\d{1,2})(?:/(\d{4}))?)?\s*(\d{1,2})[:h](\d{2})", t)
    if not m:
        raise SystemExit(f"Alvo não reconhecido: {texto!r}. Veja --help.")
    amanha, dia, mes, ano, hh, mm = m.groups()
    h = time(int(hh), int(mm))
    if not (g.abertura < h <= g.ultima_barra):
        raise SystemExit(f"Escolha entre {g.abertura:%H:%M} e {g.ultima_barra:%H:%M}, ou use --alvo fechamento.")
    if amanha:
        d = proximo_pregao(agora.date())
    elif dia:
        d = date(int(ano or agora.year), int(mes), int(dia))
        if not eh_pregao(d):
            raise SystemExit(f"{d:%d/%m/%Y} não é dia de pregão na B3.")
    else:
        d = _primeiro_pregao_com(agora, h)
    b = _barra_do_horario(g, h)
    return Alvo(d, b, f"{data_curta(d)} · {g.hora_barra(b):%H:%M}")


def perguntar_alvo() -> str:
    print("\nPara quando é a previsão?")
    opcoes = {"1": "fechamento", "2": "abertura", "3": "fechamento-amanha"}
    print("  1) Fechamento do pregão atual\n  2) Abertura do próximo pregão\n"
          "  3) Fechamento do próximo pregão\n  4) Outro horário (ex.: 15:30, amanha 11:00, 27/11 16:00)")
    escolha = input("Escolha [1]: ").strip() or "1"
    if escolha in opcoes:
        return opcoes[escolha]
    return input("Horário: ").strip() if escolha == "4" else escolha


# ----------------------------------------------------------------------------
# Modelo
# ----------------------------------------------------------------------------

MODELOS = {
    "Passeio aleatório": "o melhor palpite é o preço atual (variação esperada zero)",
    "Deriva histórica": "variação média observada nesse mesmo horizonte nos pregões anteriores",
    "Momento intradiário": "variação do dia até agora × β estimado nos pregões anteriores",
}


def prever_media(nome: str, x: float, xs: np.ndarray, ys: np.ndarray) -> float:
    if nome == "Deriva histórica":
        return float(ys.mean())
    if nome == "Momento intradiário":
        return float(x * (xs @ ys) / (xs @ xs))
    return 0.0


@dataclass
class Previsao:
    alvo: Alvo
    k: int
    preco_agora: float
    hora_agora: datetime
    mu: float
    erros: np.ndarray     # erros (log) do modelo escolhido no backtest, nesse mesmo horizonte
    modelo: str
    metricas: dict = field(default_factory=dict)
    cobertura80: float = float("nan")
    cobertura50: float = float("nan")
    n_teste: int = 0
    n_cobertura: int = 0     # pregões em que o acerto da faixa foi medido (menos que n_teste)
    dias_teste: np.ndarray = field(default_factory=lambda: np.array([], int))   # pregão de cada erro

    @property
    def sem_direcao(self) -> bool:
        """True quando nenhum modelo achou tendência: o preço central é só o ponto de PARTIDA.

        Nesse caso o centro é igual ao preço atual por definição. Não significa "vai ficar
        parado", e por isso o gráfico e o texto destacam a faixa.
        """
        return self.modelo == "Passeio aleatório"

    def preco(self, erro: float = 0.0) -> float:
        return self.preco_agora * math.exp(self.mu + erro)

    def faixa(self, nivel: float) -> tuple[float, float]:
        """Faixa central (ex.: 0.80) tirada dos erros que já ocorreram."""
        lo, hi = np.quantile(self.erros, [(1 - nivel) / 2, (1 + nivel) / 2])
        return self.preco(lo), self.preco(hi)

    @property
    def prob_alta(self) -> float:
        # +1 / +2 evitam afirmar 0% ou 100% com poucos casos
        return float(((self.mu + self.erros > 0).sum() + 1) / (len(self.erros) + 2))


def prever(g: Grade, alvo: Alvo, agora: datetime) -> Previsao:
    D, b0 = len(g.dias), g.b_agora
    hoje = g.dias[-1]
    k = 0 if alvo.dia == hoje else len(pregoes_entre(hoje, alvo.dia))
    if alvo.dia < hoje or (k == 0 and alvo.barra <= b0):
        raise SystemExit("O horário escolhido já passou — escolha um alvo no futuro.")

    # Amostras análogas: em cada pregão passado, do mesmo horário de agora até o mesmo alvo.
    amostras = []   # (dia, x = variação do dia até agora, y = variação até o alvo, preço de partida)
    for d in range(MIN_HISTORICO, D - k):
        if np.isnan([g.P[d + k, alvo.barra], g.P[d, b0], g.P[d - 1, -1]]).any():
            continue
        x = math.log(g.P[d, b0] / g.P[d - 1, -1])
        y = math.log(g.P[d + k, alvo.barra] / g.P[d, b0])
        amostras.append((d, x, y, g.P[d, b0]))
    if len(amostras) < MIN_TREINO + 5:
        raise SystemExit("Histórico intradiário insuficiente para este alvo.")
    dias_a, xs, ys, precos = map(np.array, zip(*amostras))

    def treino(j: int) -> np.ndarray:
        # só usa amostras cujo resultado já era conhecido no momento da previsão j
        fim = dias_a + k
        return (fim < dias_a[j]) | ((fim == dias_a[j]) & (alvo.barra <= b0))

    # Backtest walk-forward dos modelos de tendência
    preds = {n: [] for n in MODELOS}
    teste = []
    for j in range(len(amostras)):
        m = treino(j)
        if m.sum() < MIN_TREINO:
            continue
        teste.append(j)
        for n in MODELOS:
            preds[n].append(prever_media(n, xs[j], xs[m], ys[m]))
    teste = np.array(teste)
    yt, pt = ys[teste], precos[teste]
    metricas = {}
    for n in MODELOS:
        p = np.array(preds[n])
        erro = pt * np.abs(np.exp(yt) - np.exp(p))
        acerto_dir = np.mean(np.sign(p) == np.sign(yt)) if np.any(p != 0) else float("nan")
        metricas[n] = {"mae": erro.mean(), "mae_pct": np.mean(np.abs(np.exp(yt) - np.exp(p))),
                       "direcao": acerto_dir}
    base = metricas["Passeio aleatório"]["mae"]
    melhor = min(metricas, key=lambda n: metricas[n]["mae"])
    # só troca o passeio aleatório se errar ≥ 2% menos E acertar a direção mais que uma moeda
    if metricas[melhor]["mae"] > 0.98 * base or not metricas[melhor]["direcao"] > 0.5:
        melhor = "Passeio aleatório"

    # Faixas: quantis dos próprios erros do backtest (sem nenhuma medida de volatilidade).
    # A cobertura é medida do mesmo jeito, usando só os erros anteriores a cada dia.
    err = yt - np.array(preds[melhor])

    def cobertura(nivel: float) -> tuple[float, int]:
        ok = []
        for i in range(MIN_TREINO, len(err)):
            # com k > 0 os erros mais recentes ainda não eram conhecidos no dia i
            z = err[[treino(teste[i])[j] for j in teste]]
            if len(z) >= MIN_TREINO:
                lo, hi = np.quantile(z, [(1 - nivel) / 2, (1 + nivel) / 2])
                ok.append(lo <= err[i] <= hi)
        return (float(np.mean(ok)) if ok else float("nan")), len(ok)

    (cob80, n_cob), (cob50, _) = cobertura(0.80), cobertura(0.50)
    x_agora = math.log(g.P[-1, b0] / g.P[-2, -1])
    mu = prever_media(melhor, x_agora, xs, ys)
    hora = datetime.combine(hoje, g.hora_barra(b0), TZ)
    return Previsao(alvo, k, float(g.P[-1, b0]), min(hora, agora), mu, err, melhor, metricas,
                    cob80, cob50, len(teste), n_cob, dias_a[teste])


def previsoes_do_dia(g: Grade, agora: datetime) -> tuple[Previsao, Previsao, float | None]:
    """(previsão do início do dia, previsão do final do dia, valor real do início).

    Pregão em andamento: o início já passou, então a previsão dele é a que seria feita com o
    fechamento anterior (sem nenhum dado de hoje), para comparar com o valor real.
    Fora do pregão: as duas são para o próximo pregão e o valor real é None.
    """
    hoje = g.dias[-1]
    em_andamento = agora.date() == hoje and g.rotulos[g.b_agora] != "FECH"
    if em_andamento or (eh_pregao(agora.date()) and agora < fechamento_b3(agora.date())):
        d = agora.date()
    else:
        d = proximo_pregao(agora.date())
    ini = Alvo(d, 0, f"Início do dia {data_curta(d)} · {g.hora_barra(0):%H:%M}")
    fim = Alvo(d, g.B - 1, f"Final do dia {data_curta(d)} · {fechamento_b3(d):%H:%M}")
    if not em_andamento:
        return prever(g, ini, agora), prever(g, fim, agora), None
    ontem = Grade(g.dias[:-1], g.rotulos, g.P[:-1], g.B - 1)        # só o que se sabia antes de hoje
    if np.isnan(ontem.P[-1, -1]):
        raise SystemExit("O Yahoo ainda não publicou o fechamento oficial do pregão anterior.")
    antes = datetime.combine(ontem.dias[-1], time(23, 0), TZ)
    return prever(ontem, ini, antes), prever(g, fim, agora), float(g.P[-1, 0])


def previsoes_de_amanha(g: Grade, agora: datetime) -> tuple[Previsao, Previsao]:
    """(início, final) do próximo pregão: amanhã ou, se não houver pregão, o seguinte."""
    d = proximo_pregao(agora.date())
    ini = Alvo(d, 0, f"Início do dia {data_curta(d)} · {g.hora_barra(0):%H:%M}")
    fim = Alvo(d, g.B - 1, f"Final do dia {data_curta(d)} · {fechamento_b3(d):%H:%M}")
    return prever(g, ini, agora), prever(g, fim, agora)


def previsao_as(g: Grade, d: date, h: time, agora: datetime) -> Previsao:
    """Previsão para o horário `h` do pregão `d` (hoje ou um pregão futuro).

    Aceita qualquer hora:
      - até a abertura: vale o início do dia (primeiro preço que existe);
      - durante o pregão: a barra de 5 min que termina em `h` ou logo depois;
      - entre a última barra do Yahoo (17:00) e o fechamento: estimativa entre os dois;
      - do fechamento em diante: vale o fechamento.
    """
    fech = fechamento_b3(d).time()
    nome = f"{'Hoje' if d == agora.date() else 'Amanhã' if d == agora.date() + timedelta(1) else 'Próximo pregão'} {data_curta(d)}"
    if h >= fech:
        return prever(g, Alvo(d, g.B - 1, f"{nome} · {fech:%H:%M} (fechamento)"), agora)
    if h > g.ultima_barra:
        return _previsao_entre_17h_e_fechamento(g, d, h, nome, agora)
    minutos = (h.hour * 60 + h.minute) - (g.abertura.hour * 60 + g.abertura.minute)
    b = int(np.clip(math.ceil(minutos / BARRA_MIN) - 1, 0, g.B - 2))
    inicio = " (início do dia)" if h <= g.abertura else ""
    return prever(g, Alvo(d, b, f"{nome} · {g.hora_barra(b, d):%H:%M}{inicio}"), agora)


def _previsao_entre_17h_e_fechamento(g: Grade, d: date, h: time, nome: str, agora: datetime) -> Previsao:
    """O Yahoo não tem preços entre 17:00 e o fechamento: estima em linha reta entre os dois.

    A tendência e os quantis dos erros são combinados conforme a distância de `h` a cada ponta.
    """
    def minutos(t: time) -> int:
        return t.hour * 60 + t.minute

    ini, fim = minutos(g.ultima_barra), minutos(fechamento_b3(d).time())
    w = (minutos(h) - ini) / (fim - ini)            # 0 = última barra, 1 = fechamento
    pf = prever(g, Alvo(d, g.B - 1, ""), agora)
    q = np.linspace(0, 1, len(pf.erros))
    if d == g.dias[-1] and g.b_agora >= g.B - 2:    # o preço das 17:00 já é conhecido: erro zero nessa ponta
        mu0, e0, modelo0 = 0.0, np.zeros(len(q)), pf.modelo
    else:
        p0 = prever(g, Alvo(d, g.B - 2, ""), agora)
        mu0, e0, modelo0 = p0.mu, np.quantile(p0.erros, q), p0.modelo
    alvo = Alvo(d, g.B - 1, f"{nome} · {h:%H:%M} (estimado)", h)
    # só é "sem direção" se nenhuma das duas pontas tiver tendência
    modelo = modelo0 if pf.modelo == "Passeio aleatório" else pf.modelo
    return replace(pf, alvo=alvo, modelo=modelo, mu=(1 - w) * mu0 + w * pf.mu,
                   erros=(1 - w) * e0 + w * np.quantile(pf.erros, q))


# ----------------------------------------------------------------------------
# Visualização (estilo Google Finanças)
# ----------------------------------------------------------------------------

def plotar(g: Grade, diario: pd.DataFrame, prev: Previsao, saida: Path) -> plt.Figure:
    hoje, b0, k = g.dias[-1], g.b_agora, prev.k
    ant = diario[diario.index.date < hoje]
    fech_ant = float(ant["Close"].iloc[-1]) if len(ant) else float(g.P[-2, -1])
    dia_hoje = diario[diario.index.date == hoje]
    precos_hoje = g.P[-1, :b0 + 1]
    abertura = float(dia_hoje["Open"].iloc[0]) if len(dia_hoje) else float(precos_hoje[0])
    alta = float(max(precos_hoje.max(), dia_hoje["High"].max() if len(dia_hoje) else 0))
    baixa = float(min(precos_hoje.min(), dia_hoje["Low"].min() if len(dia_hoje) else np.inf))
    ultimo_ano = diario[diario.index >= diario.index[-1] - pd.Timedelta(days=365)]

    variacao = prev.preco_agora - fech_ant
    cor = VERDE if variacao >= 0 else VERMELHO
    fundo = "#e6f4ea" if variacao >= 0 else "#fce8e6"

    plt.rcParams.update({"font.family": "sans-serif", "font.size": 11})
    fig = plt.figure(figsize=(13, 8.4), facecolor="white")

    # Cabeçalho
    fig.text(0.06, 0.945, "Ibovespa", fontsize=28, weight="bold", color="#202124")
    fig.text(0.06, 0.912, "INDEXBVMF: IBOV", fontsize=12, color=CINZA)
    fig.text(0.06, 0.835, br(prev.preco_agora), fontsize=34, color="#202124")
    seta = "▲" if variacao >= 0 else "▼"
    fig.text(0.305, 0.848, f" {seta} {pct(abs(variacao) / fech_ant, sinal=False)} ", fontsize=15,
             color=cor, weight="bold", bbox=dict(boxstyle="round,pad=0.35", fc=fundo, ec="none"))
    fig.text(0.415, 0.848, f"{'+' if variacao >= 0 else '−'}{br(abs(variacao))} hoje",
             fontsize=15, color=cor, weight="bold")
    h = prev.hora_agora
    fig.text(0.06, 0.805, f"{h.day} de {MESES[h.month - 1]}, {h:%H:%M} BRT · Yahoo Finance "
             "(atraso ~15 min)", fontsize=10.5, color=CINZA)

    # Cartão da previsão
    alvo_preco = prev.preco()
    var_alvo = alvo_preco / prev.preco_agora - 1
    cor_prev = CINZA if abs(var_alvo) < 5e-5 else VERDE if var_alvo > 0 else VERMELHO
    cx, cy = 0.62, 0.80
    fig.patches.append(plt.Rectangle((cx, cy), 0.33, 0.165, transform=fig.transFigure,
                                     fc="#e8f0fe", ec=AZUL, lw=1.2, zorder=0))
    fig.text(cx + 0.015, cy + 0.135, f"PREVISÃO · {prev.alvo.descricao}", fontsize=10.5,
             color=AZUL, weight="bold")
    lo80, hi80 = prev.faixa(0.80)
    if prev.sem_direcao:
        # sem tendência: o destaque é a faixa, não um número "exato" igual ao preço atual
        fig.text(cx + 0.015, cy + 0.085, f"{br(lo80, 0)} a {br(hi80, 0)}", fontsize=22,
                 color="#202124", weight="bold")
        fig.text(cx + 0.015, cy + 0.048, f"Sem direção definida · ponto de partida: {br(alvo_preco, 0)}",
                 fontsize=10.5, color="#202124")
    else:
        fig.text(cx + 0.015, cy + 0.085, br(alvo_preco), fontsize=24, color="#202124", weight="bold")
        fig.text(cx + 0.19, cy + 0.093, pct(var_alvo), fontsize=13, color=cor_prev, weight="bold")
        fig.text(cx + 0.015, cy + 0.048, f"Faixa de 80%: {br(lo80, 0)} a {br(hi80, 0)}",
                 fontsize=10.5, color="#202124")
    # a taxa de acerto REAL da faixa fica à vista (antes o cartão prometia "80% de chance")
    acerto = "" if math.isnan(prev.cobertura80) else f"Faixa acertou {prev.cobertura80:.0%} no teste · "
    fig.text(cx + 0.015, cy + 0.015, f"{acerto}Chance de subir: {prev.prob_alta:.0%}",
             fontsize=10.5, color="#202124")

    # Eixo x contínuo, sem as noites: posição = pregão × (duração + espaço) + minutos
    fim_h = fechamento_b3(hoje)
    dur = (fim_h.hour * 60 + fim_h.minute) - (g.abertura.hour * 60 + g.abertura.minute)
    espaco = dur * 0.06

    def pos(j: int, b: int | None) -> float:
        return j * (dur + espaco) + (0 if b is None else dur if b == g.B - 1 else (b + 1) * BARRA_MIN)

    ax = fig.add_axes([0.06, 0.27, 0.80, 0.47])
    xs_hoje = [pos(0, None)] + [pos(0, b) for b in range(b0 + 1)]
    ys_hoje = [fech_ant] + list(precos_hoje)
    ax.plot(xs_hoje, ys_hoje, color=cor, lw=2, zorder=3)

    # Leque de incerteza até o alvo
    caminho = [(0, b0)]
    for j in range(k + 1):
        ini = b0 + 1 if j == 0 else 0
        fim = prev.alvo.barra if j == k else g.B - 1
        caminho += [(j, b) for b in range(ini, fim + 1)]
    # quantis dos movimentos passados, do mesmo horário de agora até cada ponto do caminho.
    # Usa os MESMOS pregões dos erros do alvo: com outra amostra, o leque dava um salto no fim.
    dt = prev.dias_teste
    faixas = {n: ([0.0], [0.0]) for n in (0.80, 0.50)}
    for j, b in caminho[1:]:
        y = np.log(g.P[dt + j, b] / g.P[dt, b0])
        y = y[np.isfinite(y)]
        for n, (lo, hi) in faixas.items():
            ql, qh = np.quantile(y, [(1 - n) / 2, (1 + n) / 2])
            lo.append(ql); hi.append(qh)
    m = prev.mu * np.arange(len(caminho)) / (len(caminho) - 1)
    xp = [pos(j, b) for j, b in caminho]
    if prev.alvo.hora:                        # horário entre a última barra e o fechamento
        xp[-1] = pos(k, None) + (prev.alvo.hora.hour - g.abertura.hour) * 60 + prev.alvo.hora.minute - g.abertura.minute
    P0 = prev.preco_agora
    for n, alfa in ((0.80, 0.12), (0.50, 0.22)):
        lo, hi = (np.array(v) for v in faixas[n])
        lo[-1], hi[-1] = (math.log(v / P0) - prev.mu for v in prev.faixa(n))   # no alvo: erros do modelo
        ax.fill_between(xp, P0 * np.exp(m + lo), P0 * np.exp(m + hi), color=AZUL, alpha=alfa, lw=0,
                        label=f"Faixa de {n:.0%}")
    ax.plot(xp, P0 * np.exp(m), color=AZUL, lw=1.8, ls="--",
            label="Preço de partida (sem tendência)" if prev.sem_direcao else "Previsão central")
    ax.scatter([xp[0]], [P0], s=45, color=cor, zorder=5)
    if not prev.sem_direcao:             # sem tendência não há um ponto a destacar no alvo
        ax.scatter([xp[-1]], [alvo_preco], s=70, color=AZUL, zorder=5, edgecolor="white", lw=1.5)
    rotulo = f"{br(lo80, 0)} a {br(hi80, 0)}" if prev.sem_direcao else br(alvo_preco)
    ax.annotate(f"{rotulo}\n{prev.alvo.descricao.split('·')[-1].strip()}",
                (xp[-1], alvo_preco), xytext=(-12, 22), textcoords="offset points", ha="right",
                fontsize=10.5, color="#202124",
                bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#dadce0"))

    # Fechamento anterior (linha pontilhada, como no Google)
    x_max = pos(k, g.B - 1)
    ax.axhline(fech_ant, color=CINZA, ls=(0, (1, 3)), lw=1.2)
    ax.text(x_max, fech_ant, f"Fech. ant.\n{br(fech_ant)}", ha="right", va="top",
            fontsize=10, color=CINZA)

    # Eixos
    ticks, labels = [], []
    for j in range(k + 1):
        for hh in range(g.abertura.hour, fim_h.hour + 1, 2):
            if j < k and hh == fim_h.hour:
                continue                      # não encavala com o 10:00 do pregão seguinte
            ticks.append(pos(j, None) + (hh - g.abertura.hour) * 60 - g.abertura.minute)
            labels.append(f"{hh:02d}:00")
        if k:
            d = hoje if j == 0 else pregoes_entre(hoje, prev.alvo.dia)[j - 1]
            ax.text(pos(j, None) + dur / 2, 1.01, data_curta(d), transform=ax.get_xaxis_transform(),
                    ha="center", fontsize=10.5, color=CINZA, weight="bold")
            if j:
                ax.axvline(pos(j, None) - espaco / 2, color="#dadce0", lw=1)
    ax.set_xticks(ticks, labels)
    ax.set_xlim(-dur * 0.01, x_max + dur * 0.01)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: br(v, 0)))
    ax.grid(axis="y", color=GRADE)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color("#9aa0a6")
    ax.tick_params(colors=CINZA, length=0)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.07), frameon=False, fontsize=10, ncol=3)

    # Quadro de informações
    itens = [("Abertura", br(abertura)), ("Alta", br(alta)), ("Baixa", br(baixa)),
             ("Fech. ant.", br(fech_ant)),
             ("Alt 52 sem", br(ultimo_ano["High"].max())), ("Bai 52 sem", br(ultimo_ano["Low"].min()))]
    for i, (rot, val) in enumerate(itens):
        col, lin = divmod(i, 2)
        x, y = 0.06 + col * 0.30, 0.15 - lin * 0.045
        fig.text(x, y, rot, fontsize=12, color="#202124")
        fig.text(x + 0.22, y, val, fontsize=12, color=CINZA, ha="right")
    mae = prev.metricas[prev.modelo]["mae"]
    fig.text(0.06, 0.035,
             f"Previsão: modelo “{prev.modelo}” · erro médio histórico ±{br(mae, 0)} pts · "
             f"a faixa de 80% acertou {prev.cobertura80:.0%} das vezes no teste "
             f"({prev.n_cobertura} pregões). Não é recomendação de investimento.",
             fontsize=9.5, color=CINZA)

    fig.savefig(saida, dpi=130, facecolor="white")
    return fig


# ----------------------------------------------------------------------------
# Embasamento (impresso depois do gráfico)
# ----------------------------------------------------------------------------

def explicar_centro(p: Previsao) -> None:
    """Explica o número central quando não há tendência, e a taxa de acerto real da faixa."""
    if p.sem_direcao:
        print("   Sem direção definida: o número central é só o preço de partida.")
    if not math.isnan(p.cobertura80):
        print(f"   No teste, a faixa de 80% acertou {p.cobertura80:.0%} das vezes ({p.n_cobertura} pregões).")


def imprimir_resultado(prev: Previsao) -> None:
    """Resultado em destaque: previsão central e faixa de 80% (calculadas a cada execução)."""
    linha = "=" * 78
    lo, hi = prev.faixa(0.80)
    print(f"\n{linha}\nRESULTADO DA PREVISÃO — IBOVESPA\n{linha}")
    print(f"{prev.alvo.descricao}\n")
    print(f"   {br(prev.preco(), 0)} pontos, com faixa de 80% entre {br(lo, 0)} e {br(hi, 0)}")
    explicar_centro(prev)
    print(f"   Calculado com o preço das {prev.hora_agora:%H:%M} de {prev.hora_agora:%d/%m} "
          f"({br(prev.preco_agora, 0)} pontos).")


def imprimir_previsoes_do_dia(ini: Previsao, fim: Previsao, real_ini: float | None) -> None:
    """Previsões do início e do final do dia, em destaque."""
    linha = "=" * 78
    print(f"\n{linha}\nPREVISÃO DO DIA — IBOVESPA\n{linha}")
    for p, real in ((ini, real_ini), (fim, None)):
        lo, hi = p.faixa(0.80)
        print(f"\n{p.alvo.descricao}")
        print(f"   {br(p.preco(), 0)} pontos, com faixa de 80% entre {br(lo, 0)} e {br(hi, 0)}")
        explicar_centro(p)
        print(f"   Calculado com o preço das {p.hora_agora:%H:%M} de {p.hora_agora:%d/%m}.")
        if real is not None:
            print(f"   Já ocorreu: {br(real, 0)} pontos (diferença de {br(abs(real - p.preco()), 0)} pontos, "
                  f"{pct(abs(real / p.preco() - 1), sinal=False)}).")


def imprimir_previsao(titulo: str, previsoes: list[Previsao]) -> None:
    """Só as previsões (sem embasamento), uma embaixo da outra."""
    linha = "=" * 78
    print(f"\n{linha}\n{titulo}\n{linha}")
    for p in previsoes:
        lo, hi = p.faixa(0.80)
        print(f"\n{p.alvo.descricao}")
        print(f"   {br(p.preco(), 0)} pontos, com faixa de 80% entre {br(lo, 0)} e {br(hi, 0)}")
        explicar_centro(p)
        print(f"   Calculado com o preço das {p.hora_agora:%H:%M} de {p.hora_agora:%d/%m} "
              f"({br(p.preco_agora, 0)} pontos).")


def imprimir_embasamento(g: Grade, prev: Previsao) -> None:
    linha = "=" * 78
    a, k = prev.alvo, prev.k
    alvo_dt = datetime.combine(a.dia, g.hora_barra(a.barra, a.dia), TZ)
    rw = prev.metricas["Passeio aleatório"]["mae"]

    print(f"\n{linha}\nEMBASAMENTO DA PREVISÃO — IBOVESPA\n{linha}")
    print(f"""
1. Ponto de partida
   • Último preço: {br(prev.preco_agora)} às {prev.hora_agora:%H:%M} de {prev.hora_agora:%d/%m}
     (barras de 5 min do Yahoo Finance, com atraso de ~15 min).
   • Alvo: {a.descricao} (às {alvo_dt:%H:%M} de {alvo_dt:%d/%m}), atravessando {k} noite(s).

2. Direção (tendência) — escolhida por teste histórico
   • Testamos 3 modelos simulando o passado: em cada um de {prev.n_teste} pregões anteriores,
     prevemos do mesmo horário de agora até o mesmo alvo, usando só dados daquela época:""")
    for n, desc in MODELOS.items():
        mt = prev.metricas[n]
        direcao = "—" if math.isnan(mt["direcao"]) else f"{mt['direcao']:.0%}"
        marca = "  ← escolhido" if n == prev.modelo else ""
        print(f"     - {n}: {desc}.\n       Erro médio {br(mt['mae'], 0)} pts "
              f"({pct(mt['mae_pct'], sinal=False)}) · acerto de direção {direcao}{marca}")
    ganho = 1 - prev.metricas[prev.modelo]["mae"] / rw
    print(f"""   • Regra: um modelo só substitui o passeio aleatório se errar pelo menos 2% menos.
     {'Nenhum superou essa barra; a previsão central é o preço atual.' if prev.modelo == "Passeio aleatório"
      else f'O escolhido errou {ganho:.1%} menos que o passeio aleatório.'}
   • Variação central prevista: {pct(math.exp(prev.mu) - 1)}.

3. Faixas de incerteza (sem volatilidade)
   • Conceito: nenhuma medida de volatilidade é usada. As faixas são os quantis dos erros que o
     próprio modelo cometeu nos {prev.n_teste} pregões de teste, neste mesmo horizonte.
   • Faixa de 50%: {br(prev.faixa(0.50)[0])} a {br(prev.faixa(0.50)[1])}
     → no teste, acertou {prev.cobertura50:.0%} das vezes (ideal: 50%).
   • Faixa de 80%: {br(prev.faixa(0.80)[0])} a {br(prev.faixa(0.80)[1])}
     → no teste, acertou {prev.cobertura80:.0%} das vezes (ideal: 80%).

4. Probabilidade de alta
   • Fração desses erros que deixaria o alvo acima de {br(prev.preco_agora)}: {prev.prob_alta:.0%}.

5. Volatilidade
   • Recurso não analisado na previsão.

6. Limites desta previsão
   • Preço de índice se comporta quase como passeio aleatório: nenhum modelo consegue acertar
     o número exato. O "maior acerto possível" aqui é ter faixas que acertam na frequência
     prometida e só aceitar um sinal de direção quando ele vence o passeio aleatório no teste
     (erro ≥ 2% menor e acerto de direção acima de 50%).
   • O acerto das faixas foi medido em só {prev.n_cobertura} pregões (limite de 60 dias das barras de 5 min do Yahoo):
     essas taxas têm margem de erro de cerca de ±{1.96 * math.sqrt(0.8 * 0.2 / max(prev.n_cobertura, 1)):.0%}.
   • Notícias, decisões do Copom e eventos fora do pregão não entram no modelo.
""")
    print(f"{linha}\nAviso: estimativa estatística, não é recomendação de investimento.\n{linha}")


# ----------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--alvo", help="fechamento | abertura | fechamento-amanha | HH:MM | "
                                  "'amanha HH:MM' | 'DD/MM HH:MM'")
    p.add_argument("--ticker", default="^BVSP")
    p.add_argument("--saida", default="ibovespa_previsao.png")
    p.add_argument("--sem-janela", action="store_true", help="não abrir a janela do gráfico")
    args = p.parse_args()

    alvo_txt = args.alvo or (perguntar_alvo() if sys.stdin.isatty() else "fechamento")
    agora = datetime.now(TZ)
    intra, diario = baixar(args.ticker)
    g = montar_grade(intra, diario, agora)
    prev = prever(g, resolver_alvo(alvo_txt, g, agora), agora)

    plotar(g, diario, prev, Path(args.saida))           # 1º: visualização
    print(f"Gráfico salvo em: {args.saida}")
    imprimir_resultado(prev)                              # 2º: resultado em destaque
    imprimir_embasamento(g, prev)                         # 3º: embasamento
    if not args.sem_janela:
        plt.show()


if __name__ == "__main__":
    main()
