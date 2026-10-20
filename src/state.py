from typing import TypedDict


class LogAnalysisState(TypedDict):
    raw_log: str
    cleaned_log: str
    app_targets: list[str]
    context_message: str
