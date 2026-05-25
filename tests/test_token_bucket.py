import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def make_mock_redis(tokens=None, last_refill=None):
    mock = AsyncMock()
    mock.get = AsyncMock(side_effect=lambda key: (
        str(tokens) if tokens is not None and "tokens" in key
        else str(last_refill) if last_refill is not None
        else None
    ))
    mock_pipe = AsyncMock()
    mock_pipe.execute = AsyncMock(return_value=[True, True])
    mock.pipeline = MagicMock(return_value=mock_pipe)
    return mock


@pytest.mark.asyncio
async def test_full_bucket_allows_request():
    """New client starts with full bucket."""
    with patch("app.algorithms.token_bucket.get_redis") as mock_get:
        mock_get.return_value = make_mock_redis()
        from app.algorithms.token_bucket import check
        result = await check("tb_client_1", limit=5, window_seconds=60)
        assert result.allowed is True
        assert result.tokens_remaining == 4.0


@pytest.mark.asyncio
async def test_empty_bucket_blocks_request():
    """Client with 0 tokens gets blocked."""
    import time
    with patch("app.algorithms.token_bucket.get_redis") as mock_get:
        mock_get.return_value = make_mock_redis(
            tokens=0.0,
            last_refill=time.time()
        )
        from app.algorithms.token_bucket import check
        result = await check("tb_client_2", limit=5, window_seconds=60)
        assert result.allowed is False


@pytest.mark.asyncio
async def test_algorithm_name():
    with patch("app.algorithms.token_bucket.get_redis") as mock_get:
        mock_get.return_value = make_mock_redis()
        from app.algorithms.token_bucket import check
        result = await check("tb_client_3", limit=5, window_seconds=60)
        assert result.algorithm == "token_bucket"


@pytest.mark.asyncio
async def test_retry_after_positive_when_blocked():
    """Blocked requests should have retry_after > 0."""
    import time
    with patch("app.algorithms.token_bucket.get_redis") as mock_get:
        mock_get.return_value = make_mock_redis(
            tokens=0.0,
            last_refill=time.time()
        )
        from app.algorithms.token_bucket import check
        result = await check("tb_client_4", limit=5, window_seconds=60)
        assert result.retry_after > 0


@pytest.mark.asyncio
async def test_partial_tokens_allows_request():
    """Client with 2 tokens can still make requests."""
    import time
    with patch("app.algorithms.token_bucket.get_redis") as mock_get:
        mock_get.return_value = make_mock_redis(
            tokens=2.0,
            last_refill=time.time()
        )
        from app.algorithms.token_bucket import check
        result = await check("tb_client_5", limit=5, window_seconds=60)
        assert result.allowed is True