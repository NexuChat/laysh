(() => {
  "use strict";
  const lesson = window.__LAYSH_LESSON__;
  const dir = document.documentElement.dir;
  const ar = lesson.lang === "ar";
  const labels = ar
    ? {
        lesson: "الجواب التفاعلي",
        observe: "لاحظ ما يتغيّر",
        explain: "فسّر ما رأيت",
        reset: "إعادة الضبط",
        pause: "إيقاف الحركة",
        play: "متابعة الحركة",
        projector: "وضع العرض",
        exitProjector: "إنهاء العرض",
        answerDetails: "اقرأ الجواب الكامل",
        runtimeTitle: "تعذّر تشغيل المحاكاة",
        runtimeCopy: "يمكنك الاحتفاظ بالجواب والمحاولة مرة أخرى من Laysh.",
        misconceptionLabel: "⚠ خرافة شائعة",
        instrumentNav: "أدوات العرض",
        brandLabel: "ليش",
      }
    : {
        lesson: "Interactive answer",
        observe: "Observe what changes",
        explain: "Explain what you saw",
        reset: "Reset",
        pause: "Pause motion",
        play: "Resume motion",
        projector: "Projector mode",
        exitProjector: "Exit projector",
        answerDetails: "Read the full answer",
        runtimeTitle: "The simulation could not run",
        runtimeCopy: "Keep the answer and try again from Laysh.",
        misconceptionLabel: "⚠ Common myth",
        instrumentNav: "Display tools",
        brandLabel: "Laysh",
      };

  const SWEEP_CYCLE_SECONDS = 24;
  const SWEEP_HALF_CYCLE_SECONDS = 10;
  const SETTLE_REDRAW_INTERVAL_MS = 80;
  const byId = (id) => document.getElementById(id);
  const canvas = byId("simulation");
  const control = byId("primary-control");
  const output = byId("primary-output");
  const description = byId("state-description");
  const playPause = byId("play-pause");
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const compactLayout = matchMedia("(max-width: 480px)");
  const parameter = lesson.primary_parameter;
  const state = {
    value: Number(parameter.default),
    direction: 1,
    paused: reducedMotion,
    interacting: false,
    lastTimestamp: null,
    lastSettleRedraw: 0,
  };
  let simulation;
  let frameCount = 0;
  let animationFrameId = 0;

  document.body.dataset.direction = dir === "rtl" ? "rtl" : "ltr";
  byId("lesson-label").textContent = labels.lesson;
  byId("instrument-bar").setAttribute("aria-label", labels.instrumentNav);
  byId("instrument-brand").setAttribute("aria-label", labels.brandLabel);
  byId("lesson-title").textContent = lesson.title;
  byId("answer").textContent = lesson.tldr;
  byId("answer-summary").textContent = labels.answerDetails;
  byId("formula").textContent = lesson.key_formula || "";
  byId("observe-title").textContent = labels.observe;
  byId("explain-title").textContent = labels.explain;
  byId("explanation-prompt").textContent = lesson.explanation_prompt;
  byId("misconception-label").textContent = labels.misconceptionLabel;
  byId("misconception-copy").textContent = lesson.misconception;
  byId("transfer").textContent = lesson.transfer_prompt || "";
  byId("reset").textContent = labels.reset;
  byId("projector").textContent = labels.projector;
  byId("runtime-error-title").textContent = labels.runtimeTitle;
  byId("runtime-error-copy").textContent = labels.runtimeCopy;

  function syncCompactAnswer() {
    if (compactLayout.matches) byId("answer-detail").open = false;
  }
  syncCompactAnswer();
  compactLayout.addEventListener("change", syncCompactAnswer);

  byId("primary-label").textContent = parameter.label;
  Object.assign(control, {
    min: String(parameter.min),
    max: String(parameter.max),
    step: String(parameter.step),
    value: String(parameter.default),
  });

  function displayValue(value) {
    const stepText = String(parameter.step);
    const decimals = stepText.includes(".") ? stepText.split(".")[1].length : 0;
    return Number(value).toFixed(Math.min(decimals, 4));
  }

  function formatState(value) {
    const tested = simulation.test({ [parameter.id]: Number(value) });
    const observed = tested[lesson.module_spec.outputs[0]];
    const valueText = Number.isFinite(observed) ? Number(observed).toFixed(2) : String(observed);
    const parameterText = displayValue(value);
    return ar
      ? `${parameter.label}: ${parameterText} ${parameter.unit} — النتيجة المحسوبة: ${valueText}`
      : `${parameter.label}: ${parameterText} ${parameter.unit} — calculated outcome: ${valueText}`;
  }

  function emitFrame() {
    frameCount += 1;
    document.documentElement.dataset.frameCount = String(frameCount);
    document.documentElement.dataset.layshReady = "true";
    if (window.parent !== window) {
      window.parent.postMessage({ source: "laysh-artifact", type: "ready", version: 1 }, "*");
    }
  }

  function update(value, syncControl = true) {
    state.value = Math.max(Number(parameter.min), Math.min(Number(parameter.max), Number(value)));
    simulation.setParameter(parameter.id, state.value);
    if (syncControl) control.value = String(state.value);
    const parameterText = displayValue(state.value);
    output.value = `${parameterText} ${parameter.unit}`;
    description.textContent = formatState(state.value);
  }

  function syncPlayback() {
    playPause.textContent = state.paused ? labels.play : labels.pause;
    playPause.setAttribute("aria-pressed", String(state.paused));
    document.documentElement.dataset.motionState = state.paused ? "paused" : "playing";
  }

  function advanceParameter(deltaSeconds) {
    const minimum = Number(parameter.min);
    const maximum = Number(parameter.max);
    const span = maximum - minimum;
    if (!(span > 0) || !(deltaSeconds > 0)) return;
    if (parameter.sweep_mode === "cyclic") {
      const rate = span / SWEEP_CYCLE_SECONDS;
      update(minimum + ((state.value - minimum + rate * deltaSeconds) % span));
      return;
    }
    const rate = span / SWEEP_HALF_CYCLE_SECONDS;
    let next = state.value + state.direction * rate * deltaSeconds;
    while (next > maximum || next < minimum) {
      if (next > maximum) {
        next = maximum - (next - maximum);
        state.direction = -1;
      } else {
        next = minimum + (minimum - next);
        state.direction = 1;
      }
    }
    update(next);
  }

  function beginInteraction() {
    state.interacting = true;
    state.lastTimestamp = null;
  }

  function endInteraction() {
    state.interacting = false;
    state.lastTimestamp = null;
  }

  control.addEventListener("input", () => update(Number(control.value), false));
  control.addEventListener("pointerdown", beginInteraction);
  control.addEventListener("pointerup", endInteraction);
  control.addEventListener("pointercancel", endInteraction);
  control.addEventListener("lostpointercapture", endInteraction);
  control.addEventListener("keydown", beginInteraction);
  control.addEventListener("keyup", endInteraction);
  control.addEventListener("blur", endInteraction);

  playPause.addEventListener("click", () => {
    state.paused = !state.paused;
    state.lastTimestamp = null;
    syncPlayback();
  });

  byId("reset").addEventListener("click", () => {
    state.direction = 1;
    state.paused = reducedMotion;
    state.interacting = false;
    state.lastTimestamp = null;
    update(parameter.default);
    syncPlayback();
  });

  function syncProjectorState(active) {
    document.body.classList.toggle("projector-mode", active);
    byId("projector").textContent = active ? labels.exitProjector : labels.projector;
    byId("projector").setAttribute("aria-pressed", String(active));
  }

  byId("projector").addEventListener("click", async () => {
    const active = !document.body.classList.contains("projector-mode");
    syncProjectorState(active);
    try {
      if (active && !document.fullscreenElement) await document.documentElement.requestFullscreen();
      if (!active && document.fullscreenElement) await document.exitFullscreen();
    } catch {
      // The projector layout remains available when fullscreen permission is denied.
    }
  });
  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement) syncProjectorState(false);
  });

  function animate(timestamp) {
    if (state.lastTimestamp === null) state.lastTimestamp = timestamp;
    const deltaSeconds = Math.min(0.1, Math.max(0, timestamp - state.lastTimestamp) / 1000);
    state.lastTimestamp = timestamp;
    if (!state.paused && !state.interacting) {
      advanceParameter(deltaSeconds);
    } else if (timestamp - state.lastSettleRedraw >= SETTLE_REDRAW_INTERVAL_MS) {
      state.lastSettleRedraw = timestamp;
      simulation.setParameter(parameter.id, state.value);
    }
    animationFrameId = requestAnimationFrame(animate);
  }

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
    syncPlayback();
    animationFrameId = requestAnimationFrame(animate);
    window.addEventListener("resize", resize, { passive: true });
    window.addEventListener("pagehide", () => {
      cancelAnimationFrame(animationFrameId);
      simulation.destroy();
    }, { once: true });
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
