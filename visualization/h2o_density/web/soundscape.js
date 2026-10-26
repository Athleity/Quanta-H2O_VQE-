/* Optional cinematic sonification. Kept in its own module so it never runs in the WebGL frame loop. */
(() => {
  "use strict";
  const host = document.getElementById("drawer-controls") || document.getElementById("panel");
  if (!host) return;

  const style = document.createElement("style");
  style.textContent = `
    #soundscape{margin-top:12px;padding:10px;border:1px solid #38475a;border-radius:10px;background:rgba(10,18,31,.94);color:#e8f0fa}
    #soundscape legend{padding:0 6px;color:#9fe4e0;font-weight:650}
    #soundscape .sound-row{display:grid;grid-template-columns:auto 1fr;gap:8px 12px;align-items:center}
    #soundscape button{grid-column:1/-1;min-height:40px;border:1px solid #5d8795;border-radius:8px;background:linear-gradient(110deg,#16273b,#233d51);color:#f3f7ff;font-weight:650;cursor:pointer}
    #soundscape button:hover,#soundscape button:focus-visible{border-color:#9fe4e0;outline:2px solid #9fe4e055}
    #soundscape input{width:100%;accent-color:#78d7d1}
    #soundscape .sound-readout{margin:7px 0 0;color:#d6e8ee;font-size:12px;font-variant-numeric:tabular-nums}
    #soundscape .sound-note{margin:6px 0 0;color:#aebdca;font-size:11px;line-height:1.45}
    #soundscape .sound-key{color:#f3d59c;font-weight:650}
  `;
  document.head.append(style);

  const field = document.createElement("fieldset");
  field.id = "soundscape";
  field.innerHTML = `
    <legend>Original space ambience · optional</legend>
    <div class="sound-row">
      <button id="sound-toggle" type="button" aria-pressed="false">▶ Listen to the stretch</button>
      <label for="sound-volume">Volume</label>
      <input id="sound-volume" type="range" min="0" max="0.55" step="0.01" value="0.28" aria-label="Ambient sound volume">
    </div>
    <p class="sound-readout" id="sound-readout" aria-live="polite">Waiting for the molecule…</p>
    <p class="sound-note">A slow cinematic drone with spacious echoes and a soft harmonic shimmer. As R₂ stretches, the musical root rises from D₂ through A₂ to E₃ (one perfect fifth per 0.40 Å). This is original artistic sonification—not recorded sound or measured molecular vibration.</p>`;
  host.append(field);

  const button = document.getElementById("sound-toggle");
  const volume = document.getElementById("sound-volume");
  const readout = document.getElementById("sound-readout");
  const noteNames = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"];
  let ctx = null, master = null, tones = [], airFilter = null;
  let enabled = false, currentR2 = 2.2, lastPitchR2 = NaN, lastReadout = "";

  function mappedRoot(r2) {
    const fifths = Math.max(0, Math.min(2, (r2 - 1.8) / 0.4));
    const midi = 38 + 7 * fifths; // The three calculated geometries map to D2, A2, and E3.
    return { midi, hz: 440 * Math.pow(2, (midi - 69) / 12) };
  }
  function setGeometry(value) {
    const r2 = Number(value);
    if (!Number.isFinite(r2)) return;
    currentR2 = r2;
    const map = mappedRoot(r2), roundedMidi = Math.round(map.midi);
    const label = `R₂ = ${r2.toFixed(2)} Å  ·  mapped tone ${noteNames[roundedMidi % 12]}${Math.floor(roundedMidi / 12) - 1}`;
    if (label !== lastReadout) { readout.textContent = label; lastReadout = label; }
    // Ignore sub-pixel bond changes; throttling frequency automation prevents needless audio scheduling.
    if (!ctx || !enabled || Math.abs(r2 - lastPitchR2) < 0.008) return;
    lastPitchR2 = r2;
    const now = ctx.currentTime;
    [map.hz / 2, map.hz, map.hz * 1.5, map.hz * 2, map.hz * 3].forEach((hz, i) => {
      const f = tones[i].frequency;
      f.cancelScheduledValues(now); f.setTargetAtTime(hz, now, 0.24);
    });
    airFilter.frequency.setTargetAtTime(520 + 520 * Math.max(0, Math.min(1, (r2 - 1.8) / 0.8)), now, 0.5);
  }
  function startEngine() {
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) throw new Error("This browser does not support Web Audio.");
    ctx = new Audio();
    const limiter = ctx.createDynamicsCompressor();
    limiter.threshold.value = -20; limiter.knee.value = 16; limiter.ratio.value = 3;
    limiter.attack.value = 0.035; limiter.release.value = 0.45;
    master = ctx.createGain(); master.gain.value = 0;
    master.connect(limiter); limiter.connect(ctx.destination);

    // One slow echo loop supplies a spacious film-score character without loading audio files.
    const dryBus = ctx.createGain(), delay = ctx.createDelay(1.5);
    const feedback = ctx.createGain(), echoTone = ctx.createBiquadFilter(), wetBus = ctx.createGain();
    delay.delayTime.value = 0.72; feedback.gain.value = 0.22;
    echoTone.type = "lowpass"; echoTone.frequency.value = 1700;
    dryBus.gain.value = 0.90; wetBus.gain.value = 0.24;
    dryBus.connect(master); delay.connect(echoTone); echoTone.connect(feedback);
    feedback.connect(delay); delay.connect(wetBus); wetBus.connect(master);

    const pan = ctx.createStereoPanner(), voices = ctx.createGain();
    voices.connect(pan); pan.connect(dryBus); pan.connect(delay);
    const panLfo = ctx.createOscillator(), panDepth = ctx.createGain();
    panLfo.frequency.value = 0.028; panDepth.gain.value = 0.16;
    panLfo.connect(panDepth); panDepth.connect(pan.pan); panLfo.start();

    // Five quiet harmonic layers form a warm, slowly breathing chord.
    const root = mappedRoot(currentR2).hz;
    tones = [];
    for (const [multiple, level, type] of [[0.5, 0.10, "sine"], [1, 0.20, "triangle"], [1.5, 0.075, "sine"], [2, 0.035, "sine"], [3, 0.012, "sine"]]) {
      const osc = ctx.createOscillator(), amp = ctx.createGain();
      osc.type = type; osc.frequency.value = root * multiple; amp.gain.value = level;
      osc.connect(amp); amp.connect(voices); osc.start(); tones.push(osc);
    }
    // Slow gain modulation adds motion without scheduling work on the page's animation loop.
    const breath = ctx.createOscillator(), breathDepth = ctx.createGain();
    voices.gain.value = 0.88; breath.frequency.value = 0.075; breathDepth.gain.value = 0.12;
    breath.connect(breathDepth); breathDepth.connect(voices.gain); breath.start();

    // A very quiet filtered triangle adds a distant, airy shimmer without a noise buffer or CPU-heavy reverb.
    const air = ctx.createOscillator(), airGain = ctx.createGain();
    air.type = "triangle"; air.frequency.value = root * 6;
    airFilter = ctx.createBiquadFilter(); airFilter.type = "lowpass"; airFilter.frequency.value = 520; airFilter.Q.value = 0.7;
    airGain.gain.value = 0.012; air.connect(airFilter); airFilter.connect(airGain); airGain.connect(pan); air.start();
  }
  async function play() {
    try {
      if (!ctx) startEngine();
      await ctx.resume(); enabled = true; lastPitchR2 = NaN;
      const now = ctx.currentTime;
      master.gain.cancelScheduledValues(now);
      master.gain.setTargetAtTime(Number(volume.value), now, 0.45);
      button.textContent = "Ⅱ Pause ambience"; button.setAttribute("aria-pressed", "true");
      setGeometry(currentR2);
    } catch (error) {
      button.textContent = "Audio unavailable"; button.disabled = true;
      readout.textContent = error.message;
    }
  }
  function pause() {
    enabled = false; lastPitchR2 = NaN;
    if (ctx && master) {
      const now = ctx.currentTime; master.gain.cancelScheduledValues(now);
      master.gain.setTargetAtTime(0, now, 0.16);
    }
    button.textContent = "▶ Listen to the stretch"; button.setAttribute("aria-pressed", "false");
  }
  button.addEventListener("click", () => enabled ? pause() : play());
  volume.addEventListener("input", () => {
    if (enabled && ctx && master) master.gain.setTargetAtTime(Number(volume.value), ctx.currentTime, 0.06);
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden && enabled) pause();
  });
  window.H2OSoundscape = { setGeometry };
})();
