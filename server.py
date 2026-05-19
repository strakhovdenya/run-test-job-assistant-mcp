import subprocess
import threading
import time
import uuid
from datetime import datetime
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


TEST_RUNS: dict[str, dict] = {}
TEST_RUNS_LOCK = threading.Lock()


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


def progress_bar(current: int, total: int, width: int = 24) -> str:
    if total <= 0:
        return f"[{'░' * width}] 0% (0/0)"

    current = max(0, min(current, total))
    filled = int(width * current / total)
    empty = width - filled
    percent = int(100 * current / total)

    return f"[{'█' * filled}{'░' * empty}] {percent}% ({current}/{total})"


def append_run_log(run_id: str, message: str) -> None:
    with TEST_RUNS_LOCK:
        run = TEST_RUNS.get(run_id)
        if not run:
            return

        timestamp = datetime.now().strftime("%H:%M:%S")
        run["logs"].append(f"{timestamp} | {message}")

        # Keep tool responses reasonably small for ChatGPT App polling.
        run["logs"] = run["logs"][-200:]


def update_run(run_id: str, **fields) -> None:
    with TEST_RUNS_LOCK:
        if run_id in TEST_RUNS:
            TEST_RUNS[run_id].update(fields)


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


def run_command_with_live_status(
    command_name: str,
    cmd: list[str],
    run_id: str,
    heartbeat_seconds: int = 5,
) -> dict:
    """
    Run an allowlisted command and continuously append status/log lines to TEST_RUNS.

    This is intended for ChatGPT App UI polling:
    - start_full_test_suite() starts a background thread
    - get_test_suite_status(run_id) reads TEST_RUNS and returns progress/logs
    """
    started_at = datetime.now().isoformat(timespec="seconds")
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    output_lock = threading.Lock()

    append_run_log(run_id, f"Command: {' '.join(cmd)}")

    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            bufsize=1,
        )

        def read_stream(stream, label: str, storage: list[str]) -> None:
            if stream is None:
                return

            for line in iter(stream.readline, ""):
                text = line.rstrip()
                if not text:
                    continue

                with output_lock:
                    storage.append(text)

                append_run_log(run_id, f"[{command_name}:{label}] {text}")

            stream.close()

        stdout_thread = threading.Thread(
            target=read_stream,
            args=(process.stdout, "stdout", stdout_lines),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=read_stream,
            args=(process.stderr, "stderr", stderr_lines),
            daemon=True,
        )

        stdout_thread.start()
        stderr_thread.start()

        started_monotonic = time.monotonic()
        last_heartbeat = started_monotonic

        while process.poll() is None:
            elapsed = int(time.monotonic() - started_monotonic)

            if elapsed > TEST_TIMEOUT_SECONDS:
                process.kill()
                append_run_log(
                    run_id,
                    f"⏱️ {command_name} timed out after {TEST_TIMEOUT_SECONDS} seconds",
                )
                stdout_thread.join(timeout=2)
                stderr_thread.join(timeout=2)

                with output_lock:
                    stdout = "\n".join(stdout_lines)
                    stderr = "\n".join(stderr_lines)

                return {
                    "name": command_name,
                    "ok": False,
                    "exit_code": None,
                    "command": " ".join(cmd),
                    "project_root_configured": True,
                    "started_at": started_at,
                    "error": f"Command timed out after {TEST_TIMEOUT_SECONDS} seconds.",
                    "stdout": trim_output(stdout),
                    "stderr": trim_output(stderr),
                }

            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_seconds:
                append_run_log(run_id, f"⏳ {command_name} is still running... {elapsed}s")
                last_heartbeat = now

            time.sleep(0.5)

        exit_code = process.wait()
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)

        with output_lock:
            stdout = "\n".join(stdout_lines)
            stderr = "\n".join(stderr_lines)

        ok = exit_code == 0

        if ok:
            append_run_log(run_id, f"✅ {command_name} finished successfully")
        else:
            append_run_log(run_id, f"❌ {command_name} failed with exit_code={exit_code}")

        return {
            "name": command_name,
            "ok": ok,
            "exit_code": exit_code,
            "command": " ".join(cmd),
            "project_root_configured": True,
            "started_at": started_at,
            "stdout": trim_output(stdout),
            "stderr": trim_output(stderr),
        }

    except Exception as exc:
        append_run_log(run_id, f"💥 {command_name} crashed: {repr(exc)}")

        return {
            "name": command_name,
            "ok": False,
            "exit_code": None,
            "command": " ".join(cmd),
            "project_root_configured": True,
            "started_at": started_at,
            "error": repr(exc),
        }


def run_full_test_suite_background(run_id: str) -> None:
    steps = [
        ("test_db_up", "Start PostgreSQL container"),
        ("test_backend", "Run backend tests"),
        ("test_frontend", "Run frontend tests"),
    ]

    total = len(steps)
    results = []

    update_run(
        run_id,
        status="running",
        current_step=None,
        current_step_title=None,
        completed_steps=0,
        total_steps=total,
        progress_bar=progress_bar(0, total),
        started_at=datetime.now().isoformat(timespec="seconds"),
    )
    append_run_log(run_id, "🚀 Full test suite started")

    for index, (step_name, step_title) in enumerate(steps, start=1):
        update_run(
            run_id,
            status="running",
            current_step=step_name,
            current_step_title=step_title,
            completed_steps=index - 1,
            progress_bar=progress_bar(index - 1, total),
        )

        append_run_log(run_id, f"▶️ Step {index}/{total} started: {step_name}")
        append_run_log(run_id, progress_bar(index - 1, total))

        result = run_command_with_live_status(
            step_name,
            ALLOWED_COMMANDS[step_name],
            run_id,
        )
        results.append(result)

        if result["ok"]:
            update_run(
                run_id,
                completed_steps=index,
                progress_bar=progress_bar(index, total),
                results=results,
            )
            append_run_log(run_id, f"✅ Step {index}/{total} passed: {step_name}")
            append_run_log(run_id, progress_bar(index, total))
            continue

        update_run(
            run_id,
            status="failed",
            failed_step=step_name,
            completed_steps=index,
            progress_bar=progress_bar(index, total),
            results=results,
            finished_at=datetime.now().isoformat(timespec="seconds"),
        )

        append_run_log(run_id, f"❌ Step {index}/{total} failed: {step_name}")
        append_run_log(run_id, f"🛑 Full test suite stopped at: {step_name}")
        return

    update_run(
        run_id,
        status="passed",
        failed_step=None,
        current_step=None,
        current_step_title=None,
        completed_steps=total,
        progress_bar=progress_bar(total, total),
        results=results,
        finished_at=datetime.now().isoformat(timespec="seconds"),
    )

    append_run_log(run_id, "🎉 Full test suite passed")
    append_run_log(run_id, progress_bar(total, total))


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
    Run the full Job Assistant test suite synchronously:
    1. docker compose up -d postgres
    2. backend tests
    3. frontend tests

    Stops after the first failing step.

    For ChatGPT App UI progress/log polling, prefer:
    - start_full_test_suite()
    - get_test_suite_status(run_id)
    """
    steps = [
        "test_db_up",
        "test_backend",
        "test_frontend",
    ]

    results = []

    for index, step in enumerate(steps, start=1):
        result = run_command(step, ALLOWED_COMMANDS[step])
        results.append(result)

        if not result["ok"]:
            return {
                "ok": False,
                "failed_step": step,
                "progress_bar": progress_bar(index, len(steps)),
                "results": results,
            }

    return {
        "ok": True,
        "failed_step": None,
        "progress_bar": progress_bar(len(steps), len(steps)),
        "results": results,
    }


@mcp.tool()
def start_full_test_suite() -> dict:
    """
    Start the full Job Assistant test suite in the background.

    Use this from a ChatGPT App component when the user wants to run all tests
    and see live-like progress/logs through polling.
    """
    run_id = uuid.uuid4().hex

    with TEST_RUNS_LOCK:
        TEST_RUNS[run_id] = {
            "run_id": run_id,
            "ok": True,
            "status": "queued",
            "current_step": None,
            "current_step_title": None,
            "completed_steps": 0,
            "total_steps": 3,
            "progress_bar": progress_bar(0, 3),
            "failed_step": None,
            "logs": ["Queued full test suite run"],
            "results": [],
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "started_at": None,
            "finished_at": None,
        }

    thread = threading.Thread(
        target=run_full_test_suite_background,
        args=(run_id,),
        daemon=True,
    )
    thread.start()

    return {
        "ok": True,
        "run_id": run_id,
        "status": "queued",
        "message": "Full test suite started.",
        "progress_bar": progress_bar(0, 3),
    }


@mcp.tool()
def get_test_suite_status(run_id: str) -> dict:
    """
    Get current status, progress and recent logs for a running test suite.

    Use this from a ChatGPT App component to poll progress after calling
    start_full_test_suite().
    """
    with TEST_RUNS_LOCK:
        run = TEST_RUNS.get(run_id)

        if not run:
            return {
                "ok": False,
                "error": f"Unknown run_id: {run_id}",
            }

        # Return a shallow copy so the response is not affected by concurrent updates.
        return {
            "ok": True,
            **dict(run),
        }


if __name__ == "__main__":
    mcp.settings.host = "127.0.0.1"
    mcp.settings.port = 8000
    mcp.settings.streamable_http_path = "/mcp"

    mcp.run(transport="streamable-http")
