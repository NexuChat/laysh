(() => {
  "use strict";
  const lesson = window.__LAYSH_LESSON__;
  const dir = document.documentElement.dir;
  const ar = lesson.lang === "ar";
  const labels = ar
    ? {
        lesson: "الجواب التفاعلي",
        predict: "توقّع أولًا",
        observe: "لاحظ ما يتغيّر",
        explain: "فسّر ما رأيت",
        reset: "إعادة الضبط",
        replay: "إعادة العرض",
        runtimeTitle: "تعذّر تشغيل المحاكاة",
        runtimeCopy: "يمكنك الاحتفاظ بالجواب والمحاولة مرة أخرى من Laysh.",
      }
    : {
        lesson: "Interactive answer",
        predict: "Predict first",
        observe: "Observe what changes",
        explain: "Explain what you saw",
        reset: "Reset",
        replay: "Replay",
        runtimeTitle: "The simulation could not run",
        runtimeCopy: "Keep the answer and try again from Laysh.",
      };

  const byId = (id) => document.getElementById(id);
  const canvas = byId("simulation");
  const control = byId("primary-control");
  const output = byId("primary-output");
  const description = byId("state-description");
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let simulation;
  let frameCount = 0;

  document.body.dataset.direction = dir === "rtl" ? "rtl" : "ltr";
  byId("lesson-label").textContent = labels.lesson;
  byId("lesson-title").textContent = lesson.title;
  byId("answer").textContent = lesson.tldr;
  byId("formula").textContent = lesson.key_formula || "";
  byId("prediction-title").textContent = labels.predict;
  byId("prediction-prompt").textContent = lesson.prediction.prompt;
  byId("observe-title").textContent = labels.observe;
  byId("explain-title").textContent = labels.explain;
  byId("explanation-prompt").textContent = lesson.explanation_prompt;
  byId("misconception").textContent = lesson.misconception;
  byId("transfer").textContent = lesson.transfer_prompt || "";
  byId("reset").textContent = labels.reset;
  byId("replay").textContent = labels.replay;
  byId("runtime-error-title").textContent = labels.runtimeTitle;
  byId("runtime-error-copy").textContent = labels.runtimeCopy;

  const parameter = lesson.primary_parameter;
  byId("primary-label").textContent = parameter.label;
  Object.assign(control, {
    min: String(parameter.min),
    max: String(parameter.max),
    step: String(parameter.step),
    value: String(parameter.default),
  });

  function formatState(value) {
    const tested = simulation.test({ [parameter.id]: Number(value) });
    const observed = tested[lesson.module_spec.outputs[0]];
    const valueText = Number.isFinite(observed) ? Number(observed).toFixed(2) : String(observed);
    return ar
      ? `${parameter.label}: ${value} ${parameter.unit} — النتيجة المحسوبة: ${valueText}`
      : `${parameter.label}: ${value} ${parameter.unit} — calculated outcome: ${valueText}`;
  }

  function emitFrame() {
    frameCount += 1;
    document.documentElement.dataset.frameCount = String(frameCount);
    document.documentElement.dataset.layshReady = "true";
    if (window.parent !== window) {
      window.parent.postMessage({ source: "laysh-artifact", type: "ready", version: 1 }, "*");
    }
  }

  function update(value) {
    simulation.setParameter(parameter.id, Number(value));
    output.value = `${value} ${parameter.unit}`;
    description.textContent = formatState(value);
  }

  function selectPrediction(button) {
    for (const choice of byId("prediction-choices").querySelectorAll("button")) {
      choice.setAttribute("aria-pressed", String(choice === button));
    }
    control.disabled = false;
    control.focus();
  }

  for (const choice of lesson.prediction.choices) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = choice;
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", () => selectPrediction(button));
    byId("prediction-choices").append(button);
  }

  control.addEventListener("input", () => {
    update(control.value);
    byId("explain").hidden = false;
  });

  byId("reset").addEventListener("click", () => {
    control.value = String(parameter.default);
    update(control.value);
  });

  byId("replay").addEventListener("click", () => {
    const replayValue = Number(control.value) === parameter.max ? parameter.min : parameter.max;
    control.value = String(replayValue);
    update(control.value);
    byId("explain").hidden = false;
  });

  function resize() {
    const width = Math.max(280, Math.min(720, canvas.clientWidth || 720));
    const height = Math.round(width * 0.56);
    canvas.width = width;
    canvas.height = height;
    simulation.resize(width, height);
  }

  try {
    simulation = window.LayshContract.assertSimulation(window.LayshSimulation);
    simulation.init({
      canvas,
      context: canvas.getContext("2d"),
      width: canvas.width,
      height: canvas.height,
      locale: lesson.lang,
      reducedMotion,
      emitFrame,
    });
    update(parameter.default);
    window.addEventListener("resize", resize, { passive: true });
    window.addEventListener("pagehide", () => simulation.destroy(), { once: true });
  } catch {
    byId("runtime-error").hidden = false;
    document.documentElement.dataset.runtimeError = "SIM_RUNTIME_ERROR";
    if (window.parent !== window) {
      window.parent.postMessage(
        { source: "laysh-artifact", type: "runtime-error", code: "SIM_RUNTIME_ERROR" },
        "*",
      );
    }
  }
})();
