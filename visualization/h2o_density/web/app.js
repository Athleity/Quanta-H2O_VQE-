"use strict";
/* H2O electron-density viewer. Pure WebGL2, no dependencies.
   Rendering = real geometry (no ray-marching): isodensity shells meshed once in JS (marching tetrahedra),
   additive "glass" shading, opaque lit atom/bond meshes.  Cost per frame is a few dozen draw calls. */
const $ = (id) => document.getElementById(id);
const STILL = new URLSearchParams(location.search).has("still");    // ?still: no intro / auto-rotate / auto-stretch (tests)
const errs = (window.__errors = []); window.__perf = { meshMs: 0, remeshes: 0 };
window.addEventListener("error", (e) => errs.push(String(e.message)));
function fail(m) { errs.push(m); const e = $("error"); e.hidden = false; e.textContent = m; $("progress").hidden = true; }

// ---------------- math (column-major mat4) ----------------
const sub = (a, b) => [a[0]-b[0], a[1]-b[1], a[2]-b[2]], dot = (a, b) => a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
const cross = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
const nrm = (a) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0]/l, a[1]/l, a[2]/l]; };
function mul(a, b) { const o = new Float32Array(16); for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) o[c*4+r] = a[r]*b[c*4] + a[4+r]*b[c*4+1] + a[8+r]*b[c*4+2] + a[12+r]*b[c*4+3]; return o; }
function persp(fy, asp, n, f) { const t = 1 / Math.tan(fy / 2); return new Float32Array([t/asp,0,0,0, 0,t,0,0, 0,0,(f+n)/(n-f),-1, 0,0,2*f*n/(n-f),0]); }
function lookAt(e, t, up) { const z = nrm(sub(e, t)), x = nrm(cross(up, z)), y = cross(z, x); return new Float32Array([x[0],y[0],z[0],0, x[1],y[1],z[1],0, x[2],y[2],z[2],0, -dot(x,e),-dot(y,e),-dot(z,e),1]); }
const FOV = 40 * Math.PI / 180, TANH = Math.tan(FOV / 2);

// ---------------- scene constants ----------------
const BOHR = 0.52917721092;
const BASE_LEVELS = [0.004, 0.02, 0.08, 0.4, 2.5];                       // e/bohr^3, outer -> inner
const SHELL_COL = [[0.10,0.32,1.0],[0.16,0.52,1.0],[0.20,0.78,1.0],[0.62,0.97,1.0],[1.0,0.97,0.86]];
const SHELL_A = [0.50,0.50,0.55,0.65,0.8];
const ATOM = { O: { r: 0.62, c: [1.0, 0.24, 0.18] }, H: { r: 0.36, c: [0.96, 0.97, 1.0] } };
const BOND_C = [0.62, 0.68, 0.78], DEF = { yaw: 0.65, pitch: 0.45, dist: 15 };
const defDist = () => Math.max(DEF.dist, 11 / (TANH * (view.w / view.h)));
const narrow = () => window.innerWidth <= 820;

// ---------------- WebGL setup ----------------
const canvas = $("gl");
const gl = canvas.getContext("webgl2", { antialias: true, alpha: false, powerPreference: "high-performance", preserveDrawingBuffer: false });
const S = { man: null, sets: [], levMul: 1, r: 2.2, playing: !STILL, auto: false, phase: 0, reveal: STILL ? 1 : 0, ready: false, dirty: true, lastInput: 0, interacting: false, q: 0.78, src: "casci", nearest: -1 };
const cam = { yaw: DEF.yaw, pitch: DEF.pitch, dist: DEF.dist, target: [0, 0, 0] };
let view = { w: 800, h: 600 }, camAnim = null, rTween = null, idleT, P = {}, SPH, CYL;

const MESH_VS = `#version 300 es
layout(location=0) in vec3 aPos; layout(location=1) in vec3 aNrm; uniform mat4 uVP; out vec3 vN; out vec3 vP;
void main(){vP=aPos;vN=aNrm;gl_Position=uVP*vec4(aPos,1.);}`;
const MESH_FS = `#version 300 es
precision highp float; in vec3 vN; in vec3 vP; uniform vec3 uEye,uCol; uniform float uA; out vec4 o;
void main(){vec3 n=normalize(vN),v=normalize(uEye-vP);float f=1.-abs(dot(n,v));float i=uA*(.14+1.35*f*f*f);o=vec4(uCol*i,1.);}`;
const SOL_VS = `#version 300 es
layout(location=0) in vec3 aPos; layout(location=1) in vec3 aNrm; uniform mat4 uVP,uModel; out vec3 vN; out vec3 vP; out float vT;
void main(){vec4 w=uModel*vec4(aPos,1.);vP=w.xyz;vN=mat3(uModel)*aNrm;vT=aPos.z;gl_Position=uVP*w;}`;
const SOL_FS = `#version 300 es
precision highp float; in vec3 vN; in vec3 vP; in float vT; uniform vec3 uEye,uCol,uL; uniform float uDash,uSpec; out vec4 o;
void main(){ if(uDash>0.5&&fract(vT*uDash)>0.55)discard;
 vec3 n=normalize(vN),v=normalize(uEye-vP),l=normalize(uL),h=normalize(l+v);
 float d=max(dot(n,l),0.),s=pow(max(dot(n,h),0.),uSpec),rim=pow(1.-max(dot(n,v),0.),3.);
 vec3 c=uCol*(0.16+0.95*d)+vec3(1.)*s*0.65+uCol*rim*0.55; o=vec4(c,1.);}`;
function program(vs, fs) {
  const sh = (t, s) => { const x = gl.createShader(t); gl.shaderSource(x, s); gl.compileShader(x); if (!gl.getShaderParameter(x, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(x)); return x; };
  const p = gl.createProgram(); gl.attachShader(p, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  const u = {}; for (let i = 0, n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS); i < n; i++) { const nm = gl.getActiveUniform(p, i).name; u[nm] = gl.getUniformLocation(p, nm); }
  return { p, u };
}
function vao(data) {
  const v = gl.createVertexArray(); gl.bindVertexArray(v); const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 24, 0); gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 3, gl.FLOAT, false, 24, 12);
  return { v, n: data.length / 6, b };
}
function sphereMesh(la = 40, lo = 72) {
  const pt = (i, j) => { const th = Math.PI * i / la, ph = 2 * Math.PI * j / lo, s = Math.sin(th); return [s * Math.cos(ph), Math.cos(th), s * Math.sin(ph)]; }, out = [];
  for (let i = 0; i < la; i++) for (let j = 0; j < lo; j++) for (const q of [pt(i,j), pt(i+1,j), pt(i+1,j+1), pt(i,j), pt(i+1,j+1), pt(i,j+1)]) out.push(...q, ...q);
  return vao(new Float32Array(out));
}
function cylMesh(seg = 48) {
  const out = []; for (let j = 0; j < seg; j++) { const a = 2*Math.PI*j/seg, b = 2*Math.PI*(j+1)/seg, ca = Math.cos(a), sa = Math.sin(a), cb = Math.cos(b), sb = Math.sin(b);
    const V = (c, s, z) => [c, s, z, c, s, 0]; out.push(...V(ca,sa,0), ...V(cb,sb,0), ...V(cb,sb,1), ...V(ca,sa,0), ...V(cb,sb,1), ...V(ca,sa,1)); }
  return vao(new Float32Array(out));
}

// ---------------- marching tetrahedra isosurface ----------------
const CO = [[0,0,0],[1,0,0],[1,1,0],[0,1,0],[0,0,1],[1,0,1],[1,1,1],[0,1,1]];
const TETS = [[0,5,1,6],[0,1,2,6],[0,2,3,6],[0,3,7,6],[0,7,4,6],[0,4,5,6]];
async function isoMesh(vol, nx, ny, nz, org, h, L, st) {
  let buf = new Float32Array(1 << 16), len = 0;
  const push = (x, y, z, a, b, c) => { if (len + 6 > buf.length) { const nb = new Float32Array(buf.length * 2); nb.set(buf); buf = nb; } buf[len++] = x; buf[len++] = y; buf[len++] = z; buf[len++] = a; buf[len++] = b; buf[len++] = c; };
  const at = (i, j, k) => vol[Math.min(nx-1, Math.max(0, i)) + nx * (Math.min(ny-1, Math.max(0, j)) + ny * Math.min(nz-1, Math.max(0, k)))];
  const v = new Float64Array(8), ci = new Int32Array(8), cj = new Int32Array(8), ck = new Int32Array(8);
  const edge = (a, b) => {
    const t = (L - v[a]) / (v[b] - v[a]), ia = ci[a], ja = cj[a], ka = ck[a], ib = ci[b], jb = cj[b], kb = ck[b];
    const gx = (1-t) * (at(ia+1,ja,ka) - at(ia-1,ja,ka)) + t * (at(ib+1,jb,kb) - at(ib-1,jb,kb));
    const gy = (1-t) * (at(ia,ja+1,ka) - at(ia,ja-1,ka)) + t * (at(ib,jb+1,kb) - at(ib,jb-1,kb));
    const gz = (1-t) * (at(ia,ja,ka+1) - at(ia,ja,ka-1)) + t * (at(ib,jb,kb+1) - at(ib,jb,kb-1));
    const l = Math.hypot(gx, gy, gz) || 1;
    return [org[0] + h * (ia + t * (ib - ia)), org[1] + h * (ja + t * (jb - ja)), org[2] + h * (ka + t * (kb - ka)), -gx / l, -gy / l, -gz / l];
  };
  for (let k = 0; k < nz - st; k += st) {
    await tick(); // let the browser paint and process input between volume slices
    for (let j = 0; j < ny - st; j += st) for (let i = 0; i < nx - st; i += st) {
    let mn = 1e30, mx = -1e30;
    for (let c = 0; c < 8; c++) { ci[c] = i + CO[c][0]*st; cj[c] = j + CO[c][1]*st; ck[c] = k + CO[c][2]*st; const x = vol[ci[c] + nx * (cj[c] + ny * ck[c])]; v[c] = x; if (x < mn) mn = x; if (x > mx) mx = x; }
    if (mn >= L || mx < L) continue;
    for (const T of TETS) {
      const ins = [], out = []; for (const c of T) (v[c] >= L ? ins : out).push(c);
      const tri = (a, b, c) => { for (const e of [a, b, c]) push(...e); };
      if (ins.length === 1) tri(edge(ins[0], out[0]), edge(ins[0], out[1]), edge(ins[0], out[2]));
      else if (ins.length === 3) tri(edge(out[0], ins[0]), edge(out[0], ins[1]), edge(out[0], ins[2]));
      else if (ins.length === 2) { const a = edge(ins[0], out[0]), b = edge(ins[0], out[1]), c = edge(ins[1], out[1]), d = edge(ins[1], out[0]); tri(a, b, c); tri(a, c, d); }
    }
  }
  }
  return buf.slice(0, len);
}
const H2F = (() => { const t = new Float32Array(65536); for (let h = 0; h < 65536; h++) { const e = (h >> 10) & 31, m = h & 1023, s = h & 0x8000 ? -1 : 1; t[h] = s * (e === 0 ? m * 5.960464477539063e-8 : e === 31 ? 0 : Math.pow(2, e - 15) * (1 + m / 1024)); } return t; })();
async function subVolume(u16, n, o, h) { // decode float16 -> float32 while yielding so loading does not freeze the page
  const [nx, ny, nz] = n, mn = [nx, ny, nz], mx = [-1, -1, -1];
  for (let z = 0; z < nz; z++) {
    if ((z & 3) === 0) await tick();
    for (let y = 0; y < ny; y++) {
      const b = nx * (y + ny * z);
      for (let x = 0; x < nx; x++) if (H2F[u16[b + x]] > 3e-4) {
        if (x < mn[0]) mn[0] = x; if (x > mx[0]) mx[0] = x;
        if (y < mn[1]) mn[1] = y; if (y > mx[1]) mx[1] = y;
        if (z < mn[2]) mn[2] = z; if (z > mx[2]) mx[2] = z;
      }
    }
  }
  const lo = [0, 1, 2].map((k) => Math.max(0, mn[k] - 3));
  const hi = [0, 1, 2].map((k) => Math.min(n[k] - 1, mx[k] + 3));
  const d = [0, 1, 2].map((k) => hi[k] - lo[k] + 1);
  const vol = new Float32Array(d[0] * d[1] * d[2]); let q = 0;
  for (let z = lo[2]; z <= hi[2]; z++) {
    if (((z - lo[2]) & 3) === 0) await tick();
    for (let y = lo[1]; y <= hi[1]; y++) {
      const b = nx * (y + ny * z);
      for (let x = lo[0]; x <= hi[0]; x++) vol[q++] = H2F[u16[b + x]];
    }
  }
  return { vol, d, org: [0, 1, 2].map((k) => o[k] + lo[k] * h), h };
}const tick = () => new Promise((r) => setTimeout(r, 0));
async function buildMeshes(set, onStep) {
  for (const m of set.meshes || []) { gl.deleteVertexArray(m.v); gl.deleteBuffer(m.b); }
  set.meshes = [];
  for (let li = 0; li < BASE_LEVELS.length; li++) {
    const L = BASE_LEVELS[li] * S.levMul, st = L < 0.01 ? 2 : 1;
    const data = await isoMesh(set.sv.vol, set.sv.d[0], set.sv.d[1], set.sv.d[2], set.sv.org, set.sv.h, L, st);
    set.meshes.push(vao(data)); await tick(); if (onStep) onStep();
  }
}

// ---------------- camera + animation ----------------
function basis() {
  const cp = Math.cos(cam.pitch), eye = [cam.target[0] + cam.dist*cp*Math.sin(cam.yaw), cam.target[1] + cam.dist*Math.sin(cam.pitch), cam.target[2] + cam.dist*cp*Math.cos(cam.yaw)];
  const fwd = nrm(sub(cam.target, eye)), right = nrm(cross(fwd, [0, 1, 0])), up = cross(right, fwd); return { eye, fwd, right, up };
}
const ease = (t) => (t < 0.5 ? 4*t*t*t : 1 - Math.pow(-2*t + 2, 3) / 2), easeOut = (t) => 1 - Math.pow(1 - t, 4);
function flyTo(to, ms, ef = ease) { camAnim = { from: { yaw: cam.yaw, pitch: cam.pitch, dist: cam.dist, target: cam.target.slice() }, to, t0: performance.now(), ms, ef }; }
function stepCam(now) {
  if (!camAnim) return false; const a = camAnim, u = Math.min(1, (now - a.t0) / a.ms), e = a.ef(u), L = (x, y) => x + (y - x) * e;
  cam.yaw = L(a.from.yaw, a.to.yaw); cam.pitch = L(a.from.pitch, a.to.pitch); cam.dist = L(a.from.dist, a.to.dist); cam.target = a.from.target.map((v, i) => L(v, a.to.target[i]));
  if (u >= 1) camAnim = null; return true;
}
function resetView(keep) { flyTo({ yaw: keep ? cam.yaw : DEF.yaw + Math.round((cam.yaw - DEF.yaw) / (2*Math.PI)) * 2*Math.PI, pitch: keep ? cam.pitch : DEF.pitch, dist: defDist(), target: S.center }, 750); S.dirty = true; }
function glideTo(r) { S.playing = false; syncPlay(); rTween = { from: S.r, to: r, t0: performance.now(), ms: 800 }; }

// ---------------- geometry for current bond length ----------------
function atomsAt(r) { const d = S.dir2; return [[0, 0, 0], S.h1, [d[0] * r / BOHR, d[1] * r / BOHR, d[2] * r / BOHR]]; }
function weights(r) { return S.sets.map((s) => Math.max(0, 1 - Math.abs(r - s.r2) / 0.4)); }
const T4 = (x, y, z, sx, sy, sz) => new Float32Array([sx,0,0,0, 0,sy,0,0, 0,0,sz,0, x,y,z,1]);
function bondM(A, B, rad) {
  const d = sub(B, A), len = Math.hypot(...d), z = nrm(d), hh = Math.abs(z[1]) > 0.9 ? [1, 0, 0] : [0, 1, 0], x = nrm(cross(hh, z)), y = cross(z, x);
  return new Float32Array([x[0]*rad,x[1]*rad,x[2]*rad,0, y[0]*rad,y[1]*rad,y[2]*rad,0, z[0]*len,z[1]*len,z[2]*len,0, A[0],A[1],A[2],1]);
}

// ---------------- drawing ----------------
function draw() {
  if (!S.ready) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2), k = Math.sqrt(Math.min(1, 2.4e6 / (view.w * view.h * dpr * dpr))) * S.q;
  const w = Math.max(2, Math.round(view.w * dpr * k)), h = Math.max(2, Math.round(view.h * dpr * k));
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  gl.viewport(0, 0, w, h); gl.clearColor(0, 0, 0, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  const b = basis(), VP = mul(persp(FOV, w / h, 0.5, 300), lookAt(b.eye, cam.target, [0, 1, 0]));
  const A = atomsAt(S.r), asz = +$("asz").value;
  gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LEQUAL); gl.depthMask(true); gl.disable(gl.BLEND); gl.disable(gl.CULL_FACE);
  const sp = P.sol; gl.useProgram(sp.p); gl.uniformMatrix4fv(sp.u.uVP, false, VP); gl.uniform3fv(sp.u.uEye, b.eye);
  gl.uniform3fv(sp.u.uL, nrm([b.eye[0] - cam.target[0] - b.right[0]*6 + b.up[0]*8, b.eye[1] - cam.target[1] - b.right[1]*6 + b.up[1]*8, b.eye[2] - cam.target[2] - b.right[2]*6 + b.up[2]*8]));
  gl.bindVertexArray(SPH.v);
  [["O", A[0]], ["H", A[1]], ["H", A[2]]].forEach(([el, p]) => { const r = ATOM[el].r * asz; gl.uniformMatrix4fv(sp.u.uModel, false, T4(p[0], p[1], p[2], r, r, r)); gl.uniform3fv(sp.u.uCol, ATOM[el].c); gl.uniform1f(sp.u.uDash, 0); gl.uniform1f(sp.u.uSpec, 60); gl.drawArrays(gl.TRIANGLES, 0, SPH.n); });
  gl.bindVertexArray(CYL.v); gl.uniform3fv(sp.u.uCol, BOND_C); gl.uniform1f(sp.u.uSpec, 30);
  gl.uniformMatrix4fv(sp.u.uModel, false, bondM(A[0], A[1], 0.075 * asz)); gl.uniform1f(sp.u.uDash, 0); gl.drawArrays(gl.TRIANGLES, 0, CYL.n);
  gl.uniformMatrix4fv(sp.u.uModel, false, bondM(A[0], A[2], 0.075 * asz)); gl.uniform1f(sp.u.uDash, 16); gl.drawArrays(gl.TRIANGLES, 0, CYL.n);
  // translucent density shells: additive, order independent, depth-tested against atoms
  const mp = P.mesh; gl.useProgram(mp.p); gl.uniformMatrix4fv(mp.u.uVP, false, VP); gl.uniform3fv(mp.u.uEye, b.eye);
  gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE); gl.depthMask(false);
  const wt = weights(S.r), glow = +$("sop").value;
  S.sets.forEach((set, si) => { if (wt[si] < 0.002 || !set.meshes) return; set.meshes.forEach((m, li) => {
      const loc = Math.min(1, Math.max(0, (S.reveal - (4 - li) * 0.13) / 0.45)), a = SHELL_A[li] * glow * wt[si] * easeOut(loc); if (a < 0.001) return;
      gl.bindVertexArray(m.v); gl.uniform3fv(mp.u.uCol, SHELL_COL[li]); gl.uniform1f(mp.u.uA, a); gl.drawArrays(gl.TRIANGLES, 0, m.n); }); });
  gl.depthMask(true); gl.disable(gl.BLEND);
  labels(VP, A);
  window.__frames = (window.__frames || 0) + 1;
}
function labels(VP, A) {
  const L = $("labels").children, txt = ["O", "H₁", `H₂`];
  A.forEach((p, i) => {
    const q = [p[0], p[1] + (i === 0 ? 0.95 : 0.7) * +$("asz").value, p[2], 1], x = VP[0]*q[0] + VP[4]*q[1] + VP[8]*q[2] + VP[12], y = VP[1]*q[0] + VP[5]*q[1] + VP[9]*q[2] + VP[13], wv = VP[3]*q[0] + VP[7]*q[1] + VP[11]*q[2] + VP[15], s = L[i];
    if (s.textContent !== txt[i]) s.textContent = txt[i]; s.style.display = wv > 0 ? "" : "none";
    s.style.left = ((x / wv) * 0.5 + 0.5) * view.w + "px"; s.style.top = (1 - ((y / wv) * 0.5 + 0.5)) * view.h + "px";
  });
}

// ---------------- frame loop ----------------
let lastT = 0, shownR = -1;
function frame(now) {
  requestAnimationFrame(frame); const dt = Math.min(0.1, (now - (lastT || now)) / 1000); lastT = now;
  let anim = stepCam(now);
  if (S.ready) {
    if (S.reveal < 1) { S.reveal = Math.min(1, S.reveal + dt / 2.6); anim = true; }
    if (S.playing && S.reveal >= 0.85) { S.phase += dt * 2 * Math.PI / 7; S.r = 2.2 + 0.4 * Math.sin(S.phase); anim = true; }
    else if (rTween) { const u = Math.min(1, (now - rTween.t0) / rTween.ms); S.r = rTween.from + (rTween.to - rTween.from) * ease(u); if (u >= 1) rTween = null; anim = true; }
    if (S.auto && now - S.lastInput > 2200 && !camAnim) { cam.yaw += 0.16 * dt; anim = true; }
  }
  if (anim || S.dirty) { const gap = now - (S.lastDraw || now); S.lastDraw = now;   // adaptive quality: slow GPU/CPU renderer -> fewer pixels, never a stalled page
    if (anim && gap > 0) { S.gapAvg = (S.gapAvg || gap) * 0.75 + gap * 0.25; if (S.gapAvg > 32 && S.q > 0.35) { S.q = Math.max(0.35, S.q * 0.78); S.gapAvg = 24; } else if (S.gapAvg < 19 && S.q < 1) S.q = Math.min(1, S.q * 1.025); } else if (!anim) S.q = Math.min(1, S.q * 1.3);
    S.dirty = false; if (Math.abs(S.r - shownR) > 1e-4) updateReadout(); try { draw(); } catch (e) { fail(String(e)); } }
}
function bump(interactive) { S.dirty = true; if (interactive) { S.interacting = true; S.lastInput = performance.now(); camAnim = null; clearTimeout(idleT); idleT = setTimeout(() => { S.interacting = false; }, 160); } }

// ---------------- UI ----------------
function nearestIdx(r) { let b = 0; S.sets.forEach((s, i) => { if (Math.abs(s.r2 - r) < Math.abs(S.sets[b].r2 - r)) b = i; }); return b; }
function updateReadout() {
  shownR = S.r; window.H2OSoundscape?.setGeometry(S.r); const t = S.r.toFixed(2); $("r2val").textContent = t; const hr = $("hr2"); if (hr) hr.textContent = t;
  const i = nearestIdx(S.r), exact = Math.abs(S.sets[i].r2 - S.r) < 0.006, tag = $("rtag");
  tag.textContent = exact ? "computed geometry" : "interpolated · atoms move, densities cross-fade"; tag.classList.toggle("interp", !exact);
  if (document.activeElement !== $("scrub") || S.playing || rTween) $("scrub").value = S.r;
  document.querySelectorAll("#geoms button").forEach((b, j) => b.setAttribute("aria-pressed", exact && j === i));
  if (i !== S.nearest) { S.nearest = i; info(); }
}
function syncPlay() { const b = $("btn-play"); b.setAttribute("aria-pressed", S.playing); b.textContent = S.playing ? (narrow() ? "Pause" : "Pause stretch") : (narrow() ? "Play" : "Play stretch"); $("btn-rotate").textContent = narrow() ? "Rotate" : "Auto-rotate"; }
function headline() {
  const d = S.sets[0].ds;
  $("headline").innerHTML = `Asymmetric O–H stretch: R₁ = ${d.geometry.r1_angstrom.toFixed(2)} Å (fixed), R₂ = <span id="hr2">${S.r.toFixed(2)}</span> Å, ∠HOH = ${d.geometry.hoh_angle_deg}° · ρ(r) in e/bohr³, integrates to 10 electrons (not a probability density) · ${d.label}`;
}
function legend() {
  $("shells").innerHTML = BASE_LEVELS.map((v, i) => `<li><span>${(v * S.levMul).toPrecision(2)}</span><i style="color:rgb(${SHELL_COL[i].map((c) => Math.round(c * 255))});background:currentColor"></i></li>`).join("");
}
function info() {
  const d = S.sets[Math.max(0, S.nearest)].ds, k = d.checks, e = d.energies_hartree, f = (v, n = 6) => (+v).toFixed(n);
  const rows = [["Nearest computed geometry", `R₂ = ${d.geometry.r2_angstrom.toFixed(2)} Å`], ["Source", d.label], ["Energies (Eh)", `RHF ${f(e.rhf, 8)} · CASCI ${f(e.casci, 8)}`],
    ["∫ρ checks", `Tr(PS) = ${f(k.trace_PS, 8)}; fine-grid (h = ${k.audit_spacing_bohr} bohr) = ${f(k.audit_grid_sum_h0p06, 5)}; stored float16 grid sum = ${f(k.grid_sum_stored_float16, 4)}`],
    ["Active natural occ.", k.natural_occupations.map((v) => v.toFixed(3)).join(", ")], ["ρ max (e/bohr³)", d.rho_range.max.toExponential(2)], ["Grid", `${d.shape_xyz.join("×")} @ ${d.spacing_bohr} bohr, float16`]];
  if (k.vs_saved_repo_reference) rows.push(["Vs repo reference", `ΔRHF ${k.vs_saved_repo_reference.rhf_diff.toExponential(1)}, ΔCASCI ${k.vs_saved_repo_reference.casci_diff.toExponential(1)} Eh; max Δocc ${k.vs_saved_repo_reference.max_natural_occ_diff.toExponential(1)}`]);
  if (d.phase_ambiguity) rows.push(["Orbital-sign ambiguity", `max |Δρ| = ${d.phase_ambiguity.max_abs_rho.toExponential(1)}`]);
  rows.push(["Animation", "Only R₂ = 1.80, 2.20, 2.60 Å are computed. Between them the atoms move continuously and the neighbouring densities cross-fade; intermediate densities are NOT computed."], ["Note", d.notes]);
  $("info").innerHTML = rows.map(([a, b]) => `<dt>${a}</dt><dd>${b}</dd>`).join("");
  $("srcnote").textContent = (S.man.vqe && !S.man.vqe.available ? "VQE: " + S.man.vqe.reason + " " : "") + "CASCI is the exact diagonalization of the same CAS(8e,6o) Hamiltonian, the reference for comparing a VQE state.";
}
function controls() {
  const lo = S.sets[0].r2, hi = S.sets[S.sets.length - 1].r2; $("scrub").min = lo; $("scrub").max = hi;
  $("geoms").innerHTML = S.sets.map((s, i) => `<button data-i="${i}" style="left:${((s.r2 - lo) / (hi - lo)) * 100}%" aria-pressed="false">${s.r2.toFixed(2)} Å</button>`).join("");
  document.querySelectorAll("#geoms button").forEach((b) => b.addEventListener("click", () => glideTo(S.sets[+b.dataset.i].r2)));
  const hasV = S.man.datasets.some((d) => d.source_kind === "vqe");
  $("sources").innerHTML = `<label><input type="radio" name="src" value="casci" checked>CASCI exact</label><label title="${hasV ? "" : S.man.vqe.reason}"><input type="radio" name="src" value="vqe" ${hasV ? "" : "disabled"}>${narrow() ? "VQE" : "VQE · PUCCSD"}${hasV ? "" : " · n/a"}</label>`;
  $("scrub").addEventListener("input", () => { S.playing = false; rTween = null; syncPlay(); S.r = +$("scrub").value; S.phase = Math.asin(Math.max(-1, Math.min(1, (S.r - 2.2) / 0.4))); S.dirty = true; });
  $("btn-play").onclick = () => { S.playing = !S.playing; rTween = null; if (S.playing) S.phase = Math.asin(Math.max(-1, Math.min(1, (S.r - 2.2) / 0.4))); syncPlay(); S.dirty = true; };
  const rot = $("btn-rotate"); rot.setAttribute("aria-pressed", S.auto); rot.onclick = () => { S.auto = !S.auto; rot.setAttribute("aria-pressed", S.auto); S.lastInput = 0; S.dirty = true; };
  const out = () => { $("levv").textContent = "×" + (10 ** +$("lev").value).toFixed(2); $("sopv").textContent = (+$("sop").value).toFixed(2); $("aszv").textContent = (+$("asz").value).toFixed(2); S.dirty = true; };
  ["lev", "sop", "asz"].forEach((id) => $(id).addEventListener("input", out)); out();
  $("lev").addEventListener("change", async () => {
    S.levMul = 10 ** +$("lev").value; legend(); $("progress").hidden = false; $("ptext").textContent = "Re-meshing shells…"; const t0 = performance.now();
    for (const s of S.sets) await buildMeshes(s); window.__perf.remeshes++; window.__perf.lastRemeshMs = performance.now() - t0; $("progress").hidden = true; S.dirty = true; });
  $("reset").onclick = () => { resetView(false); $("lev").value = 0; $("sop").value = 1; $("asz").value = 1; out(); $("lev").dispatchEvent(new Event("change")); };
  $("fit").onclick = () => resetView(true);
  const drawers = { "btn-controls": "drawer-controls", "btn-data": "drawer-data" };
  const closeAll = () => Object.entries(drawers).forEach(([b, d]) => { $(d).classList.remove("open"); $(b).setAttribute("aria-expanded", "false"); });
  Object.entries(drawers).forEach(([b, d]) => $(b).addEventListener("click", () => { const was = $(d).classList.contains("open"); closeAll(); if (!was) { $(d).classList.add("open"); $(b).setAttribute("aria-expanded", "true"); } }));
  window.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAll(); }); window.addEventListener("resize", syncPlay);
  syncPlay(); legend();
}
function interaction() {
  const ptr = new Map(); let lastPinch = 0;
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  canvas.addEventListener("pointerdown", (e) => { canvas.setPointerCapture(e.pointerId); ptr.set(e.pointerId, { x: e.clientX, y: e.clientY, pan: e.shiftKey || e.button === 2 }); lastPinch = 0; canvas.focus(); bump(true); });
  const up = (e) => { ptr.delete(e.pointerId); lastPinch = 0; }; canvas.addEventListener("pointerup", up); canvas.addEventListener("pointercancel", up);
  const panBy = (dx, dy) => { const b = basis(), k = cam.dist * TANH * 2 / view.h; for (let i = 0; i < 3; i++) cam.target[i] += (-dx * b.right[i] + dy * b.up[i]) * k; };
  canvas.addEventListener("pointermove", (e) => {
    const p = ptr.get(e.pointerId); if (!p) return; const dx = e.clientX - p.x, dy = e.clientY - p.y;
    if (ptr.size === 1) { if (p.pan) panBy(dx, dy); else { cam.yaw -= dx * 0.008; cam.pitch = Math.max(-1.5, Math.min(1.5, cam.pitch + dy * 0.008)); } }
    else if (ptr.size === 2) { const o = [...ptr.entries()].find(([id]) => id !== e.pointerId)[1]; const d = Math.hypot(e.clientX - o.x, e.clientY - o.y); if (lastPinch) cam.dist = Math.min(80, Math.max(4, cam.dist * lastPinch / d)); lastPinch = d; panBy(dx / 2, dy / 2); }
    p.x = e.clientX; p.y = e.clientY; bump(true);
  });
  canvas.addEventListener("wheel", (e) => { e.preventDefault(); cam.dist = Math.min(80, Math.max(4, cam.dist * Math.exp(e.deltaY * 0.0012))); bump(true); }, { passive: false });
  canvas.addEventListener("keydown", (e) => {
    const s = e.shiftKey, st = 0.06; let h = true, mv = true;
    if (e.key === "ArrowLeft") s ? panBy(-30, 0) : (cam.yaw += st); else if (e.key === "ArrowRight") s ? panBy(30, 0) : (cam.yaw -= st);
    else if (e.key === "ArrowUp") s ? panBy(0, 30) : (cam.pitch = Math.min(1.5, cam.pitch + st)); else if (e.key === "ArrowDown") s ? panBy(0, -30) : (cam.pitch = Math.max(-1.5, cam.pitch - st));
    else if (e.key === "+" || e.key === "=") cam.dist = Math.max(4, cam.dist * 0.9); else if (e.key === "-" || e.key === "_") cam.dist = Math.min(80, cam.dist / 0.9);
    else if (e.key === "r" || e.key === "R") { resetView(false); mv = false; } else if (e.key === "f" || e.key === "F") { resetView(true); mv = false; } else h = false;
    if (h) { e.preventDefault(); if (mv) bump(true); }
  });
  new ResizeObserver(() => { const r = canvas.getBoundingClientRect(); view = { w: Math.max(2, r.width), h: Math.max(2, r.height) }; S.dirty = true; }).observe(canvas);
  document.addEventListener("visibilitychange", () => { lastT = 0; });
}

// ---------------- boot ----------------
(async function init() {
  try {
    if (!gl) throw new Error("WebGL2 is not available in this browser.");
    P.mesh = program(MESH_VS, MESH_FS); P.sol = program(SOL_VS, SOL_FS); SPH = sphereMesh(); CYL = cylMesh();
    const r = await fetch("../data/manifest.json"); if (!r.ok) throw new Error("manifest.json: HTTP " + r.status);
    S.man = await r.json(); const ds = S.man.datasets.filter((d) => d.source_kind === "casci").sort((a, b) => a.geometry.r2_angstrom - b.geometry.r2_angstrom);
    if (ds.length !== 3) throw new Error("expected three CASCI datasets, found " + ds.length);
    $("progress").hidden = false; const bar = $("bar").firstChild, t0 = performance.now(); let step = 0; const tot = 3 * (1 + BASE_LEVELS.length), adv = () => { bar.style.width = (++step / tot * 100) + "%"; };
    window.__viewer = { S, cam, basis, glideTo };
    for (const d of ds) {
      const resp = await fetch("../data/" + d.file); if (!resp.ok) throw new Error(`${d.file}: HTTP ${resp.status}`);
      const buf = await resp.arrayBuffer(), [nx, ny, nz] = d.shape_xyz; if (buf.byteLength !== nx*ny*nz*2) throw new Error(`${d.file}: unexpected size`);
      const set = { ds: d, r2: d.geometry.r2_angstrom, sv: await subVolume(new Uint16Array(buf), d.shape_xyz, d.origin_bohr, d.spacing_bohr) }; S.sets.push(set); adv(); await tick();
      await buildMeshes(set, adv);
    }
    window.__perf.meshMs = performance.now() - t0;
    const a = ds[1].geometry.atoms; S.h1 = a[1].xyz_bohr; const p2 = a[2].xyz_bohr, l2 = Math.hypot(...p2); S.dir2 = p2.map((v) => v / l2);
    window.__defDist = () => defDist(); S.center = [0, 1, 2].map((k) => (a[0].xyz_bohr[k] + a[1].xyz_bohr[k] + a[2].xyz_bohr[k]) / 3); cam.target = S.center.slice();
    interaction(); view = (() => { const r = canvas.getBoundingClientRect(); return { w: Math.max(2, r.width), h: Math.max(2, r.height) }; })(); controls(); headline(); S.nearest = -1; if (STILL) cam.dist = defDist(); S.ready = true; updateReadout(); $("progress").hidden = true;
    if (!STILL) { Object.assign(cam, { yaw: -0.7, pitch: 1.0, dist: defDist() * 2.6 }); flyTo({ yaw: DEF.yaw, pitch: DEF.pitch, dist: defDist(), target: S.center }, 2600, easeOut); }
    S.dirty = true; requestAnimationFrame(frame);
  } catch (e) { fail(String(e)); }
})();
