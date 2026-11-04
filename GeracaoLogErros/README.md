# GeracaoLogErros: gerador de casos de teste

Gera os dados da prova de conceito descrita em [PROBLEMA.md](PROBLEMA.md). Cada caso de teste
tem três arquivos:

| Arquivo | Conteúdo |
|---|---|
| `log.txt` | Trecho de log Android **real** (Loghub) com uma falha do app injetada no meio |
| `descricao.txt` | A frase do cliente, como chegaria no suporte |
| `gabarito.json` | A resposta certa: onde a falha começa e termina, qual ticket deveria ser achado etc. |

Como foi o gerador que inseriu a falha, o gabarito sai pronto, sem rotulagem manual.

## A ideia: três camadas

| Camada | Onde fica | O que é | Quem mexe |
|---|---|---|---|
| **Problema** | `problemas/*.yaml` | Uma falha: linhas de log, ticket do Jira, frases do cliente | Você, quando quiser simular um erro novo |
| **Receita** | `receita.yaml` | Quais problemas usar e como montar os casos neste experimento | Você, a cada rodada |
| **Caso** | `saida/casos/...` | Uma instância concreta gerada | Só o script |

Para simular um erro novo: copie `problemas/cartao_bin_nao_suportado.yaml`, mude o conteúdo e rode o
script de novo. Nada mais precisa ser alterado.

## Estrutura

```
GeracaoLogErros/
├── README.md
├── receita.yaml                 # parâmetros do experimento
├── gerar_casos.py               # o gerador
├── problemas/                   # lista de problemas (um arquivo por problema)
│   └── cartao_bin_nao_suportado.yaml
├── distratores/                 # erros do app SEM relação com a queixa (negativos difíceis)
│   └── distratores_carteira.yaml
├── dados/                       # logs reais usados como ruído de fundo (formato logcat)
│   ├── treino/                  # só os casos de treino usam estes
│   └── teste/                   # só os casos de teste usam estes (nunca vistos no treino)
└── saida/                       # gerado (pode apagar e gerar de novo)
    ├── casos/treino/caso_XXXX/  # log.txt, descricao.txt, gabarito.json
    ├── casos/teste/caso_XXXX/
    ├── jira_mock.json           # Jira simulado
    └── indice.csv               # um caso por linha, para filtrar e montar as métricas
```

## Como rodar

Requisitos: Python 3.10+ e PyYAML (`pip install pyyaml`).

```bash
python gerar_casos.py
```

Outras formas:

```bash
python gerar_casos.py --so-validar
```
```bash
python gerar_casos.py --problemas cartao_bin_nao_suportado --casos 5 --seed 7
```
`--so-validar` confere o catálogo sem gerar nada: placeholders sem definição, ticket faltando, problema
sem linha de erro no núcleo, ids repetidos.

### Ruído de fundo (`dados/treino` e `dados/teste`)

O ruído é o log real onde a falha é escondida. Ele fica separado em duas pastas:

- `dados/treino/`: logs usados **só** nos casos de treino;
- `dados/teste/`: logs usados **só** nos casos de teste. O sistema nunca viu esses logs durante os ajustes.

Para adicionar ruído, basta colocar arquivos `.log` ou `.txt` no formato logcat (ex.: saída do
`adb logcat` de um emulador) em uma das pastas. Cada caso sorteia um arquivo da pasta do seu split e
recorta um trecho dele. **Nunca coloque o mesmo log nas duas pastas** (o script avisa se o nome repetir).

Hoje as pastas têm o [`Android_2k.log`](https://github.com/logpai/loghub/tree/master/Android) do Loghub
dividido em duas partes sem linhas em comum: as primeiras 1.400 linhas em treino e as últimas 600 em
teste. Se as duas pastas estiverem vazias, o script baixa esse log de novo e faz a mesma divisão. Atrás
de proxy corporativo, se o download falhar, instale `truststore` (`pip install truststore`).

## Como escrever um problema

Veja o exemplo comentado em [`problemas/cartao_bin_nao_suportado.yaml`](problemas/cartao_bin_nao_suportado.yaml).
Os campos:

- **`id`, `descricao`**: identificação e explicação conceitual.
- **`variaveis`**: valores sorteados a cada caso (cartão, request_id, latência…), usados como `{nome}`
  nas linhas. Assim nenhum caso fica idêntico ao outro.
  - Tipo `variante`: o 1º valor é a mensagem canônica, os demais são outras formas de dizer o mesmo
    erro. Testa se a busca no Jira acha o ticket mesmo com texto diferente.
- **`linhas`**: a falha, linha a linha, com `nivel` (V/D/I/W/E/F), `tag`, `msg`, `thread` e `papel`:
  - `nucleo`: faz parte da falha. É o que o sistema deve apontar como início/fim.
  - `contexto`: acontece em volta (info, warn) e ajuda a entender, mas não é a falha.
- **`jira.presente`**: `true` coloca o ticket no Jira simulado; `false` simula um **erro desconhecido**.
- **`jira.iscas`**: tickets **parecidos mas de outro problema**. Sempre entram no Jira, para medir se o
  sistema evita o falso "conhecido" (o pior erro possível).
- **`descricoes_cliente`**: frases em vários estilos (formal, bravo, vago, com erro de português).

## O que o gerador faz em cada caso

1. **Sorteia um log de ruído** da pasta do seu split (`dados/treino` ou `dados/teste`) e **recorta** um
   trecho dele (`linhas_por_caso`).
2. **Escolhe um PID** livre para o app e insere uma linha `ActivityManager: Start proc <pid>:<pacote>`,
   como num log de verdade, permitindo ao pipeline filtrar pelo processo do app.
3. **Injeta** a falha e os distratores, cada um numa faixa diferente do trecho. Entre as linhas da falha
   podem entrar linhas de outros processos (`max_ruido_entre_linhas`), como acontece na prática.
4. **Ajusta os timestamps**: as linhas injetadas recebem horários entre os das linhas vizinhas, no mesmo
   formato do ruído. Assim o classificador não acha a falha só porque ela "parece diferente".
5. **Sorteia a descrição** do cliente e **grava o gabarito**.

### Tipos de caso (pesos em `tipos_de_caso`)

| Tipo | O que testa | Resultado esperado |
|---|---|---|
| `simples` | Uma falha + distratores | `conhecido` (ticket) ou `desconhecido` |
| `dois_problemas` | A falha alvo + outra falha real no mesmo log | idem; a outra não deve ser escolhida |
| `sem_erro_relevante` | Descrição de um problema que **não** está no log | `nenhum_erro_relevante` |

`dois_problemas` só é usado quando o catálogo tem 2 ou mais problemas.

### Separação treino / teste

É como lista de exercícios e prova. Uma parte dos casos (`proporcao_teste`) vai para `casos/teste/`.
Os casos de teste usam **logs de ruído (de `dados/teste/`) e frases do cliente que nunca aparecem no
treino**. Ajuste os prompts olhando só o `treino` e meça no `teste` uma vez, no final; senão os números
saem otimistas.

## O gabarito

Principais campos de `gabarito.json` (linhas numeradas a partir de 1):

| Campo | Significado |
|---|---|
| `resultado_esperado` | `conhecido`, `desconhecido` ou `nenhum_erro_relevante` |
| `ticket_esperado` | Ex.: `WAL-101`, ou `null` |
| `app.pid` | PID do app no log |
| `falhas[].linha_inicio` / `linha_fim` | Bloco inteiro da falha, incluindo o contexto |
| `falhas[].linha_inicio_nucleo` / `linha_fim_nucleo` | Só a falha em si |
| `falhas[].linhas_nucleo`, `linhas_contexto` | As linhas exatas (há ruído intercalado no meio) |
| `falhas[].linhas_erro_nucleo` | Linhas E/F do núcleo: o que o **filtro** precisa deixar passar |
| `falhas[].relevante_para_descricao` | `true` para a falha que a frase do cliente descreve |
| `distratores[]` | Erros do app sem relação, com suas linhas |
| `erros_do_ruido` | Linhas de erro que já vinham no log real (também devem ser descartadas) |
| `ruido` | De qual pasta e arquivo veio o ruído, e a partir de qual linha |
| `etiquetas` | Dificuldades do caso: `intercalado`, `mensagem_variante`, `isca_jira`, `descricao_vaga`, `desconhecido`… |

As `etiquetas` servem para quebrar as métricas por dificuldade ("acerta 95% no geral, mas 60% quando há
isca no Jira").

## Limitações conhecidas

- Os dados são sintéticos: validam o fluxo e a lógica, não a acurácia de produção.
- O ruído do Loghub é de outro aparelho e outra época; a falha é de um app fictício.
- Variações de formato (`ERROR`, `Error:`, exceção sem prefixo) ainda não são geradas; hoje todas as
  falhas usam o formato padrão do logcat.
- As frases do cliente são escritas à mão no YAML; gerar paráfrases com LLM é um próximo passo.
