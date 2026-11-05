from langgraph.graph import END, START, StateGraph

# Certifique-se de usar o prefixo "src." em todas as importações
from src.agents.cleaner import cleaner_node
from src.agents.classifier import classifier_node
from src.agents.classifier_llm import classifier_llm_node
from src.agents.reporter import reporter_node
from src.state import LogAnalysisState

# Instancia o Grafo de Estado
workflow = StateGraph(LogAnalysisState)

# 1. Registra os 4 nós da pipeline
workflow.add_node("cleaner", cleaner_node)
workflow.add_node("classifier", classifier_node)
workflow.add_node("classifier_llm", classifier_llm_node)
workflow.add_node("reporter", reporter_node)

# 2. Define o fluxo sequencial encadeado
workflow.add_edge(START, "cleaner")
workflow.add_edge("cleaner", "classifier")
workflow.add_edge("classifier", "classifier_llm")
workflow.add_edge("classifier_llm", "reporter")
workflow.add_edge("reporter", END)

# 3. Compila o grafo
graph = workflow.compile()