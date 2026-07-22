(() => {
  "use strict";

  let reportQueued = false;
  let lastHeight = 0;
  const lesson = document.getElementById("lesson");
  document.documentElement.style.minWidth = "0";
  document.body.style.minWidth = "0";

  function contentHeight() {
    const lessonBounds = lesson?.getBoundingClientRect();
    const bodyBounds = document.body.getBoundingClientRect();
    if (bodyBounds.width <= 0 || !lessonBounds || lessonBounds.width <= 0) return 0;
    return Math.ceil(Math.max(lessonBounds?.bottom || 0, bodyBounds.height)) + 2;
  }

  function reportHeight() {
    reportQueued = false;
    const height = contentHeight();
    if (height <= 0 || height === lastHeight || window.parent === window) return;
    lastHeight = height;
    window.parent.postMessage(
      { source: "laysh-artifact", type: "layout-height", version: 1, height },
      "*",
    );
  }

  function scheduleHeightReport() {
    if (reportQueued) return;
    reportQueued = true;
    queueMicrotask(reportHeight);
  }

  const observer = new ResizeObserver(scheduleHeightReport);
  observer.observe(document.body);
  if (lesson) observer.observe(lesson);
  window.addEventListener("resize", scheduleHeightReport, { passive: true });
  window.addEventListener("message", (event) => {
    const payload = event.data;
    if (
      event.source !== window.parent
      || !payload
      || payload.source !== "laysh-host"
      || payload.type !== "measure-layout"
      || payload.version !== 1
    ) return;
    lastHeight = 0;
    scheduleHeightReport();
  });
  document.fonts?.ready.then(scheduleHeightReport);
  window.addEventListener("pagehide", () => {
    observer.disconnect();
  }, { once: true });
  scheduleHeightReport();
})();
