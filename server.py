import subprocess
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from config import PROJECT_ROOT, MAX_OUTPUT_CHARS, TEST_TIMEOUT_SECONDS, ALLOWED_COMMANDS


mcp = FastMCP(
    "run-test-job-assistant-mcp",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


def trim_output(text: str, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    if not text:
        return ""

    if len(text) <= max_chars:
        return text

    head_size = max_chars // 3
    tail_size = max_chars - head_size

    return (
        text[:head_size]
        + "\n\n--- OUTPUT TRUNCATED ---\n\n"
        + text[-tail_size:]
    )


def run_command(command_name: str, cmd: list[str]) -> dict:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
            shell=False,
        )

        return {
            "name": command_name,
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "command": " ".join(cmd),
            "project_root_configured": True,
            "stdout": trim_output(result.stdout),
            "stderr": trim_output(result.stderr),
        }

    except subprocess.TimeoutExpired as exc:
        return {
            "name": command_name,
            "ok": False,
            "exit_code": None,
            "command": " ".join(cmd),
            "project_root_configured": True,
            "error": f"Command timed out after {TEST_TIMEOUT_SECONDS} seconds.",
            "stdout": trim_output(exc.stdout or ""),
            "stderr": trim_output(exc.stderr or ""),
        }

    except Exception as exc:
        return {
            "name": command_name,
            "ok": False,
            "exit_code": None,
            "command": " ".join(cmd),
            "project_root_configured": True,
            "error": repr(exc),
        }


@mcp.tool()
def run_tests(
    command: Literal[
        "test_db_up",
        "test_backend",
        "test_frontend",
    ] = "test_backend",
) -> dict:
    """
    Run one allowlisted test/check command for the Job Assistant project.

    Available commands:
    - test_db_up: docker compose up -d postgres
    - test_backend: uv run --project apps/backend --no-sync pytest tests/backend
    - test_frontend: uv run --project apps/frontend --no-sync pytest tests/frontend
    """
    cmd = ALLOWED_COMMANDS[command]
    return run_command(command, cmd)


@mcp.tool()
def run_full_test_suite() -> dict:
    """
    Run the full Job Assistant test suite:
    1. docker compose up -d postgres
    2. backend tests
    3. frontend tests

    Stops after the first failing step.
    """
    steps = [
        "test_db_up",
        "test_backend",
        "test_frontend",
    ]

    results = []

    for step in steps:
        result = run_command(step, ALLOWED_COMMANDS[step])
        results.append(result)

        if not result["ok"]:
            return {
                "ok": False,
                "failed_step": step,
                "results": results,
            }

    return {
        "ok": True,
        "failed_step": None,
        "results": results,
    }


if __name__ == "__main__":
    mcp.settings.host = "127.0.0.1"
    mcp.settings.port = 8000
    mcp.settings.streamable_http_path = "/mcp"

    mcp.run(transport="streamable-http")
