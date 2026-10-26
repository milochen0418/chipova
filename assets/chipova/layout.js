/**
 * Chipova's layout viewer: #layout-viewer shows a GDS of a run, drawn by KLayout on the backend
 * (data-url: a signed path of /_chipova/layout/<artifact>), for exactly the window on screen.
 *
 *   - the wheel zooms round the mouse, dragging pans, Shift+drag (or Measure) measures in µm;
 *   - while a sharper picture of the new window loads, the last one is shown moved and scaled;
 *   - notes (data-notes) are pins; in "pin" mode (data-adding="1") a click places the new note;
 *   - window.chipLayoutFit / Ruler / Share / Goto / GotoBox are called by the page's buttons.
 */
(() => {
  let v = null;

  class LayoutViewer {
    constructor(el) {
      this.el = el;
      this.key = "";
      this.box = null; // the window shown: [x0, y0, x1, y1] in µm
      this.img = null; // the last picture and the window it shows
      this.imgBox = null;
      this.ruler = false;
      this.measure = null;
      this.hover = null;
      this.canvas = document.createElement("canvas");
      this.canvas.style.cssText = "position:absolute;inset:0;width:100%;height:100%;cursor:grab";
      this.canvas.className = "chip-layout-canvas";
      el.appendChild(this.canvas);
      this.canvas.addEventListener("wheel", (e) => this.onWheel(e), { passive: false });
      this.canvas.addEventListener("pointerdown", (e) => this.onDown(e));
      this.canvas.addEventListener("pointermove", (e) => this.onMove(e));
      this.resizer = new ResizeObserver(() => { this.fitAspect(); this.draw(); this.request(); });
      this.resizer.observe(el);
    }

    attrs() {
      const a = (n) => this.el.getAttribute("data-" + n) || "";
      let notes = [];
      try { notes = JSON.parse(a("notes") || "[]"); } catch { notes = []; }
      let bbox = null;
      try { bbox = JSON.parse(a("bbox") || "null"); } catch { bbox = null; }
      let markers = [];
      try { markers = JSON.parse(a("markers") || "[]"); } catch { markers = []; }
      return { url: a("url"), backend: a("backend") || window.location.href, hidden: a("hidden"), notes, bbox, markers, artifact: a("artifact"), adding: a("adding") === "1" };
    }

    sync() {
      const a = this.attrs();
      if (!a.url || !a.bbox || a.bbox.length !== 4) return;
      const key = a.url.split("?")[0];
      this.a = a;
      if (key !== this.key) {
        this.key = key;
        this.img = null;
        this.fit();
        return;
      }
      if (a.hidden !== this.hidden) {
        this.hidden = a.hidden;
        this.request();
      }
      this.canvas.style.cursor = a.adding ? "copy" : this.ruler ? "crosshair" : "grab";
      this.draw();
    }

    size() {
      const r = this.el.getBoundingClientRect();
      return [Math.max(50, r.width), Math.max(50, r.height)];
    }

    fit() {
      const b = this.a.bbox;
      const pad = 0.05 * Math.max(b[2] - b[0], b[3] - b[1]);
      this.box = [b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad];
      this.fitAspect();
      this.hidden = this.a.hidden;
      this.draw();
      this.request();
    }

    fitAspect() {
      if (!this.box) return;
      const [w, h] = this.size();
      let [x0, y0, x1, y1] = this.box;
      const cx = (x0 + x1) / 2;
      const cy = (y0 + y1) / 2;
      let bw = x1 - x0;
      let bh = y1 - y0;
      if (bw / bh > w / h) bh = (bw * h) / w;
      else bw = (bh * w) / h;
      this.box = [cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2];
    }

    toScreen(x, y) {
      const [w, h] = this.size();
      const [x0, y0, x1, y1] = this.box;
      return [((x - x0) / (x1 - x0)) * w, h - ((y - y0) / (y1 - y0)) * h];
    }

    toWorld(px, py) {
      const [w, h] = this.size();
      const [x0, y0, x1, y1] = this.box;
      return [x0 + (px / w) * (x1 - x0), y0 + ((h - py) / h) * (y1 - y0)];
    }

    request() {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.fetchPicture(), 140);
    }

    async fetchPicture() {
      if (!this.a || !this.box) return;
      const [w, h] = this.size();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const box = this.box.slice();
      const u = new URL(this.a.url, this.a.backend);
      u.searchParams.set("op", "png");
      ["x0", "y0", "x1", "y1"].forEach((k, i) => u.searchParams.set(k, box[i].toFixed(5)));
      u.searchParams.set("w", Math.round(w * dpr));
      u.searchParams.set("h", Math.round(h * dpr));
      u.searchParams.set("hide", this.a.hidden || "");
      const seq = (this.seq = (this.seq || 0) + 1);
      try {
        const res = await fetch(u.toString());
        if (!res.ok) throw new Error((await res.json()).error || res.statusText);
        const blob = await res.blob();
        const bmp = await createImageBitmap(blob);
        if (seq !== this.seq) return;
        this.img = bmp;
        this.imgBox = box;
        this.el.setAttribute("data-drawn", String(seq));
        this.draw();
      } catch (err) {
        this.el.setAttribute("data-error", String(err));
      }
    }

    draw() {
      const [w, h] = this.size();
      const dpr = window.devicePixelRatio || 1;
      if (this.canvas.width !== Math.round(w * dpr)) this.canvas.width = Math.round(w * dpr);
      if (this.canvas.height !== Math.round(h * dpr)) this.canvas.height = Math.round(h * dpr);
      const ctx = this.canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = "#020617";
      ctx.fillRect(0, 0, w, h);
      if (!this.box) return;
      if (this.img && this.imgBox) {
        const [ax, ay] = this.toScreen(this.imgBox[0], this.imgBox[3]);
        const [bx, by] = this.toScreen(this.imgBox[2], this.imgBox[1]);
        ctx.drawImage(this.img, ax, ay, bx - ax, by - ay);
      }
      // DRC markers: a red box round each violation (at least a few pixels, to be seen).
      (this.a && this.a.markers || []).forEach((m) => {
        const [ax, ay] = this.toScreen(m.box[0], m.box[3]);
        const [bx, by] = this.toScreen(m.box[2], m.box[1]);
        const pad = Math.max(4, 14 - (bx - ax)) / 2;
        const x = ax - pad;
        const y = ay - pad;
        const w = bx - ax + 2 * pad;
        const h = by - ay + 2 * pad;
        ctx.fillStyle = "rgba(244, 63, 94, 0.18)";
        ctx.fillRect(x, y, w, h);
        ctx.strokeStyle = "#020617";
        ctx.lineWidth = 5;
        ctx.strokeRect(x, y, w, h);
        ctx.strokeStyle = "#fb7185";
        ctx.lineWidth = 2.5;
        ctx.strokeRect(x, y, w, h);
        ctx.font = "bold 12px ui-monospace, monospace";
        const tag = `DRC ${m.rule}`;
        const tw = ctx.measureText(tag).width + 10;
        ctx.fillStyle = "#e11d48";
        ctx.fillRect(x, y - 20, tw, 18);
        ctx.fillStyle = "#ffffff";
        ctx.fillText(tag, x + 5, y - 7);
      });
      // Notes.
      (this.a && this.a.notes || []).forEach((n) => {
        if (n.artifact !== this.a.artifact) return;
        const [px, py] = this.toScreen(n.x, n.y);
        if (px < -20 || py < -20 || px > w + 20 || py > h + 20) return;
        ctx.fillStyle = "#f59e0b";
        ctx.beginPath();
        ctx.arc(px, py, 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.font = "12px ui-sans-serif, system-ui";
        const label = `${n.who}: ${n.text}`;
        const tw = Math.min(260, ctx.measureText(label).width + 10);
        ctx.fillStyle = "rgba(2,6,23,0.85)";
        ctx.fillRect(px + 9, py - 10, tw, 18);
        ctx.fillStyle = "#fde68a";
        ctx.fillText(label.length > 40 ? label.slice(0, 40) + "…" : label, px + 14, py + 3);
      });
      // The ruler.
      if (this.measure) {
        const [ax, ay] = this.toScreen(this.measure[0], this.measure[1]);
        const [bx, by] = this.toScreen(this.measure[2], this.measure[3]);
        ctx.strokeStyle = "#f472b6";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(bx, by);
        ctx.stroke();
        const dx = this.measure[2] - this.measure[0];
        const dy = this.measure[3] - this.measure[1];
        const text = `${Math.hypot(dx, dy).toFixed(3)} µm  (Δx ${dx.toFixed(3)}, Δy ${dy.toFixed(3)})`;
        ctx.font = "12px ui-monospace, monospace";
        ctx.fillStyle = "rgba(2,6,23,0.9)";
        ctx.fillRect(bx + 8, by - 10, ctx.measureText(text).width + 10, 18);
        ctx.fillStyle = "#f9a8d4";
        ctx.fillText(text, bx + 13, by + 3);
        this.el.setAttribute("data-measure", Math.hypot(dx, dy).toFixed(3));
      }
    }

    onWheel(e) {
      if (!this.box) return;
      e.preventDefault();
      const r = this.canvas.getBoundingClientRect();
      const [mx, my] = this.toWorld(e.clientX - r.left, e.clientY - r.top);
      const f = e.deltaY > 0 ? 1.2 : 1 / 1.2;
      const [x0, y0, x1, y1] = this.box;
      this.box = [mx - (mx - x0) * f, my - (my - y0) * f, mx + (x1 - mx) * f, my + (y1 - my) * f];
      this.draw();
      this.request();
    }

    onDown(e) {
      if (!this.box) return;
      const r = this.canvas.getBoundingClientRect();
      const start = [e.clientX - r.left, e.clientY - r.top];
      const startWorld = this.toWorld(...start);
      if (this.a.adding) {
        const btn = document.getElementById("layout-note-at");
        if (btn) {
          btn.dataset.x = startWorld[0].toFixed(4);
          btn.dataset.y = startWorld[1].toFixed(4);
          btn.click();
        }
        return;
      }
      const measuring = this.ruler || e.shiftKey;
      const box0 = this.box.slice();
      const move = (ev) => {
        const p = [ev.clientX - r.left, ev.clientY - r.top];
        if (measuring) {
          const [wx, wy] = this.toWorld(...p);
          this.measure = [startWorld[0], startWorld[1], wx, wy];
        } else {
          const [w, h] = this.size();
          const dx = ((p[0] - start[0]) / w) * (box0[2] - box0[0]);
          const dy = ((p[1] - start[1]) / h) * (box0[3] - box0[1]);
          this.box = [box0[0] - dx, box0[1] + dy, box0[2] - dx, box0[3] + dy];
          this.canvas.style.cursor = "grabbing";
        }
        this.draw();
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        this.canvas.style.cursor = this.ruler ? "crosshair" : "grab";
        if (!measuring) this.request();
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    }

    onMove(e) {
      if (!this.box) return;
      const r = this.canvas.getBoundingClientRect();
      const [x, y] = this.toWorld(e.clientX - r.left, e.clientY - r.top);
      const el = document.getElementById("layout-coords");
      if (el) el.textContent = `x ${x.toFixed(3)} µm, y ${y.toFixed(3)} µm`;
    }

    goto(x, y) {
      const [x0, y0, x1, y1] = this.box;
      const hw = Math.min((x1 - x0) / 2, 5);
      const hh = Math.min((y1 - y0) / 2, 5);
      this.box = [x - hw, y - hh, x + hw, y + hh];
      this.fitAspect();
      this.draw();
      this.request();
    }

    gotoBox(b, around) {
      // around: show the box with room round it (a marker), else exactly (a shared view).
      if (around) {
        const w = Math.max(b[2] - b[0], 0.5);
        const h = Math.max(b[3] - b[1], 0.5);
        const cx = (b[0] + b[2]) / 2;
        const cy = (b[1] + b[3]) / 2;
        const r = Math.max(w, h) * 6;
        this.box = [cx - r, cy - r, cx + r, cy + r];
      } else {
        this.box = b.slice();
      }
      this.fitAspect();
      this.draw();
      this.request();
    }
  }

  // A jump asked for before the viewer has its layout: made once it has.
  let pending = null;

  const scan = () => {
    const el = document.getElementById("layout-viewer");
    if (!el) {
      if (v) { try { v.resizer.disconnect(); } catch {} v = null; }
      return;
    }
    if (!v || v.el !== el) v = new LayoutViewer(el);
    v.sync();
    if (pending && v.box) {
      const [fn, args] = pending;
      pending = null;
      v[fn](...args);
    }
  };
  setInterval(scan, 300);

  window.chipLayoutFit = () => v && v.fit();
  window.chipLayoutRuler = () => {
    if (!v) return;
    v.ruler = !v.ruler;
    if (!v.ruler) v.measure = null;
    v.draw();
  };
  window.chipLayoutShare = () => {
    const btn = document.getElementById("layout-share-at");
    if (!v || !btn || !v.box) return;
    ["x0", "y0", "x1", "y1"].forEach((k, i) => { btn.dataset[k] = v.box[i].toFixed(4); });
    btn.click();
  };
  window.chipLayoutGoto = (x, y) => {
    if (v && v.box) v.goto(x, y);
    else pending = ["goto", [x, y]];
  };
  window.chipLayoutGotoBox = (b, around) => {
    if (!Array.isArray(b)) return;
    if (v && v.box) v.gotoBox(b, !!around);
    else pending = ["gotoBox", [b, !!around]];
  };
})();
