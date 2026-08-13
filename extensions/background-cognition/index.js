import { appendFile, mkdir, readFile } from "node:fs/promises";
import { dirname } from "node:path";

const DEFAULT_QUEUE = "__OPENCLAW_HOME__/.openclaw/workspace-personal/memory/knowledge/cognition-queue.jsonl";
const WARNING_PREFIX = "⚠️ 🛠️ ";
const successfulRuns = new Map();
const OWNER_DM = "agent:main:discord:default:direct:__OWNER_DISCORD_ID__";
const OWNER_ID = "__OWNER_DISCORD_ID__";
const pendingStatuses = new Map();
const STATUS_TIMEOUT_MS = 4200;
const STATUS_WORK_GRACE_MS = 1800;
const OPENCLAW_DIST = "__OPENCLAW_HOME__/.openclaw/tools/node-v24.15.0/lib/node_modules/openclaw/dist";
const OPENCLAW_AGENT_DIR = "__OPENCLAW_HOME__/.openclaw/agents/main/agent";
const STATUS_INSTRUCTIONS = `Write one short, natural acknowledgement to __OWNER_NAME__ while the main assistant performs real tool-backed work. Sound like a capable, familiar personal secretary.
For an ordinary request, respond with a simple conversational variation of acknowledging it and asking for a moment. Do not repeat or paraphrase the request merely to appear personalized.
Mention its subject only when that makes the acknowledgement clearer, more reassuring, or less ambiguous. Personalize selectively, not by default.
Stay neutral about how the request will be handled. Do not claim a particular source or operation unless __OWNER_NAME__ explicitly requested it.
Never answer the request, confirm or deny a fact, state a result, or imply that the work is complete. Do not invent a plan. Do not mention tools, plugins, models, routing, memory systems, or internal mechanics.
Use no markdown. Output exactly one brief sentence. Vary acknowledgement wording naturally and avoid sounding theatrical, overly eager, formal, or repetitive.`;

class StatusSidecar {
  constructor(logger) {
    this.logger = logger;
    this.client = null;
    this.turns = new Map();
    this.earlyCompletions = new Map();
    this.ready = null;
  }

  async start() {
    if (this.ready) return this.ready;
    this.ready = (async () => {
      const [{ a: createIsolatedCodexAppServerClient }, rawConfig] = await Promise.all([
        import(`${OPENCLAW_DIST}/shared-client-DvwsvGGC.js`),
        readFile("__OPENCLAW_HOME__/.openclaw/openclaw.json", "utf8")
      ]);
      const client = await createIsolatedCodexAppServerClient({
        agentDir: OPENCLAW_AGENT_DIR,
        config: JSON.parse(rawConfig),
        timeoutMs: 10000,
        startOptions: {
          transport: "stdio",
          commandSource: "custom",
          command: "__OPENCLAW_HOME__/.openclaw/tools/codex-0.147.0",
          args: [
            "app-server", "--stdio",
            "-c", 'model="gpt-5.6-luna"',
            "-c", 'model_reasoning_effort="none"',
            "-c", 'model_reasoning_summary="none"'
          ]
        }
      });
      this.client = client;
      client.addNotificationHandler((message) => this.onMessage(message));
      client.addCloseHandler((error) => {
        for (const waiter of this.turns.values()) waiter.reject(error);
        this.turns.clear();
        this.earlyCompletions.clear();
        this.client = null;
        this.ready = null;
      });
    })();
    return this.ready;
  }

  onMessage(message) {
    if (message.method === "item/completed" && message.params?.item?.type === "agentMessage") {
      const waiter = this.turns.get(message.params.turnId);
      if (waiter) {
        this.turns.delete(message.params.turnId);
        waiter.resolve(message.params.item.text);
      } else {
        this.earlyCompletions.set(message.params.turnId, message.params.item.text);
      }
    }
  }

  request(method, params) {
    if (!this.client) return Promise.reject(new Error("status sidecar unavailable"));
    return this.client.request(method, params);
  }

  async generate(userText) {
    await this.start();
    const thread = await this.request("thread/start", {
      model: "gpt-5.6-luna",
      cwd: "/tmp",
      ephemeral: true,
      approvalPolicy: "never",
      sandbox: "read-only",
      baseInstructions: STATUS_INSTRUCTIONS
    });
    const started = await this.request("turn/start", {
      threadId: thread.thread.id,
      effort: "none",
      summary: "none",
      input: [{ type: "text", text: userText }]
    });
    if (this.earlyCompletions.has(started.turn.id)) {
      const text = this.earlyCompletions.get(started.turn.id);
      this.earlyCompletions.delete(started.turn.id);
      return text;
    }
    return new Promise((resolve, reject) => this.turns.set(started.turn.id, { resolve, reject }));
  }
}

const RETRIEVAL_POLICY = `Retrieval evidence policy for __OWNER_NAME__'s assistant:
- If an answer depends on current or external information, stored personal state, email, calendar, files, documents, or another source outside the visible chat, actually use the appropriate tool before answering.
- Never say you retrieved, checked, searched, found, or could not access something unless a real tool attempt occurred in this turn.
- Never substitute remembered or previously seen time-sensitive information and present it as current.
- Return one natural substantive answer through the normal conversation reply. Do not prepend a progress sentence such as “I'm checking now,” do not use the message tool merely for progress, and do not expose tool names or internal mechanics.`;

function textOf(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content.filter((part) => part && part.type === "text" && typeof part.text === "string")
    .map((part) => part.text).join("\n");
}

function cleanupRuns(now = Date.now()) {
  for (const [key, seen] of successfulRuns) if (now - seen > 120000) successfulRuns.delete(key);
}

function worthwhile(text, minimum) {
  const value = text.trim();
  if (value.length < minimum) return false;
  return !/^(ok(?:ay)?|thanks?|thank you|cool|nice|great|lol|yes|no|yep|nope|sure|done|finished)[.! ]*$/i.test(value);
}

function pendingStatus(ctx = {}) {
  const direct = pendingStatuses.get(ctx.runId) ?? pendingStatuses.get(ctx.sessionKey);
  if (direct) return direct;
  const now = Date.now();
  return [...pendingStatuses.values()].reverse().find((state) => now - state.createdAt < 120000);
}

async function discordToken() {
  const raw = await readFile("__OPENCLAW_HOME__/.openclaw/openclaw.json", "utf8");
  const token = JSON.parse(raw)?.channels?.discord?.token;
  return typeof token === "string" && token ? token : null;
}

async function discordRequest(token, path, init = {}) {
  return fetch(`https://discord.com/api/v10${path}`, {
    ...init,
    headers: { Authorization: `Bot ${token}`, "Content-Type": "application/json", ...(init.headers ?? {}) }
  });
}

async function createStatus(sessionKey, content) {
  const token = await discordToken();
  if (!token) return;
  const dm = await discordRequest(token, "/users/@me/channels", {
    method: "POST", body: JSON.stringify({ recipient_id: OWNER_ID })
  });
  if (!dm.ok) return;
  const channel = await dm.json();
  const sent = await discordRequest(token, `/channels/${channel.id}/messages`, {
    method: "POST", body: JSON.stringify({ content })
  });
  if (!sent.ok) return;
  const message = await sent.json();
  const state = pendingStatuses.get(sessionKey);
  if (!state || state.cancelled) {
    await discordRequest(token, `/channels/${channel.id}/messages/${message.id}`, { method: "DELETE" });
    return;
  }
  state.channelId = channel.id;
  state.messageId = message.id;
}

async function clearStatus(sessionKey) {
  const state = pendingStatuses.get(sessionKey);
  if (!state) return;
  state.cancelled = true;
  clearTimeout(state.workTimer);
  pendingStatuses.delete(sessionKey);
}

export default {
  id: "background-cognition",
  name: "Background Cognition",
  description: "Non-blocking post-response cognition and recovered-warning filtering",
  register(api) {
    const config = api.pluginConfig ?? {};
    const queuePath = config.queuePath ?? DEFAULT_QUEUE;
    const minimumUserChars = config.minimumUserChars ?? 12;
    const statusSidecar = new StatusSidecar(api.logger);
    void statusSidecar.start().catch((error) => {
      api.logger.warn?.(`background-cognition: status sidecar prewarm failed: ${String(error)}`);
    });

    async function personalizedStatus(text) {
      let timer;
      try {
        const timeout = new Promise((_, reject) => {
          timer = setTimeout(() => reject(new Error("status generation timed out")), STATUS_TIMEOUT_MS);
        });
        const generated = (await Promise.race([statusSidecar.generate(text), timeout]))?.trim();
        if (generated && generated.length <= 220) return generated;
      } catch (error) {
        api.logger.warn?.(`background-cognition: personalized status fallback: ${String(error)}`);
      } finally {
        clearTimeout(timer);
      }
      return null;
    }

    api.on("message_received", async (event, ctx) => {
      const sessionKey = event.sessionKey ?? ctx.sessionKey ?? "";
      const statusKey = event.runId ?? ctx.runId ?? sessionKey;
      const senderId = event.senderId ?? ctx.senderId ?? "";
      if (!statusKey || senderId !== OWNER_ID || !event.content?.trim() || event.content.trim().startsWith("/")) return;
      await clearStatus(statusKey);
      const state = {
        key: statusKey, createdAt: Date.now(), cancelled: false, workStarted: false,
        channelId: null, messageId: null, workTimer: null,
        content: personalizedStatus(event.content)
      };
      pendingStatuses.set(statusKey, state);
      api.logger.info?.(`background-cognition: acknowledgement candidate queued for ${statusKey}`);
    }, { priority: 1000 });

    api.on("before_tool_call", async (_event, ctx) => {
      if ((ctx.sessionKey ?? "").includes("background-cognition")) return;
      const state = pendingStatus(ctx);
      if (!state || state.cancelled || state.workStarted) return;
      state.workStarted = true;
      state.workTimer = setTimeout(() => {
        if (state.cancelled || state.messageId) return;
        void state.content
          .then((content) => content && !state.cancelled ? createStatus(state.key, content) : undefined)
          .catch((error) => api.logger.warn?.(`background-cognition: status send failed: ${String(error)}`));
      }, STATUS_WORK_GRACE_MS);
      api.logger.info?.(`background-cognition: tool-backed acknowledgement armed for ${state.key}`);
    }, { priority: 1000 });

    api.on("reply_payload_sending", async (event, ctx) => {
      cleanupRuns();
      const status = pendingStatus({ runId: event.runId ?? ctx.runId, sessionKey: ctx.sessionKey });
      if (status) await clearStatus(status.key);
      const runId = event.runId ?? ctx.runId;
      const text = event.payload?.text?.trim() ?? "";
      const warning = text.startsWith(WARNING_PREFIX);
      if (warning && runId && successfulRuns.has(runId)) {
        api.logger.info?.(`background-cognition: suppressed recovered tool warning for ${runId}`);
        return { cancel: true, reason: "recovered_tool_failure" };
      }
      if (runId && !warning && event.payload?.isError !== true && text) {
        successfulRuns.set(runId, Date.now());
      }
    }, { priority: 1000 });

    api.on("before_prompt_build", async (_event, ctx) => {
      const sessionKey = ctx.sessionKey ?? "";
      if (sessionKey !== OWNER_DM || ctx.jobId || ctx.trigger === "cron") return;
      return { appendSystemContext: RETRIEVAL_POLICY };
    }, { priority: 900 });

    api.on("agent_end", async (event, ctx) => {
      const status = pendingStatus({ runId: event.runId ?? ctx.runId, sessionKey: ctx.sessionKey });
      if (status) await clearStatus(status.key);
      if (!event.success || ctx.jobId || ctx.trigger === "cron") return;
      const sessionKey = ctx.sessionKey ?? "";
      if (sessionKey.includes("background-cognition")) return;
      const messages = Array.isArray(event.messages) ? event.messages : [];
      let user = "";
      let assistant = "";
      for (let i = messages.length - 1; i >= 0 && (!user || !assistant); i--) {
        const message = messages[i] ?? {};
        if (!assistant && message.role === "assistant") assistant = textOf(message.content);
        if (!user && message.role === "user") user = textOf(message.content);
      }
      if (!worthwhile(user, minimumUserChars) || !assistant.trim()) return;
      const record = {
        v: 1,
        id: event.runId ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        queuedAt: new Date().toISOString(),
        sessionKey,
        channel: ctx.channel ?? ctx.messageProvider ?? null,
        user: user.slice(0, 12000),
        assistant: assistant.slice(0, 12000)
      };
      await mkdir(dirname(queuePath), { recursive: true });
      await appendFile(queuePath, `${JSON.stringify(record)}\n`, { encoding: "utf8", mode: 0o600 });
    });
  }
};
