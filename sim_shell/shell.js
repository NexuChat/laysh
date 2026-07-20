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
        pause: "إيقاف المسح التلقائي",
        play: "متابعة المسح التلقائي",
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
        pause: "Pause auto-sweep",
        play: "Resume auto-sweep",
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
  const MOBILE_CANVAS_BREAKPOINT = 430;
  const MOBILE_CANVAS_ASPECT_RATIO = 0.76;
  const DESKTOP_CANVAS_ASPECT_RATIO = 0.56;
  const MINIMUM_CANVAS_WIDTH = 280;
  const MAXIMUM_CANVAS_WIDTH = 720;
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
    sweepPaused: reducedMotion,
    interacting: false,
    lastTimestamp: null,
    lastSettleRedraw: 0,
    sweepElapsedTime: 0,
    phenomenonElapsedTime: 0,
  };
  let simulation;
  let frameCount = 0;
  let animationFrameId = 0;
  let heightReportFrame = 0;
  let overlayRects = [];

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
    scheduleContentHeightReport();
  }

  function reportContentHeight() {
    heightReportFrame = 0;
    if (window.parent === window || document.body.classList.contains("projector-mode")) return;
    const scrollHeight = Math.ceil(Math.max(
      document.documentElement.scrollHeight,
      document.body.scrollHeight,
    ));
    const interactiveUnitBottom = Math.ceil(Math.max(
      canvas.getBoundingClientRect().bottom,
      control.getBoundingClientRect().bottom,
      playPause.getBoundingClientRect().bottom,
    ) + window.scrollY);
    window.parent.postMessage(
      {
        source: "laysh-artifact",
        type: "content-height",
        version: 1,
        height: scrollHeight,
        scrollHeight,
        clientHeight: document.documentElement.clientHeight,
        interactiveUnitBottom,
        canvasWidth: canvas.width,
        canvasHeight: canvas.height,
      },
      "*",
    );
  }

  function scheduleContentHeightReport() {
    if (!heightReportFrame) heightReportFrame = requestAnimationFrame(reportContentHeight);
  }

  function beginOverlayFrame() {
    overlayRects = [];
    window.__LAYSH_OVERLAY_RECTS__ = overlayRects;
  }

  function registerOverlayRect(rect) {
    if (!rect || ![rect.x, rect.y, rect.width, rect.height].every(Number.isFinite)) return;
    overlayRects.push({
      x: Number(rect.x),
      y: Number(rect.y),
      width: Math.max(0, Number(rect.width)),
      height: Math.max(0, Number(rect.height)),
      role: rect.role === "essential-state" ? "essential-state" : "readout",
    });
  }

  function simulationTime() {
    const verificationTime = Number(window.__LAYSH_VERIFICATION_TIME__);
    return Number.isFinite(verificationTime)
      ? verificationTime
      : state.phenomenonElapsedTime;
  }

  function update(value, syncControl = true) {
    state.value = Math.max(Number(parameter.min), Math.min(Number(parameter.max), Number(value)));
    document.documentElement.dataset.parameterValue = String(state.value);
    beginOverlayFrame();
    simulation.setParameter(parameter.id, state.value, simulationTime());
    if (syncControl) control.value = String(state.value);
    const parameterText = displayValue(state.value);
    output.value = `${parameterText} ${parameter.unit}`;
    description.textContent = formatState(state.value);
  }

  function syncPlayback() {
    playPause.textContent = state.sweepPaused ? labels.play : labels.pause;
    playPause.setAttribute("aria-pressed", String(state.sweepPaused));
    const sweepState = state.sweepPaused ? "paused" : "playing";
    document.documentElement.dataset.motionState = sweepState;
    document.documentElement.dataset.sweepState = sweepState;
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
    state.sweepPaused = !state.sweepPaused;
    state.lastTimestamp = null;
    syncPlayback();
  });

  byId("reset").addEventListener("click", () => {
    state.direction = 1;
    state.sweepPaused = reducedMotion;
    state.interacting = false;
    state.lastTimestamp = null;
    state.sweepElapsedTime = 0;
    state.phenomenonElapsedTime = 0;
    update(parameter.default);
    syncPlayback();
  });

  function syncProjectorState(active) {
    document.body.classList.toggle("projector-mode", active);
    byId("projector").textContent = active ? labels.exitProjector : labels.projector;
    byId("projector").setAttribute("aria-pressed", String(active));
    requestAnimationFrame(() => {
      resize();
      scheduleContentHeightReport();
    });
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
    else requestAnimationFrame(resize);
  });

  function animate(timestamp) {
    if (state.lastTimestamp === null) state.lastTimestamp = timestamp;
    const deltaSeconds = Math.min(0.1, Math.max(0, timestamp - state.lastTimestamp) / 1000);
    state.lastTimestamp = timestamp;
    if (!reducedMotion) state.phenomenonElapsedTime += deltaSeconds;
    document.documentElement.dataset.phenomenonTime = String(state.phenomenonElapsedTime);
    if (!state.sweepPaused && !state.interacting) {
      state.sweepElapsedTime += deltaSeconds;
      advanceParameter(deltaSeconds);
    } else if (!reducedMotion) {
      update(state.value);
    } else if (timestamp - state.lastSettleRedraw >= SETTLE_REDRAW_INTERVAL_MS) {
      state.lastSettleRedraw = timestamp;
      beginOverlayFrame();
      simulation.setParameter(parameter.id, state.value, simulationTime());
    }
    animationFrameId = requestAnimationFrame(animate);
  }

  function responsiveCanvasSize() {
    const width = Math.max(
      MINIMUM_CANVAS_WIDTH,
      Math.min(MAXIMUM_CANVAS_WIDTH, Math.round(canvas.clientWidth || MAXIMUM_CANVAS_WIDTH)),
    );
    const ratio = width < MOBILE_CANVAS_BREAKPOINT
      ? MOBILE_CANVAS_ASPECT_RATIO
      : DESKTOP_CANVAS_ASPECT_RATIO;
    return { width, height: Math.round(width * ratio) };
  }

  function resize() {
    const size = responsiveCanvasSize();
    if (canvas.width === size.width && canvas.height === size.height) {
      scheduleContentHeightReport();
      return;
    }
    canvas.width = size.width;
    canvas.height = size.height;
    if (simulation) {
      beginOverlayFrame();
      simulation.resize(size.width, size.height);
    }
    scheduleContentHeightReport();
  }

  try {
    simulation = window.LayshContract.assertSimulation(window.LayshSimulation);
    const initialSize = responsiveCanvasSize();
    canvas.width = initialSize.width;
    canvas.height = initialSize.height;
    beginOverlayFrame();
    simulation.init({
      canvas,
      context: canvas.getContext("2d"),
      width: initialSize.width,
      height: initialSize.height,
      locale: lesson.lang,
      reducedMotion,
      emitFrame,
      registerOverlayRect,
    });
    update(parameter.default);
    syncPlayback();
    animationFrameId = requestAnimationFrame(animate);
    window.addEventListener("resize", resize, { passive: true });
    new ResizeObserver(scheduleContentHeightReport).observe(byId("lesson"));
    scheduleContentHeightReport();
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
