(() => {
  "use strict";

  const safeExamples = [
    "لماذا يتغير شكل القمر خلال الشهر؟",
    "كيف تطفو السفن الثقيلة فوق الماء؟",
    "لماذا تتكوّن ألوان قوس المطر؟",
    "كيف تنتقل الحرارة بين الأجسام؟",
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
  };

  const byId = (id) => document.getElementById(id);
  const views = [...document.querySelectorAll("[data-view]")];
  const number = new Intl.NumberFormat("ar", { maximumFractionDigits: 0 });

  const failureCopy = {
    not_simulatable: {
      eyebrow: "الجواب متاح",
      title: "احتفظنا بالجواب",
      copy: "لا يمكن بناء محاكاة صادقة لهذا السؤال الآن. يمكنك تعديل السؤال أو اختيار تجربة مراجعة.",
      symbol: "؟",
    },
    qa_inconclusive: {
      eyebrow: "الفحص غير حاسم",
      title: "احتفظنا بالجواب",
      copy: "لم يكتمل فحص المرشح في الوقت المحدد، لذلك لم نعرض المحاكاة.",
      symbol: "…",
    },
    verification_exhausted: {
      eyebrow: "أوقفنا مرشحًا غير موثوق",
      title: "احتفظنا بالجواب",
      copy: "لم تجتز المحاكاة كل الفحوصات بعد محاولتي إصلاح، لذلك لن نعرضها أو نخزنها.",
      symbol: "×",
    },
    generation_failed: {
      eyebrow: "تعذّر إكمال البناء",
      title: "الجواب ما زال هنا",
      copy: "تعطّل البناء قبل تجهيز تجربة موثوقة. جرّب البناء مرة أخرى أو عد إلى المكتبة.",
      symbol: "↺",
    },
    simulation_runtime_error: {
      eyebrow: "حماية وقت التشغيل",
      title: "حدث خطأ داخل المحاكاة",
      copy: "أخفينا الإطار المتعطل ولم نسجل تفاصيله. يمكنك إعادة البناء أو اختيار تجربة أخرى.",
      symbol: "!",
    },
    backend_unavailable: {
      eyebrow: "وضع المكتبة فقط",
      title: "تعذّر الاتصال بالخادم",
      copy: "لا نستطيع بدء بناء جديد الآن. ما زالت بطاقات المكتبة متاحة للمعاينة.",
      symbol: "⌁",
    },
    cancelled: {
      eyebrow: "أُلغي البناء",
      title: "توقفنا بهدوء",
      copy: "لم نكمل المحاكاة. يمكنك العودة إلى السؤال أو بدء محاولة جديدة.",
      symbol: "■",
    },
    timed_out: {
      eyebrow: "انتهت مهلة البناء",
      title: "احتفظنا بالجواب",
      copy: "توقف البناء بعد المهلة القصوى بدل إبقائك في انتظار غير محدد.",
      symbol: "⌛",
    },
    unsafe_redirect: {
      eyebrow: "لنحافظ على مساحة آمنة",
      title: "لا يمكننا متابعة هذا السؤال",
      copy: "يمكننا بدلًا منه استكشاف سؤال علمي آمن من المقترحات أدناه.",
      symbol: "↗",
    },
  };

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
    return `${number.format(minutes)}:${number.format(Number(seconds)).padStart(2, "٠")}`;
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
        setConnection("ما زلنا نفحص المرشح بعناية؛ لم ننتهِ بعد.", "still-testing");
      }
    }, 1000);
  }

  function addStage(payload) {
    const item = document.createElement("li");
    const detail = document.createElement("span");
    const time = document.createElement("span");
    detail.textContent = payload.detail;
    time.className = "stage-time";
    time.textContent = `${number.format(payload.elapsed_ms / 1000)} ث`;
    item.append(detail, time);
    byId("stage-list").append(item);
    setConnection("تقدّم البناء إلى خطوة جديدة", "working");
  }

  function pinAnswer(payload) {
    state.answer = payload.tldr;
    state.formula = payload.key_formula;
    byId("answer-copy").textContent = payload.tldr;
    byId("answer-formula").textContent = payload.key_formula || "";
    byId("answer-formula").hidden = !payload.key_formula;
    byId("answer-card").hidden = false;
  }

  function showVerification(payload) {
    const box = byId("verification-summary");
    box.hidden = false;
    byId("verification-title").textContent = payload.passed ? "اجتاز المرشح الفحص" : "وجد الفحص نقاطًا تحتاج إصلاحًا";
    byId("verification-copy").textContent = `${number.format(payload.check_count)} فحصًا · ${number.format(payload.heal_count)} محاولة إصلاح`;
  }

  function normalizedReason(reason, status) {
    if (status === "rejected") return "unsafe_redirect";
    if (["failed", "answer_only"].includes(status) && !failureCopy[reason]) return "generation_failed";
    return failureCopy[reason] ? reason : "generation_failed";
  }

  function showFailure(reason, suggestions = []) {
    state.terminal = true;
    state.streamController?.abort();
    clearInterval(state.timer);
    clearInterval(state.watchdog);
    const selected = failureCopy[reason] || failureCopy.generation_failed;
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

  async function loadResult() {
    const response = await fetch(state.resultUrl, { headers: { accept: "application/json" } });
    if (!response.ok) throw new Error("result_unavailable");
    const result = await response.json();
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
    byId("simulation-alternative").textContent = state.answer || "وصف نصي للحالة متاح داخل المحاكاة.";
    byId("simulation-frame").hidden = false;
    byId("simulation-frame").src = `${simulation.artifact_url}?inline=1`;
    byId("download").href = simulation.artifact_url;
    byId("receipt-tier").textContent = simulation.tier === "A" ? "فئة أ — مراجعة بشرية" : "فئة ب — فحص آلي";
    byId("tier-badge").textContent = simulation.tier === "A" ? "مراجعة بشرية مثبتة" : "فحص آلي مكتمل";
    byId("check-count").textContent = number.format(simulation.check_count);
    byId("heal-count").textContent = number.format(simulation.heal_count);
    byId("result-elapsed").textContent = `${number.format(simulation.elapsed_ms / 1000)} ثانية`;
    byId("effective-model").textContent = simulation.effective_model;
    setView("result", { push: true });
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
    if (event.type === "heartbeat") setConnection("الاتصال مستقر، والبناء مستمر", "working");
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
      setConnection("الاتصال مستقر، والبناء مستمر", "working");
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
    setConnection("انقطع الاتصال مؤقتًا؛ نحاول إعادة الاتصال واستعادة ما فات.", "reconnecting");
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
    byId("elapsed").textContent = "٠:٠٠";
    setConnection("في قائمة البناء", "queued");
    setView("build", { push: true });
    startClock();
    try {
      const response = await fetch("/api/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question, locale: "ar" }),
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
      byId("question-error").textContent = "اكتب سؤالًا واحدًا على الأقل.";
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
      exampleIndex = (exampleIndex + 1) % safeExamples.length;
      byId("safe-example").textContent = safeExamples[exampleIndex];
    }, 5000);
  }

  byId("cancel-action").addEventListener("click", async () => {
    setConnection("جارٍ إلغاء البناء بهدوء", "cancelling");
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

  window.addEventListener("popstate", (event) => setView(event.state?.view || "ask"));
  window.addEventListener("offline", () => {
    if (state.terminal || !state.streamUrl) return;
    state.streamController?.abort();
    setConnection("انقطع الاتصال مؤقتًا؛ نحاول إعادة الاتصال واستعادة ما فات.", "reconnecting");
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
    if (payload.type === "runtime-error" && payload.code === "SIM_RUNTIME_ERROR") {
      frame.hidden = true;
      showFailure("simulation_runtime_error");
    }
  });

  history.replaceState({ view: "ask" }, "", "#ask");
})();
