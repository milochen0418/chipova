/**
 * Chipova's waveform viewer: every .chip-wave element with data-wave-url (a signed path of
 * /_chipova/wave/<artifact>) becomes a viewer of that VCD.
 *
 *   - left: the signals shown, with their value at the cursor; type to add one, × removes it;
 *   - right: the waves; the wheel zooms round the mouse, dragging pans, a click puts the cursor;
 *   - buses show their value in hex, binary or decimal; x is red, z is yellow.
 */
(() => {
  const ROW = 26;
  const NAMES_W = 250;
  const AXIS_H = 24;
  const COLORS = { line: "#34d399", bus: "#38bdf8", x: "#f87171", z: "#facc15", text: "#e2e8f0", dim: "#64748b", grid: "#1e293b", cursor: "#f472b6" };

  const unitScale = (ts) => {
    const m = /^(\d+)\s*(s|ms|us|ns|ps|fs)$/i.exec((ts || "1ns").trim());
    if (!m) return 1e-9;
    return parseInt(m[1], 10) * { s: 1, ms: 1e-3, us: 1e-6, ns: 1e-9, ps: 1e-12, fs: 1e-15 }[m[2].toLowerCase()];
  };

  const fmtTime = (seconds) => {
    if (seconds === 0) return "0";
    const a = Math.abs(seconds);
    const units = [[1, "s"], [1e-3, "ms"], [1e-6, "µs"], [1e-9, "ns"], [1e-12, "ps"], [1e-15, "fs"]];
    for (const [u, name] of units) if (a >= u || u === 1e-15) return `${+(seconds / u).toFixed(3)} ${name}`;
    return `${seconds} s`;
  };

  const radixValue = (bits, radix, width) => {
    if (!bits) return "";
    if (/[^01]/.test(bits)) return bits.length > 12 ? bits.slice(0, 12) + "…" : bits;
    if (radix === "bin") return bits;
    const big = BigInt("0b" + bits);
    if (radix === "dec") return big.toString(10);
    return big.toString(16).padStart(Math.ceil(width / 4), "0");
  };

  class Viewer {
    constructor(el, url, backend) {
      this.el = el;
      this.url = url;
      this.backend = backend;
      this.radix = "hex";
      this.shown = [];
      this.data = {};
      this.cursor = null;
      this.build();
      this.load();
    }

    endpoint(params) {
      const u = new URL(this.url, this.backend);
      Object.entries(params).forEach(([k, v]) => u.searchParams.set(k, v));
      return u.toString();
    }

    build() {
      this.el.innerHTML = "";
      this.el.style.display = "flex";
      this.el.style.flexDirection = "column";
      this.el.style.fontFamily = "ui-sans-serif, system-ui";
      const bar = document.createElement("div");
      bar.style.cssText = "display:flex;gap:6px;align-items:center;padding:6px 8px;border-bottom:1px solid #1e293b;font-size:12px;color:#94a3b8;flex-wrap:wrap";
      const btn = (label, title, fn) => {
        const b = document.createElement("button");
        b.textContent = label;
        b.title = title;
        b.style.cssText = "padding:2px 8px;border:1px solid #334155;border-radius:6px;background:#0f172a;color:#e2e8f0;cursor:pointer";
        b.onclick = fn;
        bar.appendChild(b);
        return b;
      };
      this.search = document.createElement("input");
      this.search.placeholder = "Add a signal…";
      this.search.setAttribute("list", "chip-wave-list-" + Math.random().toString(36).slice(2));
      this.search.className = "chip-wave-search";
      this.search.style.cssText = "width:220px;padding:3px 8px;border:1px solid #334155;border-radius:6px;background:#020617;color:#e2e8f0";
      this.datalist = document.createElement("datalist");
      this.datalist.id = this.search.getAttribute("list");
      this.search.addEventListener("change", () => this.addByName(this.search.value));
      bar.appendChild(this.search);
      bar.appendChild(this.datalist);
      btn("Fit", "Show the whole simulation", () => this.fit());
      btn("+", "Zoom in", () => this.zoom(0.5));
      btn("−", "Zoom out", () => this.zoom(2));
      this.radixBtn = btn("hex", "How buses show their values", () => {
        this.radix = { hex: "bin", bin: "dec", dec: "hex" }[this.radix];
        this.radixBtn.textContent = this.radix;
        this.draw();
      });
      this.info = document.createElement("span");
      this.info.className = "chip-wave-cursor";
      this.info.style.cssText = "margin-left:auto;font-family:ui-monospace,monospace;color:#cbd5e1";
      bar.appendChild(this.info);
      this.el.appendChild(bar);
      const body = document.createElement("div");
      body.style.cssText = "position:relative;flex:1;min-height:0;overflow:auto";
      this.canvas = document.createElement("canvas");
      this.canvas.className = "chip-wave-canvas";
      this.canvas.style.cssText = "display:block;cursor:crosshair";
      body.appendChild(this.canvas);
      this.el.appendChild(body);
      this.body = body;
      this.canvas.addEventListener("wheel", (e) => this.onWheel(e), { passive: false });
      this.canvas.addEventListener("pointerdown", (e) => this.onDown(e));
      this.canvas.addEventListener("click", (e) => this.onClick(e));
      this.resizer = new ResizeObserver(() => this.draw());
      this.resizer.observe(this.el);
    }

    async load() {
      try {
        const res = await fetch(this.endpoint({ op: "meta" }));
        const meta = await res.json();
        if (!res.ok) throw new Error(meta.error || res.statusText);
        this.meta = meta;
        this.scale = unitScale(meta.timescale);
        this.t0 = 0;
        this.t1 = Math.max(1, meta.end);
        this.byName = {};
        meta.signals.forEach((s) => { this.byName[s.name] = s; });
        this.datalist.innerHTML = meta.signals.map((s) => `<option value="${s.name}"></option>`).join("");
        // The testbench's own signals first, then one level down (the design's ports).
        const depth = (s) => s.name.split(".").length;
        const pick = meta.signals.filter((s) => depth(s) === 2).concat(meta.signals.filter((s) => depth(s) === 3));
        const seen = new Set();
        this.shown = pick.filter((s) => (seen.has(s.name) ? false : seen.add(s.name))).slice(0, 14);
        await this.fetchData();
        this.el.setAttribute("data-ready", "1");
        this.el.setAttribute("data-signals", String(this.shown.length));
      } catch (err) {
        this.el.setAttribute("data-error", String(err));
        this.info.textContent = "Can't read the waveform: " + err;
      }
      this.draw();
    }

    async fetchData() {
      const codes = [...new Set(this.shown.map((s) => s.code))].filter((c) => !(c in this.data));
      if (!codes.length) return;
      const res = await fetch(this.endpoint({ op: "window", codes: codes.join(","), t0: 0, t1: this.meta.end }));
      const got = await res.json();
      Object.assign(this.data, got);
    }

    async addByName(name) {
      const s = this.byName && this.byName[name.trim()];
      if (!s) return;
      if (!this.shown.find((x) => x.name === s.name)) this.shown.push(s);
      this.search.value = "";
      await this.fetchData();
      this.el.setAttribute("data-signals", String(this.shown.length));
      this.draw();
    }

    fit() {
      if (!this.meta) return;
      this.t0 = 0;
      this.t1 = Math.max(1, this.meta.end);
      this.draw();
    }

    zoom(factor, at) {
      if (!this.meta) return;
      const center = at ?? (this.t0 + this.t1) / 2;
      const span = Math.max(4, (this.t1 - this.t0) * factor);
      this.t0 = Math.max(0, center - (center - this.t0) * factor);
      this.t1 = this.t0 + span;
      this.draw();
    }

    xOf(t, w) { return NAMES_W + ((t - this.t0) / (this.t1 - this.t0)) * (w - NAMES_W - 8); }

    tOf(x, w) { return this.t0 + ((x - NAMES_W) / (w - NAMES_W - 8)) * (this.t1 - this.t0); }

    onWheel(e) {
      if (!this.meta) return;
      e.preventDefault();
      const rect = this.canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      if (x < NAMES_W) return;
      if (e.shiftKey) {
        const shift = (e.deltaY / 400) * (this.t1 - this.t0);
        this.t0 = Math.max(0, this.t0 + shift);
        this.t1 = this.t1 + shift;
        this.draw();
        return;
      }
      this.zoom(e.deltaY > 0 ? 1.25 : 0.8, this.tOf(x, rect.width));
    }

    onDown(e) {
      const rect = this.canvas.getBoundingClientRect();
      if (e.clientX - rect.left < NAMES_W) return;
      const startX = e.clientX;
      const t0 = this.t0;
      const t1 = this.t1;
      let moved = false;
      const move = (ev) => {
        const dx = ev.clientX - startX;
        if (Math.abs(dx) > 3) moved = true;
        const dt = (dx / (rect.width - NAMES_W - 8)) * (t1 - t0);
        this.t0 = Math.max(0, t0 - dt);
        this.t1 = this.t0 + (t1 - t0);
        this.draw();
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        this.dragged = moved;
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    }

    onClick(e) {
      if (this.dragged) { this.dragged = false; return; }
      const rect = this.canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      if (x < NAMES_W) {
        // The × beside a name removes that signal.
        const row = Math.floor((y - AXIS_H) / ROW);
        if (row >= 0 && row < this.shown.length && x > NAMES_W - 22) {
          this.shown.splice(row, 1);
          this.el.setAttribute("data-signals", String(this.shown.length));
          this.draw();
        }
        return;
      }
      this.cursor = Math.round(this.tOf(x, rect.width));
      this.draw();
    }

    valueAt(code, t) {
      const pts = this.data[code];
      if (!pts || !pts.length) return "";
      let lo = 0;
      let hi = pts.length - 1;
      if (pts[hi][0] === "busy") hi -= 1;
      let found = "";
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (pts[mid][0] <= t) { found = pts[mid][1]; lo = mid + 1; } else hi = mid - 1;
      }
      return found;
    }

    draw() {
      const ctx = this.canvas.getContext("2d");
      const w = Math.max(400, this.body.clientWidth);
      const h = Math.max(this.body.clientHeight, AXIS_H + this.shown.length * ROW + 10);
      const dpr = window.devicePixelRatio || 1;
      this.canvas.width = w * dpr;
      this.canvas.height = h * dpr;
      this.canvas.style.width = w + "px";
      this.canvas.style.height = h + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = "#020617";
      ctx.fillRect(0, 0, w, h);
      if (!this.meta) return;
      ctx.font = "11px ui-monospace, SFMono-Regular, monospace";
      // The time axis.
      const span = this.t1 - this.t0;
      const step = Math.pow(10, Math.floor(Math.log10(span / 6 || 1)));
      const nice = [1, 2, 5, 10].map((m) => m * step).find((s) => span / s <= 10) || step * 10;
      ctx.fillStyle = COLORS.dim;
      for (let t = Math.ceil(this.t0 / nice) * nice; t <= this.t1; t += nice) {
        const x = this.xOf(t, w);
        ctx.fillStyle = COLORS.grid;
        ctx.fillRect(x, AXIS_H, 1, h - AXIS_H);
        ctx.fillStyle = COLORS.dim;
        ctx.fillText(fmtTime(t * this.scale), x + 3, 15);
      }
      ctx.fillStyle = "#0f172a";
      ctx.fillRect(0, 0, NAMES_W, h);
      this.shown.forEach((s, i) => {
        const y = AXIS_H + i * ROW;
        ctx.fillStyle = i % 2 ? "rgba(15,23,42,0.6)" : "rgba(2,6,23,0.6)";
        ctx.fillRect(NAMES_W, y, w - NAMES_W, ROW);
        // The testbench's own signals by their name, deeper ones with their instance.
        const parts = s.name.split(".");
        const short = (parts.length > 2 ? parts.slice(-2) : parts.slice(-1)).join(".") + (s.width > 1 ? `[${s.width - 1}:0]` : "");
        const value = this.cursor !== null ? this.valueAt(s.code, this.cursor) : "";
        const shown = value === "" ? "" : s.width > 1 ? radixValue(value, this.radix, s.width) : value;
        const valueW = shown ? Math.min(90, ctx.measureText(shown).width) : 0;
        const room = NAMES_W - 30 - valueW - (shown ? 8 : 0);
        let label = short;
        while (label.length > 3 && ctx.measureText(label).width > room) label = label.slice(0, -2);
        ctx.fillStyle = COLORS.text;
        ctx.fillText(label === short ? short : label + "…", 8, y + 17);
        if (shown) {
          ctx.fillStyle = "#f9a8d4";
          ctx.fillText(shown.length > 12 ? shown.slice(0, 11) + "…" : shown, NAMES_W - 24 - valueW, y + 17);
        }
        ctx.fillStyle = COLORS.dim;
        ctx.fillText("×", NAMES_W - 16, y + 17);
        this.drawSignal(ctx, s, y, w);
      });
      if (this.cursor !== null) {
        const x = this.xOf(this.cursor, w);
        ctx.fillStyle = COLORS.cursor;
        ctx.fillRect(x, AXIS_H, 1, h - AXIS_H);
        this.info.textContent = "cursor " + fmtTime(this.cursor * this.scale);
        this.el.setAttribute("data-cursor", String(this.cursor));
      } else {
        this.info.textContent = `${this.meta.signals.length} signals · ends at ${fmtTime(this.meta.end * this.scale)}`;
      }
    }

    drawSignal(ctx, s, y, w) {
      const pts = this.data[s.code];
      if (!pts || !pts.length) return;
      const busy = pts[pts.length - 1][0] === "busy";
      const list = busy ? pts.slice(0, -1) : pts;
      const top = y + 5;
      const bottom = y + ROW - 5;
      const mid = (top + bottom) / 2;
      for (let i = 0; i < list.length; i++) {
        const [t, v] = list[i];
        const tNext = i + 1 < list.length ? list[i + 1][0] : this.meta.end;
        if (tNext < this.t0 || t > this.t1) continue;
        const x0 = Math.max(NAMES_W, this.xOf(t, w));
        const x1 = Math.min(w - 8, this.xOf(tNext, w));
        if (x1 < NAMES_W) continue;
        if (s.width === 1 && s.kind !== "real") {
          const color = v === "x" ? COLORS.x : v === "z" ? COLORS.z : COLORS.line;
          ctx.strokeStyle = color;
          ctx.beginPath();
          const yy = v === "1" ? top : v === "0" ? bottom : mid;
          if (i > 0 && t >= this.t0) {
            const prev = list[i - 1][1];
            const yp = prev === "1" ? top : prev === "0" ? bottom : mid;
            ctx.moveTo(x0, yp);
            ctx.lineTo(x0, yy);
          } else {
            ctx.moveTo(x0, yy);
          }
          ctx.lineTo(x1, yy);
          ctx.stroke();
        } else {
          const color = /[xX]/.test(v) ? COLORS.x : /[zZ]/.test(v) ? COLORS.z : COLORS.bus;
          ctx.strokeStyle = color;
          ctx.beginPath();
          const e = Math.min(3, (x1 - x0) / 2);
          ctx.moveTo(x0, mid);
          ctx.lineTo(x0 + e, top);
          ctx.lineTo(x1 - e, top);
          ctx.lineTo(x1, mid);
          ctx.lineTo(x1 - e, bottom);
          ctx.lineTo(x0 + e, bottom);
          ctx.closePath();
          ctx.stroke();
          const label = s.kind === "real" ? v : radixValue(v, this.radix, s.width);
          const room = x1 - x0 - 8;
          if (room > 14) {
            ctx.fillStyle = COLORS.text;
            const text = ctx.measureText(label).width > room ? label.slice(0, Math.max(1, Math.floor(room / 7))) + "…" : label;
            ctx.fillText(text, x0 + 5, mid + 4);
          }
        }
      }
      if (busy) {
        ctx.fillStyle = COLORS.dim;
        ctx.fillText("(busy: zoom in)", w - 110, y + 17);
      }
    }
  }

  const viewers = new Map();

  const scan = () => {
    document.querySelectorAll(".chip-wave").forEach((el) => {
      const url = el.getAttribute("data-wave-url") || "";
      const backend = el.getAttribute("data-backend") || window.location.href;
      const v = viewers.get(el);
      if (!url) return;
      // A new link to the same waveform (links are signed again now and then) keeps the view.
      const key = url.split("?")[0];
      if (!v || v.key !== key) {
        const viewer = new Viewer(el, url, backend);
        viewer.key = key;
        viewers.set(el, viewer);
      } else {
        v.url = url;
      }
    });
    viewers.forEach((v, el) => {
      if (!el.isConnected) {
        try { v.resizer.disconnect(); } catch {}
        viewers.delete(el);
      }
    });
  };
  setInterval(scan, 500);
})();
