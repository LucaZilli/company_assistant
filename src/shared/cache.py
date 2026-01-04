from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import re
import typing as t

import psycopg
from psycopg.rows import dict_row
from config import CACHE_TTL_DAYS

_CACHES: dict[str, QueryCache] = {}


@dataclass
class CachedResponse:
    """Cached response data for a query."""

    query: str
    response: str
    routing_action: str | None
    hit_count: int
    agent_type: str


class QueryCache:
    """PostgreSQL-backed cache for query responses."""

    def __init__(
        self,
        database_url: str | None = None,
        ttl_days: int = 30,
        agent_type: str = 'classic',
    ) -> None:
        """Initialize the cache.

        Args:
            database_url: Connection string for PostgreSQL.
            ttl_days: Time-to-live for cached entries, in days.
            agent_type: Assistant type namespace for cache entries.
        """
        self.database_url = database_url or os.getenv('DATABASE_URL')
        self.ttl_days = ttl_days
        self.agent_type = agent_type
        self._conn: psycopg.Connection | None = None

    @property
    def conn(self) -> psycopg.Connection:
        """Return a lazy PostgreSQL connection.

        Returns:
            An active psycopg connection.
        """
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self.database_url, autocommit=False)
        return self._conn

    def _normalize_query(self, query: str) -> str:
        """Normalize a query for matching.

        Args:
            query: Raw user query.

        Returns:
            A normalized query string.
        """
        normalized = query.lower().strip()
        normalized = re.sub(r'\s+', ' ', normalized)
        normalized = re.sub(r'[?!.]+$', '', normalized)
        return normalized

    def _hash_query(self, query: str) -> str:
        """Create a hash of a normalized query.

        Args:
            query: Raw user query.

        Returns:
            SHA-256 hash of the normalized query.
        """
        normalized = self._normalize_query(query)
        return hashlib.sha256(normalized.encode()).hexdigest()

    def get(self, query: str) -> CachedResponse | None:
        """Look up a cached response for a query.

        Args:
            query: Raw user query.

        Returns:
            CachedResponse if present and valid, otherwise None.
        """
        query_hash = self._hash_query(query)

        try:
            with self.conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    '''
                    UPDATE query_cache
                    SET last_used_at = CURRENT_TIMESTAMP,
                        hit_count = hit_count + 1
                    WHERE query_hash = %s
                      AND agent_type = %s
                      AND created_at > CURRENT_TIMESTAMP - INTERVAL '%s days'
                    RETURNING query_normalized, response, routing_action, hit_count, agent_type
                    ''',
                    (query_hash, self.agent_type, self.ttl_days),
                )

                row = cur.fetchone()
                self.conn.commit()

                if row:
                    return CachedResponse(
                        query=row['query_normalized'],
                        response=row['response'],
                        routing_action=row['routing_action'],
                        hit_count=row['hit_count'],
                        agent_type=row['agent_type'],
                    )
                return None
        except psycopg.Error as exc:
            self.conn.rollback()
            print(f'Cache get error: {exc}')
            return None

    def set(self, query: str, response: str, routing_action: str | None) -> bool:
        """Store a query response in cache.

        Args:
            query: Raw user query.
            response: Response text to cache.
            routing_action: Routing action used for this response.

        Returns:
            True if the cache write succeeds, otherwise False.
        """
        query_hash = self._hash_query(query)
        normalized = self._normalize_query(query)

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO query_cache (
                        query_hash,
                        query_normalized,
                        response,
                        routing_action,
                        agent_type
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (query_hash, agent_type) DO UPDATE SET
                        response = EXCLUDED.response,
                        routing_action = EXCLUDED.routing_action,
                        created_at = CURRENT_TIMESTAMP,
                        last_used_at = CURRENT_TIMESTAMP,
                        hit_count = query_cache.hit_count + 1
                    ''',
                    (query_hash, normalized, response, routing_action, self.agent_type),
                )
                self.conn.commit()
                return True
        except psycopg.Error as exc:
            self.conn.rollback()
            print(f'Cache set error: {exc}')
            return False

    def clear(self) -> int:
        """Clear cache entries for this agent type.

        Returns:
            The number of deleted rows.
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM query_cache WHERE agent_type = %s',
                    (self.agent_type,),
                )
                deleted = cur.rowcount
                self.conn.commit()
                return deleted
        except psycopg.Error as exc:
            self.conn.rollback()
            print(f'Cache clear error: {exc}')
            return 0

    def cleanup_expired(self) -> int:
        """Remove entries older than the TTL for this agent type.

        Returns:
            The number of deleted rows.
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    '''
                    DELETE FROM query_cache
                    WHERE agent_type = %s
                      AND created_at < CURRENT_TIMESTAMP - INTERVAL '%s days'
                    ''',
                    (self.agent_type, self.ttl_days),
                )
                deleted = cur.rowcount
                self.conn.commit()
                return deleted
        except psycopg.Error as exc:
            self.conn.rollback()
            print(f'Cache cleanup error: {exc}')
            return 0

    def stats(self) -> dict[str, t.Any]:
        """Return cache statistics for this agent type.

        Returns:
            A dictionary of summary metrics.
        """
        try:
            with self.conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    '''
                    SELECT
                        COUNT(*) AS total_entries,
                        COUNT(*) FILTER (
                            WHERE created_at > CURRENT_TIMESTAMP - INTERVAL '%s days'
                        ) AS valid_entries,
                        SUM(hit_count) AS total_hits,
                        AVG(hit_count) AS avg_hits_per_entry,
                        MIN(created_at) AS oldest_entry,
                        MAX(last_used_at) AS most_recent_use
                    FROM query_cache
                    WHERE agent_type = %s
                    ''',
                    (self.ttl_days, self.agent_type),
                )

                result = dict(cur.fetchone())
                result['ttl_days'] = self.ttl_days
                result['agent_type'] = self.agent_type
                return result
        except psycopg.Error as exc:
            print(f'Cache stats error: {exc}')
            return {}

    def close(self) -> None:
        """Close the database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()


def get_cache(agent_type: str = 'classic') -> QueryCache:
    """Get or create a global cache instance for an agent type.

    Args:
        agent_type: Assistant type namespace for cache entries.

    Returns:
        A configured QueryCache instance.
    """
    if agent_type not in _CACHES:

        _CACHES[agent_type] = QueryCache(ttl_days=CACHE_TTL_DAYS, agent_type=agent_type)# to not open a new db connection every time I save the object in the global variable
    return _CACHES[agent_type]
