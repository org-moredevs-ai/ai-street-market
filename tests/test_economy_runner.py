"""Tests for the Economy Runner — service definitions, formatting, phases."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add project root to path so we can import the script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from run_economy import (
    LABEL_WIDTH,
    RESET,
    SERVICES,
    ServiceDefinition,
    format_log_line,
    get_phases,
    get_services_for_phase,
)

# ── Service definitions ──────────────────────────────────────────────────────


class TestServiceDefinitions:
    def test_all_services_have_unique_names(self) -> None:
        names = [s.name for s in SERVICES]
        assert len(names) == len(set(names))

    def test_all_services_have_unique_labels(self) -> None:
        labels = [s.label for s in SERVICES]
        assert len(labels) == len(set(labels))

    def test_all_services_have_unique_colors(self) -> None:
        colors = [s.color for s in SERVICES]
        assert len(colors) == len(set(colors))

    def test_all_services_have_non_empty_command(self) -> None:
        for svc in SERVICES:
            assert len(svc.command) > 0, f"{svc.name} has empty command"

    def test_critical_services_are_phase_2(self) -> None:
        for svc in SERVICES:
            if svc.critical:
                assert svc.phase == 2, f"{svc.name} is critical but not phase 2"

    def test_agents_are_phase_3(self) -> None:
        agent_names = {"farmer", "chef", "lumberjack"}
        for svc in SERVICES:
            if svc.name in agent_names:
                assert svc.phase == 3, f"{svc.name} should be phase 3"

    def test_expected_service_count(self) -> None:
        # 3 core services + 3 agents = 6
        assert len(SERVICES) == 6

    def test_service_definition_is_frozen(self) -> None:
        svc = SERVICES[0]
        with pytest.raises(AttributeError):
            svc.name = "hacked"  # type: ignore[misc]

    def test_lumberjack_has_cwd(self) -> None:
        lj = next(s for s in SERVICES if s.name == "lumberjack")
        assert lj.cwd is not None
        assert "lumberjack" in str(lj.cwd)

    def test_python_services_use_sys_executable(self) -> None:
        python_services = [s for s in SERVICES if s.name != "lumberjack"]
        for svc in python_services:
            assert svc.command[0] == sys.executable, (
                f"{svc.name} should use sys.executable"
            )

    def test_lumberjack_uses_npx(self) -> None:
        lj = next(s for s in SERVICES if s.name == "lumberjack")
        assert lj.command[0] == "npx"


# ── Phases ───────────────────────────────────────────────────────────────────


class TestPhases:
    def test_get_phases_returns_sorted_unique(self) -> None:
        phases = get_phases()
        assert phases == sorted(phases)
        assert len(phases) == len(set(phases))

    def test_phases_are_2_and_3(self) -> None:
        # Phase 1 (NATS) is handled separately, not in SERVICES
        assert get_phases() == [2, 3]

    def test_phase_2_has_core_services(self) -> None:
        phase2 = get_services_for_phase(2)
        names = {s.name for s in phase2}
        assert names == {"world", "governor", "banker"}

    def test_phase_3_has_agents(self) -> None:
        phase3 = get_services_for_phase(3)
        names = {s.name for s in phase3}
        assert names == {"farmer", "chef", "lumberjack"}

    def test_all_phase_2_are_critical(self) -> None:
        for svc in get_services_for_phase(2):
            assert svc.critical is True

    def test_no_phase_3_is_critical(self) -> None:
        for svc in get_services_for_phase(3):
            assert svc.critical is False

    def test_empty_phase_returns_empty(self) -> None:
        assert get_services_for_phase(99) == []


# ── Formatting ───────────────────────────────────────────────────────────────


class TestFormatting:
    def test_format_log_line_basic(self) -> None:
        result = format_log_line("test", "\033[32m", "hello world")
        assert "test" in result
        assert "hello world" in result
        assert RESET in result

    def test_format_log_line_has_separator(self) -> None:
        result = format_log_line("svc", "\033[33m", "msg")
        assert " | " in result

    def test_format_log_line_label_padded(self) -> None:
        result = format_log_line("x", "\033[34m", "msg")
        # After the color code, label should be padded to LABEL_WIDTH
        # The color code is 5 chars (\033[34m), then padded label, then reset
        parts = result.split(" | ")
        label_part = parts[0]
        # Strip ANSI codes to check padding
        clean = label_part.replace("\033[34m", "").replace(RESET, "")
        assert len(clean) == LABEL_WIDTH

    def test_all_labels_fit_within_width(self) -> None:
        for svc in SERVICES:
            assert len(svc.label) <= LABEL_WIDTH, (
                f"{svc.name} label '{svc.label}' exceeds LABEL_WIDTH={LABEL_WIDTH}"
            )

    def test_format_preserves_message_content(self) -> None:
        msg = "2026-02-22 tick=42 potato gathered"
        result = format_log_line("farmer", "\033[35m", msg)
        assert msg in result

    def test_format_with_empty_message(self) -> None:
        result = format_log_line("test", "\033[32m", "")
        assert " | " in result


# ── ServiceDefinition construction ───────────────────────────────────────────


class TestServiceDefinitionConstruction:
    def test_create_with_defaults(self) -> None:
        svc = ServiceDefinition(
            name="test",
            label="test",
            command=["echo", "hi"],
            color="\033[0m",
            phase=1,
            critical=False,
        )
        assert svc.cwd is None

    def test_create_with_cwd(self) -> None:
        svc = ServiceDefinition(
            name="test",
            label="test",
            command=["echo", "hi"],
            color="\033[0m",
            phase=1,
            critical=False,
            cwd=Path("/tmp"),
        )
        assert svc.cwd == Path("/tmp")
