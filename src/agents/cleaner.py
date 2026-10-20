from src.state import LogAnalysisState

ERROR_INDICATORS = (
    " E ",
    "Exception",
    "FATAL",
    "KeyStoreException",
    "SecurityException",
);

def cleaner_node(state: LogAnalysisState) -> dict[str, str]:
    """Keep matching error lines and up to two surrounding lines."""
    lines = state["raw_log"].splitlines()
    app_targets = state["app_targets"]

    error_indices = {
        index
        for index, line in enumerate(lines)
        if any(package in line for package in app_targets)
        and any(indicator in line for indicator in ERROR_INDICATORS)
    }

    context_indices = {
        context_index
        for error_index in error_indices
        for context_index in range(
            max(0, error_index - 2),
            min(len(lines), error_index + 3),
        )
    }

    cleaned_log = "\n".join(lines[index] for index in sorted(context_indices))
    return {"cleaned_log": cleaned_log}
