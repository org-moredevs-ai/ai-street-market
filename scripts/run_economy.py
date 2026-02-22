"""Economy Runner — starts NATS + all services + agents with color-coded logs.

Usage:
    python scripts/run_economy.py
    make run-economy

Ctrl+C for graceful shutdown.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# ── Constants ────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NATS_HEALTH_URL = "http://localhost:8222/healthz"
NATS_HEALTH_TIMEOUT = 15  # seconds
NATS_HEALTH_INTERVAL = 0.5  # seconds between polls
SHUTDOWN_GRACE_PERIOD = 5  # seconds before SIGKILL
LABEL_WIDTH = 12  # pad labels to this width (longest: "lumberjack")

RESET = "\033[0m"

# ── Service definitions ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ServiceDefinition:
    """Describes a service to be managed by the runner."""

    name: str
    label: str
    command: list[str]
    color: str
    phase: int  # 1=infra, 2=core services, 3=agents
    critical: bool  # if True, crash → shutdown all
    cwd: Path | None = None  # working directory override


SERVICES: list[ServiceDefinition] = [
    # Phase 2: Core services (NATS is phase 1, handled separately)
    ServiceDefinition(
        name="world",
        label="world",
        command=[sys.executable, "-m", "services.world"],
        color="\033[32m",  # green
        phase=2,
        critical=True,
    ),
    ServiceDefinition(
        name="governor",
        label="governor",
        command=[sys.executable, "-m", "services.governor"],
        color="\033[33m",  # yellow
        phase=2,
        critical=True,
    ),
    ServiceDefinition(
        name="banker",
        label="banker",
        command=[sys.executable, "-m", "services.banker"],
        color="\033[34m",  # blue
        phase=2,
        critical=True,
    ),
    # Phase 3: Trading agents
    ServiceDefinition(
        name="farmer",
        label="farmer",
        command=[sys.executable, "-m", "agents.farmer"],
        color="\033[35m",  # magenta
        phase=3,
        critical=False,
    ),
    ServiceDefinition(
        name="chef",
        label="chef",
        command=[sys.executable, "-m", "agents.chef"],
        color="\033[36m",  # cyan
        phase=3,
        critical=False,
    ),
    ServiceDefinition(
        name="lumberjack",
        label="lumberjack",
        command=["npx", "tsx", "src/index.ts"],
        color="\033[31m",  # red
        phase=3,
        critical=False,
        cwd=PROJECT_ROOT / "agents" / "lumberjack",
    ),
]


def format_log_line(label: str, color: str, line: str) -> str:
    """Format a log line with a colored, padded label prefix."""
    return f"{color}{label:<{LABEL_WIDTH}}{RESET} | {line}"


def get_phases() -> list[int]:
    """Return sorted unique phases from SERVICES."""
    return sorted({s.phase for s in SERVICES})


def get_services_for_phase(phase: int) -> list[ServiceDefinition]:
    """Return services belonging to a given phase."""
    return [s for s in SERVICES if s.phase == phase]


# ── NATS management ──────────────────────────────────────────────────────────


def is_nats_healthy() -> bool:
    """Check if NATS monitoring endpoint is responding."""
    try:
        with urllib.request.urlopen(NATS_HEALTH_URL, timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


async def ensure_nats(runner_print: callable) -> None:  # type: ignore[valid-type]
    """Start NATS via docker compose if not already running."""
    if is_nats_healthy():
        runner_print("NATS already running")
        return

    runner_print("Starting NATS via docker compose...")
    compose_file = PROJECT_ROOT / "infrastructure" / "docker-compose.yml"
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "up",
        "-d",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.wait()

    # Poll for health
    elapsed = 0.0
    while elapsed < NATS_HEALTH_TIMEOUT:
        if is_nats_healthy():
            runner_print("NATS is healthy")
            return
        await asyncio.sleep(NATS_HEALTH_INTERVAL)
        elapsed += NATS_HEALTH_INTERVAL

    runner_print("ERROR: NATS failed to become healthy within timeout")
    sys.exit(1)


# ── Managed process ──────────────────────────────────────────────────────────


class ManagedProcess:
    """Wraps an asyncio subprocess with color-prefixed log streaming."""

    def __init__(self, definition: ServiceDefinition) -> None:
        self.definition = definition
        self.process: asyncio.subprocess.Process | None = None
        self._tasks: list[asyncio.Task] = []

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def start(self) -> None:
        """Launch the subprocess."""
        env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(PROJECT_ROOT),
        }
        self.process = await asyncio.create_subprocess_exec(
            *self.definition.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.definition.cwd) if self.definition.cwd else str(PROJECT_ROOT),
            env=env,
        )
        # Start stream readers
        self._tasks = [
            asyncio.create_task(self._stream_reader(self.process.stdout, "stdout")),
            asyncio.create_task(self._stream_reader(self.process.stderr, "stderr")),
        ]

    async def _stream_reader(
        self, stream: asyncio.StreamReader | None, _name: str
    ) -> None:
        """Read lines from a stream and print with color prefix."""
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            print(format_log_line(self.definition.label, self.definition.color, text))

    async def stop(self) -> None:
        """Send SIGTERM, wait grace period, then SIGKILL if needed."""
        if not self.is_running:
            return
        assert self.process is not None

        try:
            self.process.terminate()
        except ProcessLookupError:
            return

        try:
            await asyncio.wait_for(self.process.wait(), timeout=SHUTDOWN_GRACE_PERIOD)
        except asyncio.TimeoutError:
            try:
                self.process.kill()
            except ProcessLookupError:
                pass
            await self.process.wait()

        # Cancel stream readers
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def wait(self) -> int:
        """Wait for the process to exit and return the return code."""
        if self.process is None:
            return -1
        return await self.process.wait()


# ── Economy runner ───────────────────────────────────────────────────────────


class EconomyRunner:
    """Orchestrates startup, monitoring, and shutdown of all services."""

    def __init__(self) -> None:
        self.managed: list[ManagedProcess] = []
        self._shutting_down = False

    def _print(self, msg: str) -> None:
        """Print a runner status message."""
        nats_color = "\033[90m"  # gray
        print(format_log_line("runner", nats_color, msg))

    async def start(self) -> None:
        """Start all services in phased order."""
        # Phase 1: NATS
        self._print("Phase 1: Infrastructure")
        await ensure_nats(self._print)

        # Phase 2 & 3: services and agents
        for phase in get_phases():
            phase_services = get_services_for_phase(phase)
            phase_names = ", ".join(s.name for s in phase_services)
            self._print(f"Phase {phase}: Starting {phase_names}")

            for svc_def in phase_services:
                mp = ManagedProcess(svc_def)
                await mp.start()
                self.managed.append(mp)
                self._print(f"  Started {svc_def.name}")

            # Brief pause between phases to let services initialize
            await asyncio.sleep(1)

        self._print("All services running. Press Ctrl+C to stop.")

    async def watch(self) -> None:
        """Monitor running processes. Shutdown if a critical service dies."""
        while not self._shutting_down:
            for mp in self.managed:
                if mp.process is not None and mp.process.returncode is not None:
                    name = mp.definition.name
                    code = mp.process.returncode
                    if mp.definition.critical:
                        self._print(
                            f"CRITICAL: {name} exited with code {code} — shutting down"
                        )
                        await self.shutdown()
                        return
                    else:
                        self._print(f"WARNING: {name} exited with code {code}")
                        # Mark as handled by setting process to None
                        mp.process = None
            await asyncio.sleep(0.5)

    async def shutdown(self) -> None:
        """Gracefully shut down all services in reverse order."""
        if self._shutting_down:
            return
        self._shutting_down = True

        self._print("Shutting down...")

        # Stop in reverse startup order
        for mp in reversed(self.managed):
            if mp.is_running:
                self._print(f"  Stopping {mp.definition.name}")
                await mp.stop()

        self._print("All services stopped.")


# ── Main ─────────────────────────────────────────────────────────────────────


async def main() -> None:
    runner = EconomyRunner()

    loop = asyncio.get_running_loop()

    def signal_handler() -> None:
        asyncio.ensure_future(runner.shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await runner.start()
        await runner.watch()
    except asyncio.CancelledError:
        pass
    finally:
        await runner.shutdown()


if __name__ == "__main__":
    print(
        "\033[1m"
        "═══════════════════════════════════════════════════════\n"
        "  AI Street Market — Economy Runner\n"
        "═══════════════════════════════════════════════════════"
        "\033[0m\n"
    )
    asyncio.run(main())
