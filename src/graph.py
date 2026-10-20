from langgraph.graph import END, START, StateGraph

from src.agents.cleaner import cleaner_node
from src.state import LogAnalysisState


workflow = StateGraph(LogAnalysisState)
workflow.add_node("cleaner", cleaner_node)
workflow.add_edge(START, "cleaner")
workflow.add_edge("cleaner", END)

graph = workflow.compile()
