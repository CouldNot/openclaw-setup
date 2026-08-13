import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const SCRIPT = "__OPENCLAW_HOME__/.openclaw/workspace-personal/skills/second-brain/scripts/second_brain.py";
const OPENCLAW = "__OPENCLAW_HOME__/.openclaw/bin/openclaw";
// OpenClaw's reminder verifier associates the primary personal conversation
// with this canonical session. Discord delivery is configured separately.
const OWNER_SESSION = "agent:main:main";
const MAX_OUTPUT = 1024 * 1024;

async function scheduleReminder(item, signal) {
  const dueAt = item?.due_at;
  if (!item?.id || !dueAt) throw new Error("a reminder requires a persisted id and due time");
  const reminderText = item.summary || item.title;
  const args = ["cron", "add",
    "--declaration-key", `personal:active-reminder:${item.id}`,
    "--name", item.title,
    "--description", `Explicit reminder linked to active-state item ${item.id}.`,
    "--at", dueAt,
    "--agent", "main",
    "--session", "isolated",
    "--message", `Send __OWNER_NAME__ this scheduled reminder naturally and concisely: ${reminderText}. Do not schedule another reminder. Do not include metadata or a Markdown heading.`,
    "--thinking", "low",
    "--announce", "--channel", "discord", "--to", "user:__OWNER_DISCORD_ID__",
    "--best-effort-deliver", "--delete-after-run", "--json"];
  args.push("--session-key", OWNER_SESSION);
  const { stdout } = await execFileAsync(OPENCLAW, args, {
    timeout: 15000, maxBuffer: MAX_OUTPUT, signal,
    env: { PATH: "/usr/local/bin:/usr/bin:/bin", HOME: "__OPENCLAW_HOME__" }
  });
  return JSON.parse(stdout);
}

async function unscheduleReminders(ids, signal) {
  if (!ids?.length) return;
  const { stdout } = await execFileAsync(OPENCLAW, ["cron", "list", "--json"], {
    timeout: 15000, maxBuffer: MAX_OUTPUT, signal,
    env: { PATH: "/usr/local/bin:/usr/bin:/bin", HOME: "__OPENCLAW_HOME__" }
  });
  const jobs = JSON.parse(stdout)?.jobs ?? [];
  const keys = new Set(ids.map((id) => `personal:active-reminder:${id}`));
  for (const job of jobs) {
    if (job?.id && keys.has(job.declarationKey)) {
      await execFileAsync(OPENCLAW, ["cron", "rm", job.id], {
        timeout: 15000, maxBuffer: MAX_OUTPUT, signal,
        env: { PATH: "/usr/local/bin:/usr/bin:/bin", HOME: "__OPENCLAW_HOME__" }
      });
    }
  }
}

function result(value) {
  const text = JSON.stringify(value, null, 2);
  return { content: [{ type: "text", text }], details: value };
}

export default {
  id: "active-state",
  name: "Active State",
  description: "Structured retrieval for current and historical personal state",
  register(api) {
    api.registerTool({
      name: "active_state",
      label: "Active State",
      description: "Search, capture, update, or transition the owner's structured active state without Bash. Adding kind=reminder with dueAt atomically creates the actual Discord notification; do not create a separate cron job. Never claim a reminder exists unless this tool returns reminder_scheduled=true. For relative requests such as before my flight, first search with the simple entity kind (kind=flight, futureOnly=true); do not add guessed words that may not exist. Use update to attach timing to an existing item. When the owner says an item is done, cancelled, missed, or changed, call set with exact IDs and do not claim the change until it succeeds. Terminal transitions cancel pending check-ins. Deduplicate before add.",
      parameters: {
        type: "object",
        additionalProperties: false,
        required: ["action"],
        properties: {
          action: { type: "string", enum: ["search", "add", "update", "set"] },
          ids: { type: "array", items: { type: "string", pattern: "^act_[a-f0-9]+$" }, minItems: 1, maxItems: 50 },
          reason: { type: "string", maxLength: 500 },
          query: { type: "string", maxLength: 500 },
          futureOnly: { type: "boolean", default: false },
          historical: { type: "boolean", default: false },
          limit: { type: "integer", minimum: 1, maximum: 50, default: 10 },
          kind: { type: "string", maxLength: 64 },
          title: { type: "string", maxLength: 300 },
          summary: { type: "string", maxLength: 2000 },
          status: { type: "string", enum: ["tentative", "scheduled", "imminent", "awaiting_confirmation", "completed", "cancelled", "missed"] },
          startsAt: { type: "string", maxLength: 64 },
          dueAt: { type: "string", maxLength: 64 },
          endsAt: { type: "string", maxLength: 64 },
          reviewAt: { type: "string", maxLength: 64 },
          checkinAt: { type: "string", maxLength: 64 },
          checkinReason: { type: "string", maxLength: 500 },
          importance: { type: "number", minimum: 0, maximum: 1 },
          confidence: { type: "number", minimum: 0, maximum: 1 },
          sourceKind: { type: "string", maxLength: 64 },
          sourceRef: { type: "string", maxLength: 500 },
          topics: { type: "array", items: { type: "string", maxLength: 200 }, maxItems: 10 },
          archivePolicy: { type: "string", enum: ["episode", "retain", "discard"] }
        }
      },
      async execute(_toolCallId, params, signal) {
        let args;
        if (params.action === "search") {
          args = [SCRIPT, "active-list", "--limit", String(params.limit ?? 10)];
          if (params.query) args.push("--query", params.query);
          if (params.kind) args.push("--kind", params.kind);
          if (params.futureOnly) args.push("--future-only");
          if (params.historical) args.push("--historical");
        } else if (params.action === "add") {
          if (!params.kind || !params.title) throw new Error("kind and title are required for add");
          args = [SCRIPT, "active-add", "--kind", params.kind, "--title", params.title,
            "--status", params.status ?? (params.kind === "reminder" ? "scheduled" : "tentative"), "--importance", String(params.importance ?? 0.6),
            "--confidence", String(params.confidence ?? 0.9), "--source-kind", params.sourceKind ?? "user_statement",
            "--archive-policy", params.archivePolicy ?? "episode"];
          const options = [["summary", "--summary"], ["startsAt", "--starts-at"], ["dueAt", "--due-at"],
            ["endsAt", "--ends-at"], ["reviewAt", "--review-at"], ["checkinAt", "--checkin-at"],
            ["checkinReason", "--checkin-reason"], ["sourceRef", "--source-ref"]];
          for (const [key, flag] of options) if (params[key]) args.push(flag, params[key]);
          for (const topic of params.topics ?? []) args.push("--topic", topic);
        } else if (params.action === "update") {
          if (!params.ids?.length || !params.reason) throw new Error("ids and reason are required for update");
          args = [SCRIPT, "active-update", "--ids", ...params.ids, "--reason", params.reason];
          const fields = [["title", "--title"], ["summary", "--summary"], ["startsAt", "--starts-at"],
            ["dueAt", "--due-at"], ["endsAt", "--ends-at"], ["reviewAt", "--review-at"],
            ["checkinAt", "--checkin-at"], ["checkinReason", "--checkin-reason"]];
          for (const [key, flag] of fields) if (params[key] !== undefined) args.push(flag, params[key]);
        } else {
          if (!params.ids?.length || !params.status || !params.reason) {
            throw new Error("ids, status, and reason are required for set");
          }
          args = [SCRIPT, "active-set", "--ids", ...params.ids, "--status", params.status, "--reason", params.reason];
        }
        const { stdout } = await execFileAsync("/usr/bin/python3", args, {
          timeout: 15000,
          maxBuffer: MAX_OUTPUT,
          signal,
          env: {
            PATH: "/usr/local/bin:/usr/bin:/bin",
            HOME: "__OPENCLAW_HOME__"
          }
        });
        const value = JSON.parse(stdout);
        if (params.action === "set" && ["completed", "cancelled", "missed"].includes(params.status)) {
          await unscheduleReminders(params.ids, signal);
        }
        if (params.action === "add" && params.kind === "reminder") {
          if (!params.dueAt) throw new Error("dueAt is required when adding a reminder");
          try {
            const scheduled = await scheduleReminder(value, signal);
            value.reminder_scheduled = true;
            value.reminder_job_id = scheduled.id ?? scheduled.job?.id ?? null;
          } catch (error) {
            if (value?.id) {
              await execFileAsync("/usr/bin/python3", [SCRIPT, "active-set", "--ids", value.id,
                "--status", "cancelled", "--reason", "Automatic reminder scheduling failed"], {
                timeout: 15000, maxBuffer: MAX_OUTPUT,
                env: { PATH: "/usr/local/bin:/usr/bin:/bin", HOME: "__OPENCLAW_HOME__" }
              }).catch(() => {});
            }
            throw new Error(`Reminder was not scheduled: ${String(error)}`);
          }
        }
        return result(value);
      }
    }, { name: "active_state" });
  }
};
