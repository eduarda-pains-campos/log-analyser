# log-analyser
Multi-agent system for automated analysis of Android dumpstate logs using LangGraph and LangChain.

## Quick start

Install dependencies and run the example from the repository root:

```powershell
python -m pip install -r requirements.txt
python main.py
```

The Cleaner keeps lines that contain both an `app_targets` package and a configured
error indicator, along with up to two lines before and after each match. Overlapping
context is included only once. The node updates `cleaned_log` and leaves
`context_message` unchanged for downstream agents.
