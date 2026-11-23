"""
ibov/relatorio.py — ETAPA 3a DO PROJETO: o resultado do dia em texto claro.

Gera um relatório em português, pensado para ser lido por qualquer pessoa,
com a previsão de fechamento do pregão escolhido. Ele é:
  • impresso no terminal quando você roda `python -m ibov`;
  • salvo em `saida/resultado_AAAA-MM-DD.txt` (fica um arquivo por dia).

Conteúdo
  1. Cabeçalho: data, hora de geração e se o pregão está aberto ou encerrado.
  2. A previsão do horário escolhido (padrão: diária, feita às 10h), com
     uma frase "em palavras" explicando o número.
  3. Se o pregão está em andamento, também a previsão mais recente do dia.
  4. Tabela mostrando como a previsão evoluiu de horário em horário.
  5. Se o pregão já fechou: o resultado real e o quanto cada previsão errou.
  6. A confiabilidade histórica do horário escolhido.
  7. O embasamento: de onde saiu cada número.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

from .dados import RAIZ, TZ

# Nomes legíveis de cada horário de corte
NOMES = {"vespera": "Véspera, 20h", "abertura": "10h (diária)", "11h": "11h", "12h": "12h",
         "13h": "13h", "14h": "14h", "15h": "15h", "16h": "16h"}
DIAS_SEMANA = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
               "Sexta-feira", "Sábado", "Domingo"]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]
LARG = 78                                     # largura das linhas do relatório


# ---------- formatação no padrão brasileiro (1.234,56) ----------
def pts(v: float) -> str:
    """Pontos do índice: 166376.2 -> '166.376'."""
    return f"{v:,.0f}".replace(",", ".")


def pct(v: float, sinal: bool = True, casas: int = 2) -> str:
    """Fração em porcentagem: 0.0017 -> '+0,17%'."""
    s = f"{v * 100:+.{casas}f}" if sinal else f"{v * 100:.{casas}f}"
    return s.replace(".", ",") + "%"


def data_extenso(d: pd.Timestamp) -> str:
    return f"{DIAS_SEMANA[d.day_of_week]}, {d.day} de {MESES[d.month - 1]} de {d.year}"


def em_palavras(var: float, prob: float) -> str:
    """Traduz a variação prevista e a chance de alta numa frase simples."""
    a = abs(var)
    if a < 0.002:
        tom = "praticamente estável"
    elif a < 0.007:
        tom = "em leve " + ("alta" if var > 0 else "queda")
    elif a < 0.015:
        tom = "em " + ("alta" if var > 0 else "queda")
    else:
        tom = "em forte " + ("alta" if var > 0 else "queda")
    if 0.45 <= prob <= 0.55:
        chance = "a chance de alta ou de queda é praticamente a mesma (cara ou coroa)"
    elif prob > 0.55:
        chance = f"o cenário de alta é o mais provável ({prob:.0%} de chance)"
    else:
        chance = f"o cenário de queda é o mais provável ({1 - prob:.0%} de chance)"
    return f"O modelo espera que o IBOVESPA feche {tom} ({pct(var)}); {chance}."


def _bloco_previsao(x: pd.Series, titulo: str, cobertura: float | None = None) -> list[str]:
    """Bloco com a previsão de um horário específico.
    `cobertura` = % histórico de dias em que o real caiu dentro da faixa desse horário."""
    var = x.prev / x.fech_ant - 1
    return [
        titulo,
        f"  Fechamento previsto ........ {pts(x.prev)} pontos",
        f"  Variação esperada .......... {pct(var)} em relação ao fechamento anterior ({pts(x.fech_ant)})",
        f"  Faixa provável (80%) ....... entre {pts(x.lo)} e {pts(x.hi)}",
        f"  Chance de fechar em alta ... {x.prob_alta:.0%}",
        f"  Preço do IBOV no momento ... {pts(x.p_ref)}"
        + ("  (antes da abertura = fechamento anterior)" if x.name in ("vespera", "abertura") else ""),
        "",
        *[f"  {l}" for l in _quebrar(em_palavras(var, x.prob_alta), LARG - 2)],
    ] + ([f"  Historicamente, o fechamento real caiu dentro da faixa em {cobertura:.0%} dos dias."]
         if cobertura is not None else [])


def _quebrar(txt: str, larg: int) -> list[str]:
    """Quebra um texto longo em linhas de no máximo `larg` caracteres."""
    linhas, atual = [], ""
    for p in txt.split():
        if len(atual) + len(p) + 1 > larg:
            linhas.append(atual); atual = p
        else:
            atual = f"{atual} {p}".strip()
    return linhas + [atual]


def gerar_relatorio(r: pd.DataFrame, met: pd.DataFrame, dia: str, corte: str,
                    agora: pd.Timestamp | None = None, salvar: bool = True,
                    momentos: dict | None = None) -> str:
    """Monta o texto do relatório do pregão `dia` e (opcionalmente) salva em saida/.

    r     — previsões do `walk_forward` (todas as datas e horários)
    met   — tabela de `metricas` (qualidade histórica por horário)
    dia   — 'AAAA-MM-DD'
    corte — horário principal (ex.: 'abertura' para a visão diária)
    momentos — resultado de `alvos.montar()` (as previsões do gráfico)
    """
    agora = agora or pd.Timestamp.now(tz=TZ)
    d = pd.Timestamp(dia)
    hoje = r[r["dia"] == d].assign(corte=lambda t: t["corte"].astype(str)).set_index("corte")  # todas as previsões desse pregão
    fechado = not hoje.empty and hoje["fech"].notna().all()
    L: list[str] = []
    barra = "═" * LARG

    # 1) Cabeçalho
    L += [barra, "  IBOVESPA — RESULTADO DA PREVISÃO DE FECHAMENTO",
          f"  {data_extenso(d)}   (relatório gerado em {agora:%d/%m/%Y às %H:%M})",
          "  Situação do pregão: " + ("ENCERRADO — fechamento oficial conhecido" if fechado
                                     else "EM ANDAMENTO — o fechamento ainda não aconteceu"),
          barra, ""]
    if hoje.empty:
        L.append("  Não há previsões para este dia (feriado, fim de semana ou fora do período).")
        return _finalizar(L, dia, salvar)

    # 1a) Resultado em destaque: a previsão mais atual do fechamento
    u = hoje.iloc[-1]
    L += [f"  {pts(u.prev)} pontos, com faixa de 80% entre {pts(u.lo)} e {pts(u.hi)}",
          f"  (fechamento de {d:%d/%m}; previsão feita às {NOMES[hoje.index[-1]]})", ""]

    # 1b) As previsões do gráfico (início, fim, próximo pregão e --hora)
    if momentos:
        L += _bloco_momentos(momentos)

    # 2) Previsão do horário escolhido (padrão: diária)
    if corte in hoje.index:
        L += _bloco_previsao(hoje.loc[corte],
                             f"PREVISÃO PRINCIPAL — feita às {NOMES[corte]}"
                             + ("  ← visão padrão" if corte == "abertura" else ""),
                             _cob(met, corte)) + [""]
    else:
        L += [f"PREVISÃO PRINCIPAL — {NOMES[corte]}: ainda não disponível (esse horário não chegou).", ""]

    # 3) Pregão em andamento: mostra também a previsão mais atualizada
    ultimo = hoje.index[-1]
    if not fechado and ultimo != corte:
        L += _bloco_previsao(hoje.loc[ultimo],
                             f"PREVISÃO MAIS RECENTE — feita às {NOMES[ultimo]} (com mais informação do dia)",
                             _cob(met, ultimo)) + [""]

    # 4) Evolução ao longo do dia (+ erro real, se o pregão fechou)
    L += ["COMO A PREVISÃO EVOLUIU AO LONGO DO DIA", "-" * LARG]
    cab = f"  {'Horário':<14}{'IBOV no momento':>16}{'Fech. previsto':>16}{'Chance alta':>13}"
    cab += f"{'Erro real':>12}" if fechado else f"{'Erro típico*':>14}"
    L.append(cab)
    for c, x in hoje.iterrows():
        linha = f"  {NOMES[c]:<14}{pts(x.p_ref):>16}{pts(x.prev):>16}{x.prob_alta:>12.0%} "
        if fechado:
            linha += f"{pct(x.prev / x.fech - 1):>12}"
        elif c in met.index:
            linha += f"{'±' + pct(met.loc[c, 'mae_pct'] / 100, sinal=False):>14}"
        L.append(linha + ("   ◄" if c == corte else ""))
    if fechado:
        L.append("  Erro real: + = a previsão ficou acima do fechamento; - = ficou abaixo.")
    else:
        L.append("  * Erro típico = erro médio histórico desse horário (fora da amostra).")
    L.append("")

    # 5) Resultado real, se o pregão terminou
    if fechado:
        x0 = hoje.iloc[0]
        real, ant = x0.fech, x0.fech_ant
        L += ["RESULTADO DO DIA", "-" * LARG,
              f"  Fechamento real ............ {pts(real)} pontos ({pct(real / ant - 1)} no dia)"]
        if corte in hoje.index:
            x = hoje.loc[corte]
            dentro = x.lo <= real <= x.hi
            # previsão igual ao fechamento anterior não aponta direção
            sem_dir = x.prev == ant
            dir_ok = (x.prev > ant) == (real > ant)
            L += [f"  {('Previsão das ' + NOMES[corte] + ' ').ljust(28, '.')} {pts(x.prev)} → errou por {pts(abs(x.prev - real))} pontos "
                  f"({pct(abs(x.prev / real - 1), sinal=False)})",
                  f"  Ficou dentro da faixa 80%? . {'SIM' if dentro else 'NÃO'} ({pts(x.lo)} a {pts(x.hi)})",
                  f"  Acertou a direção? ......... {'—' if sem_dir else 'SIM' if dir_ok else 'NÃO'} "
                  f"(previu {'estável' if sem_dir else 'alta' if x.prev > ant else 'queda'}, foi {'alta' if real > ant else 'queda'})"]
        melhor = (hoje.prev / hoje.fech - 1).abs().idxmin()
        L += [f"  Previsão mais próxima ...... a das {NOMES[melhor]}", ""]

    # 6) Confiabilidade histórica do horário escolhido
    if corte in met.index:
        m = met.loc[corte]
        ganho = "um pouco melhor que o" if m.mae_pct < m.mae_ingenuo_pct * 0.98 else "praticamente igual ao"
        L += ["QUANTO CONFIAR NESTE HORÁRIO (histórico fora da amostra)", "-" * LARG,
              f"  Em {int(m.n)} pregões testados, a previsão das {NOMES[corte]} errou em média "
              f"{pct(m.mae_pct / 100, sinal=False)}",
              f"  — {ganho} palpite ingênuo \"fecha no preço atual\" ({pct(m.mae_ingenuo_pct / 100, sinal=False)}).",
              ("  Não aponta direção (prevê o último preço); o fechamento ficou" if pd.isna(m.acerto_direcao)
               else f"  Acertou a direção (alta/baixa) em {m.acerto_direcao:.0%} dos dias e o fechamento ficou"),
              f"  dentro da faixa de 80% em {m.cobertura_80:.0%} dos dias.", ""]
    L += _embasamento(u, hoje.index[-1])
    L += ["Aviso: modelo estatístico para estudo. Não é recomendação de investimento."]
    return _finalizar(L, dia, salvar)


def _embasamento(x: pd.Series, corte: str) -> list[str]:
    """De onde saiu a previsão mostrada no topo do relatório."""
    if corte == "abertura":
        centro = ("Regressão Ridge com 3 retornos desde o último fechamento da B3: EWZ, dólar/real e VALE "
                  "em Nova York. Foi o único caso em que um modelo errou menos que repetir o preço.")
    else:
        centro = ("É o último preço conhecido no horário da previsão. Testamos centenas de modelos e "
                  "nenhum errou menos que isso de forma consistente neste horário.")
    itens = [("Ponto de partida", f"IBOV em {pts(x.p_ref)} pontos."), ("Previsão central", centro),
             ("Faixa de 80%", "Percentis 10% e 90% dos 120 erros mais recentes do próprio modelo."),
             ("Chance de alta", "Fração desses erros que deixaria o fechamento acima do anterior."),
             ("Volatilidade", "Recurso não analisado na previsão.")]
    L = ["EMBASAMENTO DA PREVISÃO", "-" * LARG]
    for i, (t, txt) in enumerate(itens, 1):
        L += [f"  {i}. {t}", *[f"     {l}" for l in _quebrar(txt, LARG - 5)]]
    return L + [""]


def _bloco_momentos(g: dict) -> list[str]:
    """As previsões do gráfico em texto: início e final do dia, início do
    próximo pregão e, se pedida, a hora do --hora. `g` vem de alvos.montar()."""
    L = ["PREVISÕES POR MOMENTO (as mesmas do gráfico)", "-" * LARG,
         f"  {'Momento':<38}{'Previsão':>9}  {'Faixa provável':<19}{'Real':>9}"]
    for x in g["pontos"]:
        d = g["seguinte"] if x["chave"] == "amanha" else g["dia"]
        h = f"{x['min'] // 60}h" + (f"{x['min'] % 60:02d}" if x["min"] % 60 else "")
        nome = f"{d:%d/%m} às {h}" if x["chave"] == "hora" else f"{x['nome']} ({d:%d/%m}, {h})"
        faixa = f"{pts(x['lo'])} a {pts(x['hi'])}"
        real = pts(x["real"]) if np.isfinite(x["real"]) else "—"
        L.append(f"  {nome:<38}{pts(x['prev']):>9}  {faixa:<19}{real:>9}"
                 + ("  ◄" if x["chave"] == "hora" else ""))
    return L + ["  Já aconteceu: previsão da manhã e valor real. Ainda não: a previsão mais recente.",
                "  Início do dia = 11h, depois da 1ª hora de pregão. — = ainda não há valor real.", ""]


def _cob(met: pd.DataFrame, corte: str) -> float | None:
    """Cobertura histórica da faixa de 80% para um horário (None se não houver)."""
    met = met.set_axis(met.index.astype(str))
    return float(met.loc[corte, "cobertura_80"]) if corte in met.index else None


def _finalizar(L: list[str], dia: str, salvar: bool) -> str:
    """Junta as linhas e grava em saida/resultado_<dia>.txt."""
    txt = "\n".join(L) + "\n"
    if salvar:
        arq = RAIZ / "saida" / f"resultado_{dia}.txt"
        arq.parent.mkdir(exist_ok=True)
        arq.write_text(txt, encoding="utf-8")
    return txt


def caminho(dia: str) -> Path:
    """Onde o relatório do dia fica salvo."""
    return RAIZ / "saida" / f"resultado_{dia}.txt"
