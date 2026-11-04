# Análise automática de logs de suporte

## O problema

Um cliente usa o aplicativo (carteira digital) no celular e algo dá errado. Ele abre um chamado no
suporte com duas coisas:

1. **Uma frase** descrevendo o que aconteceu ("não consigo adicionar meu cartão").
2. **O log do celular** (Samsung / Android, formato logcat).

O log tem milhares de linhas, e quase todas não têm relação com o problema: são do sistema
operacional, de outros apps, de outras partes do próprio app. Encontrar à mão a falha que explica a
queixa do cliente é lento e depende de quem conhece o sistema.

Sabe-se, pela experiência com o problema, que o que causa a falha aparece em linhas de **erro**.

## A solução proposta (sistema multiagente)

```
log bruto + frase do cliente
   │
   ▼
[1] Filtro (script)          → separa só as linhas de erro, guardando o número da linha
   │
   ▼
[2] Classificador (LLM)      → decide quais erros têm a ver com a frase do cliente
   │
   ▼
[3] Janela de contexto       → pega algumas linhas antes e depois do erro escolhido
   │                           (stack trace, avisos, o que o app fazia na hora)
   ▼
[4] Busca em erros conhecidos (Jira)
   │
   ├── conhecido   → devolve o ticket, a causa, a solução e onde a falha começa e termina no log
   └── desconhecido → a LLM propõe uma explicação e avisa que não achou erro parecido
```

## A dificuldade: dados

Conseguir logs reais com o gabarito ("qual era o erro de verdade") é difícil: envolve dados de
clientes, autorização e alguém para rotular cada caso.

Por isso a primeira etapa é uma **prova de conceito com dados sintéticos e públicos**:

- **Ruído de fundo real:** logs Android públicos do [Loghub](https://github.com/logpai/loghub), separados
  em logs de treino e logs de teste (o teste nunca usa um log visto no treino).
- **Falhas injetadas:** erros do domínio da carteira, descritos por nós, inseridos no meio do ruído.
- **Gabarito automático:** como fomos nós que inserimos a falha, sabemos em que linha ela começa e
  termina e qual ticket do Jira deveria ser encontrado.
- **Jira simulado:** um arquivo JSON com tickets fictícios. Alguns cenários ficam de fora de propósito,
  para testar o caso "erro desconhecido".

Assim dá para medir cada etapa separadamente:

| Etapa | Métrica |
|---|---|
| Filtro | As linhas da falha sobreviveram ao filtro? (recall) |
| Classificador | Acertou quais erros são relevantes? Acertou início/fim da janela? |
| Busca no Jira | O ticket certo veio em 1º lugar (top-1) ou entre os 3 primeiros (top-3)? |
| Desconhecidos | Quando não há ticket, o sistema disse "desconhecido" em vez de forçar um match? |
| Explicação | Avaliação manual ou por LLM-juiz em uma amostra |

O pior erro do sistema é o **falso "conhecido"**: dizer que é o ticket X quando não é.

> Os números desta PoC validam o fluxo e a lógica. Acurácia confiável só virá com uma amostra de logs
> reais anonimizados, numa etapa seguinte.

## Próximo passo

O gerador dos casos de teste (logs + descrição + gabarito) está descrito no [README desta pasta](README.md).
