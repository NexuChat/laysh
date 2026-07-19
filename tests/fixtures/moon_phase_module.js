window.LayshSimulation = (() => {
  "use strict";
  let canvas;
  let context;
  let width;
  let height;
  let emitFrame;
  let angleDeg = 90;

  function litFraction(angle) {
    return (1 - Math.cos((angle * Math.PI) / 180)) / 2;
  }

  function draw() {
    const fraction = litFraction(angleDeg);
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#071520";
    context.fillRect(0, 0, width, height);
    context.beginPath();
    context.arc(width / 2, height / 2, Math.min(width, height) * 0.27, 0, Math.PI * 2);
    context.fillStyle = `rgb(${Math.round(42 + fraction * 213)} ${Math.round(51 + fraction * 184)} ${Math.round(61 + fraction * 102)})`;
    context.fill();
    emitFrame();
  }

  return {
    version: 1,
    init(options) {
      ({ canvas, context, width, height, emitFrame } = options);
      draw();
    },
    setParameter(name, value) {
      if (name !== "angle_deg") return;
      angleDeg = Math.max(0, Math.min(360, Number(value)));
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

