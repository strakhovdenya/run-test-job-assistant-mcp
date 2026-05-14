from pathlib import Path

PROJECT_ROOT = Path(r"D:\projects_py\job-assistant").resolve()

MAX_OUTPUT_CHARS = 16000
TEST_TIMEOUT_SECONDS = 300

ALLOWED_COMMANDS = {
    # Поднять postgres через docker compose
    "test_db_up": ["docker", "compose", "up", "-d", "postgres"],

    # Backend tests
    "test_backend": [
        "uv",
        "run",
        "--project",
        "apps/backend",
        "--no-sync",
        "pytest",
        "tests/backend",
    ],

    # Frontend tests
    "test_frontend": [
        "uv",
        "run",
        "--project",
        "apps/frontend",
        "--no-sync",
        "pytest",
        "tests/frontend",
    ],

    # Полная цепочка вручную из MCP: сначала db, потом backend, потом frontend
    # Эту команду лучше запускать отдельной функцией, см. ниже.
}