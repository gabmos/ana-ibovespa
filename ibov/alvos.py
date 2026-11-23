"""
ibov/alvos.py — ETAPA 2b DO PROJETO: prever o IBOV em MOMENTOS do dia.

O `modelo.py` responde "onde o dia vai FECHAR?". Este arquivo usa o MESMO
modelo (Ridge, sem volatilidade, mesmos atributos, mesmo walk-forward) para
responder também "onde o índice vai estar em tal momento?". São os momentos
que aparecem no gráfico principal:

  inicio  — início do dia: 11h, depois da 1ª hora de pregão
  fim     — final do dia: o fechamento (17h, ou 18h no horário de inverno de NY)
  amanha  — início do PRÓXIMO pregão: 11h do dia seguinte
  hora    — (opcional) a hora de hoje que o usuário pediu com --hora

Por que "início" = 11h e não 10h? O Yahoo informa como abertura das 10h
praticamente o fechamento anterior (igual em ~98% dos dias, porque as ações
ainda não negociaram). Prever isso seria só repetir um número conhecido. Às
11h existe preço de verdade, com 2 anos de histórico para treinar.

Qual previsão é mostrada?
  • momento que AINDA VAI acontecer -> a previsão mais recente disponível;
  • momento que JÁ aconteceu        -> a previsão das 10h (na abertura)
                                       ao lado do valor real, para comparar.
"""
from __future__ import annotations
from datetime import date, timedelta
import numpy as np
import pandas as pd

from .dados import CORTES, TZ, SerieAsOf, _ts
from .modelo import MIN_TREINO, RETREINO, _ajustar, _prever, atributos, marcar_status

HORAS = (11, 12, 13, 14, 15, 16, 17)   # horas cheias com preço horário no Yahoo
ABRE = 10 * 60                         # abertura do pregão, em minutos desde 0h
ATRASO = pd.Timedelta(minutes=16)      # o Yahoo entrega o IBOV com ~15 min de atraso


def fecha(d) -> int:
    """Minuto em que o pregão de `d` termina (contando o leilão de fechamento).

    A B3 acompanha Nova York: fecha às 16h de lá, que são 17h de Brasília no
    horário de verão americano e 18h no resto do ano (Ofício Circular B3
    050/2026-VNC). Atenção: o Yahoo só traz barras do IBOV até as 17h; entre
    17h e 18h não há preço minuto a minuto, só o fechamento oficial.
    """
    d = pd.Timestamp(d)
    t = pd.Timestamp(d.year, d.month, d.day, 16, tz="America/New_York").tz_convert(TZ)
    return t.hour * 60 + t.minute


# ---------- calendário da B3 (só para saber a data do próximo pregão) ----------
def _pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo gregoriano); dele saem os feriados móveis."""
    a = ano % 19; b, c = divmod(ano, 100); d, e = divmod(b, 4)
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


def proximo_pregao(d: date) -> date:
    """Próximo dia com pregão depois de `d` (pula fins de semana e feriados)."""
    while True:
        d += timedelta(1)
        p = _pascoa(d.year)
        fixos = {(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20),
                 (12, 24), (12, 25), (12, 31)}
        moveis = {p - timedelta(48), p - timedelta(47), p - timedelta(2), p + timedelta(60)}
        fim_ano = date(d.year, 12, 31)                   # último dia útil do ano: a B3 não abre
        while fim_ano.weekday() > 4:
            fim_ano -= timedelta(1)
        if d != fim_ano and d.weekday() < 5 and (d.month, d.day) not in fixos and d not in moveis:
            return d


# ---------- a hora que o usuário digitou ----------
def ler_hora(txt: str, dia=None) -> int:
    """'13:30', '13h30', '13h' ou '13' -> minutos desde 0h. Fora do pregão de
    `dia` (padrão: hoje): mensagem de erro clara."""
    fim = fecha(dia or pd.Timestamp.now(tz=TZ))
    try:
        hh, _, mm = txt.lower().replace("h", ":").rstrip(":").partition(":")
        m = int(hh) * 60 + int(mm or 0)
        assert 0 <= int(mm or 0) < 60
    except (ValueError, AssertionError):
        raise SystemExit(f"Não entendi a hora {txt!r}. Use, por exemplo, 13:30, 13h30 ou 13h.")
    if not ABRE < m <= fim:
        raise SystemExit(f"A hora {txt} está fora do pregão. Escolha entre 10:01 e {fim // 60}:00.")
    return m


def hhmm(m: int) -> str:
    """Minutos desde 0h -> '11h' ou '13h30'."""
    return f"{m // 60}h" + (f"{m % 60:02d}" if m % 60 else "")


# ---------- o que realmente aconteceu em cada momento (para treinar e conferir) ----------
def niveis(dd: dict, hh: dict, agora: pd.Timestamp) -> pd.DataFrame:
    """Uma linha por pregão com o preço do IBOV às 11h…17h e às 11h do pregão
    seguinte ('amanha'). O que ainda não aconteceu em `agora` fica vazio (NaN)."""
    s = SerieAsOf(hh["ibov"])
    # a barra diária de hoje só existe depois do fechamento; as horárias já trazem o dia
    dias = dd["ibov"].index.union(hh["ibov"].index.tz_localize(None).normalize().unique())
    dias = dias[dias >= hh["ibov"].index[0].tz_localize(None).normalize()]
    n = pd.DataFrame(index=dias)
    for h in HORAS:
        ts = [_ts(d, h) for d in dias]
        # 5 min de tolerância: só vale a barra que termina exatamente nessa hora
        n[f"{h}h"] = [s.em(t, "5min") if t + ATRASO <= agora else np.nan for t in ts]
    n["amanha"] = n["11h"].shift(-1)                     # 11h do pregão seguinte
    n["dia_seguinte"] = pd.Series(dias, index=dias).shift(-1)
    return n


# ---------- previsão de um alvo, sempre fora da amostra ----------
def prever_alvo(p: pd.DataFrame, niv: pd.DataFrame, corte: str, alvo: str,
                agora: pd.Timestamp) -> pd.DataFrame:
    """Walk-forward igual ao de modelo.py, mas para o alvo pedido.

    corte — quando a previsão é feita ('abertura', '11h'…)
    alvo  — '11h'…'17h' ou 'amanha'
    Devolve uma linha por pregão: p_ref, fech_ant, prev, lo, hi e real.
    """
    q = marcar_status(p, agora)
    dias = np.sort(q.loc[q["disponivel"], "dia"].unique())
    q = q[q["disponivel"] & (q["corte"] == corte)].sort_values("dia").copy()
    q["nivel"] = q["dia"].map(niv[alvo])
    # instante em que o alvo passa a ser conhecido
    if alvo == "amanha":
        base, hora = q["dia"].map(niv["dia_seguinte"]), 11
    else:
        base, hora = q["dia"], int(alvo[:-1])
    q["t_alvo"] = base.dt.tz_localize(TZ) + pd.Timedelta(hours=hora)
    q["alvo"] = np.log(q["nivel"] / q["p_ref"])          # a resposta que o modelo aprende
    cols = [c for c in atributos(q) if c not in ("nivel", "t_alvo", "fechado", "disponivel")]
    saidas = []
    for ini in range(MIN_TREINO, len(dias), RETREINO):
        te = q[q["dia"].isin(dias[ini:ini + RETREINO])]
        if te.empty:
            continue
        # regra "as-of": só treina com respostas já conhecidas na 1ª previsão do bloco
        t0 = pd.to_datetime(te["t_corte"]).min()
        tr = q[(q["t_alvo"] <= t0) & q["alvo"].notna()]
        if len(tr) < MIN_TREINO * .8:
            continue
        m, z = _ajustar(tr, cols)
        saidas.append(_prever(m, z, te, cols).assign(real=te["nivel"].to_numpy()))
    if not saidas:
        return pd.DataFrame(columns=["dia", "p_ref", "fech_ant", "prev", "lo", "hi", "real"])
    return pd.concat(saidas)[["dia", "p_ref", "fech_ant", "prev", "lo", "hi", "real"]]


def _qualidade(t: pd.DataFrame) -> tuple[float, float]:
    """(erro médio, fração dos dias em que o real caiu na faixa) fora da amostra."""
    a = t.dropna(subset=["real"])
    if a.empty:
        return np.nan, np.nan
    return float((a.prev / a.real - 1).abs().mean()), float(((a.real >= a.lo) & (a.real <= a.hi)).mean())


def _interpolar(m: int, a: tuple, b: tuple) -> dict:
    """Previsão para uma hora quebrada, entre dois pontos (minuto, prev, lo, hi).

    O valor central anda em linha reta. A largura da faixa cresce com a raiz do
    tempo (a incerteza aumenta rápido no começo e depois mais devagar).
    """
    f = (m - a[0]) / (b[0] - a[0])
    c = a[1] + f * (b[1] - a[1])
    larg = lambda i: np.sqrt((1 - f) * (a[i] - a[1]) ** 2 + f * (b[i] - b[1]) ** 2)
    return {"prev": c, "lo": c - larg(2), "hi": c + larg(3)}


def preco_em(m5: pd.DataFrame | None, t: pd.Timestamp) -> float:
    """Preço real no instante t, pelas barras de 5 min (NaN se não houver)."""
    if m5 is None or m5.empty:
        return np.nan
    fim = m5.index + pd.Timedelta(minutes=5)             # o Close só é conhecido no fim da barra
    i = int(fim.searchsorted(t, side="right")) - 1
    return float(m5["Close"].iloc[i]) if i >= 0 and t - fim[i] <= pd.Timedelta(minutes=10) else np.nan


# ---------- junta tudo o que o gráfico principal precisa ----------
def montar(p: pd.DataFrame, r: pd.DataFrame, dd: dict, hh: dict, m5: pd.DataFrame | None, dia: str,
           agora: pd.Timestamp, hora: int | None = None, feita: str | None = None) -> dict | None:
    """Monta as 3 previsões (ou 4, com --hora) do pregão `dia`.

    r     — previsões de fechamento do walk_forward (usadas no alvo 'fim')
    hora  — minutos desde 0h, ou None
    feita — força o horário em que a previsão é feita (None = automático)
    Devolve None se não houver previsão para esse dia.
    """
    d = pd.Timestamp(dia)
    hoje = r[r["dia"] == d]
    if hoje.empty:
        return None
    niv = niveis(dd, hh, agora)
    disp = [str(c) for c in hoje["corte"]]               # horários já disponíveis, em ordem
    cedo = "abertura" if "abertura" in disp else disp[0]
    tarde = feita if feita in disp else disp[-1]
    fech_ant = float(hoje["fech_ant"].iloc[0])
    FECHA = fecha(d)                                     # 17h ou 18h, conforme a época do ano
    hora = None if hora is None else min(hora, FECHA)
    minuto = lambda c: ABRE if CORTES[c] is None or CORTES[c][0] < 10 else CORTES[c][0] * 60
    cache: dict = {}

    def linha(corte: str, alvo: str) -> dict | None:
        """Previsão do dia para (corte, alvo) + qualidade histórica."""
        if (corte, alvo) not in cache:
            if alvo == "fim":
                t = r[r["corte"].astype(str) == corte].rename(columns={"fech": "real"})
            else:
                t = prever_alvo(p, niv, corte, alvo, agora)
            x = t[t["dia"] == d]
            if x.empty:
                cache[corte, alvo] = None
            else:
                erro, cob = _qualidade(t)
                cache[corte, alvo] = dict(x.iloc[0][["p_ref", "prev", "lo", "hi", "real"]].astype(float),
                                          erro=erro, cobertura=cob, feita=corte)
        return cache[corte, alvo]

    def na_hora(corte: str, m: int) -> dict | None:
        """Previsão para uma hora qualquer de hoje (cheia ou quebrada)."""
        if m == FECHA:
            return linha(corte, "fim")
        if m <= 11 * 60:
            return linha(corte, "11h")                   # dentro da 1ª hora: usa o nível das 11h
        if m % 60 == 0:
            return linha(corte, hhmm(m))
        ant, prox = m // 60 * 60, m // 60 * 60 + 60
        b = linha(corte, "fim" if prox == FECHA else hhmm(prox))
        if b is None:
            return None
        if ant <= minuto(corte):                         # o ponto de partida é o preço já conhecido
            pa = (minuto(corte), b["p_ref"], b["p_ref"], b["p_ref"])
        else:
            a = linha(corte, hhmm(ant))
            if a is None:
                return None
            pa = (ant, a["prev"], a["lo"], a["hi"])
        # erro e cobertura mostrados: os da hora cheia seguinte (a estimativa mais conservadora)
        return dict(b, **_interpolar(m, pa, (prox, b["prev"], b["lo"], b["hi"])), real=np.nan)

    def escolher(m: int, fn) -> dict | None:
        """Momento passado -> previsão das 10h; momento futuro -> a mais recente."""
        passou = _ts(d, m // 60, m % 60) + ATRASO <= agora
        if feita in disp and minuto(feita) < m:
            return fn(feita)
        return fn(cedo if passou or minuto(tarde) >= m else tarde)

    seg = niv["dia_seguinte"].get(d)
    seg = pd.Timestamp(proximo_pregao(d.date())) if pd.isna(seg) else seg
    pontos = [("inicio", "Início do dia", 11 * 60, escolher(11 * 60, lambda c: linha(c, "11h"))),
              ("fim", "Final do dia", FECHA, escolher(FECHA, lambda c: linha(c, "fim"))),
              ("amanha", "Início do próximo pregão", 11 * 60, linha(tarde, "amanha"))]
    if hora is not None:
        pontos.insert(1, ("hora", f"Às {hhmm(hora)}", hora, escolher(hora, lambda c: na_hora(c, hora))))

    saida = []
    for chave, nome, m, x in pontos:
        if x is None:
            continue
        x = dict(x, chave=chave, nome=nome, min=m)
        if chave == "hora":
            t = _ts(d, m // 60, m % 60)
            x["real"] = preco_em(m5, t) if t <= agora else np.nan
        # "amanhã" é comparado com o fim de hoje; os demais, com o fechamento anterior
        x["base"] = fech_ant
        saida.append(x)
    fim = next(x for x in saida if x["chave"] == "fim")
    for x in saida:
        if x["chave"] == "amanha":
            x["base"] = fim["real"] if np.isfinite(fim["real"]) else fim["prev"]
    # previsão das 10h para o fechamento, citada no cartão quando já existe uma mais nova
    manha = hoje[hoje["corte"].astype(str) == cedo]["prev"].iloc[0]

    # linha do preço real: 5 min se houver; senão, hora a hora
    if m5 is not None and (m5.index.tz_localize(None).normalize() == d).any():
        b, passo = m5[m5.index.tz_localize(None).normalize() == d], 5
    else:
        b, passo = hh["ibov"][hh["ibov"].index.tz_localize(None).normalize() == d], 60
    fim_b = b.index + pd.Timedelta(minutes=passo)
    b, fim_b = b[fim_b <= agora], fim_b[fim_b <= agora]
    precos = [[ABRE, fech_ant]] + [[int(t.hour * 60 + t.minute), float(v)] for t, v in zip(fim_b, b["Close"])]
    encerrado = bool(hoje["fech"].notna().all())
    if encerrado:                                        # leva a linha até o fechamento oficial
        precos.append([FECHA, float(hoje["fech"].iloc[0])])
    return {"dia": d, "seguinte": seg, "fech_ant": fech_ant, "pontos": saida, "precos": precos, "fecha": FECHA,
            "manha": float(manha), "encerrado": encerrado, "eh_hoje": d.date() == agora.date()}
