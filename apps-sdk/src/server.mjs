import express from "express";
import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { isInitializeRequest } from "@modelcontextprotocol/sdk/types.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const PORT = Number(process.env.PORT || 8000);
const PROJECT_ROOT = process.env.JOB_ASSISTANT_PROJECT_ROOT;

const WIDGET_URI = "ui://widget/test-runner.html";
const WIDGET_PATH = resolve(__dirname, "../widgets/test_runner_widget.html");

const MAX_OUTPUT_CHARS = Number(process.env.MAX_OUTPUT_CHARS || 16000);
const TEST_TIMEOUT_SECONDS = Number(process.env.TEST_TIMEOUT_SECONDS || 300);

if (!PROJECT_ROOT) {
  console.error(
    "Missing JOB_ASSISTANT_PROJECT_ROOT. Set it to the local path of your job-assistant repository."
  );
  process.exit(1);
}

const allowedCommands = {
  test_db_up: ["docker", "compose", "up", "-d", "postgres"],
  test_backend: [
    "uv",
    "run",
    "--project",
    "apps/backend",
    "--no-sync",
    "pytest",
    "tests/backend",
  ],
  test_frontend: [
    "uv",
    "run",
    "--project",
    "apps/frontend",
    "--no-sync",
    "pytest",
    "tests/frontend",
  ],
};

const testRuns = new Map();

function trimOutput(text, maxChars = MAX_OUTPUT_CHARS) {
  if (!text) return "";
  if (text.length <= maxChars) return text;

  const headSize = Math.floor(maxChars / 3);
  const tailSize = maxChars - headSize;

  return (
    text.slice(0, headSize) +
    "\n\n--- OUTPUT TRUNCATED ---\n\n" +
    text.slice(-tailSize)
  );
}

function progressBar(current, total, width = 24) {
  if (!total || total <= 0) {
    return `[${"░".repeat(width)}] 0% (0/0)`;
  }

  const safeCurrent = Math.max(0, Math.min(current, total));
  const filled = Math.floor((width * safeCurrent) / total);
  const empty = width - filled;
  const percent = Math.floor((100 * safeCurrent) / total);

  return `[${"█".repeat(filled)}${"░".repeat(empty)}] ${percent}% (${safeCurrent}/${total})`;
}

function nowTime() {
  return new Date().toLocaleTimeString("ru-RU", { hour12: false });
}

function appendRunLog(runId, message) {
  const run = testRuns.get(runId);
  if (!run) return;

  run.logs.push(`${nowTime()} | ${message}`);
  run.logs = run.logs.slice(-200);
}

function updateRun(runId, patch) {
  const run = testRuns.get(runId);
  if (!run) return;
  Object.assign(run, patch);
}

function runCommandWithLiveStatus(commandName, cmd, runId) {
  return new Promise((resolvePromise) => {
    const startedAt = new Date().toISOString();
    const stdoutLines = [];
    const stderrLines = [];

    appendRunLog(runId, `Command: ${cmd.join(" ")}`);

    let resolved = false;

    const child = spawn(cmd[0], cmd.slice(1), {
      cwd: PROJECT_ROOT,
      shell: false,
      windowsHide: true,
      env: process.env,
    });

    const startedMs = Date.now();

    const heartbeat = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedMs) / 1000);
      appendRunLog(runId, `⏳ ${commandName} is still running... ${elapsed}s`);
    }, 5000);

    const timeout = setTimeout(() => {
      if (resolved) return;

      resolved = true;
      clearInterval(heartbeat);

      child.kill("SIGKILL");

      appendRunLog(
        runId,
        `⏱️ ${commandName} timed out after ${TEST_TIMEOUT_SECONDS} seconds`
      );

      resolvePromise({
        name: commandName,
        ok: false,
        exit_code: null,
        command: cmd.join(" "),
        project_root_configured: true,
        started_at: startedAt,
        error: `Command timed out after ${TEST_TIMEOUT_SECONDS} seconds.`,
        stdout: trimOutput(stdoutLines.join("\n")),
        stderr: trimOutput(stderrLines.join("\n")),
      });
    }, TEST_TIMEOUT_SECONDS * 1000);

    child.stdout?.on("data", (chunk) => {
      const lines = chunk.toString().split(/\r?\n/).filter(Boolean);
      for (const line of lines) {
        stdoutLines.push(line);
        appendRunLog(runId, `[${commandName}:stdout] ${line}`);
      }
    });

    child.stderr?.on("data", (chunk) => {
      const lines = chunk.toString().split(/\r?\n/).filter(Boolean);
      for (const line of lines) {
        stderrLines.push(line);
        appendRunLog(runId, `[${commandName}:stderr] ${line}`);
      }
    });

    child.on("error", (error) => {
      if (resolved) return;

      resolved = true;
      clearTimeout(timeout);
      clearInterval(heartbeat);

      appendRunLog(runId, `💥 ${commandName} crashed: ${error.message}`);

      resolvePromise({
        name: commandName,
        ok: false,
        exit_code: null,
        command: cmd.join(" "),
        project_root_configured: true,
        started_at: startedAt,
        error: error.message,
        stdout: trimOutput(stdoutLines.join("\n")),
        stderr: trimOutput(stderrLines.join("\n")),
      });
    });

    child.on("close", (code) => {
      if (resolved) return;

      resolved = true;
      clearTimeout(timeout);
      clearInterval(heartbeat);

      const ok = code === 0;

      if (ok) {
        appendRunLog(runId, `✅ ${commandName} finished successfully`);
      } else {
        appendRunLog(runId, `❌ ${commandName} failed with exit_code=${code}`);
      }

      resolvePromise({
        name: commandName,
        ok,
        exit_code: code,
        command: cmd.join(" "),
        project_root_configured: true,
        started_at: startedAt,
        stdout: trimOutput(stdoutLines.join("\n")),
        stderr: trimOutput(stderrLines.join("\n")),
      });
    });
  });
}

async function runFullSuiteBackground(runId) {
  const steps = [
    ["test_db_up", "Start PostgreSQL container"],
    ["test_backend", "Run backend tests"],
    ["test_frontend", "Run frontend tests"],
  ];

  const total = steps.length;
  const results = [];

  updateRun(runId, {
    status: "running",
    current_step: null,
    current_step_title: null,
    completed_steps: 0,
    total_steps: total,
    progress_bar: progressBar(0, total),
    started_at: new Date().toISOString(),
  });

  appendRunLog(runId, "🚀 Full test suite started");

  for (let i = 0; i < steps.length; i += 1) {
    const index = i + 1;
    const [stepName, stepTitle] = steps[i];

    updateRun(runId, {
      status: "running",
      current_step: stepName,
      current_step_title: stepTitle,
      completed_steps: index - 1,
      progress_bar: progressBar(index - 1, total),
    });

    appendRunLog(runId, `▶️ Step ${index}/${total} started: ${stepName}`);
    appendRunLog(runId, progressBar(index - 1, total));

    const result = await runCommandWithLiveStatus(
      stepName,
      allowedCommands[stepName],
      runId
    );

    results.push(result);

    if (result.ok) {
      updateRun(runId, {
        completed_steps: index,
        progress_bar: progressBar(index, total),
        results,
      });

      appendRunLog(runId, `✅ Step ${index}/${total} passed: ${stepName}`);
      appendRunLog(runId, progressBar(index, total));
      continue;
    }

    updateRun(runId, {
      status: "failed",
      failed_step: stepName,
      completed_steps: index,
      progress_bar: progressBar(index, total),
      results,
      finished_at: new Date().toISOString(),
    });

    appendRunLog(runId, `❌ Step ${index}/${total} failed: ${stepName}`);
    appendRunLog(runId, `🛑 Full test suite stopped at: ${stepName}`);
    return;
  }

  updateRun(runId, {
    status: "passed",
    failed_step: null,
    current_step: null,
    current_step_title: null,
    completed_steps: total,
    progress_bar: progressBar(total, total),
    results,
    finished_at: new Date().toISOString(),
  });

  appendRunLog(runId, "🎉 Full test suite passed");
  appendRunLog(runId, progressBar(total, total));
}

function createServer() {
  const server = new McpServer({
    name: "job-assistant-test-runner-app",
    version: "0.1.0",
  });

  server.registerResource(
    "test_runner_widget",
    WIDGET_URI,
    {
      title: "Job Assistant Test Runner",
      description: "Run the full Job Assistant test suite with progress.",
      mimeType: "text/html+skybridge",
      _meta: {
        "openai/widgetDescription":
          "A test runner widget with a progress bar and live-like logs.",
        "openai/widgetPrefersBorder": true,
      },
    },
    async () => {
      const html = await readFile(WIDGET_PATH, "utf8");

      return {
        contents: [
          {
            uri: WIDGET_URI,
            mimeType: "text/html+skybridge",
            text: html,
          },
        ],
      };
    }
  );

  server.registerTool(
    "open_test_runner_widget",
    {
      title: "Open test runner widget",
      description:
        "Open the ChatGPT widget for running the full Job Assistant test suite with a progress bar and logs.",
      inputSchema: {},
      _meta: {
        "openai/outputTemplate": WIDGET_URI,
        "openai/widgetAccessible": true,
        "openai/toolInvocation/invoking": "Opening test runner…",
        "openai/toolInvocation/invoked": "Test runner ready",
      },
    },
    async () => {
      return {
        content: [
          {
            type: "text",
            text: "Test runner widget is ready. Use the button in the widget to run the full suite with progress.",
          },
        ],
        structuredContent: {
          ok: true,
          widget_uri: WIDGET_URI,
        },
        _meta: {
          widget_uri: WIDGET_URI,
        },
      };
    }
  );

  server.registerTool(
    "start_full_test_suite",
    {
      title: "Start full test suite",
      description:
        "Start the full Job Assistant test suite in the background. The widget should poll get_test_suite_status with the returned run_id.",
      inputSchema: {},
    },
    async () => {
      const runId = randomUUID().replaceAll("-", "");

      testRuns.set(runId, {
        run_id: runId,
        ok: true,
        status: "queued",
        current_step: null,
        current_step_title: null,
        completed_steps: 0,
        total_steps: 3,
        progress_bar: progressBar(0, 3),
        failed_step: null,
        logs: ["Queued full test suite run"],
        results: [],
        created_at: new Date().toISOString(),
        started_at: null,
        finished_at: null,
      });

      runFullSuiteBackground(runId).catch((error) => {
        appendRunLog(runId, `💥 Full suite crashed: ${error.message}`);
        updateRun(runId, {
          status: "failed",
          failed_step: "internal_error",
          finished_at: new Date().toISOString(),
        });
      });

      return {
        content: [
          {
            type: "text",
            text: `Full test suite started. run_id=${runId}`,
          },
        ],
        structuredContent: {
          ok: true,
          run_id: runId,
          status: "queued",
          message: "Full test suite started.",
          progress_bar: progressBar(0, 3),
        },
      };
    }
  );

  server.registerTool(
    "get_test_suite_status",
    {
      title: "Get test suite status",
      description:
        "Get current status, progress bar and recent logs for a background test suite run.",
      inputSchema: {
        run_id: z.string(),
      },
    },
    async ({ run_id }) => {
      const run = testRuns.get(run_id);

      if (!run) {
        return {
          content: [
            {
              type: "text",
              text: `Unknown run_id: ${run_id}`,
            },
          ],
          structuredContent: {
            ok: false,
            error: `Unknown run_id: ${run_id}`,
          },
        };
      }

      return {
        content: [
          {
            type: "text",
            text: `${run.status}: ${run.progress_bar}`,
          },
        ],
        structuredContent: {
          ok: true,
          ...run,
        },
      };
    }
  );

  server.registerTool(
    "run_tests",
    {
      title: "Run one test command",
      description:
        "Run one allowlisted test/check command for the Job Assistant project.",
      inputSchema: {
        command: z
          .enum(["test_db_up", "test_backend", "test_frontend"])
          .default("test_backend"),
      },
    },
    async ({ command }) => {
      const runId = randomUUID().replaceAll("-", "");

      testRuns.set(runId, {
        run_id: runId,
        ok: true,
        status: "running",
        current_step: command,
        current_step_title: command,
        completed_steps: 0,
        total_steps: 1,
        progress_bar: progressBar(0, 1),
        failed_step: null,
        logs: [`Queued single command: ${command}`],
        results: [],
        created_at: new Date().toISOString(),
        started_at: null,
        finished_at: null,
      });

      const result = await runCommandWithLiveStatus(
        command,
        allowedCommands[command],
        runId
      );

      updateRun(runId, {
        status: result.ok ? "passed" : "failed",
        completed_steps: 1,
        total_steps: 1,
        progress_bar: progressBar(1, 1),
        failed_step: result.ok ? null : command,
        results: [result],
        finished_at: new Date().toISOString(),
      });

      return {
        content: [
          {
            type: "text",
            text: result.ok
              ? `${command} passed.`
              : `${command} failed with exit_code=${result.exit_code}.`,
          },
        ],
        structuredContent: {
          ok: result.ok,
          run_id: runId,
          result,
        },
      };
    }
  );

  return server;
}

const app = express();
app.use(express.json({ limit: "10mb" }));

const transports = new Map();

app.post("/mcp", async (req, res) => {
  try {
    const sessionId = req.headers["mcp-session-id"];
    let session = sessionId ? transports.get(sessionId) : undefined;

    if (!session) {
      if (!isInitializeRequest(req.body)) {
        res.status(400).json({
          jsonrpc: "2.0",
          error: {
            code: -32000,
            message: "Bad Request: No valid MCP session ID provided",
          },
          id: null,
        });
        return;
      }

      const sessionServer = createServer();
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: () => randomUUID(),
        onsessioninitialized: (newSessionId) => {
          transports.set(newSessionId, {
            server: sessionServer,
            transport,
          });
        },
      });

      transport.onclose = () => {
        if (transport.sessionId) {
          transports.delete(transport.sessionId);
        }
      };

      await sessionServer.connect(transport);
      session = { server: sessionServer, transport };
    }

    await session.transport.handleRequest(req, res, req.body);
  } catch (error) {
    console.error("MCP POST error:", error);
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: "2.0",
        error: {
          code: -32603,
          message: "Internal server error",
        },
        id: null,
      });
    }
  }
});

app.get("/mcp", async (req, res) => {
  try {
    const sessionId = req.headers["mcp-session-id"];
    const session = sessionId ? transports.get(sessionId) : undefined;

    if (!session) {
      res.status(400).send("Invalid or missing session ID");
      return;
    }

    await session.transport.handleRequest(req, res);
  } catch (error) {
    console.error("MCP GET error:", error);
    if (!res.headersSent) {
      res.status(500).send("Internal server error");
    }
  }
});

app.delete("/mcp", async (req, res) => {
  try {
    const sessionId = req.headers["mcp-session-id"];
    const session = sessionId ? transports.get(sessionId) : undefined;

    if (!session) {
      res.status(400).send("Invalid or missing session ID");
      return;
    }

    await session.transport.handleRequest(req, res);
  } catch (error) {
    console.error("MCP DELETE error:", error);
    if (!res.headersSent) {
      res.status(500).send("Internal server error");
    }
  }
});

app.get("/health", (_req, res) => {
  res.json({
    ok: true,
    name: "job-assistant-test-runner-app",
    project_root: PROJECT_ROOT,
  });
});

app.listen(PORT, () => {
  console.log(
    `Job Assistant test runner app listening on http://127.0.0.1:${PORT}`
  );
  console.log(`MCP endpoint: http://127.0.0.1:${PORT}/mcp`);
});
