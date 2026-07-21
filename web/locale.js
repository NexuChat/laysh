(() => {
  "use strict";

  const STORAGE_KEY = "laysh-locale";
  const catalogs = window.LayshTranslations;
  const supported = new Set(["ar", "en"]);
  const byId = (id) => document.getElementById(id);

  function storedLocale() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return supported.has(saved) ? saved : "ar";
    } catch {
      return "ar";
    }
  }

  let locale = storedLocale();

  function translate(key, values = {}) {
    const template = catalogs[locale][key] || catalogs.ar[key] || key;
    return Object.entries(values).reduce(
      (copy, [name, value]) => copy.replaceAll(`{${name}}`, String(value)),
      template,
    );
  }

  function apply() {
    document.documentElement.lang = locale;
    document.documentElement.dir = locale === "ar" ? "rtl" : "ltr";
    document.title = translate("document.title");
    for (const element of document.querySelectorAll("[data-i18n]")) {
      element.textContent = translate(element.dataset.i18n);
    }
    for (const element of document.querySelectorAll("[data-i18n-html]")) {
      element.innerHTML = translate(element.dataset.i18nHtml);
    }
    for (const element of document.querySelectorAll("[data-i18n-placeholder]")) {
      element.setAttribute("placeholder", translate(element.dataset.i18nPlaceholder));
    }
    for (const element of document.querySelectorAll("[data-i18n-aria-label]")) {
      element.setAttribute("aria-label", translate(element.dataset.i18nAriaLabel));
    }
    for (const element of document.querySelectorAll("[data-i18n-title]")) {
      element.setAttribute("title", translate(element.dataset.i18nTitle));
    }
    document.dispatchEvent(new CustomEvent("laysh:locale-changed", { detail: { locale } }));
  }

  function setLocale(nextLocale, { source } = {}) {
    if (source !== "locale-control" || !supported.has(nextLocale) || nextLocale === locale) {
      return false;
    }
    locale = nextLocale;
    try {
      localStorage.setItem(STORAGE_KEY, locale);
    } catch {
      // The selection still applies for this page when preference storage is unavailable.
    }
    apply();
    return true;
  }

  window.LayshLocale = {
    current: () => locale,
    t: translate,
    setLocale,
  };

  byId("locale-control").addEventListener("click", () => {
    setLocale(locale === "ar" ? "en" : "ar", { source: "locale-control" });
  });
  apply();
})();
