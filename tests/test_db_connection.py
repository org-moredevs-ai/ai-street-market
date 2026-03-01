"""Tests for MongoDB connection helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Reset module state between tests
import streetmarket.db.connection as conn_module
from streetmarket.db.connection import close_database, get_database


@pytest.fixture(autouse=True)
def _reset_client():
    """Reset the module-level client between tests."""
    conn_module._client = None
    yield
    conn_module._client = None


class TestGetDatabase:
    @patch("streetmarket.db.connection.AsyncIOMotorClient")
    def test_creates_client_on_first_call(self, mock_motor):
        mock_client = MagicMock()
        mock_motor.return_value = mock_client

        db = get_database()

        mock_motor.assert_called_once_with("mongodb://localhost:27017")
        assert db == mock_client["streetmarket"]

    @patch("streetmarket.db.connection.AsyncIOMotorClient")
    def test_reuses_client_on_subsequent_calls(self, mock_motor):
        mock_client = MagicMock()
        mock_motor.return_value = mock_client

        get_database()
        get_database()

        # Only created once
        mock_motor.assert_called_once()

    @patch.dict("os.environ", {"MONGODB_URL": "mongodb://custom:27017", "MONGODB_DB": "testdb"})
    @patch("streetmarket.db.connection.AsyncIOMotorClient")
    def test_uses_env_vars(self, mock_motor):
        mock_client = MagicMock()
        mock_motor.return_value = mock_client

        db = get_database()

        mock_motor.assert_called_once_with("mongodb://custom:27017")
        assert db == mock_client["testdb"]


class TestCloseDatabase:
    @pytest.mark.asyncio
    async def test_close_when_connected(self):
        mock_client = MagicMock()
        conn_module._client = mock_client

        await close_database()

        mock_client.close.assert_called_once()
        assert conn_module._client is None

    @pytest.mark.asyncio
    async def test_close_when_not_connected(self):
        """Closing when no client exists should not raise."""
        await close_database()
        assert conn_module._client is None
