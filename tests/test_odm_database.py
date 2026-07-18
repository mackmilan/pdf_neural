import unittest
from datetime import datetime, timezone

from backend.app.db.odm import OdmCollection, TenantDocument


class FakeCollection:
    def __init__(self):
        self.inserted = None
        self.updated = None

    def insert_one(self, document, *args, **kwargs):
        self.inserted = document
        return object()

    def update_one(self, filter, update, *args, **kwargs):
        self.updated = (filter, update)
        return object()


class OdmDatabaseTest(unittest.TestCase):
    def test_validates_known_document_fields_before_insert(self):
        fake = FakeCollection()
        collection = OdmCollection(fake, TenantDocument)

        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        collection.insert_one({
            "tenant_id": "tenant-1",
            "name": "Tenant",
            "metadata": {"uf": "PR"},
            "created_at": now,
            "updated_at": now,
            "custom_flag": True,
        })

        self.assertEqual("tenant-1", fake.inserted["tenant_id"])
        self.assertTrue(fake.inserted["custom_flag"])

    def test_rejects_unknown_update_operator(self):
        collection = OdmCollection(FakeCollection(), TenantDocument)

        with self.assertRaises(ValueError):
            collection.update_one({"tenant_id": "tenant-1"}, {"$push": {"items": 1}})


if __name__ == "__main__":
    unittest.main()
