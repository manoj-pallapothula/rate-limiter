import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def make_mock_redis(increment_value=1):
    mock = AsyncMock()
    mock_pipe = AsyncMock()
    mock_pipe.execute = AsyncMock(return_value=[increment_value, True])
    mock.pipeline = MagicMock(return_value=mock_pipe)
    return mock


@pytest.mark.asyncio
async def test_first_request_allowed():
    with patch("app.algorithms.fixed_window.get_redis") as mock_get:
        mock_get.return_value = make_mock_redis(1)
        from app.algorithms.fixed_window import check
        result = await check("client_1", limit=5, window_seconds=60)
        assert result.allowed is True
        assert result.current_count == 1
        assert result.remaining == 4


@pytest.mark.asyncio
async def test_request_at_limit_allowed():
    with patch("app.algorithms.fixed_window.get_redis") as mock_get:
        mock_get.return_value = make_mock_redis(5)
        from app.algorithms.fixed_window import check
        result = await check("client_2", limit=5, window_seconds=60)
        assert result.allowed is True
        assert result.remaining == 0


@pytest.mark.asyncio
async def test_request_over_limit_blocked():
    with patch("app.algorithms.fixed_window.get_redis") as mock_get:
        mock_get.return_value = make_mock_redis(6)
        from app.algorithms.fixed_window import check
        result = await check("client_3", limit=5, window_seconds=60)
        assert result.allowed is False
        assert result.remaining == 0


@pytest.mark.asyncio
async def test_algorithm_name():
    with patch("app.algorithms.fixed_window.get_redis") as mock_get:
        mock_get.return_value = make_mock_redis(1)
        from app.algorithms.fixed_window import check
        result = await check("client_4", limit=10, window_seconds=60)
        assert result.algorithm == "fixed_window"


@pytest.mark.asyncio
async def test_client_id_in_result():
    with patch("app.algorithms.fixed_window.get_redis") as mock_get:
        mock_get.return_value = make_mock_redis(1)
        from app.algorithms.fixed_window import check
        result = await check("my_client", limit=10, window_seconds=60)
        assert result.client_id == "my_client"