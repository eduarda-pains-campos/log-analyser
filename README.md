# Android Log Analyzer

Projeto de multiagentes para analisar logs Android, identificar warnings e errors e agrupar ocorrências potencialmente relacionadas. Utiliza Python, LangChain e um modelo de linguagem local executado pelo Ollama.

OBS:
Por enquanto, os scripts são executados separadamente. O fluxo integrado de multiagentes ainda não foi implementado.

## Requisitos e instalação

- Python 3.10 ou superior
- [Ollama para Windows](https://ollama.com/download/windows)
- Aproximadamente 10 GB livres para baixar o modelo `qwen3:14b` (além do espaço dos arquivos do projeto)

Na pasta raiz do projeto, crie um ambiente virtual e instale as dependências:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Configurar o Ollama (escolhi esse modelo, pois nao temos custo para utilizá-lo)

Instale o Ollama pelo site oficial e baixe o modelo uma vez:

```powershell
ollama --version
ollama pull qwen3:14b
ollama list
```

O Ollama executa o modelo localmente; não é necessária uma chave de API paga. O download inicial precisa de internet e as inferências consomem memória, processamento e energia do computador.

Para testar o modelo manualmente:

```powershell
ollama run qwen3:14b
```

Digite `/bye` para sair da conversa. Para testar a integração Python + LangChain + Ollama:

```powershell
.\.venv\Scripts\python.exe test_ollama.py
```

O Ollama precisa estar disponível localmente para executar o Classifier com IA.

## Como executar

Execute os scripts, na ordem abaixo, a partir da pasta raiz `log-analyser`:

```powershell
# 1. Filtrar o CSV original e preservar o contexto
.\.venv\Scripts\python.exe src/agents/cleaner.py

# 2. Agrupar ocorrências semelhantes por regras
.\.venv\Scripts\python.exe src/agents/classifier.py

# 3. Avaliar relações entre grupos candidatos usando o LLM local
.\.venv\Scripts\python.exe src/agents/classifier_llm.py
```

O terceiro passo depende de `data/incidents.json`, gerado pelo segundo passo. Se a base original ou as regras do Cleaner mudarem, execute novamente as etapas na ordem indicada.

## O que cada componente faz?

### 1. Cleaner — `src/agents/cleaner.py`

Script determinístico em Python, sem LLM. Lê `data/android_logs.csv`, identifica registros com `Level=W` (warning) ou `Level=E` (error) e mantém até duas linhas anteriores e duas posteriores como contexto, quando disponíveis. As linhas selecionadas apenas como contexto recebem a classificação `CONTEXT`.

Na base atual existem 2.000 registros:

| Nível original | Quantidade |
|---|---:|
| `I` | 920 |
| `D` | 650 |
| `V` | 257 |
| `W` | 170 |
| `E` | 3 |
| **Total** | **2.000** |

O Cleaner gerou 524 registros: 170 `WARNING`, 3 `ERROR` e 351 `CONTEXT`. Portanto, **524 não é a quantidade de erros**: são 173 ocorrências identificadas (warnings + errors) mais 351 linhas de contexto. As janelas de contexto podem se sobrepor; um registro é selecionado apenas uma vez.

Saída: `data/android_logs_cleaned.csv`.

### 2. Classifier por regras — `src/agents/classifier.py`

Agrupa warnings e errors que compartilham classificação, componente e `EventTemplate`, considerando até cinco segundos entre ocorrências consecutivas. As linhas `CONTEXT` ajudam a interpretar os eventos, mas não iniciam grupos.

Na execução atual, as 173 ocorrências foram agrupadas em 42 grupos candidatos: 39 de warning e 3 de error. Esses grupos são produzidos por regras e não representam necessariamente causas raiz ou incidentes confirmados.

Saída: `data/incidents.json`.

### 3. Classifier com IA — `src/agents/classifier_llm.py`

Usa LangChain para consultar o Qwen3 14B local via Ollama e avaliar se **pares de grupos candidatos** parecem pertencer ao mesmo incidente, representam apenas um padrão semelhante, são relacionados mas distintos, não têm relação ou não podem ser avaliados com segurança.

O script prepara pares apenas quando há eventos com até 2 segundos de diferença e pelo menos um sinal em comum: componente, PID ou TID. Os pares são enviados ao LLM em pequenos lotes. O programa une grupos somente quando a resposta é `SAME_INCIDENT`, a confiança estimada atinge pelo menos `0.80` e a consolidação permanece dentro de uma janela total de 10 segundos. A resposta é validada; quando não há decisão válida, os grupos permanecem separados. O script também confere se os eventos de origem foram preservados sem duplicação.

Saída: `data/incidents_llm.json`, contendo as decisões dos pares e os incidentes finais.

**Por que existem dois Classifiers?** O Classifier por regras é rápido, previsível e cria uma linha de base reproduzível. O Classifier com IA acrescenta interpretação semântica para avaliar possíveis relações que regras fixas podem não reconhecer. Manter os dois permite comparar as abordagens e verificar se a IA realmente melhora os resultados. O LLM não substitui as verificações determinísticas de integridade.

A confiança informada pelo modelo é uma estimativa, não uma probabilidade calibrada. As decisões precisam ser comparadas às mensagens originais antes de considerar os grupos como incidentes reais.

## Arquivos de dados

| Arquivo | Finalidade |
|---|---|
| `data/android_logs.csv` | Base original com 2.000 registros |
| `data/android_logs_cleaned.csv` | Warnings, errors e linhas de contexto |
| `data/incidents.json` | Grupos candidatos do Classifier por regras |
| `data/incidents_llm.json` | Decisões de correlação e incidentes finais do Classifier com IA |

O CSV deve ser processado pelo Python. Para abrir no Excel, prefira **Dados → De Texto/CSV**, com vírgula como delimitador e aspas duplas como qualificador de texto, pois as mensagens podem conter vírgulas internas.
