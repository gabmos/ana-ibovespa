"""
ibov/visual.py — ETAPA 3b DO PROJETO: o painel gráfico (pop-up no navegador).

Como funciona
-------------
O painel é UM arquivo HTML autossuficiente (`saida/painel.html`):
  1. o Python converte as previsões, as barras horárias e as métricas em JSON;
  2. esse JSON é "colado" dentro do modelo de página `_MODELO` (no lugar da
     marca __DADOS__);
  3. no navegador, um pequeno JavaScript lê esse JSON e desenha os gráficos
     com a biblioteca Plotly (interativa: zoom, passar o mouse, clicar).

Não há servidor: basta abrir o arquivo. Uma cópia do Plotly é salva em
`saida/plotly.min.js` para o painel funcionar sem internet; se ela não
existir, a página busca o Plotly no CDN.

O que o painel mostra
---------------------
NO TOPO (o que importa, sem precisar clicar em nada):
  • Um cartão por momento: início do dia, final do dia e início do próximo
    pregão — mais a hora pedida com --hora, se houver (em laranja).
  • Um gráfico: a linha escura é o preço real até agora; cada ponto azul é
    uma previsão e a barra clara em volta dele é a faixa provável.
Esses dados vêm de `alvos.montar()`.

EM "DETALHES" (recolhido; clicar para abrir):
  • Seletor de horário — "Diário (10h)" vem marcado por padrão; há botões
    para Véspera e 11h…16h e um campo para digitar qualquer hora (ex.: 13:30
    usa o último corte que já tinha acontecido, o das 13h).
  • Cartões-resumo do dia escolhido: previsão, faixa de 80%, chance de alta,
    preço de referência e fechamento real.
  • Gráfico 1: previsão × fechamento real ao longo dos dias, com a faixa de 80%.
    Clicar num dia abre esse dia no gráfico 2.
  • Gráfico 2: intradiário — o IBOV hora a hora e a previsão feita em cada
    horário de corte, com a barra de incerteza encolhendo ao longo do dia.
  • Tabela de qualidade histórica por horário.
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

from .dados import CORTES, RAIZ
from .relatorio import DIAS_SEMANA, NOMES

PLOTLY_CDN = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"
# Texto exibido nos botões e títulos para cada horário de corte
ROTULOS = {"vespera": "Véspera (20h)", "abertura": "Diário (10h)", "11h": "11h", "12h": "12h",
           "13h": "13h", "14h": "14h", "15h": "15h", "16h": "16h"}


def _dados_json(r: pd.DataFrame, h_ibov: pd.DataFrame, met: pd.DataFrame) -> str:
    """Converte tudo o que o painel precisa num texto JSON compacto.

    Usa chaves curtas para o arquivo ficar pequeno:
      d=dia, c=corte, t=horário do corte, ref=preço no corte, ant=fech. anterior,
      real=fechamento real (null se não fechou), p=previsão, lo/hi=faixa 80%,
      pa=probabilidade de alta.
    """
    prev = []
    for x in r.itertuples():
        prev.append({"d": x.dia.strftime("%Y-%m-%d"), "c": str(x.corte),
                     "t": pd.Timestamp(x.t_corte).strftime("%Y-%m-%dT%H:%M"),
                     "ref": round(x.p_ref), "ant": round(x.fech_ant),
                     "real": None if pd.isna(x.fech) else round(x.fech),
                     "p": round(x.prev), "lo": round(x.lo), "hi": round(x.hi), "pa": round(x.prob_alta, 3)})

    # Barras horárias do IBOV agrupadas por dia: {dia: [[horário, preço], ...]}.
    # Cada ponto é posicionado no FIM da barra (quando o preço passa a ser conhecido);
    # o primeiro ponto do dia é a abertura (Open da 1ª barra, no início dela).
    ini = r["dia"].min()
    h = h_ibov[h_ibov.index.tz_localize(None) >= ini]
    fim = h.index + pd.Timedelta(hours=1)
    barras = {}
    for t, a, c in zip(fim, h["Open"], h["Close"]):
        d = t.strftime("%Y-%m-%d")
        lst = barras.setdefault(d, [])
        if not lst:
            lst.append([(t - pd.Timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"), round(a)])
        lst.append([t.strftime("%Y-%m-%dT%H:%M"), round(c)])

    m = met.reset_index().rename(columns={"corte": "c"})
    m["c"] = m["c"].astype(str)
    return json.dumps({"prev": prev, "barras": barras, "met": json.loads(m.round(4).to_json(orient="records")),   # NaN vira null
                       
                       "cortes": list(CORTES), "rotulos": ROTULOS})


def _grafico_json(g: dict | None) -> str:
    """Converte o resultado de `alvos.montar()` em JSON para o gráfico do topo.
    Números viram inteiros (pontos) e o que ainda não existe vira null."""
    if g is None:
        return "null"
    num = lambda v: None if v is None or pd.isna(v) else round(float(v))
    curta = lambda d: f"{DIAS_SEMANA[d.dayofweek].split('-')[0].lower()}, {d:%d/%m}"   # 'segunda, 23/11'
    pontos = [{"chave": x["chave"], "nome": x["nome"], "min": x["min"], "p": num(x["prev"]), "lo": num(x["lo"]),
               "hi": num(x["hi"]), "real": num(x["real"]), "base": num(x["base"]), "ref": num(x["p_ref"]),
               "erro": None if pd.isna(x["erro"]) else round(x["erro"], 4),
               "cob": None if pd.isna(x["cobertura"]) else round(x["cobertura"], 3),
               "feita": NOMES[x["feita"]].replace(" (diária)", "")} for x in g["pontos"]]
    return json.dumps({"dia": curta(g["dia"]), "seguinte": curta(g["seguinte"]), "amanha": bool(g["eh_hoje"] and (g["seguinte"] - g["dia"]).days == 1), "ant": num(g["fech_ant"]),
                       "pontos": pontos, "precos": [[m, round(v)] for m, v in g["precos"]],
                       "fecha": g["fecha"], "manha": num(g["manha"]), "encerrado": g["encerrado"], "ehHoje": g["eh_hoje"]})


def _plotly_local(pasta: Path) -> None:
    """Guarda uma cópia do Plotly ao lado do HTML para o painel abrir offline.
    Só baixa uma vez; nas próximas execuções o arquivo já existe."""
    arq = pasta / "plotly.min.js"
    if arq.exists():
        return
    try:
        import requests
        resp = requests.get(PLOTLY_CDN, timeout=30)
        resp.raise_for_status()
        arq.write_bytes(resp.content)
    except Exception as e:
        print(f"[aviso] Plotly não baixado ({e}); o painel usará o CDN")


def gerar_html(r: pd.DataFrame, h_ibov: pd.DataFrame, met: pd.DataFrame,
               corte_padrao: str = "abertura", dia_padrao: str | None = None,
               destino: Path | None = None, grafico: dict | None = None) -> Path:
    """Escreve o painel em `saida/painel.html` e devolve o caminho.

    corte_padrao — horário que já vem selecionado ('abertura' = visão diária)
    dia_padrao   — dia que já vem aberto ('AAAA-MM-DD'; None = o mais recente)
    grafico      — resultado de `alvos.montar()`: os dados do gráfico do topo
    """
    destino = destino or RAIZ / "saida" / "painel.html"
    destino.parent.mkdir(exist_ok=True)
    _plotly_local(destino.parent)
    # Substitui as marcas __XXX__ do modelo de página pelos valores reais
    html = (_MODELO.replace("__DADOS__", _dados_json(r, h_ibov, met))
            .replace("__GRAFICO__", _grafico_json(grafico))
            .replace("__CORTE__", json.dumps(corte_padrao))
            .replace("__DIA__", json.dumps(dia_padrao))
            .replace("__CDN__", PLOTLY_CDN))
    destino.write_text(html, encoding="utf-8")
    return destino


# =============================================================================
# Modelo da página. As marcas __DADOS__, __GRAFICO__, __CORTE__, __DIA__ e __CDN__ são
# trocadas por gerar_html(). O `r"""` evita que o Python interprete as barras.
# =============================================================================
_MODELO = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Previsão IBOVESPA</title>
<!-- Plotly: tenta a cópia local; se não existir, carrega do CDN -->
<script src="plotly.min.js"></script>
<script>window.Plotly||document.write('<script src="__CDN__"><\/script>')</script>
<style>
/* ---- Cores: definidas uma vez como variáveis, com versão para modo escuro ---- */
:root{color-scheme:light;--bg:#f7f7f5;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#8a8984;
 --grid:#e6e5e1;--line:#d9d8d3;--prev:#2a78d6;--band:rgba(42,120,214,.16);--real:#0b0b0b;--ant:#8a8984;--sel:#eb6834}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#121211;--surface:#1a1a19;
 --ink:#fff;--ink2:#c3c2b7;--muted:#8f8e86;--grid:#2c2c2a;--line:#3a3a37;--prev:#3987e5;--band:rgba(57,135,229,.22);
 --real:#fff;--ant:#8f8e86;--sel:#d95926}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#121211;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#8f8e86;
 --grid:#2c2c2a;--line:#3a3a37;--prev:#3987e5;--band:rgba(57,135,229,.22);--real:#fff;--ant:#8f8e86;--sel:#d95926}
/* ---- Layout geral ---- */
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:0 0 2px}
.sub{color:var(--ink2);margin:0 0 18px}
/* ---- Filtros: botões de horário + campos de hora e dia ---- */
.filtros{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-bottom:16px}
.seg{display:flex;flex-wrap:wrap;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--surface)}
.seg button{border:0;background:none;color:var(--ink2);padding:7px 12px;font:inherit;cursor:pointer}
.seg button+button{border-left:1px solid var(--line)}
.seg button[aria-pressed="true"]{background:var(--prev);color:#fff;font-weight:600}
label{color:var(--ink2);display:flex;gap:6px;align-items:center}
input[type=date],input[type=time]{font:inherit;padding:5px 8px;border:1px solid var(--line);border-radius:8px;
 background:var(--surface);color:var(--ink)}
/* ---- Cartões-resumo ---- */
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:16px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.tile .k{color:var(--ink2);font-size:12px}.tile .v{font-size:24px;font-weight:600;font-variant-numeric:tabular-nums}
.tile .s{color:var(--muted);font-size:12px}
/* ---- Cartões dos gráficos e tabela ---- */
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 14px 6px;margin-bottom:16px}
.card .sub{margin:0 0 6px;font-size:13px}
.graf{width:100%;height:380px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;text-align:right;border-bottom:1px solid var(--grid)}th:first-child,td:first-child{text-align:left}
th{color:var(--ink2);font-weight:500}tr.on td{font-weight:600}
.tab-wrap{overflow-x:auto;padding-bottom:8px}
/* ---- Topo: cartões das previsões e gráfico principal ---- */
.prevs{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin-bottom:16px}
.prev{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.prev .n{font-weight:600;display:flex;align-items:center;gap:8px}
.prev .n i{width:10px;height:10px;border-radius:50%;background:var(--prev);flex:none}
.prev.hora .n i{background:var(--sel)}
.prev .q{color:var(--muted);font-size:12px;margin-bottom:8px}
.prev .v{font-size:30px;font-weight:600;line-height:1.15}
.prev .l{color:var(--ink2);font-size:13px;margin-top:4px}
.prev .l b{color:var(--ink);font-weight:600}
.prev .r{border-top:1px solid var(--grid);margin-top:10px;padding-top:8px;font-size:13px;color:var(--ink2)}
.chave{display:flex;flex-wrap:wrap;gap:6px 18px;color:var(--ink2);font-size:13px;margin:8px 0 0}
.chave span{display:flex;align-items:center;gap:7px}
.chave i{display:inline-block;flex:none}
.k-real{width:18px;height:2px;background:var(--real)}.k-prev{width:10px;height:10px;border-radius:50%;background:var(--prev)}
.k-hora{width:10px;height:10px;border-radius:50%;background:var(--sel)}.k-faixa{width:10px;height:18px;border-radius:4px;background:var(--prev);opacity:.25}
.k-ant{width:18px;border-top:2px dotted var(--ant)}
#g0{width:100%;height:440px}
details{border-top:1px solid var(--line);padding-top:14px;margin-top:8px}
summary{cursor:pointer;font-weight:600;color:var(--ink2);margin-bottom:14px}
.nota{color:var(--muted);font-size:12px;margin-top:8px}
</style></head><body><main>
<h1>Previsão do IBOVESPA</h1>
<p class="sub" id="topo"></p>
<div class="prevs" id="prevs"></div>
<section class="card" id="card0">
  <h2>Preço do dia e previsões</h2>
  <div class="chave" id="chave"></div>
  <div id="g0"></div>
</section>
<p class="nota" id="aviso"></p>

<details id="det"><summary>Detalhes: histórico e qualidade das previsões de fechamento</summary>
<p class="sub">Previsões fora da amostra (walk-forward). Escolha o horário em que a previsão é feita — o padrão é a visão diária, antes da abertura.</p>

<div class="filtros">
  <div class="seg" id="seg" role="group" aria-label="Horário da previsão"></div>
  <label>ou hora <input type="time" id="hora" step="60"></label>
  <label>Dia <input type="date" id="dia"></label>
</div>

<div class="tiles" id="tiles"></div>

<section class="card">
  <h2 id="t1"></h2><p class="sub">Linha azul: previsão; faixa: intervalo de 80%; linha escura: fechamento real. Clique num dia para abrir o intradiário.</p>
  <div id="g1" class="graf"></div>
</section>
<section class="card">
  <h2 id="t2"></h2><p class="sub">Preço hora a hora e a previsão do fechamento feita em cada horário de corte (barras = intervalo de 80%). O corte selecionado aparece em destaque.</p>
  <div id="g2" class="graf"></div>
</section>
<section class="card">
  <h2>Qualidade por horário (fora da amostra)</h2>
  <p class="sub">Erro absoluto médio do fechamento previsto vs. o ingênuo “fecha no preço de referência”.</p>
  <div class="tab-wrap"><table id="tab"></table></div>
  <p class="nota">Acerto de direção: previsão e real do mesmo lado do fechamento anterior. Cobertura: % de dias em que o real caiu dentro da faixa de 80%.</p>
</section>
</details>
</main>
<script>
// ======================= ESTADO E UTILITÁRIOS =======================
// D = dados vindos do Python; corte/dia = o que está selecionado agora.
const D=__DADOS__; const G=__GRAFICO__; let corte=__CORTE__; let dia=__DIA__;

// Formatação brasileira: 166.376 e 0,17%
const fmt=v=>v==null?"—":v.toLocaleString("pt-BR",{maximumFractionDigits:0});
const pct=(v,c=1)=>v==null?"—":(v*100).toLocaleString("pt-BR",{minimumFractionDigits:c,maximumFractionDigits:c})+"%";
// Lê uma cor definida no CSS (assim o gráfico acompanha o modo claro/escuro)
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const porCorte=c=>D.prev.filter(x=>x.c===c);           // todas as previsões de um horário
const dias=[...new Set(D.prev.map(x=>x.d))];           // lista de pregões disponíveis
if(!dia||!dias.includes(dia)) dia=dias[dias.length-1]; // padrão: o pregão mais recente

// Horários de corte em (hora, minuto) — a véspera fica de fora pois é no dia anterior
const H={"abertura":[10,0],"11h":[11,0],"12h":[12,0],"13h":[13,0],"14h":[14,0],"15h":[15,0],"16h":[16,0]};

// Hora livre digitada (ex.: "13:30") -> último corte que já tinha acontecido ("13h")
function corteDaHora(hhmm){
  const [h,m]=hhmm.split(":").map(Number),a=h*60+m; let best=null,bm=-1;
  for(const [k,[hh,mm]] of Object.entries(H)){const v=hh*60+mm; if(v<=a&&v>bm){bm=v;best=k}}
  return best||(a<10*60?"vespera":"abertura");
}

// Configuração visual comum aos dois gráficos (cores, grade, separador decimal ",")
function layout(extra){return Object.assign({paper_bgcolor:"rgba(0,0,0,0)",plot_bgcolor:"rgba(0,0,0,0)",
  separators:",.",font:{family:"system-ui,sans-serif",color:css("--ink2"),size:12},margin:{l:64,r:16,t:8,b:40},
  hovermode:"x unified",hoverlabel:{bgcolor:css("--surface"),bordercolor:css("--line"),font:{color:css("--ink")}},
  legend:{orientation:"h",y:1.08,x:0},
  xaxis:{gridcolor:css("--grid"),linecolor:css("--line"),zeroline:false},
  yaxis:{gridcolor:css("--grid"),linecolor:css("--line"),zeroline:false,tickformat:",.0f"}},extra)}
const cfg={displaylogo:false,responsive:true,modeBarButtonsToRemove:["lasso2d","select2d"]};

// ======================= COMPONENTES =======================
// Botões de horário. Clicar troca o corte e redesenha tudo.
function seg(){
  const s=document.getElementById("seg"); s.innerHTML="";
  for(const c of ["abertura","vespera","11h","12h","13h","14h","15h","16h"]){
    const b=document.createElement("button");
    b.textContent=D.rotulos[c]; b.setAttribute("aria-pressed",c===corte);
    b.onclick=()=>{corte=c; document.getElementById("hora").value=""; tudo()};
    s.appendChild(b);
  }
}

// Cartões-resumo do dia + horário selecionados
function tiles(){
  const x=D.prev.find(p=>p.d===dia&&p.c===corte), el=document.getElementById("tiles");
  if(!x){el.innerHTML=`<div class="tile"><div class="k">Sem previsão</div><div class="s">Corte ${D.rotulos[corte]} ainda não disponível em ${dia}.</div></div>`;return}
  const varp=(x.p/x.ant-1);   // variação prevista vs. fechamento anterior
  el.innerHTML=`
  <div class="tile"><div class="k">Fechamento previsto · ${D.rotulos[corte]}</div><div class="v">${fmt(x.p)}</div>
    <div class="s">${varp>=0?"▲":"▼"} ${pct(Math.abs(varp))} vs. fech. anterior (${fmt(x.ant)})</div></div>
  <div class="tile"><div class="k">Intervalo de 80%</div><div class="v" style="font-size:18px">${fmt(x.lo)} – ${fmt(x.hi)}</div>
    <div class="s">largura ${pct(x.hi/x.lo-1)}</div></div>
  <div class="tile"><div class="k">Prob. de fechar em alta</div><div class="v">${pct(x.pa)}</div><div class="s">vs. fechamento anterior</div></div>
  <div class="tile"><div class="k">Preço de referência no corte</div><div class="v">${fmt(x.ref)}</div><div class="s">${x.t.replace("T"," ")}</div></div>
  <div class="tile"><div class="k">Fechamento real</div><div class="v">${fmt(x.real)}</div>
    <div class="s">${x.real==null?"pregão em andamento":"erro "+pct(Math.abs(x.p/x.real-1))}</div></div>`;
}

// Gráfico 1: previsão × real ao longo dos dias, para o horário selecionado
function g1(){
  const s=porCorte(corte), X=s.map(x=>x.d);
  document.getElementById("t1").textContent=`Fechamento previsto × real — ${D.rotulos[corte]}`;
  const sel=s.find(x=>x.d===dia);
  const tr=[
   // faixa de 80%: desenha o limite superior invisível e preenche até o inferior
   {x:X,y:s.map(x=>x.hi),line:{width:0},hoverinfo:"skip",showlegend:false,type:"scatter"},
   {x:X,y:s.map(x=>x.lo),fill:"tonexty",fillcolor:css("--band"),line:{width:0},name:"Intervalo 80%",
    customdata:s.map(x=>[x.lo,x.hi]),hovertemplate:"faixa %{customdata[0]:,.0f} – %{customdata[1]:,.0f}<extra></extra>"},
   {x:X,y:s.map(x=>x.p),name:"Previsão",line:{color:css("--prev"),width:2},
    customdata:s.map(x=>x.pa),hovertemplate:"previsão %{y:,.0f} · P(alta) %{customdata:.0%}<extra></extra>"},
   {x:X,y:s.map(x=>x.real),name:"Real",line:{color:css("--real"),width:2},hovertemplate:"real %{y:,.0f}<extra></extra>"}];
  // ponto laranja no dia selecionado
  if(sel) tr.push({x:[sel.d],y:[sel.real??sel.p],mode:"markers",name:"Dia selecionado",hoverinfo:"skip",
    marker:{size:11,color:css("--sel"),line:{color:css("--surface"),width:2}}});
  // começa mostrando os últimos ~6 meses (120 pregões), com eixo Y ajustado a esse trecho
  const ini=X[Math.max(0,X.length-120)];
  const vis=s.filter(x=>x.d>=ini).flatMap(x=>[x.lo,x.hi,x.real]).filter(v=>v!=null);
  const pad=(Math.max(...vis)-Math.min(...vis))*.05;
  Plotly.react("g1",tr,layout({
    xaxis:{gridcolor:css("--grid"),linecolor:css("--line"),range:[ini,X[X.length-1]],type:"date",
      rangeslider:{visible:true,thickness:.08,bgcolor:css("--bg")},           // barra de rolagem no rodapé
      rangeselector:{buttons:[{count:1,label:"1m",step:"month",stepmode:"backward"},
        {count:3,label:"3m",step:"month",stepmode:"backward"},{count:6,label:"6m",step:"month",stepmode:"backward"},
        {step:"all",label:"tudo"}],bgcolor:css("--surface"),activecolor:css("--grid")}},
    yaxis:{gridcolor:css("--grid"),linecolor:css("--line"),zeroline:false,tickformat:",.0f",
      range:[Math.min(...vis)-pad,Math.max(...vis)+pad]}}),cfg);
  ajustaY();
  // clique num dia -> abre esse dia nos cartões e no gráfico intradiário
  const el=document.getElementById("g1"); el.removeAllListeners?.("plotly_click");
  el.on("plotly_click",e=>{dia=e.points[0].x.slice(0,10); tudo()});
}

// Quando o usuário muda o período (zoom, botões 1m/3m…), re-ajusta o eixo Y a esse período
function ajustaY(){
  const el=document.getElementById("g1"); if(el._fit)return; el._fit=true;   // registra só uma vez
  el.on("plotly_relayout",e=>{
    const a=e["xaxis.range[0]"]??e["xaxis.range"]?.[0], b=e["xaxis.range[1]"]??e["xaxis.range"]?.[1];
    const s=porCorte(corte).filter(x=>a==null||(x.d>=String(a).slice(0,10)&&x.d<=String(b).slice(0,10)));
    const v=s.flatMap(x=>[x.lo,x.hi,x.real]).filter(v=>v!=null);
    if(!v.length||e["yaxis.range[0]"]!=null)return;      // evita laço infinito com o próprio ajuste
    const p=(Math.max(...v)-Math.min(...v))*.05;
    Plotly.relayout(el,{"yaxis.range":[Math.min(...v)-p,Math.max(...v)+p]});
  });
}

// Gráfico 2: o dia selecionado hora a hora + a previsão feita em cada horário
function g2(){
  const b=D.barras[dia]||[], s=D.prev.filter(x=>x.d===dia);
  const dt=new Date(dia+"T12:00");
  document.getElementById("t2").textContent="Intradiário de "+dt.toLocaleDateString("pt-BR",{weekday:"long",day:"2-digit",month:"long",year:"numeric"});
  const intra=s.filter(x=>x.c!=="vespera");       // a véspera vira só uma anotação à esquerda
  const ant=s[0]?.ant, real=s[0]?.real;
  const x0=dia+"T09:30", x1=dia+"T17:30";          // janela do pregão
  const tr=[
    {x:b.map(v=>v[0]),y:b.map(v=>v[1]),name:"IBOV (hora a hora)",line:{color:css("--real"),width:2},
     hovertemplate:"preço %{y:,.0f}<extra></extra>"},
    // pontos azuis = previsão de fechamento; barras verticais = faixa de 80%
    {x:intra.map(x=>x.t),y:intra.map(x=>x.p),name:"Previsão do fechamento",mode:"markers+lines",
     line:{color:css("--prev"),width:1,dash:"dot"},marker:{size:9,color:css("--prev"),line:{color:css("--surface"),width:2}},
     error_y:{type:"data",symmetric:false,array:intra.map(x=>x.hi-x.p),arrayminus:intra.map(x=>x.p-x.lo),
       color:css("--prev"),thickness:1.5,width:4},
     customdata:intra.map(x=>[D.rotulos[x.c],x.lo,x.hi,x.pa]),
     hovertemplate:"%{customdata[0]}: previsão %{y:,.0f} (%{customdata[1]:,.0f} – %{customdata[2]:,.0f}) · P(alta) %{customdata[3]:.0%}<extra></extra>"}];
  // destaque laranja no horário selecionado
  const k=intra.find(x=>x.c===corte);
  if(k) tr.push({x:[k.t],y:[k.p],mode:"markers",name:"Corte selecionado",hoverinfo:"skip",
     marker:{size:14,color:css("--sel"),line:{color:css("--surface"),width:2}}});
  // linhas horizontais: fechamento anterior (tracejada) e fechamento real (contínua)
  const shapes=[],ann=[];
  if(ant!=null){shapes.push({type:"line",xref:"x",x0,x1,y0:ant,y1:ant,line:{color:css("--ant"),width:1,dash:"dash"}});
    ann.push({x:x1,y:ant,xanchor:"right",yanchor:"bottom",text:"fech. anterior "+fmt(ant),showarrow:false,font:{size:11,color:css("--ink2")}})}
  if(real!=null){shapes.push({type:"line",xref:"x",x0,x1,y0:real,y1:real,line:{color:css("--real"),width:1}});
    ann.push({x:x1,y:real,xanchor:"right",yanchor:"top",text:"fech. real "+fmt(real),showarrow:false,font:{size:11,color:css("--ink")}})}
  const v=s.find(x=>x.c==="vespera");
  if(v) ann.push({x:x0,y:v.p,xanchor:"left",text:"véspera: "+fmt(v.p),showarrow:true,ax:40,ay:0,
    font:{size:11,color:css("--ink2")},arrowcolor:css("--muted")});
  Plotly.react("g2",tr,layout({xaxis:{type:"date",range:[x0,x1],tickformat:"%H:%M",gridcolor:css("--grid"),linecolor:css("--line")},
    shapes,annotations:ann,hovermode:"closest"}),cfg);
}

// Tabela de qualidade histórica (linha do horário selecionado em negrito)
function tabela(){
  const t=document.getElementById("tab");
  t.innerHTML="<tr><th>Horário</th><th>Dias</th><th>Erro médio</th><th>Erro ingênuo</th><th>Acerto de direção</th><th>Cobertura 80%</th></tr>"+
  D.met.map(m=>`<tr class="${m.c===corte?"on":""}"><td>${D.rotulos[m.c]}</td><td>${m.n}</td><td>${pct(m.mae_pct/100,2)}</td>
   <td>${pct(m.mae_ingenuo_pct/100,2)}</td><td>${pct(m.acerto_direcao)}</td><td>${pct(m.cobertura_80)}</td></tr>`).join("");
}

// ======================= TOPO: PREVISÕES DO DIA =======================
const hm=m=>Math.floor(m/60)+"h"+(m%60?String(m%60).padStart(2,"0"):"");     // 810 -> "13h30"
// "▲ +0,12%" / "▼ −0,12%" / "estável" (até 0,05% para cima ou para baixo)
const varia=(v,b)=>{const x=v/b-1; return Math.abs(x)<.0005?"estável":(x>0?"▲ +":"▼ −")+pct(Math.abs(x),2)};
const nomeSeg=x=>x.chave==="amanha"?(G.amanha?"Início do dia de amanhã":"Início do próximo pregão"):x.nome;

// Um cartão por previsão: número grande, variação, faixa e, se já aconteceu, o valor real
function cartoes(){
  document.getElementById("prevs").innerHTML=G.pontos.map(x=>{
    const am=x.chave==="amanha", quando=(am?G.seguinte:G.dia)+" · "+hm(x.min);
    const base=am?(G.encerrado?"ao fechamento do dia":"ao fechamento previsto"):"ao fechamento anterior";
    // rodapé: valor real (momento passado) ou como era a previsão da manhã (momento futuro)
    let rod="";
    if(x.real!=null) rod=`Real: <b>${fmt(x.real)}</b> · previsão ${x.real===x.p?"exata":`errou ${fmt(Math.abs(x.p-x.real))} pontos`}`;
    else if(x.chave==="amanha"&&x.p===x.ref) rod=`Igual ao preço das ${x.feita}: o modelo não vê sinal de alta nem de queda`;
    else if(x.chave==="fim"&&G.manha!==x.p) rod=`Às 10h a previsão era ${fmt(G.manha)}`;
    return `<div class="prev ${x.chave}"><div class="n"><i></i>${nomeSeg(x)}</div>
      <div class="q">${quando} · feita: ${x.feita}</div>
      <div class="v">${fmt(x.p)}</div>
      <div class="l">${varia(x.p,x.base)} em relação ${base} (${fmt(x.base)})</div>
      <div class="l">Provável: entre <b>${fmt(x.lo)}</b> e <b>${fmt(x.hi)}</b></div>
      ${rod?`<div class="r">${rod}</div>`:""}</div>`}).join("");
  const u=G.precos[G.precos.length-1];
  document.getElementById("topo").textContent=G.encerrado
    ?`Pregão de ${G.dia}, encerrado. Fechamento anterior: ${fmt(G.ant)} pontos.`
    :`Pregão de ${G.dia}. IBOV às ${hm(u[0])}: ${fmt(u[1])} pontos (${varia(u[1],G.ant)} no dia).`;
  const cs=G.pontos.map(x=>x.cob).filter(v=>v!=null);
  document.getElementById("aviso").textContent=`“Provável” é a faixa calculada para conter 80% dos casos; no teste histórico ela acertou de ${pct(Math.min(...cs),0)} a ${pct(Math.max(...cs),0)} dos dias, conforme o momento. Início do dia = 11h, após a 1ª hora de pregão. Modelo estatístico para estudo, não é recomendação de investimento.`;
}

// Gráfico do topo. O eixo X são minutos desde 0h; o pregão seguinte é desenhado
// logo à direita (a noite é pulada), na posição XA.
function g0(){
  const F=G.fecha, XA=F+75, x0=600-14, x1=XA+60, tela=innerWidth<640;
  const X=x=>x.chave==="amanha"?XA:x.min, cor=x=>css(x.chave==="hora"?"--sel":"--prev");
  const ps=G.pontos, fut=ps.filter(x=>x.real==null).sort((a,b)=>X(a)-X(b)), u=G.precos[G.precos.length-1];
  const tr=[];
  // barra clara = faixa provável de cada previsão
  for(const x of ps) tr.push({x:[X(x),X(x)],y:[x.lo,x.hi],mode:"lines",line:{color:cor(x),width:12},opacity:.25,hoverinfo:"skip"});
  // linha escura = preço real até agora
  tr.push({x:G.precos.map(v=>v[0]),y:G.precos.map(v=>v[1]),mode:"lines",line:{color:css("--real"),width:2},
    customdata:G.precos.map(v=>hm(v[0])),hovertemplate:"IBOV às %{customdata}: %{y:,.0f}<extra></extra>"});
  // pontilhado = caminho do preço atual até as previsões futuras
  const cam=[u,...fut.filter(x=>X(x)>u[0]).map(x=>[X(x),x.p])];
  if(cam.length>1) tr.push({x:cam.map(v=>v[0]),y:cam.map(v=>v[1]),mode:"lines",line:{color:css("--prev"),width:2,dash:"dot"},hoverinfo:"skip"});
  // ponto escuro = onde o preço está agora (só com o pregão aberto)
  if(!G.encerrado) tr.push({x:[u[0]],y:[u[1]],mode:"markers",marker:{size:9,color:css("--real"),line:{color:css("--surface"),width:2}},hoverinfo:"skip"});
  for(const x of ps) tr.push({x:[X(x)],y:[x.p],mode:"markers",marker:{size:13,color:cor(x),line:{color:css("--surface"),width:2}},
    hovertemplate:`<b>${nomeSeg(x)}</b><br>previsão ${fmt(x.p)}<br>provável ${fmt(x.lo)} a ${fmt(x.hi)}`+(x.real!=null?`<br>real ${fmt(x.real)}`:"")+"<extra></extra>"});
  // rótulos em cima da faixa; o da hora pedida desce se estiver perto de outro (não se cruzam)
  const baixo=x=>x.chave==="hora"&&ps.some(y=>y!==x&&Math.abs(X(y)-X(x))<(tela?150:75));
  const ann=ps.map(x=>({x:X(x),y:baixo(x)?x.lo:x.hi,yanchor:baixo(x)?"top":"bottom",yshift:baixo(x)?-6:6,
    showarrow:false,bgcolor:css("--surface"),borderpad:2,font:{size:12,color:css("--ink")},
    text:`${x.chave==="amanha"?(tela?"Início":G.amanha?"Início de amanhã":"Início do próximo"):x.chave==="hora"?hm(x.min):x.nome}<br><b>${fmt(x.p)}</b>`}));
  // nomes dos dois dias no topo e fechamento anterior à esquerda
  ann.push({x:(600+F)/2,y:1,yref:"paper",yanchor:"bottom",text:G.dia,showarrow:false,font:{size:12,color:css("--ink2")}},
           {x:XA+10,y:1,yref:"paper",yanchor:"bottom",text:G.seguinte,showarrow:false,font:{size:12,color:css("--ink2")}});
  const shapes=[{type:"line",x0:600,x1:F,y0:G.ant,y1:G.ant,line:{color:css("--ant"),width:1.5,dash:"dot"},layer:"below"},
    {type:"line",x0:F+30,x1:F+30,yref:"paper",y0:0,y1:1,line:{color:css("--line"),width:1}}];
  const ys=[...ps.flatMap(x=>[x.lo,x.hi]),...G.precos.map(v=>v[1]),G.ant], mn=Math.min(...ys), mx=Math.max(...ys), f=mx-mn;
  const tv=[]; for(let m=600;m<=F;m+=tela?120:60) tv.push(m);
  Plotly.react("g0",tr,layout({showlegend:false,hovermode:"closest",margin:{l:64,r:12,t:26,b:34},
    xaxis:{range:[x0,x1],tickvals:[...tv,XA],ticktext:[...tv.map(hm),"11h"],showgrid:false,linecolor:css("--line"),zeroline:false,fixedrange:true},
    yaxis:{range:[mn-f*.16,mx+f*.16],gridcolor:css("--grid"),zeroline:false,tickformat:",.0f",nticks:6,fixedrange:true},
    shapes,annotations:ann}),{displayModeBar:false,responsive:true});
  document.getElementById("chave").innerHTML=`<span><i class="k-real"></i>preço real</span><span><i class="k-prev"></i>previsão</span>`+
    (ps.some(x=>x.chave==="hora")?`<span><i class="k-hora"></i>hora que você pediu</span>`:"")+
    `<span><i class="k-faixa"></i>faixa provável</span><span><i class="k-ant"></i>fechamento anterior (${fmt(G.ant)})</span>`;
}
function topo(){
  if(G){cartoes(); g0(); return}
  document.getElementById("topo").textContent="Não há previsões para este dia (feriado, fim de semana ou fora do período).";
  document.getElementById("card0").hidden=true;
}

// ======================= LIGAÇÕES =======================
// Redesenha a página inteira a partir do estado (corte, dia)
function tudo(){document.getElementById("dia").value=dia; seg(); tiles(); g1(); g2(); tabela()}
const di=document.getElementById("dia"); di.min=dias[0]; di.max=dias[dias.length-1];
// data escolhida sem pregão (fim de semana/feriado) -> usa o pregão anterior mais próximo
di.onchange=e=>{const v=e.target.value; dia=dias.filter(d=>d<=v).pop()||dias[0]; tudo()};
document.getElementById("hora").onchange=e=>{if(e.target.value){corte=corteDaHora(e.target.value); tudo()}};
matchMedia("(prefers-color-scheme: dark)").addEventListener("change",()=>{topo(); if(det.open) tudo()});   // troca de tema do sistema
// os gráficos dos detalhes só são desenhados ao abrir (recolhidos, não têm tamanho)
const det=document.getElementById("det");
det.addEventListener("toggle",()=>{if(det.open) tudo()});
topo();
</script></body></html>"""
