"""Tests for database module — uses mocks since we can't hit real DB in CI."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone, timedelta


@pytest.mark.asyncio
async def test_get_remaining_runs_no_runs():
    mock_pool = AsyncMock()
    mock_pool.fetchrow = AsyncMock(return_value={"run_count": 0, "oldest_run": None})

    with patch("database.get_pool", return_value=mock_pool):
        from database import get_remaining_runs
        import uuid
        result = await get_remaining_runs(uuid.uuid4())

    assert result["remaining_runs"] == 3
    assert result["reset_time"] is None


@pytest.mark.asyncio
async def test_get_remaining_runs_at_limit():
    oldest = datetime.now(timezone.utc) - timedelta(hours=1)
    mock_pool = AsyncMock()
    mock_pool.fetchrow = AsyncMock(return_value={"run_count": 3, "oldest_run": oldest})

    with patch("database.get_pool", return_value=mock_pool):
        from database import get_remaining_runs
        import uuid
        result = await get_remaining_runs(uuid.uuid4())

    assert result["remaining_runs"] == 0
    assert result["reset_time"] is not None
