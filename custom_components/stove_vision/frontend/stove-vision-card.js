/*
 * Stove Vision card: the stove drawn from the integration's sensors.
 *
 *   type: custom:stove-vision-card
 *   device: <device id>        # optional, first Stove Vision device otherwise
 *   title: Kochfeld            # optional, device name otherwise
 *
 * Served by the stove_vision integration, no resource to add.
 */

const ZONES = {
  // Layout of the Miele cooktop this was built on, in glass coordinates
  rear_left: { x: 105, y: 120, rings: [70], handle: -150 },
  rear_right: { x: 421, y: 150, rings: [104, 60], handle: -30 },
  front_left: { x: 119, y: 359, rings: [91, 51], handle: 150 },
  front_right: { x: 458, y: 376, rings: [73], handle: 30 },
};
const ZONE_NAMES = {
  rear_left: "Rear left",
  rear_right: "Rear right",
  front_left: "Front left",
  front_right: "Front right",
};
// Control panel digits, spread out a bit compared to the real panel
const DIGITS = {
  rear_left: { x: 252, y: 404 },
  rear_right: { x: 328, y: 404 },
  front_left: { x: 222, y: 446 },
  front_right: { x: 358, y: 446 },
};

// Seven segments (a-g) of a 14x24 digit, slanted like the real display
const SEGMENT_PATHS = [
  "M3,0 h10 l-1.5,2.6 h-7z", // a
  "M14,0.4 l-1.3,11.2 -2.2,-1.4 1,-8.4z", // b
  "M12.6,12.4 l-1.3,11.2 -2.2,-1.8 1,-8z", // c
  "M1.6,24 h10 l-1.6,-2.6 h-7z", // d
  "M1.4,12.4 l-1.3,11.2 2.4,-1.8 1,-8z", // e
  "M2.8,0.4 l-1.3,11.2 2.2,-1.4 1,-8.4z", // f
  "M2,12 l1.8,-1.4 h7 l1.6,1.4 -1.8,1.4 h-7z", // g
];
const GLYPHS = {
  0: "abcdef",
  1: "bc",
  2: "abdeg",
  3: "abcdg",
  4: "bcfg",
  5: "acdfg",
  6: "acdefg",
  7: "abc",
  8: "abcdefg",
  9: "abcdfg",
  P: "abefg",
};
const HEAT_BARS = { 1: "d", 2: "dg", 3: "adg" };

const svgDigit = (glyph, lit) =>
  SEGMENT_PATHS.map((path, i) => {
    const on = glyph.includes("abcdefg"[i]);
    return `<path d="${path}" class="${on && lit ? "seg on" : "seg"}"/>`;
  }).join("");

class StoveVisionCard extends HTMLElement {
  static getStubConfig() {
    return {};
  }

  static getConfigElement() {
    return undefined;
  }

  setConfig(config) {
    this._config = { show_camera: false, ...config };
    this._showCamera = Boolean(this._config.show_camera);
    this._signature = undefined;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 7;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  _entities() {
    const all = Object.values(this._hass.entities || {}).filter(
      (entity) => entity.platform === "stove_vision"
    );
    const device =
      this._config.device || (all.find((entity) => entity.device_id) || {}).device_id;
    const mine = all.filter((entity) => !device || entity.device_id === device);
    const find = (key) => {
      const byKey = mine.find((entity) => entity.translation_key === key);
      if (byKey) return byKey.entity_id;
      const bySuffix = mine.find((entity) => entity.entity_id.endsWith(`_${key}`));
      return bySuffix ? bySuffix.entity_id : undefined;
    };
    const result = { device, zones: {} };
    for (const zone of Object.keys(ZONES)) {
      result.zones[zone] = {
        display: find(zone),
        occupied: find(`${zone}_occupied`),
      };
    }
    for (const key of ["on", "hot", "infrared"]) {
      result[key] = find(key);
    }
    // Annotated camera crops (the "zones" image is not the zone map above)
    result.images = { panel: find("panel"), zones: find("zones") };
    return result;
  }

  _state(entityId) {
    return entityId ? this._hass.states[entityId] : undefined;
  }

  _model() {
    const ids = this._entities();
    const zones = {};
    for (const [zone, zoneIds] of Object.entries(ids.zones)) {
      const display = this._state(zoneIds.display);
      const occupied = this._state(zoneIds.occupied);
      const state = display ? display.state : "unavailable";
      const level = /^[1-9]$/.test(state) ? Number(state) : state === "boost" ? 10 : 0;
      zones[zone] = {
        ids: zoneIds,
        state,
        level,
        heatBars: display ? display.attributes.residual_heat_bars || 0 : 0,
        occupied: occupied ? occupied.state : "unavailable",
      };
    }
    const infrared = this._state(ids.infrared);
    const device = ids.device && this._hass.devices ? this._hass.devices[ids.device] : undefined;
    const images = {};
    for (const key of ["panel", "zones"]) {
      const image = this._state(ids.images[key]);
      if (image && image.attributes.entity_picture) images[key] = image.attributes.entity_picture;
    }
    return {
      ids,
      zones,
      images,
      infrared: infrared ? infrared.state === "on" : false,
      title:
        this._config.title ||
        (device && (device.name_by_user || device.name)) ||
        "Stove",
    };
  }

  _render() {
    if (!this._hass || !this._config) return;
    const model = this._model();
    const signature = JSON.stringify([model, this._showCamera]);
    if (signature === this._signature) return;
    this._signature = signature;

    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("click", (event) => this._onClick(event));
    }
    const zones = Object.entries(model.zones);
    const on = zones.filter(([, zone]) => zone.level > 0);
    const hot = zones.filter(([, zone]) => zone.state === "residual_heat");
    const pots = zones.filter(([, zone]) => zone.occupied === "on");
    const known = zones.some(([, zone]) => zone.state !== "unavailable" && zone.state !== "unknown");

    const chips = [];
    if (model.infrared) chips.push(`<span class="chip ir">🌙 Night vision</span>`);
    else if (!known) chips.push(`<span class="chip">No reading</span>`);
    else if (on.length) chips.push(`<span class="chip on">🔥 ${on.length} zone${on.length > 1 ? "s" : ""} on</span>`);
    else chips.push(`<span class="chip off">Off</span>`);
    if (hot.length) chips.push(`<span class="chip hot">♨ ${hot.length} hot</span>`);
    if (pots.length) chips.push(`<span class="chip pot">🍲 ${pots.length} pot${pots.length > 1 ? "s" : ""}</span>`);

    const cameraButton = model.images.zones
      ? `<button class="toggle" data-action="camera" title="Camera view">${this._showCamera ? "✨" : "📷"}</button>`
      : "";

    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header">
          <div class="title">${model.title}</div>
          <div class="chips">${chips.join("")}</div>
          ${cameraButton}
        </div>
        ${
          this._showCamera
            ? `<div class="camera">
                 <img src="${model.images.zones}" alt="Zones">
                 ${model.images.panel ? `<img src="${model.images.panel}" alt="Panel">` : ""}
               </div>`
            : `<div class="stove">${this._svg(model)}${
                model.infrared
                  ? `<div class="overlay"><div>🌙</div><div>Camera is in night vision.<br>Nothing on the stove can be read.</div></div>`
                  : ""
              }</div>`
        }
      </ha-card>`;
  }

  _svg(model) {
    const zoneSvg = Object.entries(model.zones)
      .map(([key, zone]) => this._zoneSvg(key, zone))
      .join("");
    const digits = Object.entries(model.zones)
      .map(([key, zone]) => {
        const pos = DIGITS[key];
        let glyph = "";
        let lit = true;
        if (zone.level > 0) glyph = zone.level === 10 ? GLYPHS.P : GLYPHS[zone.level];
        else if (zone.state === "residual_heat") glyph = HEAT_BARS[zone.heatBars] || HEAT_BARS[1];
        else if (zone.state === "0") glyph = GLYPHS[0];
        else lit = false;
        return `<g class="digit" transform="translate(${pos.x - 9} ${pos.y - 16}) scale(1.3)" data-entity="${zone.ids.display || ""}">
                  <rect x="-6" y="-5" width="26" height="34" rx="4" class="hit"/>
                  ${svgDigit(glyph, lit)}
                </g>`;
      })
      .join("");
    const scale = Array.from({ length: 10 }, (_, i) => `<text x="${206 + i * 18}" y="492">${i}</text>`).join("");
    return `
      <svg viewBox="-24 -24 628 548" role="img" aria-label="Stove">
        <defs>
          <linearGradient id="glass" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#1c1f27"/>
            <stop offset="0.55" stop-color="#0c0d11"/>
            <stop offset="1" stop-color="#16181e"/>
          </linearGradient>
          <linearGradient id="sheen" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#ffffff" stop-opacity="0.10"/>
            <stop offset="0.35" stop-color="#ffffff" stop-opacity="0"/>
          </linearGradient>
          <radialGradient id="heat" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0" stop-color="#ffd27a"/>
            <stop offset="0.35" stop-color="#ff7a2f"/>
            <stop offset="0.75" stop-color="#e5261f"/>
            <stop offset="1" stop-color="#7a0b0b" stop-opacity="0"/>
          </radialGradient>
          <radialGradient id="ember" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0" stop-color="#ff9a3c" stop-opacity="0.55"/>
            <stop offset="0.7" stop-color="#b8321a" stop-opacity="0.25"/>
            <stop offset="1" stop-color="#b8321a" stop-opacity="0"/>
          </radialGradient>
          <radialGradient id="steel" cx="0.38" cy="0.32" r="0.75">
            <stop offset="0" stop-color="#f4f6f8"/>
            <stop offset="0.45" stop-color="#b9bfc7"/>
            <stop offset="0.8" stop-color="#7d848e"/>
            <stop offset="1" stop-color="#5a6069"/>
          </radialGradient>
          <radialGradient id="inside" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0" stop-color="#3a3f47"/>
            <stop offset="1" stop-color="#20242a"/>
          </radialGradient>
          <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="6" result="blur"/>
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <filter id="led" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="1.6" result="blur"/>
            <feMerge><feMergeNode in="blur"/><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <filter id="shadow" x="-30%" y="-30%" width="160%" height="160%">
            <feDropShadow dx="6" dy="10" stdDeviation="8" flood-color="#000" flood-opacity="0.55"/>
          </filter>
        </defs>
        <rect x="-8" y="-8" width="596" height="516" rx="26" class="frame"/>
        <rect x="0" y="0" width="580" height="500" rx="20" fill="url(#glass)"/>
        ${zoneSvg}
        <rect x="0" y="0" width="580" height="500" rx="20" fill="url(#sheen)" pointer-events="none"/>
        <text x="290" y="300" class="brand">S T O V E · V I S I O N</text>
        <g class="panel" filter="url(#led)">${digits}</g>
        <g class="scale">${scale}</g>
      </svg>`;
  }

  _zoneSvg(key, zone) {
    const { x, y, rings, handle } = ZONES[key];
    const outer = rings[0];
    const parts = [`<g class="zone" data-entity="${zone.ids.display || ""}">`];
    parts.push(`<circle cx="${x}" cy="${y}" r="${outer + 8}" class="hit"/>`);
    if (zone.level > 0) {
      const strength = Math.min(1, 0.35 + zone.level * 0.07);
      const speed = (3.2 - zone.level * 0.22).toFixed(2);
      if (zone.occupied === "on") {
        // Heat spilling out around the pot
        parts.push(
          `<circle cx="${x}" cy="${y}" r="${outer * 1.32}" fill="url(#heat)" class="heat halo"
                   style="opacity:${(strength * 0.75).toFixed(2)};animation-duration:${speed}s"/>`
        );
      }
      parts.push(
        `<circle cx="${x}" cy="${y}" r="${outer * 1.12}" fill="url(#heat)" class="heat"
                 style="opacity:${strength};animation-duration:${speed}s"/>`
      );
      // Glowing coil
      for (let r = outer * 0.25; r < outer * 0.95; r += outer * 0.14) {
        parts.push(
          `<circle cx="${x}" cy="${y}" r="${r.toFixed(1)}" class="coil" style="opacity:${(strength * 0.9).toFixed(2)}" filter="url(#glow)"/>`
        );
      }
    } else if (zone.state === "residual_heat") {
      parts.push(`<circle cx="${x}" cy="${y}" r="${outer * 1.05}" fill="url(#ember)" class="ember"/>`);
    }
    for (const r of rings) {
      parts.push(`<circle cx="${x}" cy="${y}" r="${r}" class="ring ${zone.level > 0 ? "lit" : ""}"/>`);
    }
    if (zone.level > 0) {
      // Power level as an arc around the zone, filling up clockwise from the top
      const arc = outer + 14;
      const length = 2 * Math.PI * arc;
      const filled = (Math.min(zone.level, 9) / 9) * length;
      parts.push(
        `<circle cx="${x}" cy="${y}" r="${arc}" class="track"/>
         <circle cx="${x}" cy="${y}" r="${arc}" class="level" filter="url(#glow)"
                 stroke-dasharray="${filled.toFixed(1)} ${length.toFixed(1)}"
                 transform="rotate(-90 ${x} ${y})"/>`
      );
    }
    if (zone.occupied === "unavailable" || zone.occupied === "unknown") {
      parts.push(`<circle cx="${x}" cy="${y}" r="${outer + 4}" class="unsure"/>`);
    }
    parts.push("</g>");
    if (zone.occupied === "on") parts.push(this._potSvg(key, zone, x, y, outer, handle));
    return parts.join("");
  }

  _potSvg(key, zone, x, y, outer, handle) {
    const r = outer * 0.86;
    const angle = (handle * Math.PI) / 180;
    const hx = x + Math.cos(angle) * (r + 26);
    const hy = y + Math.sin(angle) * (r + 26);
    const steam =
      zone.level > 0
        ? [-0.35, 0, 0.35]
            .map(
              (dx, i) =>
                `<path d="M${(x + dx * r).toFixed(1)},${y + 8} c-10,-14 10,-22 0,-38 c-8,-12 6,-20 0,-30"
                       class="steam" style="animation-delay:${(i * 0.7).toFixed(1)}s"/>`
            )
            .join("")
        : "";
    return `
      <g class="pot" data-entity="${zone.ids.occupied || ""}" filter="url(#shadow)">
        <line x1="${x}" y1="${y}" x2="${hx.toFixed(1)}" y2="${hy.toFixed(1)}" class="handle"/>
        <circle cx="${x}" cy="${y}" r="${r.toFixed(1)}" fill="url(#steel)"/>
        <circle cx="${x}" cy="${y}" r="${(r * 0.82).toFixed(1)}" fill="url(#inside)"/>
        <circle cx="${x}" cy="${y}" r="${(r * 0.82).toFixed(1)}" class="rim"/>
        <ellipse cx="${(x - r * 0.3).toFixed(1)}" cy="${(y - r * 0.35).toFixed(1)}" rx="${(r * 0.32).toFixed(1)}" ry="${(r * 0.12).toFixed(1)}"
                 class="glint" transform="rotate(-35 ${(x - r * 0.3).toFixed(1)} ${(y - r * 0.35).toFixed(1)})"/>
      </g>
      <g class="steamgroup">${steam}</g>`;
  }

  _onClick(event) {
    const action = event.target.closest("[data-action]");
    if (action && action.dataset.action === "camera") {
      this._showCamera = !this._showCamera;
      this._signature = undefined;
      this._render();
      return;
    }
    const target = event.target.closest("[data-entity]");
    if (!target || !target.dataset.entity) return;
    const moreInfo = new Event("hass-more-info", { bubbles: true, composed: true });
    moreInfo.detail = { entityId: target.dataset.entity };
    this.dispatchEvent(moreInfo);
  }
}

const STYLE = `
  :host { display: block; }
  ha-card { overflow: hidden; }
  .header {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    padding: 14px 16px 6px;
  }
  .title { font-size: 1.15em; font-weight: 500; flex: 1 1 auto; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; }
  .chip {
    font-size: 0.8em; padding: 3px 10px; border-radius: 999px;
    background: var(--secondary-background-color); color: var(--secondary-text-color);
  }
  .chip.on { background: rgba(229, 38, 31, 0.18); color: #ff6b4a; }
  .chip.hot { background: rgba(255, 154, 60, 0.18); color: #ff9a3c; }
  .chip.pot { background: rgba(120, 160, 200, 0.18); color: #8fb4dc; }
  .chip.ir { background: rgba(120, 110, 220, 0.2); color: #a99cff; }
  .toggle {
    border: none; background: var(--secondary-background-color); border-radius: 999px;
    width: 32px; height: 32px; cursor: pointer; font-size: 15px;
  }
  .stove { position: relative; padding: 4px 12px 14px; }
  svg { width: 100%; height: auto; display: block; }
  .frame { fill: #2a2d33; stroke: #3a3e46; stroke-width: 2; }
  .ring { fill: none; stroke: rgba(255, 255, 255, 0.32); stroke-width: 1.6; }
  .ring.lit { stroke: rgba(255, 190, 150, 0.55); }
  .track { fill: none; stroke: rgba(255, 255, 255, 0.06); stroke-width: 5; }
  .level { fill: none; stroke: #ff6a2b; stroke-width: 5; stroke-linecap: round; }
  .unsure { fill: none; stroke: rgba(255, 255, 255, 0.25); stroke-width: 2; stroke-dasharray: 4 8; }
  .coil { fill: none; stroke: #ff5a1f; stroke-width: 3; }
  .heat { animation: pulse ease-in-out infinite; transform-box: fill-box; transform-origin: center; }
  .ember { animation: breathe 5s ease-in-out infinite; }
  @keyframes pulse {
    0%, 100% { transform: scale(0.97); filter: brightness(0.9); }
    50% { transform: scale(1.02); filter: brightness(1.15); }
  }
  @keyframes breathe { 0%, 100% { opacity: 0.55; } 50% { opacity: 1; } }
  .hit { fill: transparent; cursor: pointer; }
  .zone, .digit, .pot { cursor: pointer; }
  .pot .handle { stroke: #4a4f57; stroke-width: 14; stroke-linecap: round; }
  .pot .rim { fill: none; stroke: rgba(255, 255, 255, 0.35); stroke-width: 2; }
  .pot .glint { fill: rgba(255, 255, 255, 0.55); }
  .steam {
    fill: none; stroke: rgba(255, 255, 255, 0.55); stroke-width: 4; stroke-linecap: round;
    opacity: 0; animation: steam 2.8s ease-out infinite; pointer-events: none;
  }
  @keyframes steam {
    0% { opacity: 0; transform: translateY(6px); }
    30% { opacity: 0.7; }
    100% { opacity: 0; transform: translateY(-34px); }
  }
  .seg { fill: rgba(255, 60, 90, 0.07); }
  .seg.on { fill: #ff2d55; }
  .brand {
    fill: rgba(255, 255, 255, 0.28); font: 600 11px sans-serif; text-anchor: middle;
    letter-spacing: 1px;
  }
  .scale text { fill: rgba(255, 255, 255, 0.4); font: 600 12px sans-serif; text-anchor: middle; }
  .overlay {
    position: absolute; inset: 4px 12px 14px; border-radius: 22px;
    background: rgba(18, 16, 40, 0.72); backdrop-filter: blur(3px);
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 10px; color: #cfc8ff; text-align: center; font-size: 0.95em;
  }
  .overlay div:first-child { font-size: 2.4em; }
  .camera { display: grid; gap: 8px; padding: 4px 12px 14px; }
  .camera img { width: 100%; border-radius: 12px; display: block; }
`;

if (!customElements.get("stove-vision-card")) {
  customElements.define("stove-vision-card", StoveVisionCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "stove-vision-card",
    name: "Stove Vision",
    description: "The stove drawn from Stove Vision: heat, residual heat, pots and the control panel.",
    preview: true,
    documentationURL: "https://github.com/pschmitt/homeassistant-stove-vision",
  });
}
