from __future__ import annotations

from datetime import datetime

from database import Database, normalize_field_heights


def normalize_collection_fields(collection, field_path: str) -> tuple[int, int]:
    scanned = 0
    updated = 0
    projection = {field_path: 1}
    for document in collection.find({field_path: {"$type": "array"}}, projection):
        scanned += 1
        current = document
        for part in field_path.split("."):
            current = current.get(part, {}) if isinstance(current, dict) else {}
        if not isinstance(current, list):
            continue
        normalized = normalize_field_heights(current)
        if normalized == current:
            continue
        collection.update_one(
            {"_id": document["_id"]},
            {"$set": {field_path: normalized, "field_heights_normalized_at": datetime.utcnow()}},
        )
        updated += 1
    return scanned, updated


def main() -> int:
    database = Database()
    if not database.is_available():
        print("Banco de dados indisponivel. Verifique MONGO_URI.")
        return 1

    targets = (
        ("documents", database.documents, "fields"),
        ("document_versions", database.versions, "fields"),
        ("jobs", database.jobs, "result.fields"),
    )
    total_updated = 0
    for name, collection, field_path in targets:
        scanned, updated = normalize_collection_fields(collection, field_path)
        total_updated += updated
        print(f"{name}: {updated} atualizado(s) de {scanned} com campos.")

    print(f"Total atualizado: {total_updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
