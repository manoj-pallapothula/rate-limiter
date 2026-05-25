import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def make_mock_redis(zcard_value=1):
    mock = AsyncMock()
    mock_pipe = AsyncMock()
    mock_pipe.execute = AsyncMock(return_value=[0, 1, zcard_value, True])
    mock.pipeline = MagicMock(return_value=mock_pipe)
    mock.zrange = AsyncMock(return_value=[])
    return mock


@pytest.mark.asyncio
async def test_first_request_allowed():
    with patch("app.algorithms.sliding_window.get_redis") as mock_get:
        mock_get.return_value = make_mock_redis(1)
        from app.algorithms.sliding_window import check
        result = await check("client_sw_1", limit=5, window_seconds=60)
        assert result.allowed is True
        assert result.algorithm == "sliding_window"


@pytest.mark.asyncio
async def test_request_over_limit_blocked():
    with patch("app.algorithms.sliding_window.get_redis") as mock_get:
        mock = make_mock_redis(6)
        mock.zrange = AsyncMock(return_value=[("req", 1000.0)])
        mock_get.return_value = mock
        from app.algorithms.sliding_window import check
        result = await check("client_sw_2", limit=5, window_seconds=60)
        assert result.allowed is False
        assert result.remaining == 0


@pytest.mark.asyncio
async def test_remaining_calculated_correctly():
    with patch("app.algorithms.sliding_window.get_redis") as mock_get:
        mock_get.return_value = make_mock_redis(3)
        from app.algorithms.sliding_window import check
        result = await check("client_sw_3", limit=5, window_seconds=60)
        assert result.remaining == 2


@pytest.mark.asyncio
async def test_retry_after_zero_when_allowed():
    with patch("app.algorithms.sliding_window.get_redis") as mock_get:
        mock_get.return_value = make_mock_redis(1)
        from app.algorithms.sliding_window import check
        result = await check("client_sw_4", limit=5, window_seconds=60)
        assert result.retry_after == 0