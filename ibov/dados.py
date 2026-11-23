"""
ibov/dados.py — ETAPA 1 DO PROJETO: obter os dados e montar o "painel as-of".

O que este arquivo faz
----------------------
1. `baixar()` busca no Yahoo Finance (biblioteca `yfinance`) as cotações:
     • DIÁRIAS desde 2010 (IBOV, S&P 500, petróleo, dólar global, juros
       americanos, ADRs brasileiras, bolsas da Ásia/Europa…);
     • HORÁRIAS dos últimos ~2 anos (limite do Yahoo para barras de 1h) dos
       ativos que negociam durante o pregão brasileiro.
   Tudo é salvo em `data/*.parquet` (cache), para não depender da internet
   em toda execução. Se o download falhar, o cache é usado.

2. `painel()` transforma essas séries numa TABELA DE TREINO com uma linha por
   (pregão, horário de corte). "Horário de corte" é o momento em que a
   previsão é feita: na véspera às 20h, às 10h (na abertura) e de hora
   em hora das 11h às 16h.

A regra de ouro: "as-of" (sem olhar o futuro)
---------------------------------------------
Cada linha do painel só pode conter informação que REALMENTE existia no
horário de corte. Exemplo: a linha "13h do dia 10" pode usar o preço do IBOV
das 13h, mas nunca o das 14h. Se essa regra fosse quebrada, o modelo pareceria
ótimo no teste e seria inútil na vida real (o chamado "vazamento de dados").
A classe `SerieAsOf` é quem garante isso para os dados horários.
"""
from __future__ import annotations
import warnings
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")      # o yfinance emite muitos avisos irrelevantes

TZ = "America/Sao_Paulo"               # todo horário do projeto é no fuso de Brasília
RAIZ = Path(__file__).resolve().parent.parent   # pasta raiz do projeto
CACHE = RAIZ / "data"                  # onde ficam os arquivos .parquet baixados

# Séries DIÁRIAS: apelido -> código no Yahoo Finance.
DIARIOS = {"ibov": "^BVSP",      # o próprio IBOVESPA (alvo da previsão)
           "ewz": "EWZ",         # ETF de Brasil negociado em Nova York
           "sp": "^GSPC",        # S&P 500
           "oil": "BZ=F",        # petróleo Brent
           "dxy": "DX-Y.NYB",    # força do dólar contra outras moedas
           "tnx": "^TNX",        # juros de 10 anos dos EUA
           "vale": "VALE", "pbr": "PBR", "itub": "ITUB",   # ADRs de Vale, Petrobras, Itaú
           "n225": "^N225", "hsi": "^HSI",                 # Japão e Hong Kong
           "stoxx": "^STOXX50E",                           # Europa
           "eem": "EEM"}                                   # ETF de emergentes
# Séries HORÁRIAS: usadas para saber "como o mundo andou" até o horário de corte.
HORARIOS = {"ibov": "^BVSP", "ewz": "EWZ", "brl": "BRL=X",   # BRL=X = dólar/real
            "es": "ES=F",                                    # futuro do S&P 500
            "pbr": "PBR", "vale": "VALE", "itub": "ITUB", "eem": "EEM", "oil": "BZ=F"}
# Horários de corte: nome -> (hora, minuto). `None` = véspera às 20h.
CORTES = {"vespera": None, "abertura": (10, 0), "11h": (11, 0), "12h": (12, 0), "13h": (13, 0),
          "14h": (14, 0), "15h": (15, 0), "16h": (16, 0)}


ATRASO = pd.Timedelta(minutes=16)      # o IBOV chega do Yahoo com ~15 min de atraso
FOLGA_FECH = pd.Timedelta(minutes=45)  # espera após o fim do pregão para confiar no fechamento


def fechamento_b3(dia) -> pd.Timestamp:
    """Fim do pregão: 16h de Nova York, ou seja, 17h de Brasília no horário de
    verão americano e 18h no resto do ano (nov–mar)."""
    d = pd.Timestamp(dia)
    return pd.Timestamp(d.year, d.month, d.day, 16, tz="America/New_York").tz_convert(TZ)


def _so_completas(x: pd.DataFrame, nome: str, pref: str, agora: pd.Timestamp | None = None) -> pd.DataFrame:
    """Descarta barras ainda em formação antes de gravar no cache.

    Sem isto, o preço parcial de hoje ficaria salvo e amanhã seria lido como
    se fosse o fechamento oficial."""
    agora = agora or pd.Timestamp.now(tz=TZ)
    if pref == "h":
        return x[x.index + pd.Timedelta(hours=1) + (ATRASO if nome == "ibov" else pd.Timedelta(0)) <= agora]
    if nome == "ibov":
        hoje = agora.tz_localize(None).normalize()
        if agora < fechamento_b3(hoje) + FOLGA_FECH:
            return x[x.index < hoje]
    return x


def baixar(atualizar: bool = True) -> tuple[dict, dict]:
    """Baixa (ou lê do cache) todas as séries.

    Devolve dois dicionários {apelido: DataFrame com Open/High/Low/Close/Volume}:
    o primeiro com as séries diárias e o segundo com as horárias.
    Com `atualizar=False`, só baixa o que ainda não existe em cache.
    """
    CACHE.mkdir(exist_ok=True)
    dd, hh = {}, {}
    # O mesmo laço serve para os dois tipos; o prefixo do arquivo diferencia: d_*.parquet / h_*.parquet
    for pref, mapa, saida in (("d", DIARIOS, dd), ("h", HORARIOS, hh)):
        for nome, tic in mapa.items():
            arq = CACHE / f"{pref}_{nome}.parquet"
            if atualizar or not arq.exists():
                try:
                    if pref == "d":
                        x = yf.Ticker(tic).history(start="2010-01-01", interval="1d", auto_adjust=False)
                        # data "pura" (sem fuso e sem hora) para alinhar ativos de bolsas diferentes
                        x.index = x.index.tz_localize(None).normalize()
                    else:
                        # 729 dias é o máximo que o Yahoo devolve em barras de 1 hora;
                        # prepost=True inclui pré e pós-mercado americano (ADRs reagem antes do Brasil abrir)
                        x = yf.Ticker(tic).history(period="729d", interval="1h", prepost=True, auto_adjust=False)
                        x = x.tz_convert(TZ)
                    x = x[["Open", "High", "Low", "Close", "Volume", "Dividends"]].dropna(subset=["Close"])
                    x = x[~x.index.duplicated(keep="last")].sort_index()   # remove barras repetidas
                    if len(x) < 100:
                        raise ValueError(f"poucos dados para {tic}: {len(x)}")
                    x = _so_completas(x, nome, pref)
                    # guarda o histórico antigo: o Yahoo descarta barras horárias com mais de
                    # 2 anos e, sem isso, o treino mudaria a cada download
                    if arq.exists():
                        velho = pd.read_parquet(arq)
                        x = pd.concat([velho[velho.index < x.index[0]], x]).fillna({"Dividends": 0.0})
                    x.to_parquet(arq)
                except Exception as e:
                    # Sem internet ou Yahoo fora do ar: segue com o cache, se existir.
                    if not arq.exists():
                        raise RuntimeError(f"Falha ao baixar {tic} e sem cache") from e
                    print(f"[aviso] {tic}: usando cache ({e})")
            saida[nome] = pd.read_parquet(arq)
    return dd, hh


def baixar_5min(atualizar: bool = True) -> pd.DataFrame | None:
    """IBOV em barras de 5 min (~60 dias, limite do Yahoo).

    NÃO entra no modelo: serve só para desenhar o preço do dia e conferir o
    valor real numa hora quebrada (ex.: 13h30). Sem dados, devolve None e o
    gráfico usa as barras de 1 hora.
    """
    arq = CACHE / "m5_ibov.parquet"
    if atualizar:
        try:
            x = yf.Ticker("^BVSP").history(period="60d", interval="5m", auto_adjust=False).tz_convert(TZ)
            x = x[["Open", "High", "Low", "Close"]].dropna(subset=["Close"])
            if x.empty:
                raise ValueError("sem barras de 5 min")
            x.to_parquet(arq)
        except Exception as e:
            print(f"[aviso] IBOV 5 min: usando cache ({e})")
    return pd.read_parquet(arq) if arq.exists() else None


class SerieAsOf:
    """Consulta "qual era o último preço conhecido no instante t?".

    Uma barra horária do Yahoo é rotulada pelo seu INÍCIO (a barra "13:00" vai
    de 13:00 a 14:00) e seu `Close` só é conhecido no FIM. Por isso calculamos
    o fim de cada barra e, numa consulta em t, só aceitamos barras cujo fim já
    passou (fim <= t). Assim nunca usamos uma barra ainda em formação.
    """

    def __init__(self, df: pd.DataFrame):
        ini = df.index
        # fim da barra = início + 1h, a não ser que a próxima barra comece antes disso
        # (acontece em barras parciais de abertura/fechamento)
        fim = pd.Series(ini + pd.Timedelta(hours=1), index=ini)
        prox = pd.Series(ini, index=ini).shift(-1)
        fim = fim.where(prox.isna() | (fim <= prox), prox)
        self.fim = pd.DatetimeIndex(fim.values, tz="UTC") if fim.dt.tz is None else pd.DatetimeIndex(fim)
        # guardamos os instantes como inteiros (nanossegundos UTC) para busca binária rápida
        self.fim = self.fim.tz_convert("UTC").as_unit("ns").asi8
        self.px = df["Close"].to_numpy(float)

    def em(self, t: pd.Timestamp, max_idade: str = "5D") -> float:
        """Preço da última barra encerrada até `t`. Se essa barra for mais
        velha que `max_idade` (ex.: ativo sem negociação), devolve NaN."""
        ts = t.tz_convert("UTC").as_unit("ns").value
        i = int(np.searchsorted(self.fim, ts, side="right")) - 1   # última barra com fim <= t
        if i < 0 or ts - self.fim[i] > pd.Timedelta(max_idade).value:
            return np.nan
        return float(self.px[i])


def _ts(dia: pd.Timestamp, h: int, m: int = 0) -> pd.Timestamp:
    """Monta o instante dia + hh:mm no fuso de Brasília."""
    return pd.Timestamp(dia.year, dia.month, dia.day, h, m, tz=TZ)


def atributos_diarios(dd: dict) -> pd.DataFrame:
    """Indicadores técnicos do IBOV calculados no FECHAMENTO de cada pregão.

    Como dependem do fechamento, só podem ser usados a partir do pregão
    SEGUINTE (o `painel()` cuida disso usando a linha do dia anterior).
    Todos os retornos são em log: log(preço_hoje / preço_antes).
    """
    i = dd["ibov"]; c = np.log(i.Close); r = c.diff()
    f = pd.DataFrame(index=i.index)
    for k in (1, 2, 3, 5, 10, 21):
        f[f"ret{k}"] = c.diff(k)                       # retorno acumulado de k pregões (momento)
    # onde fechou dentro da faixa do dia: 0 = na mínima, 1 = na máxima
    f["pos_no_dia"] = ((i.Close - i.Low) / (i.High - i.Low).replace(0, np.nan)).fillna(.5)
    f["dist_mm21"] = c - c.rolling(21).mean()          # distância da média móvel de 21 dias
    # RSI de 14 dias (força relativa: perto de 1 = sobrecomprado, perto de 0 = sobrevendido)
    g = r.clip(lower=0).rolling(14).mean(); p = (-r.clip(upper=0)).rolling(14).mean()
    f["rsi14"] = g / (g + p)
    return f


def painel(dd: dict, hh: dict, dias: list | None = None) -> pd.DataFrame:
    """Monta a tabela de treino: uma linha por (pregão, horário de corte).

    Colunas principais
      dia, corte, t_corte  -> qual pregão e em que momento a previsão é feita
      fech_ant             -> fechamento do pregão anterior
      p_ref                -> último preço do IBOV conhecido no corte
                              (na véspera/abertura é o próprio fech_ant)
      fech                 -> fechamento do dia (é a resposta; NÃO é atributo)
      alvo                 -> log(fech / p_ref): quanto o índice ainda vai andar
                              do corte até o fechamento. É isto que o modelo prevê.
    Atributos (o que o modelo "vê")
      ret*, rsi14…         -> indicadores do IBOV até o pregão anterior
      d_sp, d_dxy…          -> variação do último dia das bolsas globais
      on_*                 -> quanto cada ativo horário andou desde o fechamento
                              anterior do IBOV até o corte ("overnight" + manhã)
      ret_intra, ret_1h    -> quanto o próprio IBOV já andou no dia e na última hora
    """
    ib = dd["ibov"]; fd = atributos_diarios(dd)
    # Antes da abertura o Yahoo ainda não tem a barra diária de hoje. Sem ela não
    # existiria linha de hoje e a previsão da manhã sumiria; por isso criamos a
    # linha com fechamento vazio (NaN = "ainda não aconteceu").
    from .alvos import proximo_pregao            # importado aqui para evitar importação circular
    hoje = pd.Timestamp.now(tz=TZ).tz_localize(None).normalize()
    if ib.index[-1] < hoje and pd.Timestamp(proximo_pregao(hoje.date() - pd.Timedelta(days=1))) == hoje:
        ib = pd.concat([ib, pd.DataFrame(np.nan, index=[hoje], columns=ib.columns)])
    S = {k: SerieAsOf(v) for k, v in hh.items()}
    # só monta linhas a partir de quando há dados horários (+12 dias de folga)
    ini_h = hh["ibov"].index[0].tz_localize(None).normalize() + pd.Timedelta(days=12)
    idx = ib.index
    # segurança: se falta o fechamento do pregão anterior, não inventa uma previsão errada
    if idx[-1] == hoje and pd.Timestamp(proximo_pregao(idx[-2].date())) < hoje:
        print(f"[aviso] falta o fechamento oficial entre {idx[-2]:%d/%m} e hoje; sem previsão para hoje.")
        ib = ib.iloc[:-1]; idx = ib.index
    div = {k: dd[k]["Dividends"] for k in ("ewz", "vale", "pbr", "itub", "eem") if "Dividends" in dd[k]}
    linhas = []
    for n in range(1, len(idx)):
        dia = idx[n]
        if dia < ini_h or (dias is not None and dia not in dias):
            continue
        ant = idx[n - 1]; pa = float(ib.Close.iloc[n - 1])     # pregão anterior e seu fechamento
        # --- parte comum a todos os cortes do dia ---
        base = {"dia": dia, "fech_ant": pa, "fech": float(ib.Close.iloc[n]),
                "dias_gap": (dia - ant).days,       # 1 = dia útil seguido; 3 = depois de fim de semana
                "dsem": dia.dayofweek}              # dia da semana (0 = segunda)
        base.update(fd.loc[ant].to_dict())          # indicadores do pregão ANTERIOR (já conhecidos)
        t_ref = fechamento_b3(ant)                  # instante do fechamento anterior (17h ou 18h)
        refs = {k: S[k].em(t_ref) for k in S}       # preço de cada ativo nesse instante
        # bolsas globais: só fechamentos de datas < dia (Ásia do próprio dia fica de fora, conservador)
        for k in ("sp", "n225", "hsi", "stoxx", "dxy", "tnx"):
            s = dd[k].Close; s = s[s.index < dia]
            base[f"d_{k}"] = float(np.log(s.iloc[-1] / s.iloc[-2]))
        # --- uma linha para cada horário de corte ---
        for nome, hm in CORTES.items():
            # véspera = 20h do dia corrido anterior; demais = hora marcada no próprio dia
            t = _ts(dia - pd.Timedelta(days=1), 20, 0) if hm is None else _ts(dia, *hm)
            L = dict(base, corte=nome, t_corte=t)
            for k in S:
                if k != "ibov":
                    # variação do ativo k entre o fechamento anterior do IBOV e o corte
                    v = S[k].em(t)
                    if k in div:                     # ADR/ETF "ex-dividendo": devolve o valor pago
                        ex = div[k][(div[k].index > ant) & (div[k].index <= t.tz_localize(None))]
                        v += float(ex.sum())
                    L[f"on_{k}"] = float(np.log(v / refs[k])) if refs[k] > 0 else np.nan
            if hm is None or hm[0] <= 10:
                # antes da abertura o IBOV ainda não negociou: referência = fechamento anterior
                L["p_ref"] = pa; L["ret_intra"] = 0.0; L["ret_1h"] = 0.0
            else:
                p = S["ibov"].em(t, "5min")         # preço do IBOV no corte (no máx. 5 min de idade)
                if not np.isfinite(p):
                    continue                         # sem preço confiável: pula esta linha
                L["p_ref"] = p; L["ret_intra"] = float(np.log(p / pa))
                p1 = S["ibov"].em(t - pd.Timedelta(hours=1), "5min")
                L["ret_1h"] = float(np.log(p / p1)) if np.isfinite(p1) else L["ret_intra"]
            L["alvo"] = float(np.log(L["fech"] / L["p_ref"]))
            linhas.append(L)
    return pd.DataFrame(linhas)
