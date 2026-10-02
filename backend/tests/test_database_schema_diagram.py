"""Keep the maintained Excalidraw schema aligned with SQLAlchemy's persisted model."""

import json
from collections import Counter
from pathlib import Path

from app.models import Base


def test_diagram_contains_tables_columns_and_bound_foreign_keys():
    path = Path(__file__).resolve().parents[2] / "docs" / "database-schema.excalidraw"
    elements = json.loads(path.read_text(encoding="utf-8"))["elements"]
    cards = {item["id"]: item for item in elements if item["type"] == "rectangle"}
    labels = {
        item["id"].removeprefix("txt-"): item
        for item in elements if item["type"] == "text" and item["id"].startswith("txt-")
    }
    names = {key: item["text"].splitlines()[0].lower() for key, item in labels.items()}
    assert set(names.values()) == set(Base.metadata.tables)
    for key, label in labels.items():
        assert f"tbl-{key}" in cards
        for field in ("text", "originalText", "fontSize", "fontFamily", "width", "height", "textAlign", "lineHeight"):
            assert label.get(field) is not None, (key, field)
        table = Base.metadata.tables[names[key]]
        for column in table.columns:
            assert column.name in label["text"], (table.name, column.name)

    expected = Counter()
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if column.name == "user_id":
                if any(fk.column.table.name == "users" for fk in column.foreign_keys):
                    expected[table.name, "users"] += 1
            else:
                # A tenant relationship has both a scalar FK and a composite
                # (user_id, id) FK; the diagram shows that logical edge once.
                for target in {fk.column.table.name for fk in column.foreign_keys if fk.column.name == "id"}:
                    expected[table.name, target] += 1
    actual = Counter()
    for arrow in (item for item in elements if item["type"] == "arrow"):
        start = arrow["startBinding"]["elementId"]
        end = arrow["endBinding"]["elementId"]
        assert start in cards and end in cards, arrow["id"]
        actual[names[start.removeprefix("tbl-")], names[end.removeprefix("tbl-")]] += 1
    assert actual == expected
