"use strict";
const $ = (id) => document.getElementById(id);
const errs = (window.__errors = []);
window.addEventListener("error", (e) => errs.push(String(e.message)));
function fail(m) { errs.push(m); const e = $("error"); e.hidden = false; e.textContent = m; $("progress").hidden = true; }

const VIR = [[0.0002189403691192265,0.001651004631001012,-0.01948089843709184],[0.1065134194856116,0.5639564367884091,3.932712388889277],[11.60249308247187,-3.972853965665698,-15.9423941062914],[-41.70399613139459,17.43639888205313,44.35414519872813],[77.162935699427,-33.40235894210092,-81.80730925738979],[-71.31942824499214,32.62606426397723,73.20951985803202],[25.13112622477341,-12.24266895238567,-23.07032500287172]]; // inferno
function viridis(t) { return [0,1,2].map((k) => { let v = 0; for (let i = 6; i >= 0; i--) v = v * t + VIR[i][k]; return Math.min(1, Math.max(0, v)); }); }

const VS = `#version 300 es
void main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);gl_Position=vec4(p*2.-1.,0,1);}`;
const FS = `#version 300 es
precision highp float; precision highp sampler3D;
uniform sampler3D uTex; uniform vec3 uOrigin,uN,uEye,uRight,uUp,uFwd,uBmin,uBmax; uniform float uH,uTan,uAsp,uIso,uSop,uVol,uSlc,uSy,uLo,uHi,uStep;
uniform vec2 uRes; uniform vec3 uAP[3]; uniform float uAR[3]; uniform vec3 uAC[3];
out vec4 o;
vec3 vir(float t){t=clamp(t,0.,1.);
 vec3 c0=vec3(0.0002189,0.0016510,-0.0194809),c1=vec3(0.1065134,0.5639564,3.9327124),c2=vec3(11.6024931,-3.9728540,-15.9423941),c3=vec3(-41.7039961,17.4363989,44.3541452),c4=vec3(77.1629357,-33.4023589,-81.8073093),c5=vec3(-71.3194282,32.6260643,73.2095199),c6=vec3(25.1311262,-12.2426690,-23.0703250);
 return clamp(c0+t*(c1+t*(c2+t*(c3+t*(c4+t*(c5+t*c6))))),0.,1.);}
float lg(vec3 p){vec3 uv=((p-uOrigin)/uH+0.5)/uN;return log2(max(texture(uTex,uv).r,1e-7))*0.30103;}
void main(){
 vec2 q=(gl_FragCoord.xy/uRes)*2.-1.; vec3 rd=normalize(uFwd+uTan*(q.x*uAsp*uRight+q.y*uUp));
 vec3 bg=vec3(0.);
 vec3 inv=1./rd, t1=(uBmin-uEye)*inv, t2=(uBmax-uEye)*inv; vec3 tm=min(t1,t2),tM=max(t1,t2);
 float t0=max(max(tm.x,max(tm.y,tm.z)),0.), te=min(tM.x,min(tM.y,tM.z));
 float tA=1e9; int kA=-1;
 for(int k=0;k<3;k++){vec3 oc=uEye-uAP[k];float b=dot(oc,rd),c=dot(oc,oc)-uAR[k]*uAR[k],d=b*b-c;if(d>0.){float th=-b-sqrt(d);if(th>0.&&th<tA){tA=th;kA=k;}}}
 vec4 acc=vec4(0.); bool done=false;
 if(te>t0){
  float pl=lg(uEye+rd*t0), py=(uEye+rd*t0).y, pt=t0;
  float isoT=clamp((uIso-uLo)/(uHi-uLo),0.,1.);
  for(int i=1;i<700;i++){
   float t=t0+float(i)*uStep; if(t>te)break; vec3 p=uEye+rd*t; float l=lg(p);
   if(!done&&t>=tA){vec3 n=normalize(uEye+rd*tA-uAP[kA]);vec3 c=uAC[kA]*(0.3+0.7*max(dot(n,-rd),0.))+0.25*pow(max(dot(reflect(rd,n),-rd),0.),20.);acc+=(1.-acc.a)*vec4(c*0.96,0.96);done=true;}
   float tn=clamp((l-uLo)/(uHi-uLo),0.,1.);
   float a=1.-exp(-uVol*tn*tn*tn*uStep*7.); acc+=(1.-acc.a)*vec4(vir(tn)*a,a);
   if((pl-uIso)*(l-uIso)<0.){
    float ta=pt,tb=t; for(int k=0;k<5;k++){float tc=.5*(ta+tb);float lc=lg(uEye+rd*tc);if((lc-uIso)*(pl-uIso)<0.)tb=tc;else ta=tc;}
    vec3 ps=uEye+rd*(.5*(ta+tb)); float e=uH; 
    vec3 g=vec3(lg(ps+vec3(e,0,0))-lg(ps-vec3(e,0,0)),lg(ps+vec3(0,e,0))-lg(ps-vec3(0,e,0)),lg(ps+vec3(0,0,e))-lg(ps-vec3(0,0,e)));
    vec3 n=-normalize(g+1e-9); if(dot(n,rd)>0.)n=-n;
    float df=0.25+0.75*max(dot(n,-rd),0.); float sp=pow(max(dot(reflect(rd,n),-rd),0.),30.);
    vec3 c=vir(isoT*0.9+0.05)*df+0.35*sp; acc+=(1.-acc.a)*vec4(c*uSop,uSop);
   }
   if((py-uSy)*(p.y-uSy)<0.&&uSlc>0.){float f=(uSy-py)/(p.y-py);vec3 ps=uEye+rd*mix(pt,t,f);float ts=clamp((lg(ps)-uLo)/(uHi-uLo),0.,1.);float a2=uSlc*smoothstep(0.,.08,ts);acc+=(1.-acc.a)*vec4(vir(ts)*a2,a2);}
   pl=l;py=p.y;pt=t; if(acc.a>0.985)break;
  }
 }
 if(!done&&kA>=0&&(te<=t0||true)&&tA<1e8&&acc.a<0.985&&(te<=t0)){vec3 n=normalize(uEye+rd*tA-uAP[kA]);acc+=(1.-acc.a)*vec4(uAC[kA]*(0.3+0.7*max(dot(n,-rd),0.))*0.96,0.96);}
 o=vec4(acc.rgb+(1.-acc.a)*bg,1.);
}`;

const canvas = $("gl");
const gl = canvas.getContext("webgl2", { antialias: false, preserveDrawingBuffer: true });
const S = { man: null, ds: null, geom: null, src: "casci", cam: null, tex: null, dirty: true, scale: 1, interacting: false };
const cam = { yaw: 0.65, pitch: 0.45, dist: 30, target: [0, 0, 0] };
let prog, U = {};

function compile() {
  const sh = (t, s) => { const x = gl.createShader(t); gl.shaderSource(x, s); gl.compileShader(x); if (!gl.getShaderParameter(x, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(x)); return x; };
  prog = gl.createProgram(); gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
  const n = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS);
  for (let i = 0; i < n; i++) { const nm = gl.getActiveUniform(prog, i).name.replace("[0]", ""); U[nm] = gl.getUniformLocation(prog, nm + (gl.getActiveUniform(prog, i).size > 1 ? "[0]" : "")); }
}

const sub = (a, b) => a.map((v, i) => v - b[i]);
const dot = (a, b) => a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
const nrm = (a) => { const l = Math.hypot(...a); return a.map((v) => v / l); };
const cross = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
const TANH = Math.tan(0.5 * (40 * Math.PI / 180));
function basis() {
  const cp = Math.cos(cam.pitch);
  const eye = [cam.target[0] + cam.dist*cp*Math.sin(cam.yaw), cam.target[1] + cam.dist*Math.sin(cam.pitch), cam.target[2] + cam.dist*cp*Math.cos(cam.yaw)];
  const fwd = nrm(sub(cam.target, eye)), right = nrm(cross(fwd, [0, 1, 0])), up = cross(right, fwd);
  return { eye, fwd, right, up };
}
const ATOM = { O: { r: 0.34, c: [1.0, 0.42, 0.22] }, H: { r: 0.2, c: [0.93, 0.92, 0.9] } };

function centroid() { const a = S.ds.geometry.atoms.map((x) => x.xyz_bohr); return [0, 1, 2].map((k) => a.reduce((s, v) => s + v[k], 0) / a.length); }
function resetView(keepAngles) {
  const c = centroid(); cam.target = c; cam.dist = 17;
  if (!keepAngles) { cam.yaw = 0.65; cam.pitch = 0.45; }
  S.dirty = true;
}

function resize() {
  const r = canvas.getBoundingClientRect(), d = Math.min(window.devicePixelRatio || 1, 2) * S.scale;
  const w = Math.max(2, Math.round(r.width * d)), h = Math.max(2, Math.round(r.height * d));
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
}
function draw() {
  if (!S.ds || !S.tex) return; resize(); gl.viewport(0, 0, canvas.width, canvas.height);
  gl.useProgram(prog); const b = basis(), ds = S.ds, n = ds.shape_xyz, h = ds.spacing_bohr, o = ds.origin_bohr;
  const bmin = o.map((v) => v - 0.5*h), bmax = o.map((v, i) => v + (n[i] - 0.5)*h);
  gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_3D, S.tex); gl.uniform1i(U.uTex, 0);
  gl.uniform3fv(U.uOrigin, o); gl.uniform3fv(U.uN, n); gl.uniform3fv(U.uBmin, bmin); gl.uniform3fv(U.uBmax, bmax);
  gl.uniform3fv(U.uEye, b.eye); gl.uniform3fv(U.uRight, b.right); gl.uniform3fv(U.uUp, b.up); gl.uniform3fv(U.uFwd, b.fwd);
  gl.uniform1f(U.uH, h); gl.uniform1f(U.uTan, TANH); gl.uniform1f(U.uAsp, canvas.width / canvas.height); gl.uniform2f(U.uRes, canvas.width, canvas.height);
  gl.uniform1f(U.uIso, +$("iso").value); gl.uniform1f(U.uSop, +$("sop").value); gl.uniform1f(U.uVol, +$("vol").value);
  gl.uniform1f(U.uSlc, +$("slc").value); gl.uniform1f(U.uSy, +$("sy").value); gl.uniform1f(U.uLo, LO); gl.uniform1f(U.uHi, HI); gl.uniform1f(U.uStep, 0.07 / (S.scale < 1 ? 0.7 : 1));
  const A = ds.geometry.atoms; gl.uniform3fv(U.uAP, A.flatMap((a) => a.xyz_bohr)); gl.uniform1fv(U.uAR, A.map((a) => ATOM[a.element].r)); gl.uniform3fv(U.uAC, A.flatMap((a) => ATOM[a.element].c));
  gl.drawArrays(gl.TRIANGLES, 0, 3); labels(b);
}
let LO = -4, HI = 2;
function labels(b) {
  const box = canvas.getBoundingClientRect(), L = $("labels"), A = S.ds.geometry.atoms, g = S.ds.geometry;
  const names = ["O", `H₁ ${g.r1_angstrom.toFixed(2)} Å`, `H₂ ${g.r2_angstrom.toFixed(2)} Å`];
  if (L.children.length !== 3) { L.innerHTML = "<span></span><span></span><span></span>"; }
  A.forEach((a, i) => {
    const d = sub(a.xyz_bohr, b.eye), z = dot(d, b.fwd), x = dot(d, b.right) / (z * TANH * (box.width / box.height)), y = dot(d, b.up) / (z * TANH);
    const s = L.children[i]; s.textContent = names[i]; s.style.left = ((x + 1) / 2 * box.width) + "px"; s.style.top = ((1 - y) / 2 * box.height) + "px"; s.style.display = z > 0 ? "" : "none";
  });
}
function loop() { if (S.dirty) { S.dirty = false; try { draw(); } catch (e) { fail(String(e)); } window.__frames = (window.__frames || 0) + 1; } requestAnimationFrame(loop); }
let idleT; function bump(interactive) { S.dirty = true; if (interactive) { S.scale = 0.5; clearTimeout(idleT); idleT = setTimeout(() => { S.scale = 1; S.dirty = true; }, 180); } }

async function loadDataset(ds) {
  $("progress").hidden = false; $("ptext").textContent = "Loading density…"; $("bar").firstChild.style.width = "10%";
  const r = await fetch(ds.file); if (!r.ok) throw new Error(`${ds.file}: HTTP ${r.status}`);
  const buf = await r.arrayBuffer(); const [nx, ny, nz] = ds.shape_xyz;
  if (buf.byteLength !== nx*ny*nz*2) throw new Error(`${ds.file}: size ${buf.byteLength} != ${nx*ny*nz*2}`);
  if (S.tex) gl.deleteTexture(S.tex); S.tex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_3D, S.tex);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  gl.texImage3D(gl.TEXTURE_3D, 0, gl.R16F, nx, ny, nz, 0, gl.RED, gl.HALF_FLOAT, new Uint16Array(buf));
  for (const [p, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_3D, p, v);
  S.ds = ds; HI = Math.log10(ds.rho_range.max); $("progress").hidden = true; legend(); info(); headline(); resetView(true); S.dirty = true;
}
function select() {
  const ds = S.man.datasets.find((d) => d.geometry_id === S.geom && d.source_kind === S.src);
  if (!ds) return fail(`No dataset for ${S.geom}/${S.src}`);
  loadDataset(ds).catch((e) => fail(String(e)));
}
function headline() {
  const g = S.ds.geometry;
  $("headline").textContent = `Asymmetric O–H stretch: R₁ = ${g.r1_angstrom.toFixed(2)} Å (fixed), R₂ = ${g.r2_angstrom.toFixed(2)} Å, ∠HOH = ${g.hoh_angle_deg}° · ρ(r) in e/bohr³, integrates to 10 electrons (not a probability density) · ${S.ds.label}`;
}
function legend() {
  const c = $("legendbar"), x = c.getContext("2d");
  for (let i = 0; i < c.width; i++) { const v = viridis(i / (c.width - 1)).map((q) => Math.round(q * 255)); x.fillStyle = `rgb(${v})`; x.fillRect(i, 0, 1, c.height); }
  const f = (e) => (10 ** e).toExponential(0).replace("e+", "e").replace("e-", "e−");
  $("lt0").textContent = f(LO); $("lt1").textContent = f((LO + HI) / 2); $("lt2").textContent = (10 ** HI).toFixed(0);
}
function info() {
  const d = S.ds, k = d.checks, e = d.energies_hartree, f = (v, n = 6) => (+v).toFixed(n);
  const rows = [["Source", d.label], ["Geometry", `R₂ = ${d.geometry.r2_angstrom.toFixed(2)} Å (asymmetric stretch)`], ["Energies (Eh)", `RHF ${f(e.rhf, 8)} · CASCI ${f(e.casci, 8)}`],
    ["∫ρ checks", `Tr(PS) = ${f(k.trace_PS, 8)}; fine-grid (h=${k.audit_spacing_bohr} bohr) = ${f(k.audit_grid_sum_h0p06, 5)}; stored float16 grid sum = ${f(k.grid_sum_stored_float16, 4)}`],
    ["Active natural occ.", k.natural_occupations.map((v) => v.toFixed(3)).join(", ")], ["ρ range (e/bohr³)", `${d.rho_range.max.toExponential(2)} max`],
    ["Grid", `${d.shape_xyz.join("×")} @ ${d.spacing_bohr} bohr, float16`]];
  if (k.vs_saved_repo_reference) rows.push(["Vs repo reference", `ΔRHF ${k.vs_saved_repo_reference.rhf_diff.toExponential(1)}, ΔCASCI ${k.vs_saved_repo_reference.casci_diff.toExponential(1)} Eh; max Δ occ ${k.vs_saved_repo_reference.max_natural_occ_diff.toExponential(1)}`]);
  if (d.phase_ambiguity) rows.push(["Orbital-sign ambiguity", `max |Δρ| = ${d.phase_ambiguity.max_abs_rho.toExponential(1)}`]);
  rows.push(["Note", d.notes]);
  $("info").innerHTML = rows.map(([a, b]) => `<dt>${a}</dt><dd>${b}</dd>`).join("");
  $("srcnote").textContent = S.src === "casci" ? "Exact diagonalization of the same CAS(8e,6o) Hamiltonian; the reference for comparing a VQE state." : "";
}
function controls() {
  const gs = [...new Set(S.man.datasets.map((d) => d.geometry_id))];
  $("geoms").innerHTML = gs.map((g, i) => { const d = S.man.datasets.find((x) => x.geometry_id === g); return `<label><input type="radio" name="geom" value="${g}" ${i === 1 ? "checked" : ""}>${d.geometry.r2_angstrom.toFixed(2)} Å</label>`; }).join("");
  S.geom = gs[1] || gs[0];
  const hasV = S.man.datasets.some((d) => d.source_kind === "vqe");
  $("sources").innerHTML = `<label><input type="radio" name="src" value="casci" checked> CASCI reference · exact</label>
   <label class="${hasV ? "" : "dis"}"><input type="radio" name="src" value="vqe" ${hasV ? "" : "disabled"}> VQE-derived · saved PUCCSD state${hasV ? "" : " — not generated"}</label>` + (hasV ? "" : `<p class="note">${S.man.vqe.reason}</p>`);
  document.querySelectorAll("input[name=geom]").forEach((e) => e.addEventListener("change", () => { S.geom = e.value; select(); }));
  document.querySelectorAll("input[name=src]").forEach((e) => e.addEventListener("change", () => { S.src = e.value; select(); }));
  const upd = () => { $("isov").textContent = (10 ** +$("iso").value).toPrecision(2); bump(false); };
  ["iso", "sop", "vol", "slc", "sy"].forEach((id) => $(id).addEventListener("input", upd)); upd();
  $("reset").onclick = () => { resetView(false); $("iso").value = -1.3; $("sop").value = 0.55; $("vol").value = 0.35; $("slc").value = 0; $("sy").value = 0; upd(); };
  $("fit").onclick = () => resetView(true);
}
function interaction() {
  const ptr = new Map(); let lastPinch = 0;
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  canvas.addEventListener("pointerdown", (e) => { canvas.setPointerCapture(e.pointerId); ptr.set(e.pointerId, { x: e.clientX, y: e.clientY, pan: e.shiftKey || e.button === 2 }); lastPinch = 0; canvas.focus(); });
  const up = (e) => { ptr.delete(e.pointerId); lastPinch = 0; }; canvas.addEventListener("pointerup", up); canvas.addEventListener("pointercancel", up);
  const panBy = (dx, dy) => { const b = basis(), k = cam.dist * TANH * 2 / canvas.getBoundingClientRect().height; for (let i = 0; i < 3; i++) cam.target[i] += (-dx * b.right[i] + dy * b.up[i]) * k; };
  canvas.addEventListener("pointermove", (e) => {
    const p = ptr.get(e.pointerId); if (!p) return; const dx = e.clientX - p.x, dy = e.clientY - p.y;
    if (ptr.size === 1) { if (p.pan) panBy(dx, dy); else { cam.yaw -= dx * 0.008; cam.pitch = Math.max(-1.5, Math.min(1.5, cam.pitch + dy * 0.008)); } }
    else if (ptr.size === 2) { const o = [...ptr.entries()].find(([id]) => id !== e.pointerId)[1]; const d = Math.hypot(e.clientX - o.x, e.clientY - o.y); if (lastPinch) cam.dist = Math.min(80, Math.max(4, cam.dist * lastPinch / d)); lastPinch = d; panBy(dx / 2, dy / 2); }
    p.x = e.clientX; p.y = e.clientY; bump(true);
  });
  canvas.addEventListener("wheel", (e) => { e.preventDefault(); cam.dist = Math.min(80, Math.max(4, cam.dist * Math.exp(e.deltaY * 0.0012))); bump(true); }, { passive: false });
  canvas.addEventListener("keydown", (e) => {
    const s = e.shiftKey, st = 0.06; let h = true;
    if (e.key === "ArrowLeft") s ? panBy(-30, 0) : (cam.yaw += st); else if (e.key === "ArrowRight") s ? panBy(30, 0) : (cam.yaw -= st);
    else if (e.key === "ArrowUp") s ? panBy(0, 30) : (cam.pitch = Math.min(1.5, cam.pitch + st)); else if (e.key === "ArrowDown") s ? panBy(0, -30) : (cam.pitch = Math.max(-1.5, cam.pitch - st));
    else if (e.key === "+" || e.key === "=") cam.dist = Math.max(4, cam.dist * 0.9); else if (e.key === "-" || e.key === "_") cam.dist = Math.min(80, cam.dist / 0.9);
    else if (e.key === "r" || e.key === "R") resetView(false); else if (e.key === "f" || e.key === "F") resetView(true); else h = false;
    if (h) { e.preventDefault(); bump(true); }
  });
  window.addEventListener("resize", () => { S.dirty = true; });
}
(async function init() {
  try {
    if (!gl) throw new Error("WebGL2 is not available in this browser.");
    compile(); const r = await fetch("../data/manifest.json"); if (!r.ok) throw new Error("manifest.json: HTTP " + r.status);
    S.man = await r.json(); S.man.datasets.forEach((d) => (d.file = "../data/" + d.file));
    controls(); interaction(); select(); requestAnimationFrame(loop);
    window.__viewer = { S, cam, select, basis };
  } catch (e) { fail(String(e)); }
})();
