window.LayshSimulation = (() => {
  "use strict";
  let canvas;
  let context;
  let width;
  let height;
  let emitFrame;
  let value = 0.25;

  function model(input) {
    return { response_strength: 10 + Number(input) * 20 };
  }

  function draw() {
    const response = model(value).response_strength;
    const size = 12 + response * 0.8;
    const x = width * 0.28 + value * width * 0.5;
    const y = height * 0.5;
    context.clearRect(0, 0, width, height);
    context.fillStyle = "rgb(8 18 34)";
    context.fillRect(0, 0, width, height);
    context.fillStyle = "rgb(31 211 174)";
    context.fillRect(x - size / 2, y - size / 2, size, size);
    emitFrame();
  }

  return {
    version: 1,
    init(options) {
      ({ canvas, context, width, height, emitFrame } = options);
      draw();
    },
    setParameter(name, nextValue) {
      if (name === "stimulus") value = Number(nextValue);
      draw();
    },
    test(inputs) {
      return model(inputs.stimulus);
    },
    resize(nextWidth, nextHeight) {
      width = nextWidth;
      height = nextHeight;
      canvas.width = nextWidth;
      canvas.height = nextHeight;
      draw();
    },
    destroy() {},
  };
})();
