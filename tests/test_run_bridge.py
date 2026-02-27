"""Tests for the standalone bridge entry point."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on path for import
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_bridge import parse_args  # noqa: E402


class TestBridgeArgs:
    """Test bridge argument parsing."""

    def test_defaults(self) -> None:
        args = parse_args([])
        assert args.nats_url == "nats://localhost:4222"
        assert args.ws_host == "0.0.0.0"
        assert args.ws_port == 9090

    def test_custom_nats_url(self) -> None:
        args = parse_args(["--nats-url", "nats://nats.internal:4222"])
        assert args.nats_url == "nats://nats.internal:4222"

    def test_custom_ws_host(self) -> None:
        args = parse_args(["--ws-host", "127.0.0.1"])
        assert args.ws_host == "127.0.0.1"

    def test_custom_ws_port(self) -> None:
        args = parse_args(["--ws-port", "8080"])
        assert args.ws_port == 8080

    def test_all_custom(self) -> None:
        args = parse_args(
            [
                "--nats-url",
                "nats://prod:4222",
                "--ws-host",
                "0.0.0.0",
                "--ws-port",
                "3000",
            ]
        )
        assert args.nats_url == "nats://prod:4222"
        assert args.ws_host == "0.0.0.0"
        assert args.ws_port == 3000
