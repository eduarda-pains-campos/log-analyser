import csv
import re
from collections import Counter
from pathlib import Path


# Localização do projeto
ROOT_DIR = Path(__file__).resolve().parents[2]

# Arquivo original e resultado do Cleaner
INPUT_PATH = ROOT_DIR / "data" / "android_logs.csv"
OUTPUT_PATH = ROOT_DIR / "data" / "android_logs_cleaned.csv"

# Quantidade de registros mantidos antes e depois
CONTEXT_LINES = 2

# Colunas necessárias para identificar os registros
REQUIRED_COLUMNS = {"LineId", "Level", "Content"}

# Alguns padrões críticos que queremos reconhecer
CRITICAL_PATTERNS = [
    re.compile(r"\bFATAL EXCEPTION\b", re.IGNORECASE),
    re.compile(r"\bFatal signal\b", re.IGNORECASE),
    re.compile(r"\bANR in\b", re.IGNORECASE),
]


def classify_row(row: dict[str, str]) -> str | None:
    """Identifica warnings e errors no registro."""

    level = (row.get("Level") or "").strip().upper()

    if level == "E":
        return "ERROR"

    if level == "W":
        return "WARNING"

    return None


def clean_csv(
    input_path: Path = INPUT_PATH,
    output_path: Path = OUTPUT_PATH,
    context_lines: int = CONTEXT_LINES,
) -> dict[str, int]:

    # 1. Lê o CSV e preserva os campos originais
    with input_path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:

        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise ValueError("O arquivo não possui cabeçalho CSV.")

        reader.fieldnames = [
            name.strip() for name in reader.fieldnames
        ]

        missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames)

        if missing_columns:
            raise ValueError(
                f"Colunas obrigatórias ausentes: "
                f"{sorted(missing_columns)}"
            )

        rows = []

        for record_number, row in enumerate(reader, start=2):

            # Detecta registros com campos extras
            if None in row:
                raise ValueError(
                    f"Registro CSV {record_number} inválido. "
                    "Verifique as vírgulas e as aspas do arquivo."
                )

            normalized_row = {
                key: value if value is not None else ""
                for key, value in row.items()
                if key is not None
            }

            rows.append(normalized_row)

    # 2. Identifica warnings, erros e registros críticos
    target_types = {}

    for index, row in enumerate(rows):
        category = classify_row(row)

        if category is not None:
            target_types[index] = category

    # 3. Seleciona as linhas próximas de cada ocorrência
    selected = {}

    for target_index in target_types:

        start = max(0, target_index - context_lines)
        end = min(
            len(rows),
            target_index + context_lines + 1,
        )

        for index in range(start, end):
            selected.setdefault(index, "CONTEXT")

    # A classificação da ocorrência tem prioridade sobre CONTEXT
    selected.update(target_types)

    # 4. Salva os registros selecionados em outro CSV
    output_columns = reader.fieldnames + [
        "CleanerClassification"
    ]

    with output_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=output_columns,
        )

        writer.writeheader()

        for index in sorted(selected):
            output_row = rows[index].copy()
            output_row["CleanerClassification"] = selected[index]
            writer.writerow(output_row)

    # 5. Exibe um resumo da execução
    counts = Counter(target_types.values())

    summary = {
        "total_records": len(rows),
        "warnings": counts["WARNING"],
        "errors": counts["ERROR"],
        "critical": counts["CRITICAL"],
        "selected_records": len(selected),
    }

    print("\n=== CLEANER EXECUTADO ===")
    print(f"Registros lidos: {summary['total_records']}")
    print(f"Warnings encontrados: {summary['warnings']}")
    print(f"Errors encontrados: {summary['errors']}")
    print(f"Críticos encontrados: {summary['critical']}")
    print(f"Registros selecionados: {summary['selected_records']}")
    print(f"Arquivo gerado: {output_path}")

    if not target_types:
        print(
            "Nenhum registro relevante foi identificado. "
            "O arquivo de saída contém apenas o cabeçalho."
        )

    return summary


if __name__ == "__main__":
    clean_csv()