from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from src.graph import graph

ROOT_DIR = Path(__file__).resolve().parent
LOG_FILE_PATH = (
    ROOT_DIR
    / "GeracaoLogErros"
    / "dados"
    / "teste"
    / "loghub_android_2k_teste.log"
)


def load_raw_log(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    with path.open("r", encoding="utf-8", errors="ignore") as file:
        return file.read()


def main() -> None:
    print(f"📂 Carregando log: {LOG_FILE_PATH.name}")
    raw_log_content = load_raw_log(LOG_FILE_PATH)

    print("🚀 Executando Pipeline no LangGraph...")

    initial_state = {
        "raw_log": raw_log_content,
        "cleaned_log": "",
        "app_targets": [
            "com.samsung.android.spay",
            "com.samsung.android.spayfw",
            "KnoxService",
        ],
        "context_message": "Investigar falhas relacionadas ao Knox e Samsung Wallet.",
    }

    final_state = graph.invoke(initial_state)

    # ----------------------------------------------------
    # EXIBIÇÃO SUCINTA NO TERMINAL
    # ----------------------------------------------------
    summary = final_state.get("classifier_llm_summary", {})
    incidents = final_state.get("final_incidents", [])

    print("\n==========================================")
    print("        RESUMO EXECUTIVO DA ANÁLISE       ")
    print("==========================================")
    print(f"• Total de Logs Lidos:       {summary.get('source_event_count', 0)}")
    print(f"• Candidatos (Regras):       {summary.get('candidate_groups', 0)}")
    print(f"• Incidentes Consolidados:  {len(incidents)}")
    print(f"• Agrupamentos via IA:       {summary.get('accepted_merge_links', 0)}")
    print("------------------------------------------")
    print("📁 Relatório detalhado salvo com sucesso em:")
    print("   -> data/final_report.md")
    print("==========================================\n")


if __name__ == "__main__":
    main()