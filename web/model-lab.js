(() => {
  "use strict";

  const form = document.getElementById("model-lab-form");
  const question = document.getElementById("lab-question");
  const error = document.getElementById("lab-error");
  const submit = document.getElementById("run-pipeline-button");
  const runStatus = document.getElementById("run-status");
  const results = document.getElementById("pipeline-results");
  const sharedAnswer = document.getElementById("shared-answer");
  const answerCopy = document.getElementById("shared-answer-title");
  const formula = document.getElementById("shared-formula");
  const artifactPanel = document.getElementById("pipeline-preview");
  const artifactFrame = artifactPanel.querySelector("iframe");
  const artifactTier = artifactPanel.querySelector(".artifact-tier");
  const previewWarning = artifactPanel.querySelector(".preview-warning");
  const trace = document.getElementById("pipeline-trace");
  const revisionLabel = document.getElementById("revision-label");
  const localeControl = document.getElementById("locale-control");
  const sourceMode = document.getElementById("source-mode");
  const visualMode = document.getElementById("visual-mode");
  const cards = new Map(
    [...document.querySelectorAll("[data-stage]")].map((card) => [
      card.dataset.stage,
      card,
    ]),
  );
  const modelStages = new Set([
    "understand",
    "physics",
    "visual",
    "repair_1",
    "repair_2",
    "qa",
  ]);
  const supportedEfforts = {
    "gpt-5.6-luna": new Set(["low", "medium", "high", "xhigh", "max"]),
    "gpt-5.6-terra": new Set(["low", "medium", "high", "xhigh", "max", "ultra"]),
    "gpt-5.6-sol": new Set(["low", "medium", "high", "xhigh", "max", "ultra"]),
  };
  const stageOrder = [
    "evidence",
    "understand",
    "physics",
    "plan",
    "visual",
    "verify",
    "browser",
    "repair_1",
    "repair_2",
    "qa",
    "finalize",
  ];
  let activeStatusUrl = null;
  let currentRun = null;
  let pollTimer = 0;

  const locale = () => window.LayshLocale.current();
  const t = (key, values = {}) => window.LayshLocale.t(key, values);
  const formatNumber = (value, options = {}) => (
    new Intl.NumberFormat(locale(), options).format(value)
  );
  const formatDuration = (milliseconds) => {
    if (!Number.isFinite(milliseconds)) return "—";
    const seconds = milliseconds / 1000;
    return t("modelLab.seconds", {
      value: formatNumber(seconds, {
        minimumFractionDigits: seconds < 10 ? 1 : 0,
        maximumFractionDigits: 1,
      }),
    });
  };
  const displayModel = (model) => model
    .replace("gpt-5.6-", "GPT-5.6 ")
    .replace(/\b(luna|terra|sol)\b/, (name) => (
      name[0].toUpperCase() + name.slice(1)
    ));

  function stageConfig(stage) {
    const card = cards.get(stage);
    return {
      model: card.querySelector('[name="model"]').value,
      effort: card.querySelector('[name="effort"]').value,
      fast: card.querySelector('[name="fast"]').checked,
    };
  }

  function pipelineConfig() {
    return Object.fromEntries(
      [...modelStages].map((stage) => [stage, stageConfig(stage)]),
    );
  }

  function syncEfforts(card) {
    const model = card.querySelector('[name="model"]').value;
    const effort = card.querySelector('[name="effort"]');
    const allowed = supportedEfforts[model];
    for (const option of effort.options) {
      option.disabled = !allowed.has(option.value);
    }
    if (!allowed.has(effort.value)) effort.value = "max";
    const note = card.querySelector(".effort-note");
    if (note) {
      note.textContent = model === "gpt-5.6-luna"
        ? t("modelLab.lunaLimit")
        : "";
      note.hidden = model !== "gpt-5.6-luna";
    }
  }

  function syncAllEfforts() {
    for (const stage of modelStages) syncEfforts(cards.get(stage));
  }

  function updateEffortLabels() {
    for (const card of document.querySelectorAll(".model-stage")) {
      for (const option of card.querySelector('[name="effort"]').options) {
        option.textContent = t(`modelLab.effort.${option.value}`);
      }
    }
  }

  function updateLocaleControl() {
    const isArabic = locale() === "ar";
    localeControl.textContent = isArabic ? "EN" : "العربية";
    localeControl.setAttribute(
      "aria-label",
      isArabic ? "Switch to English" : "التبديل إلى العربية",
    );
  }

  function setBusy(busy) {
    submit.disabled = busy;
    submit.querySelector("span").textContent = t(
      busy ? "modelLab.submitBusy" : "modelLab.submit",
    );
    for (const control of form.querySelectorAll("textarea, select, input")) {
      control.disabled = busy;
    }
    for (const button of form.querySelectorAll('[data-action="rerun"]')) {
      button.disabled = busy || !currentRun;
    }
  }

  function showError(key) {
    error.textContent = t(key);
    error.hidden = false;
    question.setAttribute("aria-invalid", "true");
  }

  function clearError() {
    error.hidden = true;
    error.textContent = "";
    question.removeAttribute("aria-invalid");
  }

  function renderRunStatus(status, activeStage = null) {
    const statusKey = {
      queued: "modelLab.queued",
      running: "modelLab.running",
      complete: "modelLab.complete",
      rejected: "modelLab.rejected",
      failed: "modelLab.failed",
    }[status] || "modelLab.idle";
    runStatus.dataset.state = status;
    runStatus.querySelector("strong").textContent = activeStage
      ? t("modelLab.runningStage", {
        stage: t(`modelLab.stage.${activeStage.replace("_1", "1").replace("_2", "2")}`),
      })
      : t(statusKey);
  }

  function appendText(container, className, text) {
    if (!text) return;
    const element = document.createElement("p");
    element.className = className;
    element.textContent = text;
    container.append(element);
  }

  function appendList(container, titleKey, values, className = "") {
    if (!Array.isArray(values) || values.length === 0) return;
    const group = document.createElement("div");
    group.className = `output-group ${className}`.trim();
    const title = document.createElement("strong");
    title.textContent = t(titleKey);
    const list = document.createElement("ul");
    for (const value of values) {
      const item = document.createElement("li");
      item.textContent = value;
      list.append(item);
    }
    group.append(title, list);
    container.append(group);
  }

  function appendSources(container, sources) {
    if (!Array.isArray(sources) || sources.length === 0) return;
    const group = document.createElement("div");
    group.className = "output-group source-output";
    const title = document.createElement("strong");
    title.textContent = t("modelLab.output.sources");
    const list = document.createElement("ul");
    for (const source of sources) {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = source.title;
      const metadata = document.createElement("small");
      metadata.textContent = `${source.provider} · ${source.license}`;
      item.append(link, metadata);
      list.append(item);
    }
    group.append(title, list);
    container.append(group);
  }

  function appendDiscovery(container, discovery) {
    if (!discovery?.learning_cycle || !discovery?.representation) return;
    const group = document.createElement("div");
    group.className = "discovery-output";
    const family = document.createElement("p");
    family.className = "representation-family";
    family.textContent = t("modelLab.output.representation", {
      value: discovery.representation.family.replaceAll("_", " "),
    });
    const cycle = document.createElement("ol");
    for (const [name, copy] of Object.entries(discovery.learning_cycle)) {
      const item = document.createElement("li");
      const label = document.createElement("strong");
      label.textContent = t(`modelLab.discovery.${name}`);
      const text = document.createElement("span");
      text.textContent = copy;
      item.append(label, text);
      cycle.append(item);
    }
    group.append(family, cycle);
    if (Array.isArray(discovery.related_references)
      && discovery.related_references.length > 0) {
      const references = document.createElement("div");
      references.className = "output-group source-output related-reference-output";
      const heading = document.createElement("strong");
      heading.textContent = t("modelLab.output.relatedReferences");
      const list = document.createElement("ul");
      for (const reference of discovery.related_references) {
        const item = document.createElement("li");
        const link = document.createElement("a");
        link.href = reference.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = reference.title;
        const metadata = document.createElement("small");
        metadata.textContent = [
          reference.provider,
          reference.language,
          reference.license_note,
        ].filter(Boolean).join(" · ");
        item.append(link, metadata);
        list.append(item);
      }
      references.append(heading, list);
      group.append(references);
    }
    container.append(group);
  }

  function renderStageOutput(card, event, result) {
    const output = card.querySelector(".stage-output");
    output.replaceChildren();
    if (!event) {
      output.hidden = true;
      return;
    }
    const stageOutput = event.output || {};
    appendText(output, "output-summary", stageOutput.summary);
    if (stageOutput.formula) {
      const code = document.createElement("code");
      code.dir = "auto";
      code.textContent = stageOutput.formula;
      output.append(code);
    }
    appendList(output, "modelLab.output.details", stageOutput.details);
    appendList(
      output,
      "modelLab.output.expressions",
      stageOutput.expressions,
      "expressions",
    );
    appendList(output, "modelLab.output.assumptions", stageOutput.assumptions);
    appendList(output, "modelLab.output.outputs", stageOutput.output_names, "outputs");
    appendList(output, "modelLab.output.issues", stageOutput.issues, "issues");
    appendSources(output, stageOutput.sources);
    appendDiscovery(output, stageOutput.discovery);
    appendList(output, "modelLab.gates", [
      ...(stageOutput.failed_gates || []),
      ...(stageOutput.failure_codes || []),
    ], "failures");
    if (stageOutput.visual_richness) {
      const quality = document.createElement("div");
      quality.className = "quality-grid";
      for (const [name, passed] of Object.entries(stageOutput.visual_richness)) {
        const chip = document.createElement("span");
        chip.dataset.passed = String(passed);
        chip.textContent = `${passed ? "✓" : "×"} ${t(`modelLab.quality.${name}`)}`;
        quality.append(chip);
      }
      output.append(quality);
    }
    if (Number.isFinite(stageOutput.check_count) && stageOutput.check_count > 0) {
      appendText(
        output,
        "output-checks",
        t("modelLab.checkCount", { value: formatNumber(stageOutput.check_count) }),
      );
    }
    if (
      result.artifact_url
      && ["visual", "repair_1", "repair_2", "finalize"].includes(event.stage)
    ) {
      const link = document.createElement("a");
      link.className = "visual-output-link";
      link.href = "#pipeline-preview";
      link.textContent = t("modelLab.openVisual");
      output.append(link);
    }
    output.hidden = output.childElementCount === 0;
  }

  function latestEvents(result) {
    const latest = new Map();
    for (const event of result.timeline) {
      if (event.revision === result.revision) latest.set(event.stage, event);
    }
    return latest;
  }

  function renderCards(result) {
    const events = latestEvents(result);
    for (const stage of stageOrder) {
      const card = cards.get(stage);
      const event = events.get(stage);
      const status = card.querySelector(".stage-status");
      if (!event) {
        const isActive = result.active_stage === stage;
        status.dataset.state = isActive ? "running" : "idle";
        status.textContent = isActive
          ? t("modelLab.event.running")
          : t("modelLab.notRunThisRevision");
        renderStageOutput(card, null, result);
        continue;
      }
      status.dataset.state = event.status;
      status.textContent = `${t(`modelLab.event.${event.status}`)} · ${formatDuration(event.elapsed_ms)}`;
      renderStageOutput(card, event, result);
    }
  }

  function renderTrace(result) {
    trace.replaceChildren();
    revisionLabel.textContent = t("modelLab.revision", {
      value: formatNumber(result.revision),
    });
    for (const event of result.timeline) {
      const item = document.createElement("li");
      item.dataset.status = event.status;
      item.dataset.revision = String(event.revision);
      const marker = document.createElement("span");
      marker.className = "trace-marker";
      marker.textContent = String(event.sequence).padStart(2, "0");
      const copy = document.createElement("div");
      const heading = document.createElement("strong");
      heading.textContent = t(
        `modelLab.stage.${event.stage.replace("_1", "1").replace("_2", "2")}`,
      );
      const metadata = document.createElement("p");
      const route = event.model
        ? `${displayModel(event.model)} · ${t(`modelLab.effort.${event.effort}`)} · ${
          event.fast ? t("modelLab.fast") : t("modelLab.standard")
        }`
        : t("modelLab.noModel");
      metadata.textContent = `${t(`modelLab.event.${event.status}`)} · ${
        formatDuration(event.elapsed_ms)
      } · ${route}`;
      copy.append(heading, metadata);
      if (event.output?.summary) {
        const summary = document.createElement("p");
        summary.className = "trace-summary";
        summary.textContent = event.output.summary;
        copy.append(summary);
      }
      const revision = document.createElement("small");
      revision.textContent = `R${event.revision}`;
      item.append(marker, copy, revision);
      trace.append(item);
    }
  }

  function renderArtifact(result) {
    if (!result.artifact_url) {
      artifactPanel.hidden = true;
      delete artifactPanel.dataset.ready;
      artifactFrame.removeAttribute("src");
      return;
    }
    artifactPanel.hidden = false;
    artifactTier.dataset.tier = result.artifact_tier;
    artifactTier.textContent = t(
      result.artifact_tier === "verified"
        ? "modelLab.verified"
        : "modelLab.unverified",
    );
    previewWarning.hidden = result.artifact_tier !== "unverified_preview";
    if (artifactFrame.getAttribute("src") !== result.artifact_url) {
      artifactPanel.dataset.ready = "false";
      artifactFrame.style.removeProperty("height");
      artifactFrame.src = result.artifact_url;
    }
  }

  function renderResult(result) {
    currentRun = result;
    results.hidden = result.timeline.length === 0;
    renderRunStatus(result.status, result.active_stage);
    if (result.answer?.tldr) {
      sharedAnswer.hidden = false;
      answerCopy.textContent = result.answer.tldr;
      formula.textContent = result.answer.key_formula || "";
      formula.hidden = !result.answer.key_formula;
    } else {
      sharedAnswer.hidden = true;
    }
    renderCards(result);
    renderTrace(result);
    renderArtifact(result);
  }

  async function poll(statusUrl, minimumRevision) {
    if (activeStatusUrl !== statusUrl) return;
    try {
      const response = await fetch(statusUrl, {
        headers: { accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error("status_unavailable");
      const result = await response.json();
      renderResult(result);
      if (
        result.revision >= minimumRevision
        && ["complete", "rejected", "failed"].includes(result.status)
      ) {
        activeStatusUrl = null;
        setBusy(false);
        return;
      }
      pollTimer = window.setTimeout(
        () => poll(statusUrl, minimumRevision),
        650,
      );
    } catch {
      activeStatusUrl = null;
      setBusy(false);
      renderRunStatus("failed");
      showError("modelLab.error.generic");
    }
  }

  async function startPipeline() {
    const normalizedQuestion = question.value.normalize("NFKC").trim();
    if (!normalizedQuestion) {
      showError("modelLab.error.required");
      question.focus();
      return;
    }
    clearError();
    setBusy(true);
    renderRunStatus("queued");
    const response = await fetch("/api/model-lab/pipeline", {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify({
        question: normalizedQuestion,
        locale: locale(),
        source_mode: sourceMode.value,
        visual_mode: visualMode.value,
        stages: pipelineConfig(),
      }),
    });
    if (!response.ok) {
      showError(
        response.status === 429 ? "modelLab.error.rate" : "modelLab.error.generic",
      );
      renderRunStatus("failed");
      setBusy(false);
      return;
    }
    const accepted = await response.json();
    activeStatusUrl = accepted.status_url;
    await poll(activeStatusUrl, 1);
  }

  async function rerunFrom(stage) {
    if (!currentRun || activeStatusUrl) return;
    clearError();
    setBusy(true);
    const nextRevision = currentRun.revision + 1;
    const payload = {
      stage,
      config: modelStages.has(stage) ? stageConfig(stage) : null,
      source_mode: stage === "evidence" ? sourceMode.value : null,
      visual_mode: ["evidence", "understand", "physics", "plan", "visual"].includes(stage)
        ? visualMode.value
        : null,
    };
    const response = await fetch(
      `/api/model-lab/pipeline/${encodeURIComponent(currentRun.run_id)}/rerun`,
      {
        method: "POST",
        headers: { "content-type": "application/json", accept: "application/json" },
        body: JSON.stringify(payload),
      },
    );
    if (!response.ok) {
      showError("modelLab.error.rerun");
      setBusy(false);
      return;
    }
    const accepted = await response.json();
    activeStatusUrl = accepted.status_url;
    await poll(activeStatusUrl, nextRevision);
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    window.clearTimeout(pollTimer);
    activeStatusUrl = null;
    try {
      await startPipeline();
    } catch {
      activeStatusUrl = null;
      setBusy(false);
      renderRunStatus("failed");
      showError("modelLab.error.generic");
    }
  });

  for (const card of document.querySelectorAll(".pipeline-stage")) {
    card.querySelector('[data-action="rerun"]').addEventListener("click", async () => {
      try {
        await rerunFrom(card.dataset.stage);
      } catch {
        activeStatusUrl = null;
        setBusy(false);
        showError("modelLab.error.rerun");
      }
    });
    const model = card.querySelector('[name="model"]');
    if (model) model.addEventListener("change", () => syncEfforts(card));
  }

  window.addEventListener("message", (event) => {
    if (event.source !== artifactFrame.contentWindow || event.origin !== "null") return;
    const payload = event.data;
    if (!payload || payload.source !== "laysh-artifact") return;
    if (payload.type === "ready" && payload.version === 1) {
      artifactPanel.dataset.ready = "true";
      return;
    }
    if (
      payload.type === "layout-height"
      && payload.version === 1
      && Number.isFinite(payload.height)
      && payload.height >= 100
      && payload.height <= 100_000
    ) {
      artifactFrame.style.height = `${Math.ceil(payload.height)}px`;
    }
  });

  let resizeFrame = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {
      artifactFrame.contentWindow?.postMessage(
        { source: "laysh-host", type: "measure-layout", version: 1 },
        "*",
      );
    });
  }, { passive: true });

  document.addEventListener("laysh:locale-changed", () => {
    updateLocaleControl();
    updateEffortLabels();
    syncAllEfforts();
    if (currentRun) renderResult(currentRun);
    else renderRunStatus("idle");
    setBusy(Boolean(activeStatusUrl));
  });

  updateEffortLabels();
  updateLocaleControl();
  syncAllEfforts();
  renderRunStatus("idle");
  setBusy(false);
})();
