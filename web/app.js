(() => {
  "use strict";

  let booted = false;

  function boot() {
    if (booted) return;
    const catalogs = window.LayshTranslations;
    const localeState = window.LayshLocale;
    if (!catalogs || !localeState) return;
    booted = true;
    const state = {
    locale: localeState.initial,
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
    failureReason: null,
  };

    const byId = (id) => document.getElementById(id);
    const views = [...document.querySelectorAll("[data-view]")];
    const MIN_ARTIFACT_HEIGHT = 480;
    const MAX_ARTIFACT_HEIGHT = 12000;
    let number = new Intl.NumberFormat(state.locale, { maximumFractionDigits: 0 });
    const failureSymbols = {
    not_simulatable: "?",
    qa_inconclusive: "…",
    verification_exhausted: "×",
    generation_failed: "↺",
    simulation_runtime_error: "!",
    backend_unavailable: "⌁",
    cancelled: "■",
    timed_out: "⌛",
    unsafe_redirect: "↗",
    };

    function withoutLocalePrefix(pathname) {
      return pathname.replace(/^\/(?:ar|en)(?=\/|$)/, "") || "/";
    }

    function localePath(pathname = window.location.pathname, hash = window.location.hash) {
      const barePath = withoutLocalePrefix(pathname);
      return `/${state.locale}${barePath === "/" ? "" : barePath}${hash}`;
    }

    function replaceLocalePath() {
      history.replaceState(history.state, "", localePath());
    }

    function t(key, replacements = {}) {
    let value = catalogs[state.locale][key] || catalogs.ar[key] || key;
    for (const [name, replacement] of Object.entries(replacements)) {
      value = value.replaceAll(`{${name}}`, String(replacement));
    }
    return value;
  }

    function hasTranslation(key) {
    return Object.hasOwn(catalogs[state.locale], key) || Object.hasOwn(catalogs.ar, key);
  }

    function applyTranslations() {
    document.title = t("document_title");
    document.documentElement.lang = state.locale;
    document.documentElement.dir = state.locale === "ar" ? "rtl" : "ltr";
    document.documentElement.dataset.locale = state.locale;
    for (const node of document.querySelectorAll("[data-i18n]")) {
      node.textContent = t(node.dataset.i18n);
    }
    for (const attribute of ["aria-label", "placeholder", "title"]) {
      const dataName = `i18n${attribute.split("-").map((part) => part[0].toUpperCase() + part.slice(1)).join("")}`;
      for (const node of document.querySelectorAll(`[data-i18n-${attribute}]`)) {
        node.setAttribute(attribute, t(node.dataset[dataName]));
      }
    }
    for (const button of document.querySelectorAll("#locale-switch > button[data-locale]")) {
      button.setAttribute("aria-pressed", String(button.dataset.locale === state.locale));
    }
    number = new Intl.NumberFormat(state.locale, { maximumFractionDigits: 0 });
  }

    function setView(name, { push = false } = {}) {
    state.view = name;
    for (const view of views) view.hidden = view.dataset.view !== name;
    if (push) {
      const destination = name === "ask"
        ? localePath("/", "#ask")
        : localePath(window.location.pathname, `#${name}`);
      history.pushState({ view: name }, "", destination);
    }
    const target = document.querySelector(`[data-view="${name}"] h1, [data-view="${name}"] h2`);
    requestAnimationFrame(() => (target || byId("main-content")).focus?.({ preventScroll: true }));
    window.scrollTo({ top: 0, behavior: "auto" });
  }

    function formatElapsed(milliseconds) {
    const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = String(totalSeconds % 60).padStart(2, "0");
    const zero = state.locale === "ar" ? "٠" : "0";
    return `${number.format(minutes)}:${number.format(Number(seconds)).padStart(2, zero)}`;
  }

  function setConnection(copy, mode = "working") {
    byId("connection-copy").textContent = copy;
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
        setConnection(t("connection.still_testing"), "still-testing");
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
    const stageKey = `stage.${payload.stage}`;
    const detailKey = `stage_detail.${payload.stage}`;
    name.textContent = t(hasTranslation(stageKey) ? stageKey : "stage.unknown");
    detail.textContent = payload.detail || t(
      hasTranslation(detailKey) ? detailKey : "stage_detail.unknown",
    );
    time.className = "stage-time";
    time.textContent = t("seconds", { value: number.format(payload.elapsed_ms / 1000) });
    item.append(name, detail, time);
    byId("stage-list").append(item);
    if (payload.stage === "healing") byId("heal-act").hidden = false;
    setConnection(t("connection.progress"), "working");
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
    byId("verification-title").textContent = t(payload.passed ? "verification.passed" : "verification.failed");
    byId("verification-copy").textContent = t("verification.summary", {
      checks: number.format(payload.check_count),
      heals: number.format(payload.heal_count),
    });
    const grid = byId("verification-grid");
    grid.replaceChildren();
    for (const [index, gate] of payload.evidence.entries()) {
      const chip = document.createElement("span");
      chip.className = `verification-chip ${payload.passed ? "passed" : "failed"}`;
      const gateKey = `gate.${gate}`;
      chip.textContent = `${payload.passed ? "✓" : "!"} ${hasTranslation(gateKey) ? t(gateKey) : gate}`;
      grid.append(chip);
      setTimeout(() => chip.classList.add("visible"), Math.min(index * 90, 720));
    }
  }

  function normalizedReason(reason, status) {
    if (status === "rejected") return "unsafe_redirect";
    if (["failed", "answer_only"].includes(status) && !failureSymbols[reason]) return "generation_failed";
    return failureSymbols[reason] ? reason : "generation_failed";
  }

  function showFailure(reason, suggestions = []) {
    state.terminal = true;
    state.streamController?.abort();
    clearInterval(state.timer);
    clearInterval(state.watchdog);
    state.failureReason = failureSymbols[reason] ? reason : "generation_failed";
    byId("failure-eyebrow").textContent = t(`failure.${state.failureReason}.eyebrow`);
    byId("failure-title").textContent = t(`failure.${state.failureReason}.title`);
    byId("failure-copy").textContent = t(`failure.${state.failureReason}.copy`);
    byId("failure-symbol").textContent = failureSymbols[state.failureReason];
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

    function displayResult(result, { push = true } = {}) {
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
    byId("simulation-alternative").textContent = state.answer || t("simulation_text_fallback");
    const simulationFrame = byId("simulation-frame");
    simulationFrame.hidden = false;
    simulationFrame.style.height = `${MIN_ARTIFACT_HEIGHT}px`;
    delete simulationFrame.dataset.contentHeight;
    simulationFrame.src = `${simulation.artifact_url}?inline=1`;
    byId("download").href = simulation.artifact_url;
    const shareActions = byId("share-actions");
    const nativeShare = byId("native-share");
    byId("share-status").textContent = "";
    if (simulation.share_url) {
      shareActions.dataset.shareUrl = new URL(
        localePath(simulation.share_url, ""), window.location.origin,
      ).href;
      shareActions.hidden = false;
      nativeShare.hidden = typeof navigator.share !== "function";
    } else {
      delete shareActions.dataset.shareUrl;
      shareActions.hidden = true;
      nativeShare.hidden = true;
    }
    byId("receipt-tier").textContent = t(simulation.tier === "A" ? "tier.a.receipt" : "tier.b.receipt");
    byId("tier-badge").textContent = t(simulation.tier === "A" ? "tier.a.badge" : "tier.b.badge");
    byId("check-count").textContent = number.format(simulation.check_count);
    byId("heal-count").textContent = number.format(simulation.heal_count);
    byId("result-elapsed").textContent = t("seconds", { value: number.format(simulation.elapsed_ms / 1000) });
    byId("effective-model").textContent = simulation.effective_model;
    setView("result", { push });
  }

  async function loadResult() {
    const response = await fetch(state.resultUrl, { headers: { accept: "application/json" } });
    if (!response.ok) throw new Error("result_unavailable");
    displayResult(await response.json());
  }

  async function loadLesson(lessonId) {
    const response = await fetch(`/api/gallery/${encodeURIComponent(lessonId)}`, {
      headers: { accept: "application/json" },
    });
    if (!response.ok) throw new Error("lesson_unavailable");
    const lesson = await response.json();
    pinAnswer(lesson.answer);
    displayResult({ status: "complete", answer: lesson.answer, simulation: lesson.simulation });
  }

  async function loadSharedSimulation(simId) {
    const response = await fetch(`/api/sims/${encodeURIComponent(simId)}`, {
      headers: { accept: "application/json" },
    });
    if (!response.ok) throw new Error("shared_simulation_unavailable");
    displayResult(await response.json(), { push: false });
  }

  async function copyShareLink() {
    const shareUrl = byId("share-actions").dataset.shareUrl;
    if (!shareUrl) return;
    try {
      await navigator.clipboard.writeText(shareUrl);
    } catch {
      const fallback = document.createElement("textarea");
      fallback.value = shareUrl;
      fallback.setAttribute("readonly", "");
      fallback.style.position = "fixed";
      fallback.style.opacity = "0";
      document.body.append(fallback);
      fallback.select();
      document.execCommand("copy");
      fallback.remove();
    }
    byId("share-status").textContent = t("share_copied");
  }

  async function hydrateGallery() {
    const requestedLocale = state.locale;
    document.documentElement.dataset.galleryState = "loading";
    for (const card of document.querySelectorAll('[data-dynamic-card="true"]')) card.remove();
    for (const card of document.querySelectorAll(".gallery-card")) {
      card.dataset.lessonId = "";
      const badge = card.querySelector(".instant-badge, .coming-badge");
      badge.className = "coming-badge";
      badge.textContent = t("coming_soon");
      const launch = card.querySelector(".golden-launch");
      launch.disabled = true;
      launch.textContent = t("launch_lesson");
      launch.onclick = null;
      card.querySelector(".card-summary")?.remove();
    }
    try {
      const response = await fetch(`/api/gallery?locale=${encodeURIComponent(requestedLocale)}`, {
        headers: { accept: "application/json" },
      });
      if (!response.ok) return;
      const gallery = await response.json();
      if (requestedLocale !== state.locale) return;
      for (const lesson of gallery.lessons) {
        if (!lesson.instant) continue;
        const conceptId = lesson.id.endsWith("_en") ? lesson.id.slice(0, -3) : lesson.id;
        let card = [...document.querySelectorAll(".gallery-card")].find(
          (candidate) => candidate.dataset.goldenId === conceptId,
        );
        if (!card) {
          card = document.createElement("article");
          card.className = "gallery-card";
          card.dataset.lessonId = lesson.id;
          card.dataset.dynamicCard = "true";
          const icon = document.createElement("span");
          icon.className = "gallery-icon";
          icon.setAttribute("aria-hidden", "true");
          icon.textContent = "✦";
          const domain = document.createElement("p");
          domain.className = "card-domain";
          const title = document.createElement("h3");
          const badge = document.createElement("span");
          badge.className = "coming-badge";
          const launch = document.createElement("button");
          launch.className = "golden-launch";
          launch.type = "button";
          launch.textContent = t("launch_lesson");
          card.append(icon, domain, title, badge, launch);
          document.querySelector(".gallery-grid").append(card);
        }
        card.dataset.lessonId = lesson.id;
        card.querySelector("h3").textContent = lesson.title;
        card.querySelector(".card-domain").textContent = lesson.domain;
        let summary = card.querySelector(".card-summary");
        if (!summary) {
          summary = document.createElement("p");
          summary.className = "card-summary";
          card.querySelector("h3").after(summary);
        }
        summary.textContent = lesson.summary;
        const badge = card.querySelector(".coming-badge");
        badge.className = "instant-badge";
        badge.textContent = t("instant");
        const launch = card.querySelector(".golden-launch");
        launch.disabled = false;
        launch.onclick = () => {
          loadLesson(lesson.id).catch(() => showFailure("backend_unavailable"));
        };
      }
      document.documentElement.dataset.galleryState = "ready";
    } catch (error) {
      // Honest placeholders remain visible when the gallery endpoint is unavailable.
      document.documentElement.dataset.galleryState = "unavailable";
      document.documentElement.dataset.galleryError = error?.name || "Error";
    }
  }

  function setLocale(locale, { persist = true } = {}) {
    if (locale !== "ar" && locale !== "en") return;
    if (persist) {
      try {
        localStorage.setItem(localeState.storageKey, locale);
      } catch {
        // The in-memory choice still applies when storage is unavailable.
      }
    }
    if (locale === state.locale) {
      applyTranslations();
      replaceLocalePath();
      return;
    }
    state.locale = locale;
    applyTranslations();
    replaceLocalePath();
    if (state.result?.simulation?.share_url) {
      byId("share-actions").dataset.shareUrl = new URL(
        localePath(state.result.simulation.share_url, ""), window.location.origin,
      ).href;
    }
    exampleIndex = 0;
    byId("safe-example").textContent = t("example.0");
    if (state.view === "ask") hydrateGallery();
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
    if (event.type === "heartbeat") setConnection(t("connection.stable"), "working");
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
      setConnection(t("connection.stable"), "working");
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
    setConnection(t("connection.reconnecting"), "reconnecting");
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
    byId("elapsed").textContent = formatElapsed(0);
    setConnection(t("connection.queued"), "queued");
    setView("build", { push: true });
    startClock();
    try {
      const response = await fetch("/api/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question, locale: state.locale }),
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
      byId("question-error").textContent = t("question_required");
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
      exampleIndex = (exampleIndex + 1) % 4;
      byId("safe-example").textContent = t(`example.${exampleIndex}`);
    }, 5000);
  }

  byId("cancel-action").addEventListener("click", async () => {
    setConnection(t("connection.cancelling"), "cancelling");
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
    frame.style.height = `${MIN_ARTIFACT_HEIGHT}px`;
    delete frame.dataset.contentHeight;
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
  document.addEventListener("fullscreenchange", () => {
    const frame = byId("simulation-frame");
    if (document.fullscreenElement || !frame.dataset.contentHeight) return;
    frame.style.height = `${frame.dataset.contentHeight}px`;
  });
  byId("copy-share").addEventListener("click", copyShareLink);
  byId("native-share").addEventListener("click", async () => {
    const url = byId("share-actions").dataset.shareUrl;
    if (!url || typeof navigator.share !== "function") return;
    try {
      await navigator.share({ title: byId("result-title").textContent, url });
    } catch (error) {
      if (error.name !== "AbortError") await copyShareLink();
    }
  });

  window.addEventListener("popstate", (event) => setView(event.state?.view || "ask"));
  window.addEventListener("offline", () => {
    if (state.terminal || !state.streamUrl) return;
    state.streamController?.abort();
    setConnection(t("connection.reconnecting"), "reconnecting");
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
    if (payload.type === "content-height" && payload.version === 1) {
      const measured = Math.ceil(Number(payload.height));
      if (!Number.isFinite(measured) || measured <= 0) return;
      const height = Math.max(
        MIN_ARTIFACT_HEIGHT,
        Math.min(MAX_ARTIFACT_HEIGHT, measured),
      );
      frame.dataset.contentHeight = String(height);
      for (const [name, value] of Object.entries({
        scrollHeight: payload.scrollHeight,
        clientHeight: payload.clientHeight,
        interactiveUnitBottom: payload.interactiveUnitBottom,
        canvasWidth: payload.canvasWidth,
        canvasHeight: payload.canvasHeight,
      })) {
        if (Number.isFinite(Number(value))) frame.dataset[name] = String(Math.ceil(Number(value)));
      }
      if (document.fullscreenElement !== frame) frame.style.height = `${height}px`;
      return;
    }
    if (payload.type === "runtime-error" && payload.code === "SIM_RUNTIME_ERROR") {
      frame.hidden = true;
      showFailure("simulation_runtime_error");
    }
  });

  for (const button of document.querySelectorAll("#locale-switch > button[data-locale]")) {
    button.addEventListener("click", () => setLocale(button.dataset.locale));
  }

  applyTranslations();
  replaceLocalePath();
  const sharedPath = withoutLocalePrefix(window.location.pathname).match(/^\/sims\/([^/]+)$/);
  if (sharedPath) {
    history.replaceState({ view: "result" }, "", window.location.href);
    loadSharedSimulation(decodeURIComponent(sharedPath[1])).catch(() => {
      showFailure("backend_unavailable");
    });
  } else {
    history.replaceState({ view: "ask" }, "", "#ask");
    hydrateGallery();
  }
  }

  boot();
  if (!booted) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", boot, { once: true });
    } else {
      setTimeout(boot, 0);
    }
  }
})();
