(() => {
  "use strict";
  const required = ["destroy", "init", "resize", "setParameter", "test", "version"];

  window.LayshContract = Object.freeze({
    assertSimulation(simulation) {
      if (!simulation || typeof simulation !== "object") throw new Error("SIM_CONTRACT_MISSING");
      const keys = Object.keys(simulation).sort();
      if (JSON.stringify(keys) !== JSON.stringify(required)) throw new Error("SIM_CONTRACT_KEYS");
      if (simulation.version !== 1) throw new Error("SIM_CONTRACT_VERSION");
      for (const method of ["init", "setParameter", "test", "resize", "destroy"]) {
        if (typeof simulation[method] !== "function") throw new Error("SIM_CONTRACT_METHOD");
      }
      return simulation;
    },
  });
})();

