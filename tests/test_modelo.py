"""
Testes automáticos. Rodar com:  .venv/bin/python -m pytest -q tests

Eles verificam as garantias mais importantes do projeto:
  • a tradução de "hora digitada" -> horário de corte;
  • que o walk-forward NUNCA usa informação do futuro;
  • que o relatório de texto é gerado nos dois casos (pregão aberto e encerrado);
  • que nenhuma medida de volatilidade entra no modelo;
  • as previsões por momento (início, fim, próximo pregão e --hora) do gráfico.
Usam o painel salvo em data/painel.parquet (não precisam de internet).
"""
import pandas as pd
import pytest
from ibov import alvos
from ibov.dados import CACHE, TZ, baixar
from ibov.modelo import corte_para_hora, metricas, walk_forward, MIN_TREINO
from ibov.relatorio import gerar_relatorio


@pytest.fixture(scope="module")
def painel():
    return pd.read_parquet(CACHE / "painel.parquet")


@pytest.mark.parametrize("hora,corte", [(None, "abertura"), ("diario", "abertura"), ("08:00", "vespera"),
                                        ("10:30", "abertura"), ("13:30", "13h"), ("16h", "16h"), ("18", "16h")])
def test_corte_para_hora(hora, corte):
    """Sem hora = visão diária; hora livre = último corte já ocorrido."""
    assert corte_para_hora(hora) == corte


def test_walk_forward_nao_usa_futuro(painel):
    """Simula estar às 12h30 de um pregão e confere que nada do futuro vaza."""
    p = painel
    dias = sorted(p.dia.unique())
    corte = dias[MIN_TREINO + 30]
    agora = pd.Timestamp(corte).tz_localize(TZ) + pd.Timedelta(hours=12, minutes=30)
    r = walk_forward(p[p.dia <= corte], agora)
    hoje = r[r.dia == corte]
    # às 12h30, só os cortes até 12h podem existir
    assert set(hoje.corte.astype(str)) == {"vespera", "abertura", "11h", "12h"}
    # o fechamento do dia ainda não aconteceu, então não pode aparecer
    assert hoje.fech.isna().all()
    # previsões passadas não mudam quando dados posteriores entram
    r2 = walk_forward(p, agora + pd.Timedelta(days=400))
    a = r[r.dia < dias[MIN_TREINO + 21]].set_index(["dia", "corte"]).prev
    b = r2.set_index(["dia", "corte"]).prev.reindex(a.index)
    pd.testing.assert_series_equal(a, b)


def test_relatorio_aberto_e_encerrado(painel):
    """O texto sai nos dois cenários, com as seções esperadas."""
    dias = sorted(painel.dia.unique())
    d = dias[-5]
    agora_aberto = pd.Timestamp(d).tz_localize(TZ) + pd.Timedelta(hours=12, minutes=30)
    r = walk_forward(painel[painel.dia <= d], agora_aberto)
    txt = gerar_relatorio(r, metricas(r), str(d.date()), "abertura", agora_aberto, salvar=False)
    assert "EM ANDAMENTO" in txt and "PREVISÃO MAIS RECENTE" in txt and "RESULTADO DO DIA" not in txt

    agora_fechado = agora_aberto + pd.Timedelta(hours=8)
    r = walk_forward(painel[painel.dia <= d], agora_fechado)
    txt = gerar_relatorio(r, metricas(r), str(d.date()), "abertura", agora_fechado, salvar=False)
    assert "ENCERRADO" in txt and "RESULTADO DO DIA" in txt and "Fechamento real" in txt


def test_modelo_sem_volatilidade(painel):
    """Nenhuma medida de volatilidade pode entrar no modelo."""
    from ibov.modelo import ATRIB_VOLATILIDADE, atributos
    usados = set(atributos(painel))
    assert not usados & ATRIB_VOLATILIDADE
    assert not any(c.startswith("vol") or "vix" in c or c == "amplitude" for c in usados)


def test_fechamento_acompanha_nova_york():
    """17h no horário de verão dos EUA, 18h no resto do ano."""
    assert alvos.fecha("2026-09-15") == 17 * 60 and alvos.fecha("2026-11-23") == 18 * 60


@pytest.mark.parametrize("txt,minutos", [("13:30", 810), ("13h30", 810), ("13h", 780), ("13", 780)])
def test_ler_hora(txt, minutos):
    assert alvos.ler_hora(txt, "2026-11-23") == minutos


@pytest.mark.parametrize("txt", ["09:00", "17:30", "abc", "13:75"])
def test_ler_hora_invalida(txt):
    """Fora do pregão (em setembro ele fecha às 17h) ou texto inválido: erro claro."""
    with pytest.raises(SystemExit):
        alvos.ler_hora(txt, "2026-09-15")


def test_proximo_pregao_pula_feriado():
    """20/11/2026 (sexta) é feriado: depois de quinta 19 vem segunda 23."""
    assert str(alvos.proximo_pregao(pd.Timestamp("2026-11-19").date())) == "2026-11-23"


def test_momentos_do_grafico(painel):
    """As 3 previsões aparecem sempre; com hora, são 4. O que não aconteceu não tem real."""
    dd, hh = baixar(False)
    d = "2026-09-15"
    agora = pd.Timestamp("2026-09-15 14:30", tz=TZ)
    p = painel[painel.dia <= d]
    r = walk_forward(p, agora)
    g = alvos.montar(p, r, dd, hh, None, d, agora)
    assert [x["chave"] for x in g["pontos"]] == ["inicio", "fim", "amanha"]
    x = {x["chave"]: x for x in alvos.montar(p, r, dd, hh, None, d, agora, hora=15 * 60 + 30)["pontos"]}
    assert len(x) == 4 and all(v["lo"] < v["prev"] < v["hi"] for v in x.values())
    assert x["inicio"]["real"] > 0 and x["inicio"]["feita"] == "abertura"   # já passou: previsão da manhã
    assert x["fim"]["feita"] == "14h"                                       # futuro: a mais recente
    assert all(pd.isna(x[k]["real"]) for k in ("hora", "fim", "amanha"))


def test_alvos_nao_usam_futuro(painel):
    """Previsões passadas (inclusive 'amanhã') não mudam quando entram dados novos."""
    dd, hh = baixar(False)
    dias = sorted(painel.dia.unique())
    d = dias[MIN_TREINO + 30]
    t1 = pd.Timestamp(d).tz_localize(TZ) + pd.Timedelta(hours=12, minutes=30)
    t2 = t1 + pd.Timedelta(days=200)
    for alvo in ("15h", "amanha"):
        a = alvos.prever_alvo(painel[painel.dia <= d], alvos.niveis(dd, hh, t1), "11h", alvo, t1)
        b = alvos.prever_alvo(painel[painel.dia <= t2.tz_localize(None)], alvos.niveis(dd, hh, t2), "11h", alvo, t2)
        a = a.set_index("dia").prev
        pd.testing.assert_series_equal(a, b.set_index("dia").prev.reindex(a.index))


def test_barra_parcial_nao_vai_para_o_cache():
    """Com o pregão aberto, a barra diária de hoje (preço parcial) é descartada."""
    from ibov.dados import _so_completas
    x = pd.DataFrame({"Close": [1.0, 2.0]}, index=pd.to_datetime(["2026-11-19", "2026-11-23"]))
    t = lambda h: pd.Timestamp(f"2026-11-23 {h}", tz=TZ)
    assert len(_so_completas(x, "ibov", "d", t("15:00"))) == 1
    assert len(_so_completas(x, "ibov", "d", t("18:30"))) == 1      # ainda pode mudar
    assert len(_so_completas(x, "ibov", "d", t("18:50"))) == 2


def test_fech_de_hoje_vazio_com_pregao_aberto(painel):
    """Nenhuma linha do painel pode ter fechamento de um pregão que não terminou."""
    from ibov.dados import FOLGA_FECH, fechamento_b3
    agora = pd.Timestamp.now(tz=TZ)
    abertos = painel[[fechamento_b3(d) + FOLGA_FECH > agora for d in painel.dia]]
    assert abertos.fech.isna().all()


def test_painel_sem_colunas_de_volatilidade(painel):
    """As medidas de volatilidade nem chegam a ser calculadas."""
    from ibov.modelo import ATRIB_VOLATILIDADE
    assert not set(painel.columns) & ATRIB_VOLATILIDADE
