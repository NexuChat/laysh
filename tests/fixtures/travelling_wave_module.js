window.LayshSimulation = (() => {
  "use strict";
  let canvas;
  let context;
  let width;
  let height;
  let emitFrame;
  let frequency = 440;
  let phenomenonTimeSeconds = 0;

  function model(value) {
    const bounded = Math.max(110, Math.min(880, Number(value)));
    return {
      wavelength_m: 343 / bounded,
      period_ms: 1000 / bounded,
    };
  }

  function draw() {
    const values = model(frequency);
    const cycles = 2 * frequency / 110;
    const phase = 2 * Math.PI * frequency * phenomenonTimeSeconds;
    context.clearRect(0, 0, width, height);
    context.fillStyle = "rgb(5 17 30)";
    context.fillRect(0, 0, width, height);
    context.strokeStyle = "rgb(103 232 249)";
    context.lineWidth = Math.max(5, height * 0.025);
    context.beginPath();
    for (let x = 0; x < width; x += 2) {
      const y = height / 2 + Math.sin(2 * Math.PI * cycles * x / width - phase) * height * 0.24;
      if (x === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    }
    context.stroke();
    context.fillStyle = `rgba(255, 196, 92, ${0.18 + values.wavelength_m * 0.08})`;
    context.fillRect(0, height * 0.82, width, height * 0.08);
    emitFrame();
  }

  return {
    version: 1,
    init(options) {
      ({ canvas, context, width, height, emitFrame } = options);
      draw();
    },
    setParameter(name, value, timeSeconds) {
      if (name !== "frequency_hz") return;
      frequency = Math.max(110, Math.min(880, Number(value)));
      phenomenonTimeSeconds = Number.isFinite(Number(timeSeconds)) ? Number(timeSeconds) : 0;
      draw();
    },
    test(inputs) {
      return model(inputs.frequency_hz);
    },
    resize(nextWidth, nextHeight) {
      width = nextWidth;
      height = nextHeight;
      canvas.width = nextWidth;
      canvas.height = nextHeight;
      draw();
    },
    destroy() {
      canvas = null;
      context = null;
    },
  };
})();
