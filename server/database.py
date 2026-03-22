"""Async Postgres connection pool and query helpers for auth and rate limiting."""

import os
import asyncpg

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Get or create the connection pool."""
    global _pool
    if _pool is None:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL not set")
        # Strip quotes if present (some .env formats add them)
        database_url = database_url.strip("'\"")
        _pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    return _pool


async def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def create_user(email: str, password_hash: str) -> dict:
    """Insert a new user. Returns {id, email, created_at}. Raises if email taken."""
    pool = await get_pool()
    try:
        row = await pool.fetchrow(
            "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING id, email, created_at",
            email, password_hash,
        )
        return dict(row)
    except asyncpg.UniqueViolationError:
        raise ValueError("Email already registered")


async def get_user_by_email(email: str) -> dict | None:
    """Look up user by email. Returns {id, email, password_hash} or None."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, email, password_hash FROM users WHERE email = $1",
        email,
    )
    return dict(row) if row else None


async def get_remaining_runs(user_id) -> dict:
    """Get remaining runs and reset time for a user.

    Returns {remaining_runs: int, reset_time: str | None}.
    reset_time is when the next run becomes available (oldest run + 24h).
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT
            count(*) AS run_count,
            min(created_at) AS oldest_run
        FROM benchmark_runs
        WHERE user_id = $1 AND created_at > now() - interval '24 hours'
        """,
        user_id,
    )
    run_count = row["run_count"]
    remaining = max(0, 3 - run_count)
    reset_time = None
    if row["oldest_run"] and run_count >= 3:
        from datetime import timedelta
        reset_time = (row["oldest_run"] + timedelta(hours=24)).isoformat()
    return {"remaining_runs": remaining, "reset_time": reset_time}


async def try_record_run(user_id) -> dict | None:
    """Atomically check rate limit and record a run.

    Returns {id, remaining_runs, reset_time} if allowed, None if rate limited.
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        WITH current_count AS (
            SELECT count(*) AS cnt,
                   min(created_at) AS oldest_run
            FROM benchmark_runs
            WHERE user_id = $1 AND created_at > now() - interval '24 hours'
        )
        INSERT INTO benchmark_runs (user_id)
        SELECT $1 FROM current_count WHERE cnt < 3
        RETURNING id
        """,
        user_id,
    )
    if row is None:
        # Rate limited — get reset time
        info = await get_remaining_runs(user_id)
        return None
    # Success — return updated counts
    info = await get_remaining_runs(user_id)
    return {"id": str(row["id"]), **info}
