window.LayshSimulation = (() => {
  "use strict";
  let canvas;
  let context;
  let width;
  let height;
  let emitFrame;
  let angleDeg = 90;

  /* LAYSH_SHARED_MODEL: moonState */
  function moonState(value) {
    const numeric = Number(value);
    const angle = Number.isFinite(numeric) ? Math.max(0, Math.min(360, numeric)) : 90;
    return {
      angle_deg: angle,
      lit_fraction: (1 - Math.cos((angle * Math.PI) / 180)) / 2,
    };
  }

  function draw() {
    const state = moonState(angleDeg);
    const fraction = state.lit_fraction;
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#071520";
    context.fillRect(0, 0, width, height);
    context.beginPath();
    context.arc(width / 2, height / 2, Math.min(width, height) * 0.27, 0, Math.PI * 2);
    context.fillStyle = `rgb(${Math.round(42 + fraction * 213)} ${Math.round(51 + fraction * 184)} ${Math.round(61 + fraction * 102)})`;
    context.fill();
    canvas.__layshSceneGeometry = [{
      schemaVersion: "1.0",
      phase: "post_fit",
      viewport: { width, height, safeInset: 0 },
      state: { id: "rendered", timeMs: 0 },
      objects: [{
        id: "actor",
        scientific: true,
        clippingPolicy: "forbid",
        geometry: {
          type: "circle",
          cx: width / 2,
          cy: height / 2,
          radius: Math.min(width, height) * 0.27,
        },
      }],
      relations: [],
    }];
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
      const state = moonState(Number(inputs.angle_deg));
      return { lit_fraction: state.lit_fraction };
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
