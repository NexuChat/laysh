(() => {
  "use strict";

  const t = (key, values) => window.LayshLocale.t(key, values);
  let currentLocale = window.LayshLocale.current();
  let number = new Intl.NumberFormat(currentLocale, { maximumFractionDigits: 0 });
  const safeExamples = () => [
    t("ask.example"),
    t("ask.example.1"),
    t("ask.example.2"),
    t("ask.example.3"),
  ];
  const state = {
    view: "ask",
    jobId: null,
    streamUrl: null,
    resultUrl: null,
    lastEventId: 0,
    startedAt: 0,
    lastEventAt: 0,
    streamController: null,
    timer: null,
    watchdog: null,
    reconnectAttempt: 0,
    terminal: false,
    answer: null,
    formula: null,
    lastQuestion: "",
    result: null,
    connectionKey: null,
    failure: null,
  };

  const byId = (id) => document.getElementById(id);
  const views = [...document.querySelectorAll("[data-view]")];
  const stageLabelKeys = {
    filtering: "stage.filtering",
    understanding: "stage.understanding",
    cache_lookup: "stage.cache_lookup",
    generating: "stage.generating",
    verifying: "stage.verifying",
    healing: "stage.healing",
    qa: "stage.qa",
    qa_retry: "stage.qa_retry",
    browser_check: "stage.browser_check",
    complete: "stage.complete",
  };
  const stageDetailKeys = {
    filtering: "stage.detail.filtering",
    understanding: "stage.detail.understanding",
    cache_lookup: "stage.detail.cache_lookup",
    generating: "stage.detail.generating",
    verifying: "stage.detail.verifying",
    fixture_refresh: "stage.detail.fixture_refresh",
    healing: "stage.detail.healing",
    qa: "stage.detail.qa",
    qa_retry: "stage.detail.qa_retry",
    browser_check: "stage.detail.browser_check",
    complete: "stage.detail.complete",
  };
  const gateLabelKeys = {
    closed_schema: "gate.closed_schema",
    restricted_source: "gate.restricted_source",
    node_runtime: "gate.node_runtime",
    fixtures: "gate.fixtures",
    browser_readiness: "gate.browser_readiness",
    verified_cache: "gate.verified_cache",
    artifact_hash: "gate.artifact_hash",
    interface: "gate.interface",
    security: "gate.security",
    invariant: "gate.invariant",
    formula_presentation: "gate.formula_presentation",
    fixture_integrity: "gate.fixture_integrity",
  };

  const failureReasons = new Set([
    "not_simulatable",
    "qa_inconclusive",
    "verification_exhausted",
    "generation_failed",
    "simulation_runtime_error",
    "backend_unavailable",
    "cancelled",
    "timed_out",
    "unsafe_redirect",
  ]);
  const failureSymbols = {
    not_simulatable: "؟",
    qa_inconclusive: "…",
    verification_exhausted: "×",
    generation_failed: "↺",
    simulation_runtime_error: "!",
    backend_unavailable: "⌁",
    cancelled: "■",
    timed_out: "⌛",
    unsafe_redirect: "↗",
  };

  function localizedFailure(reason) {
    const selected = failureReasons.has(reason) ? reason : "generation_failed";
    return {
      reason: selected,
      eyebrow: t(`failure.${selected}.eyebrow`),
      title: t(`failure.${selected}.title`),
      copy: t(`failure.${selected}.copy`),
      symbol: failureSymbols[selected],
    };
  }

  function setView(name, { push = false } = {}) {
    state.view = name;
    for (const view of views) view.hidden = view.dataset.view !== name;
    if (push) history.pushState({ view: name }, "", `#${name}`);
    const target = document.querySelector(`[data-view="${name}"] h1, [data-view="${name}"] h2`);
    requestAnimationFrame(() => (target || byId("main-content")).focus?.({ preventScroll: true }));
    window.scrollTo({ top: 0, behavior: "auto" });
  }

  function formatElapsed(milliseconds) {
    const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = String(totalSeconds % 60).padStart(2, "0");
    const zero = currentLocale === "ar" ? "٠" : "0";
    return `${number.format(minutes)}:${number.format(Number(seconds)).padStart(2, zero)}`;
  }

  function setConnection(key, mode = "working") {
    state.connectionKey = key;
    byId("connection-copy").textContent = t(key);
    byId("connection-state").dataset.mode = mode;
  }

  function startClock() {
    clearInterval(state.timer);
    state.timer = setInterval(() => {
      if (!state.startedAt || state.terminal) return;
      const elapsed = Date.now() - state.startedAt;
      byId("elapsed").textContent = formatElapsed(elapsed);
      byId("elapsed").dateTime = `PT${Math.floor(elapsed / 1000)}S`;
      if (elapsed >= 180_000) {
        state.terminal = true;
        state.streamController?.abort();
        showFailure("timed_out");
      } else if (elapsed >= 90_000) {
        setConnection("connection.stillTesting", "still-testing");
      }
    }, 1000);
  }

  function addStage(payload) {
    const item = document.createElement("li");
    const name = document.createElement("strong");
    const detail = document.createElement("span");
    const time = document.createElement("span");
    item.dataset.stage = payload.stage;
    item.dataset.elapsedMs = String(payload.elapsed_ms);
    name.className = "stage-name";
    name.textContent = t(stageLabelKeys[payload.stage] || "build.genericStage");
    detail.textContent = currentLocale === "ar"
      ? payload.detail
      : t(stageDetailKeys[payload.stage] || "build.genericDetail");
    time.className = "stage-time";
    time.textContent = t("build.seconds", { value: number.format(payload.elapsed_ms / 1000) });
    item.append(name, detail, time);
    byId("stage-list").append(item);
    if (payload.stage === "healing") byId("heal-act").hidden = false;
    setConnection("connection.progress", "working");
  }

  function pinAnswer(payload) {
    state.answer = payload.tldr;
    state.formula = payload.key_formula;
    byId("answer-copy").textContent = payload.tldr;
    byId("answer-formula").textContent = payload.key_formula || "";
    byId("answer-formula").hidden = !payload.key_formula;
    byId("answer-card").hidden = false;
    byId("domain-fact-copy").textContent = state.answer;
    byId("domain-fact").hidden = false;
  }

  function showVerification(payload) {
    const box = byId("verification-summary");
    box.hidden = false;
    byId("verification-title").textContent = t(
      payload.passed ? "verification.passed" : "verification.failed",
    );
    byId("verification-copy").textContent = t("verification.summary", {
      checks: number.format(payload.check_count),
      heals: number.format(payload.heal_count),
    });
    const grid = byId("verification-grid");
    grid.replaceChildren();
    for (const [index, gate] of payload.evidence.entries()) {
      const chip = document.createElement("span");
      chip.className = `verification-chip ${payload.passed ? "passed" : "failed"}`;
      chip.textContent = `${payload.passed ? "✓" : "!"} ${t(gateLabelKeys[gate] || gate)}`;
      grid.append(chip);
      setTimeout(() => chip.classList.add("visible"), Math.min(index * 90, 720));
    }
  }

  function normalizedReason(reason, status) {
    if (status === "rejected") return "unsafe_redirect";
    if (["failed", "answer_only"].includes(status) && !failureReasons.has(reason)) return "generation_failed";
    return failureReasons.has(reason) ? reason : "generation_failed";
  }

  function showFailure(reason, suggestions = []) {
    state.terminal = true;
    state.streamController?.abort();
    clearInterval(state.timer);
    clearInterval(state.watchdog);
    const selected = localizedFailure(reason);
    state.failure = { reason: selected.reason, suggestions };
    byId("failure-eyebrow").textContent = selected.eyebrow;
    byId("failure-title").textContent = selected.title;
    byId("failure-copy").textContent = selected.copy;
    byId("failure-symbol").textContent = selected.symbol;
    byId("preserved-answer").hidden = !state.answer;
    byId("preserved-answer").textContent = state.answer || "";
    const list = byId("suggestion-list");
    list.replaceChildren();
    for (const suggestion of suggestions.slice(0, 3)) {
      const item = document.createElement("li");
      item.textContent = suggestion;
      list.append(item);
    }
    setView("failure", { push: true });
  }

  function displayResult(result) {
    if (result.status !== "complete" || !result.simulation) {
      const reason = normalizedReason(result.fallback?.reason_code, result.status);
      showFailure(reason, result.fallback?.suggestions || []);
      return;
    }
    state.result = result;
    state.terminal = true;
    state.streamController?.abort();
    clearInterval(state.timer);
    clearInterval(state.watchdog);
    const simulation = result.simulation;
    byId("result-title").textContent = simulation.title;
    byId("result-answer").textContent = state.answer || result.answer?.tldr || "";
    byId("simulation-alternative").textContent = state.answer || t("result.alternativeShort");
    const simulationFrame = byId("simulation-frame");
    simulationFrame.hidden = false;
    simulationFrame.style.removeProperty("height");
    delete simulationFrame.dataset.contentHeight;
    simulationFrame.src = `${simulation.artifact_url}?inline=1`;
    byId("download").href = simulation.artifact_url;
    byId("receipt-tier").textContent = t(simulation.tier === "A" ? "result.tierA" : "result.tierB");
    byId("tier-badge").textContent = t(
      simulation.tier === "A" ? "result.humanBadge" : "result.autoBadge",
    );
    byId("check-count").textContent = number.format(simulation.check_count);
    byId("heal-count").textContent = number.format(simulation.heal_count);
    byId("result-elapsed").textContent = t("result.seconds", {
      value: number.format(simulation.elapsed_ms / 1000),
    });
    byId("effective-model").textContent = simulation.effective_model;
    setView("result", { push: true });
  }

  async function loadResult() {
    const response = await fetch(state.resultUrl, { headers: { accept: "application/json" } });
    if (!response.ok) throw new Error("result_unavailable");
    displayResult(await response.json());
  }

  async function loadGolden(goldenId) {
    const response = await fetch(
      `/api/gallery/${encodeURIComponent(goldenId)}?locale=${currentLocale}`,
      {
      headers: { accept: "application/json" },
      },
    );
    if (!response.ok) throw new Error("golden_unavailable");
    const golden = await response.json();
    pinAnswer(golden.answer);
    displayResult({ status: "complete", answer: golden.answer, simulation: golden.simulation });
  }

  async function hydrateGallery() {
    try {
      const response = await fetch(`/api/gallery?locale=${currentLocale}`, {
        headers: { accept: "application/json" },
      });
      if (!response.ok) return;
      const gallery = await response.json();
      for (const lesson of gallery.lessons) {
        const card = document.querySelector(`[data-golden-id="${lesson.id}"]`);
        if (!card || !lesson.instant) continue;
        card.querySelector("h3").textContent = lesson.title;
        card.querySelector(".card-domain").textContent = lesson.domain;
        const badge = card.querySelector(".coming-badge");
        badge.className = "instant-badge";
        badge.textContent = t("gallery.instant");
        const launch = card.querySelector(".golden-launch");
        launch.disabled = false;
        launch.onclick = () => {
          loadGolden(lesson.id).catch(() => showFailure("backend_unavailable"));
        };
      }
    } catch {
      // Honest placeholders remain visible when the gallery endpoint is unavailable.
    }
  }

  function parseSseBlock(block) {
    const event = { type: "message", id: null, data: "" };
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event.type = line.slice(6).trim();
      if (line.startsWith("id:")) event.id = Number(line.slice(3).trim());
      if (line.startsWith("data:")) event.data += line.slice(5).trim();
    }
    return event.data ? event : null;
  }

  async function handleEvent(event) {
    state.lastEventAt = Date.now();
    state.reconnectAttempt = 0;
    if (event.id) state.lastEventId = Math.max(state.lastEventId, event.id);
    const message = JSON.parse(event.data);
    if (event.type === "answer") pinAnswer(message.payload);
    if (event.type === "stage") addStage(message.payload);
    if (event.type === "heartbeat") setConnection("connection.stable", "working");
    if (event.type === "verification") showVerification(message.payload);
    if (event.type === "fallback") showFailure(normalizedReason(message.payload.reason_code, "answer_only"), message.payload.suggestions);
    if (event.type === "terminal") showFailure(normalizedReason(message.payload.reason_code, message.payload.status));
    if (event.type === "result") await loadResult();
  }

  async function connectStream() {
    if (state.terminal || !state.streamUrl) return;
    state.streamController?.abort();
    const controller = new AbortController();
    state.streamController = controller;
    const headers = { accept: "text/event-stream" };
    if (state.lastEventId) headers["Last-Event-ID"] = String(state.lastEventId);
    try {
      const response = await fetch(state.streamUrl, { headers, signal: controller.signal });
      if (!response.ok || !response.body) throw new Error("stream_unavailable");
      setConnection("connection.stable", "working");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!state.terminal) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replaceAll("\r\n", "\n");
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          const event = parseSseBlock(block);
          if (event) await handleEvent(event);
        }
      }
      if (!state.terminal) scheduleReconnect();
    } catch (error) {
      if (!state.terminal && error.name !== "AbortError") scheduleReconnect();
    }
  }

  function scheduleReconnect() {
    if (state.terminal) return;
    state.reconnectAttempt += 1;
    if (state.reconnectAttempt > 3) {
      showFailure("backend_unavailable");
      return;
    }
    setConnection("connection.reconnecting", "reconnecting");
    const delays = [1200, 2500, 5000];
    setTimeout(connectStream, delays[state.reconnectAttempt - 1]);
  }

  function startWatchdog() {
    clearInterval(state.watchdog);
    state.watchdog = setInterval(() => {
      if (!state.terminal && Date.now() - state.lastEventAt > 15_000) {
        state.streamController?.abort();
        scheduleReconnect();
      }
    }, 5000);
  }

  async function submitQuestion(question) {
    state.terminal = false;
    state.jobId = null;
    state.lastEventId = 0;
    state.answer = null;
    state.formula = null;
    state.result = null;
    state.lastQuestion = question;
    state.startedAt = Date.now();
    state.lastEventAt = Date.now();
    byId("answer-card").hidden = true;
    byId("stage-list").replaceChildren();
    byId("verification-summary").hidden = true;
    byId("verification-grid").replaceChildren();
    byId("domain-fact").hidden = true;
    byId("heal-act").hidden = true;
    byId("elapsed").textContent = currentLocale === "ar" ? "٠:٠٠" : "0:00";
    setConnection("connection.queued", "queued");
    setView("build", { push: true });
    startClock();
    try {
      const response = await fetch("/api/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question, locale: currentLocale }),
      });
      if (!response.ok) throw new Error("ask_unavailable");
      const accepted = await response.json();
      state.jobId = accepted.job_id;
      state.streamUrl = accepted.stream_url;
      state.resultUrl = accepted.result_url;
      startWatchdog();
      await connectStream();
    } catch (error) {
      if (!state.terminal && error.name !== "AbortError") showFailure("backend_unavailable");
    }
  }

  byId("ask-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const question = byId("question").value.trim();
    if (!question) {
      byId("question-error").hidden = false;
      byId("question-error").textContent = t("ask.required");
      byId("question").setAttribute("aria-invalid", "true");
      byId("question").focus();
      return;
    }
    byId("question-error").hidden = true;
    byId("question").removeAttribute("aria-invalid");
    submitQuestion(question);
  });

  let exampleIndex = 0;
  byId("safe-example").addEventListener("click", () => {
    byId("question").value = byId("safe-example").textContent;
    byId("question").focus();
  });
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
    setInterval(() => {
      exampleIndex = (exampleIndex + 1) % safeExamples().length;
      byId("safe-example").textContent = safeExamples()[exampleIndex];
    }, 5000);
  }

  byId("cancel-action").addEventListener("click", async () => {
    setConnection("connection.cancelling", "cancelling");
    if (state.jobId) await fetch(`/api/jobs/${state.jobId}/cancel`, { method: "POST" }).catch(() => {});
    showFailure("cancelled");
  });
  byId("back-action").addEventListener("click", () => history.back());
  byId("retry-action").addEventListener("click", () => {
    if (state.lastQuestion) submitQuestion(state.lastQuestion);
    else setView("ask", { push: true });
  });
  byId("gallery-action").addEventListener("click", () => {
    setView("ask", { push: true });
    byId("gallery").scrollIntoView({ block: "start" });
  });
  for (const id of ["ask-another", "ask-another-top"]) {
    byId(id).addEventListener("click", () => setView("ask", { push: true }));
  }
  byId("replay-result").addEventListener("click", () => {
    const frame = byId("simulation-frame");
    frame.src = frame.src;
    frame.focus();
  });
  byId("projector-result").addEventListener("click", async () => {
    const frame = byId("simulation-frame");
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await frame.requestFullscreen();
    } catch {
      frame.scrollIntoView({ block: "center" });
      frame.focus();
    }
  });

  window.addEventListener("popstate", (event) => setView(event.state?.view || "ask"));
  window.addEventListener("offline", () => {
    if (state.terminal || !state.streamUrl) return;
    state.streamController?.abort();
    setConnection("connection.reconnecting", "reconnecting");
  });
  window.addEventListener("online", () => {
    if (state.terminal || !state.streamUrl) return;
    state.reconnectAttempt = 0;
    connectStream();
  });
  window.addEventListener("message", (event) => {
    const frame = byId("simulation-frame");
    if (event.source !== frame.contentWindow || event.origin !== "null") return;
    const payload = event.data;
    if (!payload || payload.source !== "laysh-artifact") return;
    if (
      payload.type === "layout-height"
      && payload.version === 1
      && Number.isFinite(payload.height)
      && payload.height >= 100
      && payload.height <= 100_000
    ) {
      const height = Math.ceil(payload.height);
      frame.style.height = `${height}px`;
      frame.dataset.contentHeight = String(height);
      return;
    }
    if (payload.type === "runtime-error" && payload.code === "SIM_RUNTIME_ERROR") {
      frame.hidden = true;
      showFailure("simulation_runtime_error");
    }
  });

  let frameResizeId = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(frameResizeId);
    frameResizeId = requestAnimationFrame(() => {
      const frame = byId("simulation-frame");
      if (!frame.src) return;
      frame.contentWindow?.postMessage(
        { source: "laysh-host", type: "measure-layout", version: 1 },
        "*",
      );
    });
  }, { passive: true });

  document.addEventListener("laysh:locale-changed", (event) => {
    currentLocale = event.detail.locale;
    number = new Intl.NumberFormat(currentLocale, { maximumFractionDigits: 0 });
    exampleIndex = 0;
    byId("safe-example").textContent = t("ask.example");
    if (state.connectionKey) setConnection(state.connectionKey, byId("connection-state").dataset.mode);
    if (state.failure) {
      const selected = localizedFailure(state.failure.reason);
      byId("failure-eyebrow").textContent = selected.eyebrow;
      byId("failure-title").textContent = selected.title;
      byId("failure-copy").textContent = selected.copy;
    }
    hydrateGallery();
  });

  history.replaceState({ view: "ask" }, "", "#ask");
  hydrateGallery();
})();
