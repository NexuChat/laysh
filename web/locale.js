(() => {
  "use strict";

  const storageKey = "laysh.locale";
  const pathMatch = window.location.pathname.match(/^\/(ar|en)(?:\/|$)/);
  const pathLocale = pathMatch?.[1] || null;
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
  const hasStoredLocale = stored === "ar" || stored === "en";
  const initial = pathLocale || (hasStoredLocale ? stored : detected);
  if (pathLocale) {
    try {
      localStorage.setItem(storageKey, pathLocale);
    } catch {
      // Storage can be unavailable in hardened or private browser contexts.
    }
  }

  document.documentElement.setAttribute("lang", initial);
  document.documentElement.setAttribute("dir", initial === "ar" ? "rtl" : "ltr");
  document.documentElement.dataset.locale = initial;
  window.LayshLocale = {
    storageKey,
    initial,
    detected,
    explicit: pathLocale !== null || hasStoredLocale,
    pathLocale,
  };
})();
