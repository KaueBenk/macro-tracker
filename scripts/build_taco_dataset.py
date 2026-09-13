"""Build the committed TACO dataset from the official NEPA/Unicamp spreadsheet.

Downloads (or reads) the TACO 4th edition Excel file published by NEPA/Unicamp and
writes ``data/taco.json``, the dataset consumed by ``scripts/import_taco.py``.

Usage:
    uv run --with openpyxl python scripts/build_taco_dataset.py [--source path-or-url]
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import openpyxl

TACO_URL = "https://nepa.unicamp.br/publicacoes/tabela-taco-excel/"
SHEET = "CMVCol taco3"
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "taco.json"

COLUMNS = {
    "number": 0,
    "name": 1,
    "kcal": 3,
    "protein_g": 5,
    "fat_g": 6,
    "carbs_g": 8,
    "fiber_g": 9,
}
MACROS = ("protein_g", "fat_g", "carbs_g")
HEADER_LABELS = {"Número do", "Alimento", "Descrição dos alimentos"}


def _number(value: Any) -> Decimal | None:
    """Convert a TACO cell into a rounded value, or None when not quantified.

    TACO uses ``Tr`` for traces (treated as zero) and ``NA``/``*`` for values that
    were not analysed or not applicable.
    """
    if value is None:
        return None
    if isinstance(value, int | float):
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = str(value).strip()
    if text.lower() in {"tr", "traço", "traco"}:
        return Decimal("0.00")
    if text in {"NA", "*", ""}:
        return None
    return Decimal(text.replace(",", ".")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build(source: str) -> list[dict[str, Any]]:
    if source.startswith("http"):
        with urllib.request.urlopen(source) as response:  # noqa: S310 - fixed official URL
            raw = response.read()
        path = Path("/tmp/taco-source.xlsx")
        path.write_bytes(raw)
    else:
        path = Path(source)
    sheet = openpyxl.load_workbook(path, data_only=True)[SHEET]

    foods: list[dict[str, Any]] = []
    category: str | None = None
    skipped: list[str] = []
    for row in sheet.iter_rows(min_row=4, values_only=True):
        number = row[COLUMNS["number"]]
        name = row[COLUMNS["name"]]
        if number is None:
            continue
        label = str(number).strip()
        if not label.isdigit():
            # Category rows carry a label and nothing else; the header block repeats
            # once per category and must not be mistaken for one.
            if (
                label
                and label not in HEADER_LABELS
                and not any(cell is not None for cell in row[1:])
            ):
                category = label
            continue
        if name is None:
            continue
        values = {
            key: _number(row[index])
            for key, index in COLUMNS.items()
            if key not in {"number", "name"}
        }
        food = {
            "taco_id": label,
            "name": " ".join(str(name).split()),
            "category": category,
            **{key: (None if value is None else float(value)) for key, value in values.items()},
        }
        if food["kcal"] is None:
            skipped.append(f"{food['taco_id']} {food['name']}")
            continue
        # TACO leaves a component blank or marks it NA when it was not quantified for
        # that food; with calories known, an unquantified macro is nutritionally zero
        # (e.g. protein and carbohydrate in refined oils). Fibre stays unknown.
        for macro in MACROS:
            if food[macro] is None:
                food[macro] = 0.0
        foods.append(food)

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(foods, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print(f"foods: {len(foods)}  skipped (missing required macros): {len(skipped)}")
    for item in skipped:
        print(f"  skipped {item}")
    names = [food["name"] for food in foods]
    duplicates = {name for name in names if names.count(name) > 1}
    print(f"duplicate names: {len(duplicates)}")
    for name in sorted(duplicates):
        print(f"  duplicate {name}")
    return foods


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=TACO_URL)
    args = parser.parse_args()
    build(args.source)


if __name__ == "__main__":
    main()
