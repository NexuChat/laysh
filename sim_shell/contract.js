(() => {
  "use strict";
  const required = ["destroy", "init", "resize", "setParameter", "test", "version"];
  const minimumFractionDigits = 2;
  const maximumFractionDigits = 8;

  function endpointChecks(lesson) {
    const parameter = lesson.primary_parameter;
    const output = lesson.module_spec.outputs[0];
    const declared = lesson.checks
      .filter((check) => check.kind === "numeric" && check.output === output)
      .map((check) => ({
        check,
        parameterInput: check.inputs.find((input) => input.name === parameter.id),
      }))
      .filter(({ parameterInput }) => parameterInput && Number.isFinite(Number(parameterInput.value)))
      .sort((left, right) => Number(left.parameterInput.value) - Number(right.parameterInput.value));
    const extremes = declared.length >= 2
      ? [declared[0], declared[declared.length - 1]]
      : [
          { check: null, parameterInput: { value: parameter.min } },
          { check: null, parameterInput: { value: parameter.max } },
        ];
    return extremes.map(({ check, parameterInput }) => Object.freeze({
      inputs: Object.freeze(check
        ? Object.fromEntries(check.inputs.map(({ name, value }) => [name, value]))
        : { [parameter.id]: parameterInput.value }),
      parameterValue: parameterInput.value,
      expected: check ? Number(check.expected) : Number.NaN,
    }));
  }

  function precisionForEndpoints(endpoints) {
    const [minimum, maximum] = endpoints.map((endpoint) => endpoint.expected);
    if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) {
      return minimumFractionDigits;
    }
    for (
      let precision = minimumFractionDigits;
      precision <= maximumFractionDigits;
      precision += 1
    ) {
      if (minimum.toFixed(precision) !== maximum.toFixed(precision)) return precision;
    }
    return maximumFractionDigits;
  }

  const readout = Object.freeze({
    maximumFractionDigits,
    forLesson(lesson) {
      const endpoints = Object.freeze(endpointChecks(lesson));
      const precision = precisionForEndpoints(endpoints);
      return Object.freeze({
        endpoints,
        precision,
        format(value) {
          return Number.isFinite(value) ? Number(value).toFixed(precision) : String(value);
        },
      });
    },
  });

  Object.defineProperty(window, "LayshReadout", {
    value: readout,
    configurable: false,
    writable: false,
  });

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
