"""Database migrations manager."""

from __future__ import annotations

from pathlib import Path
import os
import re
import typing as t

import psycopg


class MigrationManager:
    """Manage database schema migrations."""

    def __init__(
        self,
        database_url: str | None = None,
        migrations_dir: str | None = None,
    ) -> None:
        """Initialize the migration manager.

        Args:
            database_url: Database connection string.
            migrations_dir: Directory containing migration SQL files.
        """
        self.database_url = database_url or os.getenv('DATABASE_URL')
        self.migrations_dir = Path(
            migrations_dir or os.getenv('MIGRATIONS_DIR', 'migrations')
        )
        self._conn: psycopg.Connection | None = None

    @property
    def conn(self) -> psycopg.Connection:
        """Return a lazy database connection.

        Returns:
            An active psycopg connection.
        """
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self.database_url, autocommit=False)
        return self._conn

    def _ensure_migrations_table(self) -> None:
        """Create migrations tracking table if it does not exist."""
        with self.conn.cursor() as cur:
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(255) PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            self.conn.commit()

    def _get_applied_migrations(self) -> set[str]:
        """Return a set of applied migration versions."""
        self._ensure_migrations_table()
        with self.conn.cursor() as cur:
            cur.execute('SELECT version FROM schema_migrations ORDER BY version')
            return {row[0] for row in cur.fetchall()}

    def _get_pending_migrations(self) -> list[tuple[str, Path]]:
        """Return a list of pending migration version/filepath tuples."""
        if not self.migrations_dir.exists():
            return []

        applied = self._get_applied_migrations()
        pending: list[tuple[str, Path]] = []

        pattern = re.compile(r'^(\d{3})_.+\.sql$')

        for filepath in sorted(self.migrations_dir.glob('*.sql')):
            match = pattern.match(filepath.name)
            if match:
                version = filepath.stem
                if version not in applied:
                    pending.append((version, filepath))

        return pending

    def _apply_migration(self, version: str, filepath: Path) -> bool:
        """Apply a single migration file.

        Args:
            version: Migration version label.
            filepath: Path to the migration SQL file.

        Returns:
            True if the migration succeeds, otherwise False.
        """
        try:
            sql = filepath.read_text(encoding='utf-8')

            with self.conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    'INSERT INTO schema_migrations (version) VALUES (%s)',
                    (version,),
                )

            self.conn.commit()
            return True
        except (OSError, psycopg.Error) as exc:
            self.conn.rollback()
            print(f'Migration {version} failed: {exc}')
            return False

    def migrate(self, target_version: str | None = None) -> dict[str, t.Any]:
        """Run all pending migrations or up to a target version.

        Args:
            target_version: Optional target version to stop at.

        Returns:
            A dictionary with migration results.
        """
        results: dict[str, t.Any] = {
            'applied': [],
            'failed': [],
            'skipped': [],
        }

        pending = self._get_pending_migrations()

        if not pending:
            print('No pending migrations.')
            return results

        for version, filepath in pending:
            if target_version and version > target_version:
                results['skipped'].append(version)
                continue

            print(f'Applying migration: {version}...')

            if self._apply_migration(version, filepath):
                print(f'  ✓ {version} applied successfully')
                results['applied'].append(version)
            else:
                print(f'  ✗ {version} failed')
                results['failed'].append(version)
                break

        return results

    def status(self) -> dict[str, t.Any]:
        """Return migration status.

        Returns:
            A dictionary with applied and pending migration data.
        """
        applied = self._get_applied_migrations()
        pending = self._get_pending_migrations()

        return {
            'applied': sorted(applied),
            'pending': [version for version, _ in pending],
            'total_applied': len(applied),
            'total_pending': len(pending),
        }

    def close(self) -> None:
        """Close the database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()

