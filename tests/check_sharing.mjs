import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const mode = process.argv[2];
const baseUrl = process.argv[3];
const suppliedValue = process.argv[4] || "";
const chromePath = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const profilePath = fs.mkdtempSync(path.join(os.tmpdir(), "laysh-share-chrome-"));
const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function freePort() {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${response.status} ${url}`);
  return await response.json();
}

const debuggingPort = await freePort();
const chrome = spawn(chromePath, [
  "--headless=new",
  "--disable-gpu",
  "--no-first-run",
  "--no-default-browser-check",
  `--remote-debugging-port=${debuggingPort}`,
  `--user-data-dir=${profilePath}`,
  "about:blank",
], { stdio: "ignore" });

let socket;
try {
  let version;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      version = await fetchJson(`http://127.0.0.1:${debuggingPort}/json/version`);
      break;
    } catch {
      await delay(50);
    }
  }
  if (!version) throw new Error("Chrome debugging endpoint did not start");
  const target = await fetchJson(
    `http://127.0.0.1:${debuggingPort}/json/new?${encodeURIComponent("about:blank")}`,
    { method: "PUT" },
  );
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });

  let nextId = 1;
  const pending = new Map();
  const consoleErrors = [];
  const networkFailures = [];
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const waiter = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) waiter.reject(new Error(message.error.message));
      else waiter.resolve(message.result);
      return;
    }
    if (message.method === "Runtime.exceptionThrown") {
      consoleErrors.push(message.params.exceptionDetails.text || "runtime exception");
    }
    if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
      consoleErrors.push(message.params.entry.text);
    }
    if (
      message.method === "Network.loadingFailed"
      && ["Document", "Script", "Stylesheet", "Font"].includes(message.params.type)
      && message.params.errorText !== "net::ERR_ABORTED"
    ) {
      networkFailures.push(`${message.params.type}:${message.params.errorText}`);
    }
  });

  function command(method, params = {}) {
    const id = nextId;
    nextId += 1;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async function evaluate(expression) {
    const response = await command("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.text || "evaluation failed");
    return response.result.value;
  }

  async function waitFor(expression, timeout = 15000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (await evaluate(expression)) return;
      await delay(100);
    }
    throw new Error(`Timed out waiting for: ${expression}`);
  }

  async function navigate(url) {
    await command("Page.navigate", { url });
    await waitFor("document.readyState === 'complete'", 10000);
  }

  async function pressEnter() {
    await command("Input.dispatchKeyEvent", {
      type: "keyDown",
      key: "Enter",
      code: "Enter",
      text: "\r",
      unmodifiedText: "\r",
      windowsVirtualKeyCode: 13,
      nativeVirtualKeyCode: 13,
    });
    await command("Input.dispatchKeyEvent", {
      type: "keyUp",
      key: "Enter",
      code: "Enter",
      windowsVirtualKeyCode: 13,
      nativeVirtualKeyCode: 13,
    });
  }

  await command("Runtime.enable");
  await command("Page.enable");
  await command("Network.enable");
  await command("Log.enable");

  if (mode === "create") {
    await command("Browser.grantPermissions", {
      origin: baseUrl,
      permissions: ["clipboardReadWrite", "clipboardSanitizedWrite"],
    });
    await navigate(`${baseUrl}/`);
    await evaluate(`(() => {
      const field = document.querySelector('#question');
      field.value = 'success private-browser-question-7391';
      document.querySelector('#ask-form').requestSubmit();
    })()`);
    await waitFor("!document.querySelector('#result-view').hidden", 20000);
    await evaluate(`(() => {
      window.__shareKeyEvents = [];
      const button = document.querySelector('#share-result');
      button.addEventListener('keydown', (event) => window.__shareKeyEvents.push({
        key: event.key,
        code: event.code,
        trusted: event.isTrusted,
      }));
      button.focus();
    })()`);
    await pressEnter();
    try {
      await waitFor("document.querySelector('#share-status').textContent.includes('نُسخ رابط')");
    } catch (error) {
      const diagnostics = await evaluate(`({
        activeId: document.activeElement?.id,
        buttonDisabled: document.querySelector('#share-result')?.disabled,
        feedback: document.querySelector('#share-status')?.textContent,
        shareUrl: document.querySelector('#share-result')?.dataset.shareUrl || null,
        clipboardAvailable: Boolean(navigator.clipboard?.writeText),
        keyEvents: window.__shareKeyEvents,
      })`);
      throw new Error(`${error.message}; diagnostics=${JSON.stringify(diagnostics)}`);
    }
    const copiedUrl = await evaluate("navigator.clipboard.readText()");
    const arabicFeedback = await evaluate("document.querySelector('#share-status').textContent");
    const keyboardActivated = await evaluate(
      "(async () => document.querySelector('#share-result').dataset.shareUrl === await navigator.clipboard.readText())()",
    );
    await evaluate("document.querySelector('#locale-control').click()");
    await waitFor("document.documentElement.lang === 'en'");
    await evaluate(`Object.defineProperty(navigator.clipboard, 'writeText', {
      configurable: true,
      value: async () => { throw new Error('clipboard denied'); },
    })`);
    await evaluate("document.querySelector('#share-result').focus()");
    await pressEnter();
    await waitFor("document.querySelector('#share-status').textContent.includes('Could not copy')");
    const englishFailure = await evaluate("document.querySelector('#share-status').textContent");
    process.stdout.write(JSON.stringify({
      copiedUrl,
      keyboardActivated,
      arabicFeedback,
      englishFailure,
      sharePath: new URL(copiedUrl).pathname,
    }));
  } else if (mode === "recover") {
    await navigate(suppliedValue);
    await waitFor("typeof window.LayshSimulation === 'object'", 10000);
    const evidence = await evaluate(`({
      artifactReady: typeof window.LayshSimulation?.init === 'function',
      scientificCanvas: Boolean(document.querySelector('#simulation')),
      rawQuestionAbsent: !location.href.includes('private-browser-question-7391')
        && !document.body.textContent.includes('private-browser-question-7391'),
    })`);
    process.stdout.write(JSON.stringify({ ...evidence, consoleErrors, networkFailures }));
  } else {
    throw new Error(`unsupported mode: ${mode}`);
  }
} finally {
  socket?.close();
  chrome.kill("SIGTERM");
}
