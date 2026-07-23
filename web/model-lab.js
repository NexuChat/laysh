(() => {
  "use strict";

  const form = document.getElementById("model-lab-form");
  const question = document.getElementById("lab-question");
  const error = document.getElementById("lab-error");
  const submit = document.getElementById("compare-button");
  const runStatus = document.getElementById("run-status");
  const sharedAnswer = document.getElementById("shared-answer");
  const answerCopy = document.getElementById("shared-answer-title");
  const formula = document.getElementById("shared-formula");
  const understandRoute = document.getElementById("understand-route");
  const bays = new Map(
    [...document.querySelectorAll("[data-candidate]")].map((bay) => [
      bay.dataset.candidate,
      bay,
    ]),
  );
  let activeRun = null;
  let lastResult = null;
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
  const displayModel = (model) => model.replace("gpt-5.6-", "GPT-5.6 ").replace(
    /\b(luna|terra|sol)\b/,
    (name) => name[0].toUpperCase() + name.slice(1),
  );

  const candidateStatusKey = {
    queued: "modelLab.queued",
    generating: "modelLab.generating",
    verifying: "modelLab.verifying",
    verified: "modelLab.verified",
    rejected: "modelLab.rejected",
    failed: "modelLab.failed",
  };
  const runStatusKey = {
    idle: "modelLab.idle",
    queued: "modelLab.queued",
    understanding: "modelLab.understanding",
    generating: "modelLab.generating",
    complete: "modelLab.complete",
    rejected: "modelLab.rejected",
    failed: "modelLab.failed",
  };

  function translateSlots() {
    for (const element of document.querySelectorAll("[data-i18n-slot]")) {
      if (element.dataset.i18n) {
        element.textContent = t(element.dataset.i18n, {
          slot: element.dataset.i18nSlot,
        });
      }
      if (element.dataset.i18nTitle) {
        element.title = t(element.dataset.i18nTitle, {
          slot: element.dataset.i18nSlot,
        });
      }
    }
  }

  function selectedStage(container) {
    return {
      model: container.querySelector('[name="model"]').value,
      effort: container.querySelector('[name="effort"]').value,
    };
  }

  function selectedUnderstanding() {
    return selectedStage(document.querySelector('[data-role="understand"]'));
  }

  function selectedCandidates() {
    return [...document.querySelectorAll(".candidate-config")].map((fieldset) => ({
      physics: selectedStage(fieldset.querySelector('[data-role="physics"]')),
      visual: selectedStage(fieldset.querySelector('[data-role="visual"]')),
    }));
  }

  function resetBay(bay, config) {
    bay.dataset.state = "queued";
    const status = bay.querySelector(".candidate-status");
    status.dataset.status = "queued";
    status.textContent = t("modelLab.idle");
    bay.querySelector(".physics-model").textContent = displayModel(config.physics.model);
    bay.querySelector(".physics-effort").textContent = t(
      `modelLab.effort.${config.physics.effort}`,
    );
    bay.querySelector(".visual-model").textContent = displayModel(config.visual.model);
    bay.querySelector(".visual-effort").textContent = t(
      `modelLab.effort.${config.visual.effort}`,
    );
    for (const metric of bay.querySelectorAll("[data-metric]")) metric.textContent = "—";
    const frame = bay.querySelector("iframe");
    frame.hidden = true;
    frame.removeAttribute("src");
    frame.style.removeProperty("height");
    bay.querySelector(".withheld").hidden = true;
  }

  function resetComparison(configs) {
    lastResult = null;
    sharedAnswer.hidden = true;
    answerCopy.textContent = "";
    formula.hidden = true;
    formula.textContent = "";
    [...bays.values()].forEach((bay, index) => resetBay(bay, configs[index]));
  }

  function renderRunStatus(status) {
    runStatus.dataset.state = status;
    runStatus.querySelector("strong").textContent = t(
      runStatusKey[status] || "modelLab.failed",
    );
  }

  function renderCandidate(candidate) {
    const bay = bays.get(candidate.slot);
    if (!bay) return;
    bay.dataset.state = candidate.status;
    bay.querySelector(".physics-model").textContent = displayModel(
      candidate.physics_model,
    );
    bay.querySelector(".physics-effort").textContent = t(
      `modelLab.effort.${candidate.physics_effort}`,
    );
    bay.querySelector(".visual-model").textContent = displayModel(candidate.visual_model);
    bay.querySelector(".visual-effort").textContent = t(
      `modelLab.effort.${candidate.visual_effort}`,
    );
    const status = bay.querySelector(".candidate-status");
    status.dataset.status = candidate.status;
    status.textContent = t(candidateStatusKey[candidate.status] || "modelLab.failed");
    bay.querySelector('[data-metric="physics"]').textContent = formatDuration(
      candidate.physics_elapsed_ms,
    );
    bay.querySelector('[data-metric="visual"]').textContent = formatDuration(
      candidate.visual_elapsed_ms,
    );
    bay.querySelector('[data-metric="verification"]').textContent = formatDuration(
      candidate.verification_elapsed_ms,
    );
    bay.querySelector('[data-metric="checks"]').textContent = candidate.check_count
      ? formatNumber(candidate.check_count)
      : "—";

    const frame = bay.querySelector("iframe");
    const withheld = bay.querySelector(".withheld");
    if (candidate.status === "verified" && candidate.artifact_url) {
      withheld.hidden = true;
      frame.hidden = false;
      if (frame.getAttribute("src") !== candidate.artifact_url) {
        frame.src = candidate.artifact_url;
      }
      return;
    }
    frame.hidden = true;
    if (candidate.status === "rejected" || candidate.status === "failed") {
      withheld.hidden = false;
      const safeFailures = candidate.failure_codes?.length
        ? candidate.failure_codes
        : candidate.failed_gates;
      bay.querySelector(".failed-gates").textContent = safeFailures.length
        ? safeFailures.join(", ")
        : "—";
    } else {
      withheld.hidden = true;
    }
  }

  function renderResult(result) {
    lastResult = result;
    renderRunStatus(result.status);
    if (result.answer?.tldr) {
      sharedAnswer.hidden = false;
      answerCopy.textContent = result.answer.tldr;
      formula.textContent = result.answer.key_formula || "";
      formula.hidden = !result.answer.key_formula;
    }
    understandRoute.textContent = `${displayModel(result.understand_model)} · ${t(
      `modelLab.effort.${result.understand_effort}`,
    )} · ${formatDuration(result.understand_elapsed_ms)}`;
    result.candidates.forEach(renderCandidate);
  }

  function setBusy(busy) {
    submit.disabled = busy;
    submit.querySelector("[data-i18n]").textContent = t(
      busy ? "modelLab.submitBusy" : "modelLab.submit",
    );
    for (const control of form.querySelectorAll("textarea, select")) control.disabled = busy;
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

  async function poll(statusUrl) {
    if (activeRun !== statusUrl) return;
    try {
      const response = await fetch(statusUrl, {
        headers: { accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error("status_unavailable");
      const result = await response.json();
      renderResult(result);
      if (["complete", "rejected", "failed"].includes(result.status)) {
        activeRun = null;
        setBusy(false);
        return;
      }
      pollTimer = window.setTimeout(() => poll(statusUrl), 800);
    } catch {
      activeRun = null;
      setBusy(false);
      renderRunStatus("failed");
      showError("modelLab.error.generic");
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearError();
    const normalizedQuestion = question.value.normalize("NFKC").trim();
    if (!normalizedQuestion) {
      showError("modelLab.error.required");
      question.focus();
      return;
    }

    window.clearTimeout(pollTimer);
    activeRun = null;
    const candidates = selectedCandidates();
    resetComparison(candidates);
    setBusy(true);
    renderRunStatus("queued");
    try {
      const response = await fetch("/api/model-lab/compare", {
        method: "POST",
        headers: { "content-type": "application/json", accept: "application/json" },
        body: JSON.stringify({
          question: normalizedQuestion,
          locale: locale(),
          understand: selectedUnderstanding(),
          candidates,
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
      activeRun = accepted.status_url;
      await poll(activeRun);
    } catch {
      showError("modelLab.error.generic");
      renderRunStatus("failed");
      setBusy(false);
    }
  });

  window.addEventListener("message", (event) => {
    const frame = [...bays.values()]
      .map((bay) => bay.querySelector("iframe"))
      .find((candidate) => event.source === candidate.contentWindow);
    if (!frame || event.origin !== "null") return;
    const payload = event.data;
    if (!payload || payload.source !== "laysh-artifact") return;
    if (
      payload.type === "layout-height"
      && payload.version === 1
      && Number.isFinite(payload.height)
      && payload.height >= 100
      && payload.height <= 100_000
    ) {
      frame.style.height = `${Math.ceil(payload.height)}px`;
      return;
    }
    if (payload.type === "runtime-error" && payload.code === "SIM_RUNTIME_ERROR") {
      const bay = frame.closest(".observation-bay");
      frame.hidden = true;
      bay.dataset.state = "failed";
      const withheld = bay.querySelector(".withheld");
      withheld.hidden = false;
      bay.querySelector(".failed-gates").textContent = "runtime";
    }
  });

  let resizeFrame = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {
      for (const frame of document.querySelectorAll(".bay-stage iframe[src]")) {
        frame.contentWindow?.postMessage(
          { source: "laysh-host", type: "measure-layout", version: 1 },
          "*",
        );
      }
    });
  }, { passive: true });

  document.addEventListener("laysh:locale-changed", () => {
    translateSlots();
    if (lastResult) renderResult(lastResult);
    else {
      const configs = selectedCandidates();
      [...bays.values()].forEach((bay, index) => {
        bay.querySelector(".physics-effort").textContent = t(
          `modelLab.effort.${configs[index].physics.effort}`,
        );
        bay.querySelector(".visual-effort").textContent = t(
          `modelLab.effort.${configs[index].visual.effort}`,
        );
      });
      renderRunStatus(runStatus.dataset.state || "idle");
    }
    setBusy(Boolean(activeRun));
  });

  translateSlots();
  resetComparison(selectedCandidates());
  renderRunStatus("idle");
})();
