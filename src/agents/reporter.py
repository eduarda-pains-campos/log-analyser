import json
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from src.state import LogAnalysisState

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[2]
INPUT_PATH = ROOT_DIR / "data" / "incidents_llm.json"
OUTPUT_PATH = ROOT_DIR / "data" / "final_report.md"

SYSTEM_PROMPT_REPORTER = """
Você é um especialista em análise de logs do Android.
Sua tarefa é analisar os incidentes de log fornecidos e propor diagnósticos e soluções reais para os erros/warnings do sistema Android.

ATENÇÃO:
- Frases como "Grupo candidato mantido isolado" ou "Nenhuma correlação SAME_INCIDENT aprovada" são apenas status internos do sistema de análise/pipeline indicando que o evento não foi agrupado com outros.
- NÃO trate o status de isolamento da pipeline como um erro de software do Android.
- Foque sua análise no componente do Android (ex: ActivityManager, KeyguardUpdateMonitor) e no conteúdo real do log.

Responda estritamente em Markdown formatado com:
1. Resumo da Causa Raiz Principal (baseada no log do sistema Android).
2. Solução Recomendada / Plano de Ação em até 3 passos claros.
""".strip()


def generate_ai_report(data: dict) -> str:
    incidents = data.get("incidents") or data.get("final_incidents") or []
    summary = data.get("summary", {})

    if not incidents:
        return "# 📋 Relatório de Análise de Logs\n\nNenhum incidente crítico identificado."

    # 1. Filtro enxuto: seleciona apenas os ERRORs ou no máximo os 5 primeiros incidentes
    critical_incidents = [
        inc for inc in incidents if inc.get("classification") == "ERROR"
    ]
    if not critical_incidents:
        critical_incidents = incidents[:5]

    # 2. Modelo ativo e disponível na API da Groq
    llm = ChatGroq(
        model="openai/gpt-oss-20b",
        temperature=0.2,
    )

    # 3. Payload resumido para não estourar tokens
    payload = {
        "total_incidentes_encontrados": len(incidents),
        "incidentes_prioritarios": [
            {
                "id": inc.get("incident_id"),
                "classificacao": inc.get("classification"),
                "componentes": inc.get("components"),
                "total_ocorrencias": inc.get("occurrence_count"),
                "resumo": inc.get("summary"),
            }
            for inc in critical_incidents
        ],
    }

    response = llm.invoke([
        SystemMessage(content=SYSTEM_PROMPT_REPORTER),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
    ])

    report_lines = [
        "# 📋 Relatório de Diagnóstico e Soluções (IA)",
        "",
        "## 💡 Diagnóstico e Ações Recomendadas",
        response.content,
        "",
        "---",
        f"*Total de incidentes consolidados pela pipeline: {len(incidents)}.*",
    ]

    return "\n".join(report_lines)


def reporter_node(state: LogAnalysisState) -> dict:
    incidents = state.get("final_incidents") or state.get("incidents") or []
    summary = state.get("classifier_llm_summary") or state.get("classifier_summary") or {}

    state_data = {
        "summary": summary,
        "incidents": incidents,
    }

    if not incidents and INPUT_PATH.exists():
        with INPUT_PATH.open("r", encoding="utf-8") as file:
            state_data = json.load(file)

    print("🧠 Gerando diagnósticos e soluções recomendadas com a IA...")
    report_text = generate_ai_report(state_data)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        file.write(report_text)

    return {"final_report": report_text}

if __name__ == "__main__":
    import json

    input_file = ROOT_DIR / "data" / "incidents_llm.json"
    if input_file.exists():
        with input_file.open("r", encoding="utf-8") as f:
            data = json.load(f)

        print("📂 Executando Reporter isoladamente usando data/incidents_llm.json...")
        report_text = generate_ai_report(data)

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with OUTPUT_PATH.open("w", encoding="utf-8") as f:
            f.write(report_text)

        print(f"✅ Relatório atualizado com sucesso em: {OUTPUT_PATH}")
    else:
        print("⚠️ O arquivo data/incidents_llm.json não foi encontrado. Rode a pipeline completa uma vez primeiro.")