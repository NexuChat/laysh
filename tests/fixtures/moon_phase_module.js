window.LayshSimulation = (() => {
  "use strict";
  let canvas;
  let context;
  let width;
  let height;
  let emitFrame;
  let angleDeg = 90;
  let phenomenonTimeSeconds = 0;
  let reducedMotion = false;

  function litFraction(angle) {
    return (1 - Math.cos((angle * Math.PI) / 180)) / 2;
  }

  function draw() {
    const fraction = litFraction(angleDeg);
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#071520";
    context.fillRect(0, 0, width, height);
    const orbitOffset = Math.sin(phenomenonTimeSeconds * Math.PI * 2 / 12)
      * Math.min(width, height) * 0.12;
    context.beginPath();
    context.arc(width / 2 + orbitOffset, height / 2, Math.min(width, height) * 0.27, 0, Math.PI * 2);
    context.fillStyle = `rgb(${Math.round(42 + fraction * 213)} ${Math.round(51 + fraction * 184)} ${Math.round(61 + fraction * 102)})`;
    context.fill();
    const actorAngle = ((angleDeg + phenomenonTimeSeconds * 360 / 12) * Math.PI) / 180;
    const actorRadiusX = Math.min(width, height) * 0.32;
    const actorRadiusY = Math.min(width, height) * 0.2;
    context.beginPath();
    context.arc(
      width / 2 + Math.cos(actorAngle) * actorRadiusX,
      height / 2 + Math.sin(actorAngle) * actorRadiusY,
      Math.max(7, Math.min(width, height) * 0.025),
      0,
      Math.PI * 2,
    );
    context.fillStyle = "rgb(255 118 92)";
    context.fill();
    emitFrame();
  }

  return {
    version: 1,
    init(options) {
      ({ canvas, context, width, height, emitFrame } = options);
      reducedMotion = options.reducedMotion;
      draw();
    },
    setParameter(name, value, timeSeconds) {
      if (name !== "angle_deg") return;
      angleDeg = Math.max(0, Math.min(360, Number(value)));
      phenomenonTimeSeconds = Number.isFinite(Number(timeSeconds))
        ? Math.max(0, Number(timeSeconds))
        : 0;
      draw();
    },
    test(inputs) {
      return { lit_fraction: litFraction(Number(inputs.angle_deg)) };
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
