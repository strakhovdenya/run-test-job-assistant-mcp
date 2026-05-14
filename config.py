import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT_ENV_VAR = "JOB_ASSISTANT_PROJECT_ROOT"

project_root_value = os.getenv(PROJECT_ROOT_ENV_VAR)
if not project_root_value:
    raise RuntimeError(
        f"Missing environment variable {PROJECT_ROOT_ENV_VAR}. "
        "Create a local .env file and set it to the path of your job-assistant repository."
    )

PROJECT_ROOT = Path(project_root_value).resolve()

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
