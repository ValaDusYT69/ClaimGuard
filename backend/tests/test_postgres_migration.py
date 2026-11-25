import sqlite3
import tempfile
import unittest
from pathlib import Path

from data.migrate_sqlite_to_postgres import backup_and_verify_source


class MigrationSafetyTests(unittest.TestCase):
    def test_source_backup_is_verified_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.db"
            connection = sqlite3.connect(source)
            try:
                connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
                connection.execute("INSERT INTO sample VALUES (1)")
                connection.commit()
            finally:
                connection.close()

            original = source.read_bytes()
            backup = backup_and_verify_source(source, root / "backup")

            self.assertTrue(backup.is_file())
            self.assertEqual(source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
