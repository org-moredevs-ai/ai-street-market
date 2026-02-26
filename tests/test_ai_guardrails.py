"""AI Guardrails — automated enforcement of AI-mandatory architecture.

These tests ensure that the AI Street Market stays AI-driven.
They check code structure, not runtime behavior — no API key needed.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _python_agent_dirs() -> list[Path]:
    """Return all Python agent directories (have agent.py)."""
    agents_dir = PROJECT_ROOT / "agents"
    return [
        d for d in agents_dir.iterdir()
        if d.is_dir() and (d / "agent.py").exists()
    ]


def _ts_agent_dirs() -> list[Path]:
    """Return all TypeScript agent directories (have src/index.ts)."""
    agents_dir = PROJECT_ROOT / "agents"
    return [
        d for d in agents_dir.iterdir()
        if d.is_dir() and (d / "src" / "index.ts").exists()
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEveryAgentHasLLMBrain:
    """Every Python agent must import AgentLLMBrain."""

    def test_python_agents_import_llm_brain(self):
        for agent_dir in _python_agent_dirs():
            agent_file = agent_dir / "agent.py"
            source = agent_file.read_text()
            assert "AgentLLMBrain" in source, (
                f"{agent_file.relative_to(PROJECT_ROOT)} does not import AgentLLMBrain"
            )

    def test_ts_agents_have_llm_brain(self):
        for agent_dir in _ts_agent_dirs():
            llm_brain = agent_dir / "src" / "llm_brain.ts"
            assert llm_brain.exists(), (
                f"{agent_dir.name} is missing src/llm_brain.ts"
            )


class TestEveryAgentHasPersona:
    """Every Python agent's strategy must define a PERSONA constant."""

    def test_python_agents_have_persona(self):
        for agent_dir in _python_agent_dirs():
            strategy_file = agent_dir / "strategy.py"
            if not strategy_file.exists():
                continue
            source = strategy_file.read_text()
            assert "PERSONA" in source, (
                f"{strategy_file.relative_to(PROJECT_ROOT)} does not define PERSONA"
            )


class TestNoLLMToggleEnvVars:
    """The .env.example must not have any USE_LLM=false lines."""

    def test_no_llm_toggle_in_env_example(self):
        env_file = PROJECT_ROOT / ".env.example"
        content = env_file.read_text()
        assert "USE_LLM" not in content, (
            ".env.example still has USE_LLM toggle variables"
        )
        assert "ANTHROPIC_API_KEY" not in content, (
            ".env.example still references ANTHROPIC_API_KEY (use OPENROUTER_API_KEY)"
        )


class TestTownCrierUsesLLMUnconditionally:
    """Town Crier narrator must not have toggle logic."""

    def test_narrator_no_toggle(self):
        narrator_file = PROJECT_ROOT / "services" / "town_crier" / "narrator.py"
        source = narrator_file.read_text()
        assert "TOWN_CRIER_USE_LLM" not in source, (
            "narrator.py still checks TOWN_CRIER_USE_LLM toggle"
        )
        assert "self.enabled" not in source, (
            "narrator.py still has self.enabled toggle"
        )


class TestWorldNatureUsesLLMUnconditionally:
    """World Nature must not have toggle logic."""

    def test_nature_no_toggle(self):
        nature_file = PROJECT_ROOT / "services" / "world" / "nature.py"
        source = nature_file.read_text()
        assert "WORLD_USE_LLM_NATURE" not in source, (
            "nature.py still checks WORLD_USE_LLM_NATURE toggle"
        )


class TestNoAgentWithoutLLM:
    """Every agent directory must have LLM integration."""

    def test_all_agent_dirs_have_llm(self):
        agents_dir = PROJECT_ROOT / "agents"
        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            if agent_dir.name.startswith("_"):
                continue
            # Python agent
            if (agent_dir / "agent.py").exists():
                source = (agent_dir / "agent.py").read_text()
                assert "AgentLLMBrain" in source, (
                    f"Python agent {agent_dir.name} has no LLM integration"
                )
            # TypeScript agent
            elif (agent_dir / "src" / "index.ts").exists():
                assert (agent_dir / "src" / "llm_brain.ts").exists(), (
                    f"TypeScript agent {agent_dir.name} has no LLM integration"
                )


class TestEconomyRunnerChecksAPIKey:
    """The economy runner must refuse to start without API keys."""

    def test_run_economy_checks_service_key(self):
        runner_file = PROJECT_ROOT / "scripts" / "run_economy.py"
        source = runner_file.read_text()
        assert "OPENROUTER_API_KEY" in source, (
            "run_economy.py does not check for OPENROUTER_API_KEY"
        )

    def test_run_economy_validates_agent_keys(self):
        """Economy runner must validate that each agent has its own key."""
        runner_file = PROJECT_ROOT / "scripts" / "run_economy.py"
        source = runner_file.read_text()
        assert "_validate_agent_env" in source, (
            "run_economy.py does not call _validate_agent_env()"
        )
        assert "AGENT_PREFIXES" in source, (
            "run_economy.py does not check all agent prefixes"
        )


class TestStrictAgentIsolation:
    """Agent LLM config must enforce strict per-agent isolation."""

    def test_for_agent_requires_own_key(self):
        """LLMConfig.for_agent() must not fall back to OPENROUTER_API_KEY."""
        config_file = (
            PROJECT_ROOT / "libs" / "streetmarket" / "agent" / "llm_config.py"
        )
        source = config_file.read_text()
        # for_agent must NOT contain a fallback to OPENROUTER_API_KEY
        # Find the for_agent method body
        start = source.index("def for_agent(")
        end = source.index("def for_service(")
        for_agent_body = source[start:end]
        assert "OPENROUTER_API_KEY" not in for_agent_body, (
            "LLMConfig.for_agent() still falls back to shared OPENROUTER_API_KEY"
        )
        assert "DEFAULT_MODEL" not in for_agent_body, (
            "LLMConfig.for_agent() still falls back to DEFAULT_MODEL"
        )

    def test_for_agent_raises_on_missing_key(self):
        """LLMConfig.for_agent() must raise without per-agent key."""
        config_file = (
            PROJECT_ROOT / "libs" / "streetmarket" / "agent" / "llm_config.py"
        )
        source = config_file.read_text()
        assert "raise KeyError" in source or "raise ValueError" in source, (
            "LLMConfig.for_agent() does not raise on missing config"
        )

    def test_lumberjack_ts_requires_own_key(self):
        """Lumberjack TypeScript config must not fall back to shared key."""
        config_file = (
            PROJECT_ROOT / "agents" / "lumberjack" / "src" / "llm_brain.ts"
        )
        source = config_file.read_text()
        # Uses template literal: ${prefix}_API_KEY where prefix = "LUMBERJACK"
        assert "prefix" in source and "_API_KEY" in source, (
            "Lumberjack loadConfig() does not check per-agent API key"
        )
        assert "throw new Error" in source, (
            "Lumberjack loadConfig() does not throw on missing config"
        )
        # Must NOT fall back to shared OPENROUTER_API_KEY for the agent key
        # (API base fallback is fine — it's just infrastructure URL)
        assert 'OPENROUTER_API_KEY' not in source, (
            "Lumberjack loadConfig() still falls back to shared OPENROUTER_API_KEY"
        )

    def test_agent_prefixes_constant_exists(self):
        """AGENT_PREFIXES must enumerate all agents for validation."""
        config_file = (
            PROJECT_ROOT / "libs" / "streetmarket" / "agent" / "llm_config.py"
        )
        source = config_file.read_text()
        assert "AGENT_PREFIXES" in source, (
            "llm_config.py missing AGENT_PREFIXES constant"
        )
        # Every known agent must be listed
        for agent in ("FARMER", "CHEF", "BAKER", "MASON", "BUILDER", "LUMBERJACK"):
            assert f'"{agent}"' in source, (
                f"AGENT_PREFIXES missing {agent}"
            )


class TestOpenRouterIsGateway:
    """No direct anthropic.AsyncAnthropic() usage in agent/service code."""

    def test_no_direct_anthropic_in_agents(self):
        for agent_dir in _python_agent_dirs():
            agent_file = agent_dir / "agent.py"
            source = agent_file.read_text()
            assert "anthropic.AsyncAnthropic" not in source, (
                f"{agent_file.relative_to(PROJECT_ROOT)} uses direct Anthropic client"
            )

    def test_no_direct_anthropic_in_narrator(self):
        narrator = PROJECT_ROOT / "services" / "town_crier" / "narrator.py"
        source = narrator.read_text()
        assert "anthropic.AsyncAnthropic" not in source, (
            "narrator.py uses direct Anthropic client instead of OpenRouter"
        )

    def test_no_direct_anthropic_in_nature(self):
        nature = PROJECT_ROOT / "services" / "world" / "nature.py"
        source = nature.read_text()
        assert "anthropic.AsyncAnthropic" not in source, (
            "nature.py uses direct Anthropic client instead of OpenRouter"
        )


class TestCLAUDEMDHasAIRule:
    """CLAUDE.md must contain the AI-Mandatory rule."""

    def test_claude_md_has_ai_mandatory_rule(self):
        claude_md = PROJECT_ROOT / "CLAUDE.md"
        content = claude_md.read_text()
        assert "AI-Mandatory Rule" in content, (
            "CLAUDE.md is missing the AI-Mandatory Rule section"
        )
        assert "OPENROUTER_API_KEY" in content, (
            "CLAUDE.md AI-Mandatory Rule does not mention OPENROUTER_API_KEY"
        )
