/**
 * Chipova's page helpers:
 *   - [data-splitter="--css-var"] handles resize the panel the variable sizes (data-axis x or y);
 *     the sizes are kept per browser;
 *   - [data-ago="<unix seconds>"] shows "5 min ago", kept current;
 *   - [data-autoscroll] stays scrolled to the bottom while new lines come in, unless you
 *     scrolled up to read;
 *   - a[download] links download: the page's router would otherwise take a same-origin link
 *     (behind re-ddns the backend's downloads are on the page's own host) as a page change.
 */
(() => {
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a[download]");
    if (a) e.stopImmediatePropagation();
  }, true);

  const STORE = "chipova.panels";
  const LIMITS = {
    "--chip-explorer": [160, 520],
    "--chip-right": [240, 640],
    "--chip-bottom": [80, 900],
  };

  const load = () => {
    try { return JSON.parse(localStorage.getItem(STORE) || "{}"); } catch { return {}; }
  };
  const save = (sizes) => {
    try { localStorage.setItem(STORE, JSON.stringify(sizes)); } catch {}
  };
  const sizes = load();
  const apply = () => {
    Object.entries(sizes).forEach(([k, v]) => document.documentElement.style.setProperty(k, v + "px"));
  };
  apply();

  document.addEventListener("pointerdown", (e) => {
    const handle = e.target.closest && e.target.closest("[data-splitter]");
    if (!handle) return;
    e.preventDefault();
    const name = handle.getAttribute("data-splitter");
    const axis = handle.getAttribute("data-axis") || "x";
    const [min, max] = LIMITS[name] || [100, 1000];
    const current = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)) ||
      ({ "--chip-explorer": 240, "--chip-right": 330, "--chip-bottom": 260 })[name] || 240;
    const start = axis === "x" ? e.clientX : e.clientY;
    // The right and bottom panels grow when the handle moves left / up.
    const sign = name === "--chip-explorer" ? 1 : -1;
    const move = (ev) => {
      const now = axis === "x" ? ev.clientX : ev.clientY;
      const size = Math.max(min, Math.min(max, current + sign * (now - start)));
      sizes[name] = Math.round(size);
      document.documentElement.style.setProperty(name, size + "px");
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.style.cursor = "";
      save(sizes);
      window.dispatchEvent(new Event("resize"));
    };
    document.body.style.cursor = axis === "x" ? "col-resize" : "row-resize";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  });

  const ago = (ts) => {
    const s = Math.max(0, Date.now() / 1000 - ts);
    if (!ts) return "";
    if (s < 45) return "just now";
    const units = [[86400 * 30, "mo"], [86400, "d"], [3600, "h"], [60, "min"]];
    for (const [size, unit] of units) if (s >= size) return `${Math.floor(s / size)} ${unit} ago`;
    return "1 min ago";
  };

  const tick = () => {
    document.querySelectorAll("[data-ago]").forEach((el) => {
      const ts = parseFloat(el.getAttribute("data-ago"));
      const prefix = el.__chipPrefix ?? (el.__chipPrefix = el.textContent.replace(/\s*(just now|\d+ (mo|d|h|min) ago)$/, ""));
      const text = (prefix ? prefix + " " : "") + ago(ts);
      if (el.textContent !== text) el.textContent = text;
      el.title = ts ? new Date(ts * 1000).toLocaleString() : "";
    });
    document.querySelectorAll("[data-autoscroll]").forEach((el) => {
      const atBottom = el.__chipAtBottom !== false;
      if (atBottom && el.scrollHeight - el.clientHeight - el.scrollTop > 2) el.scrollTop = el.scrollHeight;
      if (!el.__chipWatch) {
        el.__chipWatch = true;
        el.addEventListener("scroll", () => {
          el.__chipAtBottom = el.scrollHeight - el.clientHeight - el.scrollTop < 30;
        });
      }
    });
  };
  setInterval(tick, 500);
  if (document.readyState !== "loading") tick();
  else document.addEventListener("DOMContentLoaded", tick);
})();
