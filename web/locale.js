(() => {
  "use strict";

  const storageKey = "laysh.locale";
  let stored = null;
  try {
    stored = localStorage.getItem(storageKey);
  } catch {
    // Storage can be unavailable in hardened or private browser contexts.
  }
  const languages = Array.isArray(navigator.languages) && navigator.languages.length
    ? navigator.languages
    : [navigator.language || ""];
  const detected = languages.some((language) =>
    String(language).toLowerCase().startsWith("ar"),
  ) ? "ar" : "en";
  const initial = stored === "ar" || stored === "en" ? stored : detected;

  document.documentElement.setAttribute("lang", initial);
  document.documentElement.setAttribute("dir", initial === "ar" ? "rtl" : "ltr");
  document.documentElement.dataset.locale = initial;
  window.LayshLocale = { storageKey, initial, detected, explicit: stored === "ar" || stored === "en" };
})();
