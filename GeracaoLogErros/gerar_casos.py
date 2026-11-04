"""Gera casos de teste (log + descrição do cliente + gabarito) para o sistema de análise de logs.

Fluxo:
  1. Lê o catálogo de problemas (problemas/*.yaml), os distratores e a receita.
  2. Valida tudo (placeholders, tickets, linhas de erro).
  3. Para cada caso: sorteia um log de ruído real (dados/treino/ ou dados/teste/, conforme o
     split do caso), recorta um trecho, injeta a falha e os distratores no meio, sorteia a
     descrição do cliente e grava o gabarito.
  4. Grava o Jira simulado (jira_mock.json) e um índice (indice.csv).

Casos de treino só usam logs de dados/treino/; casos de teste só usam logs de dados/teste/.
Se as duas pastas estiverem vazias, baixa o Android_2k.log do Loghub e divide entre elas.

Uso:
  python gerar_casos.py
  python gerar_casos.py --problemas cartao_bin_nao_suportado --casos 5 --seed 7
  python gerar_casos.py --so-validar
"""

import argparse
import csv
import json
import random
import re
import shutil
import sys
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import yaml

PASTA = Path(__file__).resolve().parent
URL_LOGHUB_ANDROID = "https://raw.githubusercontent.com/logpai/loghub/master/Android/Android_2k.log"
EXTENSOES_RUIDO = {".log", ".txt"}
SPLITS = ("treino", "teste")

# 03-17 16:13:38.811  1702  2395 D WindowManager: mensagem
RE_LOGCAT = re.compile(r"^(\d\d-\d\d \d\d:\d\d:\d\d\.\d{3})\s+(\d+)\s+(\d+)\s+([VDIWEF])\s")
RE_PLACEHOLDER = re.compile(r"\{(\w+)\}")
NIVEIS = set("VDIWEF")
NIVEIS_ERRO = {"E", "F"}


# ---------------------------------------------------------------------------
# Leitura e validação
# ---------------------------------------------------------------------------

def ler_yaml(caminho):
    with open(caminho, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def carregar_problemas(pasta):
    problemas = []
    for arq in sorted(pasta.glob("*.yaml")):
        p = ler_yaml(arq)
        p["_arquivo"] = arq.name
        problemas.append(p)
    return problemas


def carregar_distratores(pasta):
    distratores = []
    for arq in sorted(pasta.glob("*.yaml")):
        for d in ler_yaml(arq).get("distratores", []):
            d["_arquivo"] = arq.name
            distratores.append(d)
    return distratores


def validar_bloco(bloco, onde, erros):
    """Valida o que problemas e distratores têm em comum: variáveis e linhas."""
    variaveis = bloco.get("variaveis") or {}
    for nome, spec in variaveis.items():
        tipo = (spec or {}).get("tipo")
        if tipo not in {"inteiro", "hex", "uuid", "escolha", "variante"}:
            erros.append(f"{onde}: variável '{nome}' com tipo inválido: {tipo}")
        if tipo in {"escolha", "variante"} and not spec.get("valores"):
            erros.append(f"{onde}: variável '{nome}' precisa de 'valores'")
    linhas = bloco.get("linhas") or []
    if not linhas:
        erros.append(f"{onde}: sem linhas")
    for i, ln in enumerate(linhas, 1):
        if ln.get("nivel") not in NIVEIS:
            erros.append(f"{onde}: linha {i} com nivel inválido: {ln.get('nivel')}")
        if not ln.get("tag") or ln.get("msg") is None:
            erros.append(f"{onde}: linha {i} sem tag ou msg")
        if ln.get("thread", "principal") not in {"principal", "worker"}:
            erros.append(f"{onde}: linha {i} com thread inválida: {ln.get('thread')}")
        for ph in RE_PLACEHOLDER.findall(str(ln.get("msg", ""))):
            if ph not in variaveis:
                erros.append(f"{onde}: linha {i} usa {{{ph}}}, que não está em variaveis")


def validar(problemas, distratores):
    erros = []
    ids = set()
    tickets = {}
    for p in problemas:
        onde = p["_arquivo"]
        pid = p.get("id")
        if not pid:
            erros.append(f"{onde}: sem id")
        elif pid in ids:
            erros.append(f"{onde}: id repetido '{pid}'")
        ids.add(pid)
        validar_bloco(p, onde, erros)
        linhas = p.get("linhas") or []
        nucleo = [ln for ln in linhas if ln.get("papel") == "nucleo"]
        if not nucleo:
            erros.append(f"{onde}: nenhuma linha com papel: nucleo")
        if not any(ln.get("nivel") in NIVEIS_ERRO for ln in nucleo):
            erros.append(f"{onde}: o núcleo não tem nenhuma linha de nível E/F (o filtro nunca a acharia)")
        for i, ln in enumerate(linhas, 1):
            if ln.get("papel") not in {"nucleo", "contexto"}:
                erros.append(f"{onde}: linha {i} com papel inválido: {ln.get('papel')}")
        if not p.get("descricoes_cliente"):
            erros.append(f"{onde}: sem descricoes_cliente")
        jira = p.get("jira") or {}
        a_registrar = list(jira.get("iscas") or [])
        if jira.get("presente"):
            if not (jira.get("ticket") or {}).get("id"):
                erros.append(f"{onde}: jira.presente = true, mas sem ticket.id")
            else:
                a_registrar.append(jira["ticket"])
        for t in a_registrar:
            tid = t.get("id")
            if tid in tickets and tickets[tid] != onde:
                erros.append(f"{onde}: ticket {tid} já definido em {tickets[tid]}")
            tickets[tid] = onde
    dids = set()
    for d in distratores:
        onde = f"{d['_arquivo']} ({d.get('id')})"
        if not d.get("id") or d["id"] in dids:
            erros.append(f"{onde}: distrator sem id ou id repetido")
        dids.add(d.get("id"))
        validar_bloco(d, onde, erros)
    return erros


# ---------------------------------------------------------------------------
# Ruído de fundo (log real)
# ---------------------------------------------------------------------------

def arquivos_ruido(pasta):
    if not pasta.exists():
        return []
    return sorted(a for a in pasta.iterdir() if a.is_file() and a.suffix.lower() in EXTENSOES_RUIDO)


def preparar_ruido_padrao(pastas, proporcao_teste):
    """Se não há nenhum log de ruído, baixa o Android_2k.log do Loghub e divide entre treino e teste.

    O começo do arquivo vai para treino e o final para teste, sem nenhuma linha em comum.
    """
    print(f"Nenhum log em dados/treino nem dados/teste. Baixando do Loghub: {URL_LOGHUB_ANDROID}")
    try:
        try:
            import truststore  # usa os certificados do Windows (necessário atrás de proxy corporativo)
            truststore.inject_into_ssl()
        except ImportError:
            pass
        with urllib.request.urlopen(URL_LOGHUB_ANDROID, timeout=60) as r:
            linhas = r.read().decode("utf-8", errors="replace").splitlines()
    except Exception as e:
        sys.exit(
            f"Não consegui baixar o log ({e}).\n"
            f"Coloque logs no formato logcat em {pastas['treino']} e {pastas['teste']}."
        )
    corte = int(len(linhas) * (1 - proporcao_teste))
    partes = {"treino": linhas[:corte], "teste": linhas[corte:]}
    for split, conteudo in partes.items():
        pastas[split].mkdir(parents=True, exist_ok=True)
        destino = pastas[split] / f"loghub_android_2k_{split}.log"
        destino.write_text("\n".join(conteudo) + "\n", encoding="utf-8")
        print(f"  {destino.name}: {len(conteudo)} linhas")


def carregar_ruidos(pasta):
    """Lê todos os logs de ruído de uma pasta. Devolve [(nome_do_arquivo, linhas)]."""
    return [(a.name, ler_ruido(a)) for a in arquivos_ruido(pasta)]


def ler_ruido(caminho):
    """Lê o log e devolve uma lista de dicts {texto, ts, pid, nivel}. ts pode ser None."""
    linhas = []
    with open(caminho, encoding="utf-8-sig", errors="replace") as f:
        for texto in f:
            texto = texto.rstrip("\r\n")
            if not texto.strip():
                continue
            m = RE_LOGCAT.match(texto)
            if m:
                ts = datetime.strptime("2000-" + m.group(1), "%Y-%m-%d %H:%M:%S.%f")
                linhas.append({"texto": texto, "ts": ts, "pid": int(m.group(2)), "nivel": m.group(4)})
            else:
                linhas.append({"texto": texto, "ts": None, "pid": None, "nivel": None})
    validas = sum(1 for ln in linhas if ln["ts"])
    if validas < len(linhas) * 0.5:
        sys.exit(f"{caminho}: só {validas}/{len(linhas)} linhas no formato logcat. Verifique o arquivo.")
    return linhas


def preencher_timestamps(segmento):
    """Linhas fora do formato herdam o timestamp da anterior (ou da próxima, no início)."""
    ultimo = next((ln["ts"] for ln in segmento if ln["ts"]), None)
    for ln in segmento:
        if ln["ts"]:
            ultimo = ln["ts"]
        ln["ts_efetivo"] = ultimo


# ---------------------------------------------------------------------------
# Montagem dos blocos injetados
# ---------------------------------------------------------------------------

def sortear_variaveis(variaveis, rng, prob_variante):
    valores, usou_variante = {}, False
    for nome, spec in (variaveis or {}).items():
        tipo = spec["tipo"]
        if tipo == "inteiro":
            valores[nome] = str(rng.randint(spec.get("min", 0), spec.get("max", 9999)))
        elif tipo == "hex":
            valores[nome] = "".join(rng.choice("0123456789abcdef") for _ in range(spec.get("tamanho", 8)))
        elif tipo == "uuid":
            valores[nome] = str(uuid.UUID(int=rng.getrandbits(128), version=4))
        elif tipo == "escolha":
            valores[nome] = str(rng.choice(spec["valores"]))
        elif tipo == "variante":
            opcoes = spec["valores"]
            if len(opcoes) > 1 and rng.random() < prob_variante:
                valores[nome] = str(rng.choice(opcoes[1:]))
                usou_variante = True
            else:
                valores[nome] = str(opcoes[0])
    return valores, usou_variante


def renderizar(msg, valores):
    # Só troca {nome} conhecido; chaves que fazem parte do texto ficam como estão.
    return RE_PLACEHOLDER.sub(lambda m: valores.get(m.group(1), m.group(0)), str(msg))


def montar_bloco(origem, tipo_origem, definicao, rng, prob_variante, relevante=False):
    valores, usou_variante = sortear_variaveis(definicao.get("variaveis"), rng, prob_variante)
    linhas = [
        {
            "nivel": ln["nivel"],
            "tag": ln["tag"],
            "msg": renderizar(ln["msg"], valores),
            "thread": ln.get("thread", "principal"),
            "papel": ln.get("papel", "nucleo"),
        }
        for ln in definicao["linhas"]
    ]
    return {
        "origem": origem,
        "tipo_origem": tipo_origem,
        "relevante": relevante,
        "linhas": linhas,
        "variaveis": valores,
        "usou_variante": usou_variante,
    }


def formatar_linha(ts, pid, tid, nivel, tag, msg):
    return f"{ts:%m-%d %H:%M:%S}.{ts.microsecond // 1000:03d} {pid:>5} {tid:>5} {nivel} {tag}: {msg}"


def injetar(segmento, blocos, linha_start_proc, app, rng, max_entre):
    """Insere os blocos no segmento de ruído. Devolve (linhas do log, posições de cada bloco).

    Cada bloco ocupa uma faixa própria do segmento (sem sobreposição). Entre as linhas de um bloco
    podem entrar até `max_entre` linhas de ruído, como acontece num log real com vários processos.
    Os timestamps são interpolados entre as linhas de ruído vizinhas, então ficam sempre crescentes.
    """
    n = len(segmento)
    # depois_de[i] = lista de (id_bloco, idx_linha, linha) inseridas logo após a linha i do ruído
    depois_de = {}
    if linha_start_proc is not None:
        depois_de.setdefault(0, []).append(("start_proc", 0, linha_start_proc))

    # Divide o segmento em faixas iguais (deixando a ponta inicial livre) e sorteia uma para cada bloco
    inicio_util = max(2, n // 20)
    faixas = len(blocos)
    tam_faixa = (n - inicio_util) // max(faixas, 1)
    ordem = list(range(faixas))
    rng.shuffle(ordem)
    for b_id, bloco in enumerate(blocos):
        a = inicio_util + ordem[b_id] * tam_faixa
        offsets, pos = [], 0
        for _ in bloco["linhas"]:
            offsets.append(pos)
            pos += rng.randint(0, max_entre)
        espaco = max(tam_faixa - pos - 1, 0)
        ancora = a + rng.randint(0, espaco)
        for idx, ln in enumerate(bloco["linhas"]):
            alvo = min(ancora + offsets[idx], n - 1)
            depois_de.setdefault(alvo, []).append((b_id, idx, ln))

    linhas_log = []
    posicoes = {b_id: {} for b_id in range(len(blocos))}
    for i, ruido in enumerate(segmento):
        linhas_log.append({"texto": ruido["texto"], "origem": "ruido", "nivel": ruido["nivel"]})
        inseridas = depois_de.get(i, [])
        if not inseridas:
            continue
        ts_a = ruido["ts_efetivo"]
        ts_b = segmento[i + 1]["ts_efetivo"] if i + 1 < n else ts_a + timedelta(milliseconds=50 * len(inseridas))
        passo = (ts_b - ts_a) / (len(inseridas) + 1)
        for k, (b_id, idx, ln) in enumerate(inseridas, 1):
            ts = ts_a + passo * k
            if b_id == "start_proc":
                linhas_log.append({"texto": formatar_linha(ts, *ln), "origem": "start_proc", "nivel": "I"})
                continue
            tid = app["tid_worker"] if ln["thread"] == "worker" else app["pid"]
            texto = formatar_linha(ts, app["pid"], tid, ln["nivel"], ln["tag"], ln["msg"])
            linhas_log.append({"texto": texto, "origem": blocos[b_id]["origem"], "nivel": ln["nivel"]})
            posicoes[b_id][idx] = len(linhas_log)  # número da linha, começando em 1
    return linhas_log, posicoes


def resumo_bloco(bloco, pos):
    numeros = [pos[i] for i in range(len(bloco["linhas"]))]
    nucleo = [pos[i] for i, ln in enumerate(bloco["linhas"]) if ln["papel"] == "nucleo"]
    return {
        "linha_inicio": min(numeros),
        "linha_fim": max(numeros),
        "linha_inicio_nucleo": min(nucleo) if nucleo else None,
        "linha_fim_nucleo": max(nucleo) if nucleo else None,
        "linhas_nucleo": nucleo,
        "linhas_erro_nucleo": [pos[i] for i, ln in enumerate(bloco["linhas"])
                               if ln["papel"] == "nucleo" and ln["nivel"] in NIVEIS_ERRO],
        "linhas_contexto": [pos[i] for i, ln in enumerate(bloco["linhas"]) if ln["papel"] == "contexto"],
        "todas_as_linhas": numeros,
        "intercalado": max(numeros) - min(numeros) + 1 > len(numeros),
    }


# ---------------------------------------------------------------------------
# Geração dos casos
# ---------------------------------------------------------------------------

def dividir_descricoes(problema, rng, proporcao_teste):
    descr = list(problema["descricoes_cliente"])
    rng.shuffle(descr)
    if len(descr) < 2:
        return descr, descr
    n_teste = min(max(1, round(len(descr) * proporcao_teste)), len(descr) - 1)
    return descr[n_teste:], descr[:n_teste]


def ticket_do_problema(problema):
    jira = problema.get("jira") or {}
    return jira["ticket"]["id"] if jira.get("presente") else None


def gerar_caso(num, split, tipo, alvo, problemas, distratores, descricao, ruidos, receita, rng):
    nome_ruido, ruido = rng.choice(ruidos)
    tam = min(receita["ruido"].get("linhas_por_caso", 400), len(ruido))
    inicio = rng.randint(0, len(ruido) - tam)
    segmento = [dict(ln) for ln in ruido[inicio:inicio + tam]]
    preencher_timestamps(segmento)

    prob_var = receita.get("prob_variante", 0.5)
    blocos = []
    if tipo in {"simples", "dois_problemas"}:
        blocos.append(montar_bloco(alvo["id"], "problema", alvo, rng, prob_var, relevante=True))
    if tipo == "dois_problemas":
        outro = rng.choice([p for p in problemas if p["id"] != alvo["id"]])
        blocos.append(montar_bloco(outro["id"], "problema", outro, rng, prob_var))
    dmin = receita["distratores_por_caso"]["min"]
    dmax = receita["distratores_por_caso"]["max"]
    qtd = min(rng.randint(dmin, dmax), len(distratores))
    for d in rng.sample(distratores, qtd):
        blocos.append(montar_bloco(d["id"], "distrator", d, rng, prob_var))

    # PID do app: livre no trecho de ruído. A linha "Start proc" permite ao pipeline filtrar por PID.
    pids_ruido = {ln["pid"] for ln in segmento if ln["pid"]}
    pid = rng.choice([p for p in range(2000, 32000) if p not in pids_ruido])
    app = {"pacote": receita["app"]["pacote"], "pid": pid, "tid_worker": pid + rng.randint(10, 200)}
    pid_am = next((ln["pid"] for ln in segmento if " ActivityManager:" in ln["texto"] and ln["pid"]), 1000)
    start_proc = (pid_am, pid_am, "I", "ActivityManager",
                  f"Start proc {pid}:{app['pacote']}/u0a{rng.randint(100, 399)} for activity "
                  f"{app['pacote']}/.MainActivity")

    linhas_log, posicoes = injetar(segmento, blocos, start_proc, app, rng,
                                   receita.get("max_ruido_entre_linhas", 0))

    falhas, distr_info, etiquetas = [], [], {tipo}
    for b_id, bloco in enumerate(blocos):
        info = {"id": bloco["origem"], **resumo_bloco(bloco, posicoes[b_id]), "variaveis": bloco["variaveis"]}
        if bloco["tipo_origem"] == "problema":
            p = next(p for p in problemas if p["id"] == bloco["origem"])
            info["relevante_para_descricao"] = bloco["relevante"]
            info["ticket"] = ticket_do_problema(p)
            info["mensagem_variante"] = bloco["usou_variante"]
            falhas.append(info)
            if bloco["relevante"] and bloco["usou_variante"]:
                etiquetas.add("mensagem_variante")
            if bloco["relevante"] and info["intercalado"]:
                etiquetas.add("intercalado")
        else:
            distr_info.append(info)
    if distr_info:
        etiquetas.add("distrator_mesmo_dominio")
    jira_alvo = alvo.get("jira") or {}
    if jira_alvo.get("iscas"):
        etiquetas.add("isca_jira")
    if tipo == "sem_erro_relevante":
        esperado, ticket = "nenhum_erro_relevante", None
    elif ticket_do_problema(alvo):
        esperado, ticket = "conhecido", ticket_do_problema(alvo)
    else:
        esperado, ticket = "desconhecido", None
        etiquetas.add("desconhecido")
    if descricao.get("estilo") == "vago":
        etiquetas.add("descricao_vaga")

    erros_ruido = [i for i, ln in enumerate(linhas_log, 1)
                   if ln["origem"] == "ruido" and ln["nivel"] in NIVEIS_ERRO]
    gabarito = {
        "caso": f"caso_{num:04d}",
        "split": split,
        "tipo": tipo,
        "problema_alvo": alvo["id"],
        "descricao_cliente": descricao,
        "resultado_esperado": esperado,
        "ticket_esperado": ticket,
        "app": {"pacote": app["pacote"], "pid": app["pid"]},
        "falhas": falhas,
        "distratores": distr_info,
        "erros_do_ruido": {"quantidade": len(erros_ruido), "linhas": erros_ruido},
        "total_linhas": len(linhas_log),
        "etiquetas": sorted(etiquetas),
        "ruido": {"pasta": f"dados/{split}", "arquivo": nome_ruido, "linha_origem_inicio": inicio + 1,
                  "linhas": tam},
        "seed": receita["seed"],
    }
    return [ln["texto"] for ln in linhas_log], gabarito


def montar_jira(problemas):
    tickets = []
    for p in problemas:
        jira = p.get("jira") or {}
        if jira.get("presente"):
            tickets.append({**jira["ticket"], "problema": p["id"], "isca": False})
        for isca in jira.get("iscas") or []:
            tickets.append({**isca, "problema": None, "isca": True})
    return sorted(tickets, key=lambda t: t["id"])


def sortear_tipos(n, pesos, rng):
    tipos = [t for t, w in pesos.items() if w > 0]
    return rng.choices(tipos, weights=[pesos[t] for t in tipos], k=n)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--receita", default=str(PASTA / "receita.yaml"))
    ap.add_argument("--problemas", help="ids separados por vírgula (sobrescreve a receita)")
    ap.add_argument("--casos", type=int, help="casos por problema (sobrescreve a receita)")
    ap.add_argument("--seed", type=int, help="sobrescreve a receita")
    ap.add_argument("--so-validar", action="store_true", help="só valida catálogo e receita")
    args = ap.parse_args()

    receita = ler_yaml(args.receita)
    if args.seed is not None:
        receita["seed"] = args.seed
    if args.casos is not None:
        receita["casos_por_problema"] = args.casos
    if args.problemas:
        receita["problemas"] = [s.strip() for s in args.problemas.split(",")]

    catalogo = carregar_problemas(PASTA / "problemas")
    distratores = carregar_distratores(PASTA / "distratores")
    erros = validar(catalogo, distratores)
    selecionados = receita.get("problemas", "todos")
    if selecionados != "todos":
        faltando = set(selecionados) - {p.get("id") for p in catalogo}
        erros += [f"receita: problema '{f}' não existe em problemas/" for f in sorted(faltando)]
    if erros:
        print("Erros de validação:")
        for e in erros:
            print("  -", e)
        sys.exit(1)
    alvos = catalogo if selecionados == "todos" else [p for p in catalogo if p["id"] in selecionados]
    print(f"OK: {len(catalogo)} problema(s) no catálogo, {len(distratores)} distrator(es), "
          f"{len(alvos)} problema(s) selecionado(s).")
    if args.so_validar:
        return

    rng = random.Random(receita["seed"])
    p_teste = receita.get("proporcao_teste", 0.3)
    n_casos = receita["casos_por_problema"]
    n_teste = round(n_casos * p_teste)
    splits_usados = [s for s, qtd in (("treino", n_casos - n_teste), ("teste", n_teste)) if qtd > 0]

    cfg_ruido = receita.get("ruido") or {}
    pastas = {s: PASTA / cfg_ruido.get(f"pasta_{s}", f"dados/{s}") for s in SPLITS}
    if not any(arquivos_ruido(p) for p in pastas.values()):
        preparar_ruido_padrao(pastas, p_teste)
    ruidos = {}
    for split in splits_usados:
        ruidos[split] = carregar_ruidos(pastas[split])
        if not ruidos[split]:
            sys.exit(f"Nenhum log de ruído (.log/.txt) em {pastas[split]}, necessário para os casos de {split}.")
        print(f"Ruído de {split}: " + ", ".join(f"{nome} ({len(ls)} linhas)" for nome, ls in ruidos[split]))
    nomes = {s: {nome for nome, _ in ruidos.get(s, [])} for s in SPLITS}
    if nomes["treino"] & nomes["teste"]:
        print(f"Aviso: o mesmo arquivo está em treino e teste: {', '.join(sorted(nomes['treino'] & nomes['teste']))}")
    tam = cfg_ruido.get("linhas_por_caso", 400)
    curtos = [nome for s in ruidos for nome, ls in ruidos[s] if len(ls) < tam]
    if curtos:
        print(f"Aviso: logs menores que linhas_por_caso ({tam}), os casos com eles sairão menores: {', '.join(curtos)}")

    pesos = dict(receita["tipos_de_caso"])
    if len(catalogo) < 2 and pesos.get("dois_problemas"):
        print("Aviso: 'dois_problemas' precisa de 2+ problemas no catálogo; tipo ignorado por enquanto.")
        pesos["dois_problemas"] = 0

    saida = PASTA / receita.get("saida", "saida")
    if (saida / "casos").exists():
        shutil.rmtree(saida / "casos")
    (saida / "casos").mkdir(parents=True)

    indice, num = [], 0
    for alvo in alvos:
        descr_split = dict(zip(SPLITS, dividir_descricoes(alvo, rng, p_teste)))
        for i, tipo in enumerate(sortear_tipos(n_casos, pesos, rng)):
            split = "teste" if i < n_teste else "treino"
            num += 1
            descricao = rng.choice(descr_split[split])
            linhas, gab = gerar_caso(num, split, tipo, alvo, catalogo, distratores, descricao,
                                     ruidos[split], receita, rng)
            pasta_caso = saida / "casos" / split / gab["caso"]
            pasta_caso.mkdir(parents=True)
            (pasta_caso / "log.txt").write_text("\n".join(linhas) + "\n", encoding="utf-8")
            (pasta_caso / "descricao.txt").write_text(descricao["texto"] + "\n", encoding="utf-8")
            (pasta_caso / "gabarito.json").write_text(json.dumps(gab, ensure_ascii=False, indent=2),
                                                      encoding="utf-8")
            alvo_falha = next((f for f in gab["falhas"] if f["relevante_para_descricao"]), None)
            indice.append({
                "caso": gab["caso"], "split": split, "tipo": tipo, "problema_alvo": alvo["id"],
                "resultado_esperado": gab["resultado_esperado"], "ticket_esperado": gab["ticket_esperado"] or "",
                "linha_inicio": alvo_falha["linha_inicio"] if alvo_falha else "",
                "linha_fim": alvo_falha["linha_fim"] if alvo_falha else "",
                "arquivo_ruido": gab["ruido"]["arquivo"],
                "distratores": len(gab["distratores"]), "erros_do_ruido": gab["erros_do_ruido"]["quantidade"],
                "etiquetas": ";".join(gab["etiquetas"]),
            })

    (saida / "jira_mock.json").write_text(json.dumps(montar_jira(catalogo), ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    with open(saida / "indice.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(indice[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(indice)
    por_split = {s: sum(1 for r in indice if r["split"] == s) for s in SPLITS}
    print(f"Gerados {len(indice)} casos em {saida / 'casos'} (treino={por_split['treino']}, teste={por_split['teste']}).")
    print(f"Jira simulado: {saida / 'jira_mock.json'} | Índice: {saida / 'indice.csv'}")


if __name__ == "__main__":
    main()
