// SPDX-License-Identifier: GPL-3.0-only
// Frozen-frame calibration. All reads and writes use admin-only HA WebSockets.
class StoveVisionCalibrationCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
  }
  setConfig(config) { this._config = config; }
  set hass(hass) {
    this._hass = hass;
    if (!this._started) { this._started = true; this._init(); }
  }
  getCardSize() { return 7; }
  async _call(action, extra = {}) {
    return this._hass.callWS({ type: "stove_vision/calibration", action,
      entry_id: this._entry, frame_id: this._frame?.frame_id, ...extra });
  }
  async _run(fn) {
    if (this._busy) return;
    this._busy = true;
    this._status("Working…");
    this.shadowRoot.querySelectorAll("button").forEach(b => b.disabled = true);
    try { await fn(); }
    catch (err) { this._status(err.message || String(err)); }
    finally {
      this._busy = false;
      this.shadowRoot.querySelectorAll("button").forEach(b => b.disabled = false);
    }
  }
  _status(text) { const el = this.shadowRoot.querySelector(".status"); if (el) el.textContent = text; }
  async _init() {
    this.shadowRoot.innerHTML = `<style>
      :host{display:block;color:var(--primary-text-color,#eee)}
      ha-card{padding:16px;background:var(--card-background-color,#222)}
      h2{margin:0 0 8px;font-size:20px}p{line-height:1.5}
      .controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0}
      button,select,input{font:inherit;padding:8px;border-radius:6px;border:1px solid #888;
        color:inherit;background:var(--secondary-background-color,#333)}
      button{cursor:pointer}button:disabled{opacity:.5}input{width:70px}
      canvas{width:100%;display:block;background:#111;cursor:crosshair;touch-action:manipulation}
      .status{min-height:2em;white-space:pre-wrap;line-height:1.5}
    </style><ha-card><h2>Stove Vision calibration</h2>
      <p>Select a target, then tap its center in the image. Digit targets are zoomed in.
      Use X/Y for fine adjustment. Preview reads this frozen frame; Save applies the positions.</p>
      <div class="controls"><select class="entries" aria-label="Stove"></select>
      <button data-action="frame">Refresh frame</button><button data-action="auto">Auto-align</button></div>
      <div class="controls"><select class="target" aria-label="Calibration target"></select>
      <label>X <input class="x" type="number" step="1"></label>
      <label>Y <input class="y" type="number" step="1"></label>
      <label>Radius X <input class="rx" type="number" min="1" step="1"></label>
      <label>Radius Y <input class="ry" type="number" min="1" step="1"></label></div>
      <canvas aria-label="Camera frame: tap to place selected calibration target"></canvas>
      <div class="controls"><button data-action="preview">Preview readings</button>
      <button data-action="save">Save positions</button></div>
      <div class="status" role="status" aria-live="polite"></div></ha-card>`;
    const root = this.shadowRoot;
    root.querySelector(".entries").onchange = e => {
      this._entry = e.target.value; this._run(() => this._loadFrame());
    };
    root.querySelector(".target").onchange = () => { this._fields(); this._draw(); };
    root.querySelectorAll("input").forEach(el => el.onchange = () => this._edit());
    root.querySelector("canvas").onclick = e => {
      if (!this._image || this._busy) return;
      const bounds = e.target.getBoundingClientRect();
      const [x, y, w, h] = this._crop;
      root.querySelector(".x").value = Math.round(x + (e.clientX - bounds.left) / bounds.width * w);
      root.querySelector(".y").value = Math.round(y + (e.clientY - bounds.top) / bounds.height * h);
      this._edit();
    };
    root.querySelectorAll("[data-action]").forEach(button => button.onclick = () => this._run(async () => {
      const action = button.dataset.action;
      if (action === "frame") { await this._loadFrame(); return; }
      if (!this._frame) throw new Error("Load a frame first");
      const result = await this._call(action, { positions: this._positions });
      this._positions = result.positions;
      this._fields(); this._draw();
      this._status((result.saved ? "Saved. Integration is reloading.\n" : "Preview: ") +
        Object.entries(result.readings).map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`).join(" · ") +
        (result.timer_digits ? ` · Timer: ${result.timer_digits.map(d => d ?? "_").join("")}` : ""));
      if (result.saved) this._frame = null;
    }));
    await this._run(async () => {
      const entries = await this._call("list");
      const select = root.querySelector(".entries");
      entries.forEach(entry => {
        const option = document.createElement("option");
        option.value = entry.entry_id; option.textContent = entry.title; select.append(option);
      });
      this._entry = entries.find(e => e.entry_id === this._config.entry_id)?.entry_id || entries[0]?.entry_id;
      if (!this._entry) throw new Error("No loaded Stove Vision integration");
      select.value = this._entry;
      await this._loadFrame();
    });
  }
  async _loadFrame() {
    const frame = await this._call("frame");
    const image = new Image();
    image.src = `data:image/png;base64,${frame.image}`;
    await image.decode();
    this._frame = frame; this._image = image; this._positions = structuredClone(frame.positions);
    const select = this.shadowRoot.querySelector(".target");
    select.replaceChildren();
    const add = (value, label) => {
      const option = document.createElement("option"); option.value = value; option.textContent = label; select.append(option);
    };
    Object.keys(frame.positions).filter(k => k.startsWith("zone_")).forEach(k => add(k, k.replaceAll("_", " ")));
    add("timer", "Timer tens digit");
    Object.entries(frame.positions).filter(([k]) => k.startsWith("rings_")).forEach(([k, value]) =>
      value.split(";").forEach((_, index) => add(`${k}:${index}`, `${k.replaceAll("_", " ")} ${index + 1}`)));
    add("glass:0", "Bare glass: top left"); add("glass:1", "Bare glass: bottom right");
    this._fields(); this._draw();
    this._status(`Frame ${frame.width} × ${frame.height}. Place a target or use Auto-align, then Preview.`);
  }
  _point() {
    const key = this.shadowRoot.querySelector(".target").value;
    if (key === "timer") return [this._positions.timer_x, this._positions.timer_y];
    if (key.startsWith("glass:")) return this._positions.glass_box.split(",").map(Number).slice(Number(key.split(":")[1]) * 2);
    if (key.startsWith("rings_")) {
      const [name, index] = key.split(":"); return this._positions[name].split(";")[Number(index)].split(",").map(Number);
    }
    return this._positions[key].split(",").map(Number);
  }
  _fields() {
    if (!this._positions) return;
    const [x, y, rx, ry] = this._point();
    ["x", "y", "rx", "ry"].forEach((key, i) => {
      const input = this.shadowRoot.querySelector(`.${key}`);
      input.value = [x, y, rx, ry][i] ?? ""; input.disabled = i >= 2 && rx === undefined;
    });
  }
  _edit() {
    if (!this._positions || this._busy) return;
    const root = this.shadowRoot, key = root.querySelector(".target").value;
    const values = ["x", "y", "rx", "ry"].map(k => Number(root.querySelector(`.${k}`).value));
    if (values.some(v => !Number.isInteger(v))) { this._status("Use whole pixel coordinates"); return; }
    if (key === "timer") { [this._positions.timer_x, this._positions.timer_y] = values; }
    else if (key.startsWith("glass:")) {
      const box = this._positions.glass_box.split(",").map(Number), offset = Number(key.split(":")[1]) * 2;
      box.splice(offset, 2, ...values.slice(0, 2)); this._positions.glass_box = box.join(",");
    } else if (key.startsWith("rings_")) {
      const [name, index] = key.split(":"), rings = this._positions[name].split(";");
      rings[Number(index)] = values.join(","); this._positions[name] = rings.join(";");
    } else { this._positions[key] = values.slice(0, 2).join(","); }
    this._draw(); this._status("Unsaved placements. Preview before saving.");
  }
  _draw() {
    if (!this._image) return;
    const [cx, cy] = this._point(), key = this.shadowRoot.querySelector(".target").value;
    const zoom = key.startsWith("zone_") || key === "timer";
    // Keep the zoom centered on the frozen frame's original target so clicking
    // does not move the image underneath the pointer.
    const original = key === "timer" ? [this._frame.positions.timer_x, this._frame.positions.timer_y]
      : key.startsWith("zone_") ? this._frame.positions[key].split(",").map(Number) : [0, 0];
    const w = zoom ? Math.min(160, this._image.width) : this._image.width;
    const h = zoom ? Math.min(100, this._image.height) : this._image.height;
    const x = zoom ? Math.max(0, Math.min(this._image.width - w, original[0] - w / 2)) : 0;
    const y = zoom ? Math.max(0, Math.min(this._image.height - h, original[1] - h / 2)) : 0;
    this._crop = [x, y, w, h];
    const canvas = this.shadowRoot.querySelector("canvas"); canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext("2d"); ctx.drawImage(this._image, x, y, w, h, 0, 0, w, h);
    ctx.translate(-x, -y); ctx.strokeStyle = "#00e5ff"; ctx.lineWidth = zoom ? .5 : 2;
    Object.entries(this._positions).forEach(([name, value]) => {
      if (name.startsWith("zone_")) { const [px, py] = value.split(",").map(Number); ctx.strokeRect(px - 9, py - 11, 19, 23); }
      if (name.startsWith("rings_")) value.split(";").forEach(r => {
        const [px, py, rx, ry] = r.split(",").map(Number);
        if (rx > 0 && ry > 0) { ctx.beginPath(); ctx.ellipse(px, py, rx, ry, 0, 0, Math.PI * 2); ctx.stroke(); }
      });
    });
    ctx.strokeRect(this._positions.timer_x - 5, this._positions.timer_y - 8, 10, 16);
    const box = this._positions.glass_box.split(",").map(Number); ctx.strokeRect(box[0], box[1], box[2] - box[0], box[3] - box[1]);
    ctx.strokeStyle = "#ffdb00"; ctx.beginPath();
    ctx.moveTo(cx - 6, cy); ctx.lineTo(cx + 6, cy); ctx.moveTo(cx, cy - 6); ctx.lineTo(cx, cy + 6); ctx.stroke();
  }
}
customElements.define("stove-vision-calibration-card", StoveVisionCalibrationCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "stove-vision-calibration-card", name: "Stove Vision Calibration", description: "Place digit windows, zone rings and glass reference on a camera frame" });
