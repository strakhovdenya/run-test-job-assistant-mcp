# run-test-job-assistant-mcp

MCP server for safely running checks in the [`strakhovdenya/job-assistant`](https://github.com/strakhovdenya/job-assistant) project.

This server exposes a small allowlisted set of test commands that can be invoked by an AI assistant through MCP. Its goal is to make project validation repeatable, explicit, and safe.

---

## Purpose

`run-test-job-assistant-mcp` is a helper MCP server for the **AI Job Assistant** project.

It allows an AI assistant to:

- start the test PostgreSQL dependency
- run backend tests
- run frontend tests
- run the full project test suite
- start a full test suite run in the background
- poll full-suite progress and logs from a ChatGPT App UI

The server is intentionally narrow in scope. It is not a general shell runner and should not expose arbitrary command execution.

---

## Target project

Main project repository:

```text
strakhovdenya/job-assistant
```

The target project is a Python monorepo with:

- FastAPI backend
- Streamlit frontend
- PostgreSQL database
- `uv` workspace dependency management
- `pytest` test suite

---

## Configuration

The MCP server needs to know where the local `job-assistant` repository is located.

Set this environment variable before running the server:

```text
JOB_ASSISTANT_PROJECT_ROOT=
```

You can use `.env.example` as a reference for the required variable names.

Do not commit your real `.env` file or local machine paths to the repository.

---

## Available tools

### `run_tests`

Runs one allowlisted test/check command.

Supported commands:

| Command | Description |
| --- | --- |
| `test_db_up` | Starts PostgreSQL with Docker Compose |
| `test_backend` | Runs backend tests |
| `test_frontend` | Runs frontend tests |

Expected command behavior:

```bash
# test_db_up
docker compose up -d postgres

# test_backend
uv run --project apps/backend --no-sync pytest tests/backend

# test_frontend
uv run --project apps/frontend --no-sync pytest tests/frontend
```

---

### `run_full_test_suite`

Runs the complete project test suite synchronously in order:

1. Start PostgreSQL
2. Run backend tests
3. Run frontend tests

The suite stops after the first failing step.

Expected command sequence:

```bash
docker compose up -d postgres
uv run --project apps/backend --no-sync pytest tests/backend
uv run --project apps/frontend --no-sync pytest tests/frontend
```

This tool returns only when the suite has finished. For a ChatGPT App UI with progress/log polling, use `start_full_test_suite` and `get_test_suite_status` instead.

---

### `start_full_test_suite`

Starts the complete project test suite in a background thread and immediately returns a `run_id`.

Use this from a ChatGPT App component when the user wants to see progress while the suite is running.

Example response:

```json
{
  "ok": true,
  "run_id": "abc123",
  "status": "queued",
  "message": "Full test suite started.",
  "progress_bar": "[░░░░░░░░░░░░░░░░░░░░░░░░] 0% (0/3)"
}
```

---

### `get_test_suite_status`

Returns current progress, status and recent logs for a background full-suite run.

Arguments:

| Argument | Description |
| --- | --- |
| `run_id` | ID returned by `start_full_test_suite` |

Possible statuses:

| Status | Meaning |
| --- | --- |
| `queued` | Run was created but has not started yet |
| `running` | A suite step is currently executing |
| `passed` | All suite steps passed |
| `failed` | A suite step failed and the suite stopped |

Example response:

```json
{
  "ok": true,
  "run_id": "abc123",
  "status": "running",
  "current_step": "test_backend",
  "current_step_title": "Run backend tests",
  "completed_steps": 1,
  "total_steps": 3,
  "progress_bar": "[████████░░░░░░░░░░░░░░░░] 33% (1/3)",
  "failed_step": null,
  "logs": [
    "12:00:01 | 🚀 Full test suite started",
    "12:00:02 | ▶️ Step 2/3 started: test_backend",
    "12:00:07 | ⏳ test_backend is still running... 5s"
  ],
  "results": []
}
```

---

## ChatGPT App progress pattern

ChatGPT does not stream arbitrary long-running tool logs directly into the chat message while one tool is still running.

For app-style progress, use polling:

1. The UI calls `start_full_test_suite`.
2. The tool returns a `run_id` quickly.
3. The UI calls `get_test_suite_status` every 1-2 seconds.
4. The UI renders `status`, `progress_bar` and `logs`.
5. Polling stops when `status` is `passed` or `failed`.

Minimal browser-side sketch:

```js
const start = await window.openai.callTool("start_full_test_suite", {});
const runId = start.structuredContent?.run_id ?? start.run_id;

const timer = setInterval(async () => {
  const status = await window.openai.callTool("get_test_suite_status", {
    run_id: runId,
  });

  const data = status.structuredContent ?? status;

  renderProgress(data.progress_bar);
  renderLogs(data.logs);

  if (["passed", "failed"].includes(data.status)) {
    clearInterval(timer);
  }
}, 1000);
```

---

## Safety model

This MCP server should follow a strict allowlist model:

- no arbitrary shell access
- no user-provided command strings
- no destructive commands
- no access to secrets beyond what the test environment requires
- commands should be explicit and auditable
- local project paths should be provided through environment variables, not committed to the repository

The server should only expose commands that are safe to run repeatedly during development and review.

---

## Typical usage

An AI assistant can use this MCP server while helping with the `job-assistant` project, for example:

- after changing backend code, run backend tests
- after changing frontend code, run frontend tests
- before opening or reviewing a pull request, run the full suite
- when debugging CI failures, reproduce the failing test command locally
- in a ChatGPT App, show a progress panel for a background full-suite run

Example assistant workflow:

```text
1. Inspect the code change
2. Decide which tests are relevant
3. Run one of the allowlisted MCP commands
4. Read the test output
5. Suggest or apply fixes
6. Re-run the relevant command
```

Example ChatGPT App workflow:

```text
1. User clicks Run Full Test Suite
2. App calls start_full_test_suite
3. App polls get_test_suite_status(run_id)
4. App renders progress/logs
5. App shows final passed/failed state
```

---

## Requirements

The target `job-assistant` project should have:

- Docker / Docker Compose
- Python and `uv`
- project dependencies installed or resolvable through `uv`
- test folders available at:
  - `tests/backend`
  - `tests/frontend`

---

## Relationship to CI

This MCP server does not replace GitHub Actions.

It is meant to complement CI by giving an AI assistant a safe way to run the same checks earlier in the development loop.

Recommended flow:

```text
Local / MCP checks → Pull Request → GitHub Actions
```

---

## Documentation in the main project

The main `job-assistant` repository can reference this MCP server from its developer documentation, for example:

```text
Docs/mcp-test-server.md
```

That document should explain how the MCP server fits into the development workflow of the main project.

---

## Notes

- Keep the command surface small.
- Prefer explicit tools over flexible shell commands.
- Add new commands only when they are useful, repeatable, and safe.
- Treat this repository as developer automation infrastructure for `job-assistant`.
