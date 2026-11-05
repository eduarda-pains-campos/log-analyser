from typing import TypedDict


class LogAnalysisState(TypedDict):
    raw_log: str
    cleaned_log: str
    app_targets: list[str]
    context_message: str

    cleaner_summary: dict
    classifier_summary: dict
    incidents: list[dict]

    classifier_llm_summary: dict
    final_incidents: list[dict]

    final_report: str