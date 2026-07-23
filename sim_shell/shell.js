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
  let scenePattern = "world_only";
  let simulation;
  let graphCanvas;
  let frameCount = 0;
  let replayStartedAt = 0;
  let replayFrom = 0;
  let replayTo = 0;
  let previousIdleAt = 0;
  let motionSampleBudget = 0;
  let playbackState = "paused";
  let destroyed = false;
  let moduleReducedMotion = reducedMotion;
  const periodicSamplesPerCycle = 74;
  const maxIdleStepMs = 100;
  const replayDurationMs = 900;

  function createAnimationClock() {
    let idleFrameId = 0;
    let replayFrameId = 0;
    return Object.freeze({
      cancelIdle() {
        if (idleFrameId) cancelAnimationFrame(idleFrameId);
        idleFrameId = 0;
      },
      cancelReplay() {
        if (replayFrameId) cancelAnimationFrame(replayFrameId);
        replayFrameId = 0;
      },
      requestIdle(callback) {
        if (idleFrameId || replayFrameId) return;
        idleFrameId = requestAnimationFrame((timestamp) => {
          idleFrameId = 0;
          callback(timestamp);
        });
      },
      requestReplay(callback) {
        replayFrameId = requestAnimationFrame((timestamp) => {
          replayFrameId = 0;
          callback(timestamp);
        });
      },
    });
  }

  const animationClock = createAnimationClock();

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
  const primaryOutputName = lesson.module_spec.outputs[0];
  const outcomeUnit = lesson.checks.find((check) => check.output === primaryOutputName)?.unit || "";
  const outputLabel = lesson.output_labels?.[primaryOutputName]
    || primaryOutputName.replaceAll("_", " ");
  byId("primary-label").textContent = parameter.label;
  Object.assign(control, {
    min: String(parameter.min),
    max: String(parameter.max),
    step: String(parameter.step),
    value: String(parameter.default),
  });

  function numericChecksForPrimaryOutput() {
    return lesson.checks
      .filter((check) => check.kind === "numeric" && check.output === primaryOutputName)
      .map((check) => ({
        input: check.inputs.find((item) => item.name === parameter.id),
        value: Number(check.expected),
      }))
      .filter((item) => item.input && Number.isFinite(Number(item.input.value))
        && Number.isFinite(item.value))
      .sort((left, right) => Number(left.input.value) - Number(right.input.value));
  }

  function graphDirectionSummary() {
    const values = numericChecksForPrimaryOutput();
    const deltas = values.slice(1).map((item, index) => item.value - values[index].value);
    const increases = deltas.length > 0 && deltas.every((delta) => delta > 0);
    const decreases = deltas.length > 0 && deltas.every((delta) => delta < 0);
    if (ar) {
      if (increases) return `يزداد مع زيادة ${parameter.label}`;
      if (decreases) return `يقل مع زيادة ${parameter.label}`;
      return `يتغير مع ${parameter.label}`;
    }
    if (increases) return `increases as ${parameter.label} increases`;
    if (decreases) return `decreases as ${parameter.label} increases`;
    return `changes with ${parameter.label}`;
  }

  function createGraphPanel() {
    if (scenePattern !== "world_plus_graph") return;
    const sceneLayout = document.createElement("div");
    sceneLayout.className = "scene-layout";
    const stage = canvas.parentElement;
    stage.insertBefore(sceneLayout, canvas);
    sceneLayout.append(canvas);
    graphCanvas = document.createElement("canvas");
    graphCanvas.id = "simulation-graph";
    graphCanvas.width = 360;
    graphCanvas.height = 300;
    graphCanvas.setAttribute("role", "img");
    graphCanvas.setAttribute("aria-label", `${outputLabel}: ${graphDirectionSummary()}`);
    sceneLayout.append(graphCanvas);
    document.body.dataset.scenePattern = scenePattern;
  }

  function graphNumber(value) {
    return new Intl.NumberFormat(lesson.lang, { maximumFractionDigits: 3 }).format(value);
  }

  function graphUnitLabel(label, unit) {
    return unit ? `${label} (${unit})` : label;
  }

  function renderGraph(value) {
    if (!graphCanvas || !simulation) return;
    const width = Math.max(220, Math.round(graphCanvas.clientWidth || graphCanvas.width));
    const height = Math.max(190, Math.round(graphCanvas.clientHeight || graphCanvas.height));
    if (graphCanvas.width !== width || graphCanvas.height !== height) {
      graphCanvas.width = width;
      graphCanvas.height = height;
    }
    const context = graphCanvas.getContext("2d");
    const pointCount = 40;
    const minimum = Number(parameter.min);
    const maximum = Number(parameter.max);
    const samples = Array.from({ length: pointCount }, (_, index) => {
      const input = minimum + ((maximum - minimum) * index) / (pointCount - 1);
      return { input, output: Number(simulation.test({ [parameter.id]: input })[primaryOutputName]) };
    }).filter((sample) => Number.isFinite(sample.output));
    if (samples.length < 2) return;
    let outputMinimum = Math.min(...samples.map((sample) => sample.output));
    let outputMaximum = Math.max(...samples.map((sample) => sample.output));
    if (outputMinimum === outputMaximum) {
      const padding = Math.max(1, Math.abs(outputMinimum) * 0.1);
      outputMinimum -= padding;
      outputMaximum += padding;
    }
    const pad = { top: 30, right: 14, bottom: 46, left: 56 };
    const plotWidth = width - pad.left - pad.right;
    const plotHeight = height - pad.top - pad.bottom;
    const x = (input) => pad.left + ((input - minimum) / (maximum - minimum || 1)) * plotWidth;
    const y = (observed) => pad.top + (1 - (observed - outputMinimum) / (outputMaximum - outputMinimum)) * plotHeight;
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#0d0f12";
    context.fillRect(0, 0, width, height);
    context.font = "600 11px Laysh Kufi, sans-serif";
    context.textBaseline = "middle";
    context.strokeStyle = "rgb(241 236 223 / 16%)";
    context.fillStyle = "#98a1ad";
    for (let index = 0; index < 4; index += 1) {
      const ratio = index / 3;
      const tickX = pad.left + ratio * plotWidth;
      const tickY = pad.top + ratio * plotHeight;
      context.beginPath();
      context.moveTo(tickX, pad.top);
      context.lineTo(tickX, pad.top + plotHeight);
      context.moveTo(pad.left, tickY);
      context.lineTo(pad.left + plotWidth, tickY);
      context.stroke();
      context.textAlign = "center";
      context.fillText(graphNumber(minimum + ratio * (maximum - minimum)), tickX, height - 27);
      context.textAlign = "right";
      context.fillText(graphNumber(outputMaximum - ratio * (outputMaximum - outputMinimum)), pad.left - 7, tickY);
    }
    context.fillStyle = "#f1ecdf";
    context.textAlign = "left";
    context.fillText(graphUnitLabel(outputLabel, outcomeUnit), pad.left, 14);
    context.textAlign = "center";
    context.fillText(graphUnitLabel(parameter.label, parameter.unit), pad.left + plotWidth / 2, height - 10);
    context.strokeStyle = "#76d6c8";
    context.lineWidth = 2;
    context.beginPath();
    samples.forEach((sample, index) => {
      if (index === 0) context.moveTo(x(sample.input), y(sample.output));
      else context.lineTo(x(sample.input), y(sample.output));
    });
    context.stroke();
    const currentInput = Number(value);
    const currentOutput = Number(simulation.test({ [parameter.id]: currentInput })[primaryOutputName]);
    const markerX = x(currentInput);
    const markerY = y(currentOutput);
    context.fillStyle = "#ffc247";
    context.beginPath();
    context.arc(markerX, markerY, 5, 0, Math.PI * 2);
    context.fill();
    graphCanvas.dataset.markerX = String(Math.round(markerX * 100) / 100);
    graphCanvas.dataset.markerY = String(Math.round(markerY * 100) / 100);
  }

  function formatState(value) {
    const tested = simulation.test({ [parameter.id]: Number(value) });
    const observed = tested[primaryOutputName];
    const valueText = readout.format(observed);
    const unitSuffix = outcomeUnit ? ` ${outcomeUnit}` : "";
    return ar
      ? `${parameter.label}: ${value} ${parameter.unit} — النتيجة المحسوبة: ${valueText}${unitSuffix}`
      : `${parameter.label}: ${value} ${parameter.unit} — calculated outcome: ${valueText}${unitSuffix}`;
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
    renderGraph(value);
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
    animationClock.cancelIdle();
  }

  function cancelReplaySweep() {
    animationClock.cancelReplay();
    replayStartedAt = 0;
  }

  function requestIdleFrame() {
    if (destroyed || playbackState !== "running") return;
    animationClock.requestIdle(scheduleIdleFrame);
  }

  function pausePlayback(reason) {
    playbackState = "paused";
    previousIdleAt = 0;
    motionSampleBudget = 0;
    cancelReplaySweep();
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
    cancelReplaySweep();
    update(control.value);
    byId("explain").hidden = false;
    syncPlaybackUi("user-control");
    requestIdleFrame();
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

  function stepReplaySweep(timestamp) {
    if (destroyed || playbackState !== "running") return;
    if (!replayStartedAt) replayStartedAt = timestamp;
    const progress = Math.min(1, Math.max(0, (timestamp - replayStartedAt) / replayDurationMs));
    const eased = progress * progress * (3 - 2 * progress);
    const value = progress >= 1 ? replayTo : replayFrom + (replayTo - replayFrom) * eased;
    control.value = String(value);
    update(control.value);
    byId("explain").hidden = false;
    if (progress < 1) animationClock.requestReplay(stepReplaySweep);
    else {
      replayStartedAt = 0;
      requestIdleFrame();
    }
  }

  function startReplaySweep() {
    cancelReplaySweep();
    cancelIdleFrame();
    replayFrom = Number(control.value);
    replayTo = replayFrom === parameter.max ? parameter.min : parameter.max;
    if (moduleReducedMotion) {
      control.value = String(replayTo);
      update(control.value);
      byId("explain").hidden = false;
      syncPlaybackUi("reduced-motion");
      return;
    }
    playbackState = "running";
    previousIdleAt = 0;
    motionSampleBudget = 0;
    syncPlaybackUi("replay");
    animationClock.requestReplay(stepReplaySweep);
  }

  byId("replay").addEventListener("click", startReplaySweep);

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
    if (destroyed || playbackState !== "running") return;
    if (simulation.setParameter.length >= 3) {
      const elapsedMs = previousIdleAt > 0
        ? Math.min(maxIdleStepMs, Math.max(0, timestamp - previousIdleAt))
        : 0;
      previousIdleAt = timestamp;
      simulation.setParameter(parameter.id, Number(control.value), elapsedMs);
      requestIdleFrame();
      return;
    }
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
    renderGraph(control.value);
  }

  try {
    simulation = window.LayshContract.assertSimulation(window.LayshSimulation);
    const representation = simulation.spec?.representation || lesson.representation;
    scenePattern = representation?.scene_pattern === "world_plus_graph"
      ? "world_plus_graph"
      : "world_only";
    createGraphPanel();
    simulation.init(simulationOptions());
    update(parameter.default);
    document.documentElement.dataset.reducedMotion = String(reducedMotion);
    if (reducedMotion) pausePlayback("reduced-motion");
    else resumePlayback("autoplay");
    window.addEventListener("resize", resize, { passive: true });
    window.addEventListener("pagehide", () => {
      destroyed = true;
      cancelReplaySweep();
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
