import re
import sqlite3
from importlib.resources import files
from pathlib import Path

MIGRATION_PATTERN = re.compile(r"^(?P<version>[0-9]{3})_[a-z0-9_]+\.sql$")


def _migrations() -> list[tuple[int, str, str]]:
    migration_dir = files("patchbench").joinpath("migrations")
    migrations: list[tuple[int, str, str]] = []
    for resource in migration_dir.iterdir():
        match = MIGRATION_PATTERN.fullmatch(resource.name)
        if match:
            migrations.append((int(match.group("version")), resource.name, resource.read_text()))

    migrations.sort(key=lambda migration: migration[0])
    versions = [version for version, _, _ in migrations]
    if not versions or versions != list(range(1, len(versions) + 1)):
        raise RuntimeError("History migrations must start at 001 and remain contiguous")
    return migrations


def initialize_history(connection: sqlite3.Connection) -> int:
    """Apply every pending bundled migration and return the current schema version."""

    if connection.in_transaction:
        raise ValueError("History initialization requires a connection outside a transaction")

    connection.execute("PRAGMA foreign_keys = ON")
    foreign_keys_enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    if foreign_keys_enabled != 1:
        raise RuntimeError("SQLite foreign-key enforcement could not be enabled")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    connection.commit()

    applied = dict(
        connection.execute("SELECT version, name FROM schema_migrations ORDER BY version")
    )
    migrations = _migrations()
    known_names = {version: name for version, name, _ in migrations}
    if unknown := applied.keys() - known_names.keys():
        raise RuntimeError(f"Database contains unknown history migrations: {sorted(unknown)}")
    mismatched = [
        version for version, applied_name in applied.items() if applied_name != known_names[version]
    ]
    if mismatched:
        raise RuntimeError(f"Database contains renamed history migrations: {mismatched}")

    for version, name, sql in migrations:
        if version in applied:
            continue
        safe_name = name.replace("'", "''")
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{sql}\n"
            "INSERT INTO schema_migrations (version, name) "
            f"VALUES ({version}, '{safe_name}');\n"
            "COMMIT;"
        )
        try:
            connection.executescript(script)
        except sqlite3.Error:
            if connection.in_transaction:
                connection.rollback()
            raise

    return migrations[-1][0]


def connect_history(path: str | Path) -> sqlite3.Connection:
    """Open a history database with migrations and foreign keys ready for use."""

    connection = sqlite3.connect(path)
    try:
        initialize_history(connection)
    except Exception:
        connection.close()
        raise
    return connection
