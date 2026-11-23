"""
ibov/modelo.py — ETAPA 2 DO PROJETO: prever e medir a qualidade.

Regra de ouro: só usamos um modelo onde ele COMPROVADAMENTE erra menos do que
o palpite ingênuo ("fecha no preço atual"). Testamos mais de 800 combinações
(linear, árvores, ARIMA, GARCH…) em dados até 12/11/2025, e:

  • ABERTURA (10h): há sinal real. O que EWZ, dólar/real e VALE andaram em
    Nova York desde o último fechamento da B3 antecipa parte do gap de abertura.
    Usamos uma REGRESSÃO RIDGE com só essas 3 entradas.
  • VÉSPERA e 11h…17h: nenhum modelo bateu o ingênuo de forma consistente.
    Então a previsão É o último preço conhecido — qualquer correção extra
    seria ruído e aumentaria o erro.

Modelo SEM VOLATILIDADE
-----------------------
Nenhuma medida de volatilidade entra no modelo: nem como atributo (a lista
`ATRIBUTOS` só tem retornos) nem na largura da faixa.

Faixa de 80% e chance de alta
-----------------------------
Usam os ÚLTIMOS 120 ERROS que o modelo cometeu em dias que ele não viu no
treino, sem escala e sem supor curva normal:
  • faixa = previsão + (percentis 10% e 90% desses erros);
  • P(alta) = fração desses erros que deixaria o fechamento acima do anterior.

Walk-forward (o teste honesto)
------------------------------
O modelo é treinado só com pregões ANTERIORES e prevê o bloco seguinte de 5
pregões; depois re-treina e repete. Toda previsão mostrada é assim.
Não há sorteio em nenhuma etapa: os mesmos dados dão sempre o mesmo resultado.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .dados import ATRASO, CORTES, FOLGA_FECH, TZ, fechamento_b3

# Entradas do modelo da abertura: retornos desde o fechamento anterior da B3.
ATRIBUTOS = ("on_ewz", "on_brl", "on_vale")
# Medidas de volatilidade — proibidas no modelo (há um teste que garante isso).
ATRIB_VOLATILIDADE = {"vol5", "vol21", "amplitude", "vix_nivel", "d_vix"}
COM_MODELO = {"abertura"}      # cortes em que a Ridge bate o ingênuo; nos demais, preço atual
MIN_TREINO = 250               # pregões mínimos (~1 ano) antes da 1ª previsão fora da amostra
RETREINO = 5                   # re-treina a cada 5 pregões (~1 semana)
JANELA_ERROS = 120             # nº de erros recentes usados na faixa e na P(alta)
Q_BAIXO, Q_ALTO = 0.10, 0.90   # quantis do intervalo: 10% e 90% => faixa de 80%


def atributos(p: pd.DataFrame) -> list[str]:
    """Colunas usadas como entrada do modelo (só retornos, nada de volatilidade)."""
    return [c for c in ATRIBUTOS if c in p.columns]


def marcar_status(p: pd.DataFrame, agora: pd.Timestamp | None = None) -> pd.DataFrame:
    """Acrescenta duas colunas de controle, comparando com o relógio `agora`:

    `fechado`    — o pregão terminou há pelo menos FOLGA_FECH e existe `fech`:
                   a linha pode ser usada para TREINAR e para AVALIAR.
    `disponivel` — o dado do horário de corte já chegou, então dá para PREVER
                   sem usar o futuro. O IBOV do Yahoo tem ~15 min de atraso: a
                   previsão das 13h só existe a partir das 13h16.
    """
    agora = agora or pd.Timestamp.now(tz=TZ)
    p = p.copy()
    fim = p["dia"].map({d: fechamento_b3(d) + FOLGA_FECH for d in p["dia"].unique()})
    p["fechado"] = (fim <= agora) & p["fech"].notna()
    intradia = p["corte"].astype(str).str.fullmatch(r"\d+h")
    t = pd.to_datetime(p["t_corte"]).dt.tz_convert(TZ)
    p["disponivel"] = t.where(~intradia, t + ATRASO) <= agora
    return p


class _Ingenuo:
    """Prevê variação zero: o fechamento é o último preço conhecido."""

    def predict(self, X):
        return np.zeros(len(X))


def _ridge(tr: pd.DataFrame, cols: list[str]):
    """Ridge com entradas e alvo aparados nos 0,5% extremos DO TREINO."""
    X = tr[cols].fillna(0.0)                                  # faltante = "sem variação"
    X = X.clip(X.quantile(.005), X.quantile(.995), axis=1).to_numpy()
    y = tr["alvo"].clip(*tr["alvo"].quantile([.005, .995])).to_numpy()
    return make_pipeline(StandardScaler(), RidgeCV(alphas=np.logspace(-1, 4, 30))).fit(X, y)


def _ajustar(tr: pd.DataFrame, cols: list[str]):
    """Treina o modelo de um corte e devolve (modelo, erros fora do treino)."""
    tr = tr.sort_values("dia")
    if tr["corte"].iloc[0] not in COM_MODELO or not cols:
        return _Ingenuo(), tr["alvo"].to_numpy()[-JANELA_ERROS:]
    # erros honestos: treina na parte antiga e mede nos últimos JANELA_ERROS dias
    k = min(JANELA_ERROS, len(tr) // 2)
    ant, rec = tr.iloc[:-k], tr.iloc[-k:]
    z = rec["alvo"].to_numpy() - _ridge(ant, cols).predict(rec[cols].fillna(0.0).to_numpy())
    return _ridge(tr, cols), z[np.isfinite(z)]


def _prever(m, z, te: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Aplica o modelo nas linhas `te` e monta a tabela de previsões."""
    mu = m.predict(te[cols].fillna(0.0).to_numpy())          # alvo previsto (log-retorno)
    ql, qh = np.quantile(z, [Q_BAIXO, Q_ALTO])               # erros típicos para baixo/para cima
    pref, fa = te["p_ref"].to_numpy(), te["fech_ant"].to_numpy()
    # P(fech > fech_ant): o fechamento fica acima da véspera se  mu + z > log(fa/pref).
    # Contamos quantos erros históricos z satisfazem isso.
    limiar = np.log(fa / pref) - mu
    # (+1 e +2 evitam dizer 0% ou 100%: 120 erros não bastam para ter certeza)
    prob = ((z[None, :] > limiar[:, None]).sum(axis=1) + 1) / (len(z) + 2)
    return pd.DataFrame({
        "dia": te["dia"].to_numpy(), "corte": te["corte"].to_numpy(),
        "t_corte": te["t_corte"].to_numpy(), "p_ref": pref, "fech_ant": fa,
        # o fechamento real só é exposto se o pregão já acabou
        "fech": np.where(te["fechado"], te["fech"], np.nan),
        "prev": pref * np.exp(mu),                    # fechamento previsto, em pontos
        "lo": pref * np.exp(mu + ql),                 # limite inferior da faixa de 80%
        "hi": pref * np.exp(mu + qh),                 # limite superior da faixa de 80%
        "prob_alta": prob, "fora_amostra": True,
    })


def walk_forward(p: pd.DataFrame, agora: pd.Timestamp | None = None) -> pd.DataFrame:
    """Gera previsões fora da amostra para todos os pregões após os primeiros
    MIN_TREINO, inclusive o pregão em andamento (só nos cortes já disponíveis).

    Devolve uma linha por (dia, corte) com: prev, lo, hi, prob_alta, p_ref,
    fech_ant e fech (NaN se o pregão ainda não fechou).
    """
    p = marcar_status(p, agora)
    p = p[p["disponivel"]].sort_values(["dia", "corte"])     # descarta cortes ainda no futuro
    cols = atributos(p)
    dias = np.sort(p["dia"].unique())
    saidas = []
    for corte in CORTES:                                      # um modelo por horário
        pc = p[p["corte"] == corte]
        # blocos de RETREINO pregões: treina com tudo antes do bloco, prevê o bloco
        for ini in range(MIN_TREINO, len(dias), RETREINO):
            bloco = dias[ini:ini + RETREINO]
            tr = pc[(pc["dia"] < bloco[0]) & pc["fechado"]]   # só passado e só dias encerrados
            te = pc[pc["dia"].isin(bloco)]
            if len(tr) < MIN_TREINO * .8 or te.empty:
                continue
            m, z = _ajustar(tr, cols)
            saidas.append(_prever(m, z, te, cols))
    r = pd.concat(saidas, ignore_index=True)
    # ordena os cortes na ordem cronológica do dia (e não alfabética)
    r["corte"] = pd.Categorical(r["corte"], categories=list(CORTES), ordered=True)
    return r.sort_values(["dia", "corte"]).reset_index(drop=True)


def metricas(r: pd.DataFrame) -> pd.DataFrame:
    """Qualidade fora da amostra por horário, só nos dias já encerrados.

    mae_pct          erro absoluto médio do fechamento previsto, em %
    mae_ingenuo_pct  idem para o palpite ingênuo "fecha no preço atual (p_ref)"
                     — se o modelo não bate isto, ele não está agregando valor
    acerto_direcao   % de dias em que previsão e real ficaram do mesmo lado
                     do fechamento anterior (ambos alta ou ambos baixa)
    cobertura_80     % de dias em que o real caiu dentro da faixa de 80%
                     (o ideal é ficar perto de 80%)
    """
    a = r.dropna(subset=["fech"])
    # previsão igual ao fechamento anterior não aponta direção: não conta como acerto nem erro
    sinal = np.sign(a.prev - a.fech_ant)
    acerto = (sinal == np.sign(a.fech - a.fech_ant)).astype(float).where(sinal != 0)
    g = a.assign(
        erro_pct=(a.prev / a.fech - 1).abs() * 100,
        erro_ing_pct=(a.p_ref / a.fech - 1).abs() * 100,
        acerto_dir=acerto,
        na_banda=(a.fech >= a.lo) & (a.fech <= a.hi),
    ).groupby("corte", observed=True)
    return pd.DataFrame({
        "n": g.size(), "mae_pct": g.erro_pct.mean(), "mae_ingenuo_pct": g.erro_ing_pct.mean(),
        "acerto_direcao": g.acerto_dir.mean(), "cobertura_80": g.na_banda.mean(),
    })


def corte_para_hora(hora: str | None) -> str:
    """Traduz o que o usuário digita em `--hora` para um horário de corte.

    None / 'diario'  -> 'abertura' (visão diária, previsão das 10h — o padrão)
    'vespera', '13h' -> o próprio corte
    '13:30', '13'    -> o último corte que já tinha acontecido nessa hora (13h)
    antes das 10h    -> 'vespera';  depois de 16h -> '16h'
    """
    if hora is None or hora.lower() in ("diario", "diária", "diaria", "d"):
        return "abertura"
    if hora in CORTES:
        return hora
    h = hora.lower().replace("h", ":").rstrip(":")       # '13h30' -> '13:30', '13h' -> '13'
    hh, _, mm = h.partition(":")
    alvo = int(hh) * 60 + int(mm or 0)                     # tudo em minutos desde 0h
    validos = [(v[0] * 60 + v[1], k) for k, v in CORTES.items() if v and v[0] * 60 + v[1] <= alvo]
    if not validos:
        return "vespera" if alvo < 10 * 60 else "abertura"
    return max(validos)[1]
