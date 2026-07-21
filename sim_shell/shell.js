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
        misconception: "فكرة شائعة تحتاج إلى تصحيح",
        pause: "إيقاف الحركة",
        resume: "استئناف الحركة",
        running: "الحركة تعمل",
        paused: "الحركة متوقفة",
        reset: "إعادة الضبط",
        replay: "إعادة العرض",
        projector: "وضع العرض",
        exitProjector: "إنهاء العرض",
        answerDetails: "اقرأ الجواب الكامل",
        runtimeTitle: "تعذّر تشغيل المحاكاة",
        runtimeCopy: "يمكنك الاحتفاظ بالجواب والمحاولة مرة أخرى من Laysh.",
      }
    : {
        lesson: "Interactive answer",
        predict: "Predict first",
        observe: "Observe what changes",
        explain: "Explain what you saw",
        misconception: "Common misconception",
        pause: "Pause motion",
        resume: "Resume motion",
        running: "Motion is playing",
        paused: "Motion is paused",
        reset: "Reset",
        replay: "Replay",
        projector: "Projector mode",
        exitProjector: "Exit projector",
        answerDetails: "Read the full answer",
        runtimeTitle: "The simulation could not run",
        runtimeCopy: "Keep the answer and try again from Laysh.",
      };

  const byId = (id) => document.getElementById(id);
  const canvas = byId("simulation");
  const control = byId("primary-control");
  const output = byId("primary-output");
  const description = byId("state-description");
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const compactLayout = matchMedia("(max-width: 480px)");
  let simulation;
  let frameCount = 0;
  let idleFrameId = 0;
  let previousIdleAt = 0;
  let motionSampleBudget = 0;
  let playbackState = "paused";
  let destroyed = false;
  let moduleReducedMotion = reducedMotion;
  const periodicSamplesPerCycle = 74;
  const maxIdleStepMs = 100;

  document.body.dataset.direction = dir === "rtl" ? "rtl" : "ltr";
  byId("lesson-label").textContent = labels.lesson;
  byId("lesson-title").textContent = lesson.title;
  byId("answer").textContent = lesson.tldr;
  byId("answer-summary").textContent = labels.answerDetails;
  byId("formula").textContent = lesson.key_formula || "";
  byId("prediction-title").textContent = labels.predict;
  byId("prediction-prompt").textContent = lesson.prediction.prompt;
  byId("observe-title").textContent = labels.observe;
  byId("explain-title").textContent = labels.explain;
  byId("explanation-prompt").textContent = lesson.explanation_prompt;
  byId("misconception-label").textContent = labels.misconception;
  byId("misconception").textContent = lesson.misconception;
  byId("transfer").textContent = lesson.transfer_prompt || "";
  byId("play-pause").textContent = labels.resume;
  byId("reset").textContent = labels.reset;
  byId("replay").textContent = labels.replay;
  byId("projector").textContent = labels.projector;
  byId("runtime-error-title").textContent = labels.runtimeTitle;
  byId("runtime-error-copy").textContent = labels.runtimeCopy;
  function syncCompactAnswer() {
    if (compactLayout.matches) byId("answer-detail").open = false;
  }
  syncCompactAnswer();
  compactLayout.addEventListener("change", syncCompactAnswer);

  const parameter = lesson.primary_parameter;
  const readout = window.LayshReadout.forLesson(lesson);
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
    const valueText = readout.format(observed);
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

  function syncPlaybackUi(reason) {
    const running = playbackState === "running";
    document.documentElement.dataset.playbackState = playbackState;
    document.documentElement.dataset.playbackReason = reason;
    const toggle = byId("play-pause");
    toggle.textContent = running ? labels.pause : labels.resume;
    toggle.setAttribute("aria-pressed", String(!running));
    byId("playback-status").textContent = running ? labels.running : labels.paused;
  }

  function cancelIdleFrame() {
    if (!idleFrameId) return;
    cancelAnimationFrame(idleFrameId);
    idleFrameId = 0;
  }

  function requestIdleFrame() {
    if (destroyed || playbackState !== "running" || idleFrameId) return;
    idleFrameId = requestAnimationFrame(scheduleIdleFrame);
  }

  function pausePlayback(reason) {
    playbackState = "paused";
    previousIdleAt = 0;
    motionSampleBudget = 0;
    cancelIdleFrame();
    syncPlaybackUi(reason);
  }

  function resumePlayback(reason) {
    if (destroyed) return;
    if (moduleReducedMotion) {
      const value = Number(control.value);
      simulation.destroy();
      moduleReducedMotion = false;
      simulation.init(simulationOptions());
      simulation.setParameter(parameter.id, value);
    }
    playbackState = "running";
    previousIdleAt = 0;
    motionSampleBudget = 0;
    syncPlaybackUi(reason);
    requestIdleFrame();
  }

  function selectPrediction(button) {
    for (const choice of byId("prediction-choices").querySelectorAll("button")) {
      choice.setAttribute("aria-pressed", String(choice === button));
    }
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
    pausePlayback("user-control");
    update(control.value);
    byId("explain").hidden = false;
  });

  function simulationOptions() {
    return {
      canvas,
      context: canvas.getContext("2d"),
      width: canvas.width,
      height: canvas.height,
      locale: lesson.lang,
      reducedMotion: moduleReducedMotion,
      emitFrame,
    };
  }

  function resetSimulation() {
    pausePlayback("reset");
    simulation.destroy();
    simulation.init(simulationOptions());
    control.value = String(parameter.default);
    update(control.value);
    byId("explain").hidden = true;
  }

  byId("play-pause").addEventListener("click", () => {
    if (playbackState === "running") pausePlayback("user");
    else resumePlayback("user");
  });

  byId("reset").addEventListener("click", resetSimulation);

  byId("replay").addEventListener("click", () => {
    const replayValue = Number(control.value) === parameter.max ? parameter.min : parameter.max;
    control.value = String(replayValue);
    update(control.value);
    byId("explain").hidden = false;
    resumePlayback("replay");
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

  function scheduleIdleFrame(timestamp = 0) {
    idleFrameId = 0;
    if (destroyed || playbackState !== "running") return;
    if (lesson.module_spec.action === "oscillates") {
      if (previousIdleAt > 0) {
        const elapsedMs = Math.min(maxIdleStepMs, Math.max(0, timestamp - previousIdleAt));
        const model = simulation.test({ [parameter.id]: Number(control.value) });
        const periodOutput = lesson.module_spec.outputs.find(
          (name) => /(?:^|_)(?:period|duration)_s$/.test(name),
        );
        const periodSeconds = Number(periodOutput && model && model[periodOutput]);
        if (Number.isFinite(periodSeconds) && periodSeconds > 0) {
          motionSampleBudget += (elapsedMs / (periodSeconds * 1000)) * periodicSamplesPerCycle;
          const redrawCount = Math.min(
            8,
            Math.floor(motionSampleBudget),
          );
          for (let index = 0; index < redrawCount; index += 1) {
            simulation.setParameter(parameter.id, Number(control.value));
          }
          motionSampleBudget -= redrawCount;
        }
      }
      previousIdleAt = timestamp;
      requestIdleFrame();
      return;
    }
    if (timestamp - previousIdleAt >= 80) {
      previousIdleAt = timestamp;
      simulation.setParameter(parameter.id, Number(control.value));
    }
    requestIdleFrame();
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
    simulation.init(simulationOptions());
    update(parameter.default);
    document.documentElement.dataset.reducedMotion = String(reducedMotion);
    if (reducedMotion) pausePlayback("reduced-motion");
    else resumePlayback("autoplay");
    window.addEventListener("resize", resize, { passive: true });
    window.addEventListener("pagehide", () => {
      destroyed = true;
      cancelIdleFrame();
      simulation.destroy();
      playbackState = "destroyed";
      syncPlaybackUi("pagehide");
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
