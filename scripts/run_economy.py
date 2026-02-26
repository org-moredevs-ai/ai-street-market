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

from dotenv import load_dotenv

# ── Constants ────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env from project root (does not override existing env vars)
load_dotenv(PROJECT_ROOT / ".env")
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
    ServiceDefinition(
        name="town_crier",
        label="town_crier",
        command=[sys.executable, "-m", "services.town_crier"],
        color="\033[95m",  # bright magenta
        phase=2,
        critical=False,
    ),
    ServiceDefinition(
        name="websocket_bridge",
        label="ws_bridge",
        command=[sys.executable, "-m", "services.websocket_bridge"],
        color="\033[96m",  # bright cyan
        phase=2,
        critical=False,
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
    ServiceDefinition(
        name="mason",
        label="mason",
        command=[sys.executable, "-m", "agents.mason"],
        color="\033[93m",  # bright yellow
        phase=3,
        critical=False,
    ),
    ServiceDefinition(
        name="baker",
        label="baker",
        command=[sys.executable, "-m", "agents.baker"],
        color="\033[92m",  # bright green
        phase=3,
        critical=False,
    ),
    ServiceDefinition(
        name="builder",
        label="builder",
        command=[sys.executable, "-m", "agents.builder"],
        color="\033[94m",  # bright blue
        phase=3,
        critical=False,
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

    async def _kill_stale_processes(self) -> None:
        """Kill any leftover processes from a previous economy run."""
        # Match known service/agent module patterns
        patterns = [s.name for s in SERVICES]
        proc = await asyncio.create_subprocess_exec(
            "ps", "aux",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if not stdout:
            return

        my_pid = os.getpid()
        killed = 0
        for line in stdout.decode().splitlines():
            if any(f"-m services.{p}" in line or f"-m agents.{p}" in line for p in patterns):
                parts = line.split()
                pid = int(parts[1])
                if pid == my_pid:
                    continue
                try:
                    os.kill(pid, signal.SIGTERM)
                    killed += 1
                except (ProcessLookupError, PermissionError):
                    pass
            # Also catch lumberjack (TypeScript)
            if "tsx" in line and "index.ts" in line:
                parts = line.split()
                pid = int(parts[1])
                try:
                    os.kill(pid, signal.SIGTERM)
                    killed += 1
                except (ProcessLookupError, PermissionError):
                    pass

        if killed:
            self._print(f"Killed {killed} stale processes from previous run")
            await asyncio.sleep(1)  # Let them die

    async def _purge_nats_stream(self) -> None:
        """Purge the STREETMARKET stream to avoid stale messages."""
        try:
            import nats as nats_lib
            nc = await nats_lib.connect("nats://localhost:4222")
            js = nc.jetstream()
            await js.purge_stream("STREETMARKET")
            await nc.close()
            self._print("Purged NATS stream STREETMARKET")
        except Exception as e:
            self._print(f"Stream purge skipped: {e}")

    async def start(self) -> None:
        """Start all services in phased order.

        Phase 3 (agents) launches one agent every 10 seconds so each gets
        a dramatic Town Crier introduction instead of all arriving at once.
        """
        # Phase 0: Kill stale processes from a previous run
        await self._kill_stale_processes()

        # Phase 1: NATS
        self._print("Phase 1: Infrastructure")
        await ensure_nats(self._print)

        # Purge NATS stream to avoid stale messages from previous runs
        await self._purge_nats_stream()

        # Phase 2 & 3: services and agents
        for phase in get_phases():
            phase_services = get_services_for_phase(phase)
            phase_names = ", ".join(s.name for s in phase_services)
            self._print(f"Phase {phase}: Starting {phase_names}")

            for i, svc_def in enumerate(phase_services):
                mp = ManagedProcess(svc_def)
                await mp.start()
                self.managed.append(mp)
                self._print(f"  Started {svc_def.name}")

                # Stagger agent launches (phase 3) so Town Crier can
                # introduce each one individually
                if phase == 3 and i < len(phase_services) - 1:
                    await asyncio.sleep(10)

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


def _validate_agent_env() -> list[str]:
    """Validate that every agent has its own API key and model.

    Returns a list of error messages (empty = all good).
    """
    from streetmarket.agent.llm_config import AGENT_PREFIXES

    errors: list[str] = []
    for prefix in AGENT_PREFIXES:
        if not os.environ.get(f"{prefix}_API_KEY"):
            errors.append(f"  {prefix}_API_KEY is missing")
        if not os.environ.get(f"{prefix}_MODEL"):
            errors.append(f"  {prefix}_MODEL is missing")
    return errors


async def main() -> None:
    # Services need at least a shared key OR per-service keys
    has_shared = bool(os.environ.get("OPENROUTER_API_KEY"))
    has_service_keys = all(
        os.environ.get(f"{svc}_API_KEY")
        for svc in ("TOWN_CRIER", "WORLD")
    )
    if not has_shared and not has_service_keys:
        print(
            "\033[91mERROR: Services need LLM access. Set OPENROUTER_API_KEY "
            "(shared) or TOWN_CRIER_API_KEY + WORLD_API_KEY.\033[0m"
        )
        sys.exit(1)

    # Every agent must have its own isolated config
    agent_errors = _validate_agent_env()
    if agent_errors:
        print(
            "\033[91mERROR: Agent isolation violation — each agent must have "
            "its own API key and model.\033[0m"
        )
        print("\033[91mMissing environment variables:\033[0m")
        for err in agent_errors:
            print(f"\033[91m{err}\033[0m")
        print(
            "\n\033[93mHint: Copy .env.example and set a {PREFIX}_API_KEY + "
            "{PREFIX}_MODEL for each agent.\033[0m"
        )
        sys.exit(1)

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
