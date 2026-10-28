import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


# ==================================================
# 1. CONFIGURAÇÕES DO PROJETO
# ==================================================

ROOT_DIR = Path(__file__).resolve().parents[2]

INPUT_PATH = ROOT_DIR / "data" / "android_logs_cleaned.csv"
OUTPUT_PATH = ROOT_DIR / "data" / "incidents.json"

# Quantidade de linhas próximas que serão usadas como contexto
CONTEXT_LINES = 2

# Intervalo máximo para agrupar ocorrências semelhantes
GROUPING_WINDOW_SECONDS = 5

# Analisando somente warnings e errors
TARGET_CLASSIFICATIONS = {
    "WARNING",
    "ERROR",
}

REQUIRED_COLUMNS = {
    "LineId",
    "Date",
    "Time",
    "Pid",
    "Tid",
    "Level",
    "Component",
    "Content",
    "EventId",
    "EventTemplate",
    "CleanerClassification",
}


# ==================================================
# 2. LEITURA DO CSV
# ==================================================

def read_cleaned_csv(path: Path) -> list[dict[str, str]]:
    """
    Lê o CSV produzido pelo Cleaner e verifica
    se as colunas necessárias estão presentes.
    """

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:

        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise ValueError(
                "O arquivo CSV está sem cabeçalho."
            )

        reader.fieldnames = [
            name.strip()
            for name in reader.fieldnames
        ]

        missing_columns = (
            REQUIRED_COLUMNS - set(reader.fieldnames)
        )

        if missing_columns:
            raise ValueError(
                "Colunas ausentes no CSV: "
                f"{sorted(missing_columns)}"
            )

        rows = []

        for record_number, row in enumerate(
            reader,
            start=2,
        ):

            if None in row:
                raise ValueError(
                    f"Registro CSV inválido na linha "
                    f"{record_number}."
                )

            normalized_row = {
                key: value if value is not None else ""
                for key, value in row.items()
                if key is not None
            }

            rows.append(normalized_row)

    return rows


# ==================================================
# 3. CONVERSÃO DOS DADOS
# ==================================================

def get_line_id(row: dict[str, str]) -> int:
    """Converte LineId para inteiro."""

    try:
        return int(row["LineId"])
    except (ValueError, KeyError) as error:
        raise ValueError(
            f"LineId inválido: {row.get('LineId')!r}"
        ) from error


def parse_timestamp(
    row: dict[str, str],
) -> datetime:
    """
    Converte Date e Time para permitir comparar
    os horários das ocorrências.
    """

    value = (
        f"2000-{row['Date'].strip()} "
        f"{row['Time'].strip()}"
    )

    formats = (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    )

    for date_format in formats:
        try:
            return datetime.strptime(
                value,
                date_format,
            )
        except ValueError:
            continue

    raise ValueError(
        "Data ou horário inválido na linha "
        f"{row.get('LineId')}: {value}"
    )


def format_record(
    row: dict[str, str],
) -> dict:
    """
    Organiza os campos de um registro,
    preservando sua identificação original.
    """

    return {
        "line_id": get_line_id(row),
        "date": row["Date"],
        "time": row["Time"],
        "pid": row["Pid"],
        "tid": row["Tid"],
        "level": row["Level"],
        "component": row["Component"],
        "content": row["Content"],
        "event_id": row["EventId"],
        "event_template": row["EventTemplate"],
        "cleaner_classification": (
            row["CleanerClassification"]
        ),
    }


# ==================================================
# 4. RECUPERAÇÃO DAS LINHAS DE CONTEXTO
# ==================================================

def get_context(
    event: dict[str, str],
    all_rows: list[dict[str, str]],
) -> list[dict]:
    """
    Recupera as linhas CONTEXT próximas da ocorrência.

    O contexto ajuda a entender o que aconteceu
    antes e depois de um warning ou error.
    """

    event_line_id = get_line_id(event)
    context = []

    for row in all_rows:

        classification = (
            row["CleanerClassification"]
            .strip()
            .upper()
        )

        if classification != "CONTEXT":
            continue

        distance = abs(
            get_line_id(row) - event_line_id
        )

        if 0 < distance <= CONTEXT_LINES:
            context.append(format_record(row))

    return sorted(
        context,
        key=lambda item: item["line_id"],
    )


# ==================================================
# 5. AGRUPAMENTO DE OCORRÊNCIAS
# ==================================================

def classify_incidents(
    rows: list[dict[str, str]],
) -> list[dict]:
    """
    Agrupa warnings e errors semelhantes.

    Critérios utilizados:
    - mesma classificação;
    - mesmo componente;
    - mesmo EventTemplate, quando disponível;
    - intervalo máximo de 5 segundos entre
      ocorrências consecutivas do mesmo grupo.

    O agrupamento é uma heurística inicial:
    não confirma que as ocorrências tenham
    necessariamente a mesma causa.
    """

    # Apenas WARNING e ERROR iniciam incidentes.
    # CONTEXT serve como evidência complementar.
    events = [
        row
        for row in rows
        if row["CleanerClassification"]
        .strip()
        .upper() in TARGET_CLASSIFICATIONS
    ]

    # Ordena cronologicamente as ocorrências.
    events.sort(key=parse_timestamp)

    groups = []
    latest_group_by_key = {}

    for row in events:

        classification = (
            row["CleanerClassification"]
            .strip()
            .upper()
        )

        component = row["Component"].strip()
        template = row["EventTemplate"].strip()

        # Se não existir um template, usa o conteúdo
        # original como alternativa.
        signature = template or row["Content"].strip()

        # Ocorrências com chaves diferentes não são
        # agrupadas nesta versão.
        group_key = (
            classification,
            component,
            signature,
        )

        timestamp = parse_timestamp(row)

        last_group = latest_group_by_key.get(
            group_key
        )

        elapsed = None

        if last_group is not None:
            elapsed = (
                timestamp - last_group["_last_seen_dt"]
            ).total_seconds()

        # Se a mesma assinatura ocorreu dentro da
        # janela de 5 segundos, adiciona ao grupo.
        if (
            last_group is not None
            and elapsed is not None
            and 0 <= elapsed <= GROUPING_WINDOW_SECONDS
        ):

            group = last_group

            group["last_seen"] = (
                f"{row['Date']} {row['Time']}"
            )

            group["_last_seen_dt"] = timestamp

        else:
            # Caso contrário, cria um novo grupo.
            group = {
                "classification": classification,
                "component": component,
                "event_template": template or None,
                "grouping_signature": signature,
                "first_seen": (
                    f"{row['Date']} {row['Time']}"
                ),
                "last_seen": (
                    f"{row['Date']} {row['Time']}"
                ),
                "_last_seen_dt": timestamp,
                "occurrences": [],
            }

            groups.append(group)

            latest_group_by_key[group_key] = group

        # Guarda a ocorrência e o contexto associado.
        occurrence = {
            "event": format_record(row),
            "context": get_context(row, rows),
        }

        group["occurrences"].append(occurrence)

    # Transforma os grupos internos em incidentes
    # prontos para serem salvos no JSON.
    incidents = []

    for index, group in enumerate(groups, start=1):

        source_line_ids = [
            item["event"]["line_id"]
            for item in group["occurrences"]
        ]

        incidents.append({
            "incident_id": f"INC-{index:04d}",
            "classification": group["classification"],
            "severity": group["classification"],
            "component": group["component"],
            "event_template": group["event_template"],
            "grouping_signature": (
                group["grouping_signature"]
            ),
            "first_seen": group["first_seen"],
            "last_seen": group["last_seen"],
            "occurrence_count": len(
                group["occurrences"]
            ),
            "source_line_ids": source_line_ids,
            "occurrences": group["occurrences"],
        })

    return incidents


# ==================================================
# 6. EXECUÇÃO DO CLASSIFIER
# ==================================================

def run_classifier() -> dict:
    """
    Executa o Classifier isoladamente,
    gera os incidentes e salva um JSON.
    """

    # Lê o resultado do Cleaner.
    rows = read_cleaned_csv(INPUT_PATH)

    # Agrupa as ocorrências.
    incidents = classify_incidents(rows)

    # Conta warnings e errors encontrados
    # na entrada do Classifier.
    events_by_classification = Counter(
        row["CleanerClassification"]
        .strip()
        .upper()
        for row in rows
        if row["CleanerClassification"]
        .strip()
        .upper() in TARGET_CLASSIFICATIONS
    )

    # Conta quantos grupos foram criados
    # para cada classificação.
    groups_by_classification = Counter(
        incident["classification"]
        for incident in incidents
    )

    # Organiza o resultado final.
    result = {
        "source_file": str(
            INPUT_PATH.relative_to(ROOT_DIR)
        ),
        "configuration": {
            "context_lines": CONTEXT_LINES,
            "grouping_window_seconds": (
                GROUPING_WINDOW_SECONDS
            ),
            "grouping_fields": [
                "classification",
                "component",
                "event_template",
            ],
        },
        "summary": {
            "cleaned_records": len(rows),
            "detected_events": sum(
                events_by_classification.values()
            ),
            "incident_groups": len(incidents),
            "events_by_classification": dict(
                events_by_classification
            ),
            "groups_by_classification": dict(
                groups_by_classification
            ),
        },
        "incidents": incidents,
    }

    # Cria o diretório de saída, se necessário.
    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Salva os incidentes como JSON.
    with OUTPUT_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2,
        )

    # Exibe o resumo da execução.
    print("\n=== CLASSIFIER EXECUTADO ===")
    print(f"Registros recebidos: {len(rows)}")
    print(
        "Ocorrências identificadas: "
        f"{result['summary']['detected_events']}"
    )
    print(
        "Grupos de incidentes: "
        f"{result['summary']['incident_groups']}"
    )
    print(
        "Ocorrências por classificação: "
        f"{dict(events_by_classification)}"
    )
    print(
        "Grupos por classificação: "
        f"{dict(groups_by_classification)}"
    )
    print(f"Arquivo gerado: {OUTPUT_PATH}")

    return result


# Executa somente quando este arquivo é chamado diretamente.
if __name__ == "__main__":
    run_classifier()
