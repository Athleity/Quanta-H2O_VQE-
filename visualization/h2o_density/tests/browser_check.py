#!/usr/bin/env python3
"""Headless-Chromium checks.  pip install playwright && playwright install chromium.
Serves visualization/h2o_density, exercises every control, measures load/mesh time and frame rate, saves screenshots to tests/out/."""
import hashlib, http.server, json, sys, threading, functools
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[1]; OUT = Path(__file__).parent/"out"; OUT.mkdir(exist_ok=True)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT)))
srv.RequestHandlerClass.log_message = lambda *a: None
threading.Thread(target=srv.serve_forever, daemon=True).start(); BASE = f"http://127.0.0.1:{srv.server_port}/web/index.html"
res = []
def check(name, ok, extra=""): res.append(bool(ok)); print(("PASS " if ok else "FAIL ") + name, extra)
def sig(p): return hashlib.md5(p.evaluate("document.getElementById('gl').toDataURL()").encode()).hexdigest()
def settle(p, ms=450): p.wait_for_timeout(ms)
def R(p): return p.evaluate("window.__viewer.S.r")
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    logs = []; ctx = b.new_context(viewport={"width": 1100, "height": 700}); pg = ctx.new_page()
    pg.on("console", lambda m: logs.append(m.text) if m.type in ("error", "warning") and "ERR_NAME_NOT_RESOLVED" not in m.text and "fonts.g" not in m.text else None); pg.on("pageerror", lambda e: logs.append(str(e)))
    pg.goto(BASE + "?still"); pg.wait_for_function("window.__viewer && window.__viewer.S.ready", timeout=120000); settle(pg)
    perf = pg.evaluate("window.__perf"); check("meshing finishes quickly (non-blocking, yields per shell)", perf["meshMs"] < 6000, f"{perf['meshMs']:.0f} ms for 15 isosurfaces")
    man = json.loads((ROOT/"data/manifest.json").read_text())
    check("manifest: 3 CASCI datasets, files match shape", len(man["datasets"]) == 3 and all((ROOT/"data"/d["file"]).stat().st_size == 2*d["shape_xyz"][0]*d["shape_xyz"][1]*d["shape_xyz"][2] for d in man["datasets"]))
    check("normalization Tr(PS)=10 and fine-grid ~10", all(abs(d["checks"]["trace_PS"]-10) < 1e-8 and abs(d["checks"]["audit_grid_sum_h0p06"]-10) < 2e-3 for d in man["datasets"]))
    hl = pg.inner_text("#headline"); check("headline: asymmetric stretch, e/bohr³, not a probability density", all(s in hl for s in ["Asymmetric", "e/bohr³", "not a probability density"]))
    check("VQE option disabled with reason", pg.locator("input[value=vqe]").is_disabled() and "PUCCSD" in pg.inner_text("#sources"))
    check("no JS errors after load", not pg.evaluate("window.__errors.length"), str(pg.evaluate("window.__errors")))
    sigs = set()
    for i, t in enumerate([1.8, 2.2, 2.6]):
        pg.locator("#geoms button").nth(i).click(); pg.wait_for_function(f"Math.abs(window.__viewer.S.r-{t})<1e-3", timeout=20000); settle(pg, 300); sigs.add(sig(pg))
        check(f"geometry {t:.2f} Å: readout + 'computed' tag", pg.inner_text("#r2val") == f"{t:.2f}" and "computed" in pg.inner_text("#rtag").lower() and "interpolated" not in pg.inner_text("#rtag").lower()); pg.screenshot(path=str(OUT/f"desktop_{t:.2f}.png"))
    check("three geometries render differently", len(sigs) == 3)
    pg.locator("#scrub").evaluate("e=>{e.value=2.0;e.dispatchEvent(new Event('input'))}"); settle(pg); check("scrubber sets interpolated bond length + tag", abs(R(pg)-2.0) < 1e-3 and "interpolated" in pg.inner_text("#rtag").lower(), pg.inner_text("#rtag"))
    pg.locator("#geoms button").nth(1).click(); pg.wait_for_function("Math.abs(window.__viewer.S.r-2.2)<1e-3"); settle(pg); base = sig(pg)
    box = pg.locator("#gl").bounding_box(); cx, cy = box["x"]+box["width"]/2, box["y"]+box["height"]/2
    pg.mouse.move(cx, cy); pg.mouse.down(); pg.mouse.move(cx+120, cy+40, steps=6); pg.mouse.up(); settle(pg); c = pg.evaluate("({...window.__viewer.cam})"); check("rotate by drag", sig(pg) != base and abs(c["yaw"]-0.65) > 0.5, f"yaw={c['yaw']:.2f}")
    d0 = pg.evaluate("window.__viewer.cam.dist"); pg.mouse.wheel(0, -400); settle(pg); check("zoom by wheel", pg.evaluate("window.__viewer.cam.dist") < d0)
    t0 = pg.evaluate("window.__viewer.cam.target.slice()"); pg.keyboard.down("Shift"); pg.mouse.move(cx, cy); pg.mouse.down(); pg.mouse.move(cx+80, cy-50, steps=5); pg.mouse.up(); pg.keyboard.up("Shift"); settle(pg)
    check("pan by shift-drag", max(abs(a-b) for a, b in zip(t0, pg.evaluate("window.__viewer.cam.target"))) > 0.3)
    pg.screenshot(path=str(OUT/"desktop_interacted.png"))
    pg.click("#btn-controls"); pg.wait_for_timeout(700); pg.click("#reset"); pg.wait_for_timeout(2500); c = pg.evaluate("({...window.__viewer.cam, dd: window.__defDist()})")
    check("reset restores view", abs(c["yaw"]-0.65) < 1e-3 and abs(c["pitch"]-0.45) < 1e-3 and abs(c["dist"]-c["dd"]) < 1e-3)
    pre = sig(pg); pg.locator("#sop").evaluate("e=>{e.value=2.2;e.dispatchEvent(new Event('input'))}"); settle(pg); check("glow slider changes render", sig(pg) != pre)
    pre = sig(pg); pg.locator("#asz").evaluate("e=>{e.value=1.5;e.dispatchEvent(new Event('input'))}"); settle(pg); check("atom size slider changes render", sig(pg) != pre)
    n0 = pg.evaluate("window.__perf.remeshes"); pre = sig(pg); pg.locator("#lev").evaluate("e=>{e.value=0.4;e.dispatchEvent(new Event('input'));e.dispatchEvent(new Event('change'))}"); pg.wait_for_function(f"window.__perf.remeshes>{n0}", timeout=60000); settle(pg)
    check("shell level slider re-meshes and updates legend", sig(pg) != pre and "0.010" in pg.inner_text("#shells"), f"{pg.evaluate('window.__perf.lastRemeshMs'):.0f} ms")
    pg.screenshot(path=str(OUT/"desktop_controls.png")); pg.click("#btn-data"); pg.wait_for_timeout(700); check("data drawer lists checks + interpolation note", "Tr(PS)" in pg.inner_text("#info") and "NOT computed" in pg.inner_text("#info")); pg.keyboard.press("Escape")
    pg.locator("#btn-play").click(); r0 = R(pg); pg.wait_for_timeout(1500); r1 = R(pg); f0 = pg.evaluate("window.__frames"); pg.wait_for_timeout(3000); f1 = pg.evaluate("window.__frames")
    check("play stretch animates bond length", abs(r1-r0) > 0.02 and pg.evaluate("window.__viewer.S.playing"), f"{r0:.3f}->{r1:.3f}"); print(f"INFO software-GL frame rate with animation: {(f1-f0)/3:.1f} fps (CPU rasterizer; real GPUs are far faster)")
    m = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, has_touch=True, is_mobile=True).new_page(); m.on("pageerror", lambda e: logs.append(str(e)))
    m.goto(BASE + "?still"); m.wait_for_function("window.__viewer && window.__viewer.S.ready", timeout=120000); settle(m, 700); m.screenshot(path=str(OUT/"mobile_top.png"))
    ov = m.evaluate("document.documentElement.scrollWidth - window.innerWidth"); tb = m.locator("#transport").bounding_box()
    check("mobile: no overflow, transport fully on screen", ov <= 0 and tb["y"] > 300 and tb["y"]+tb["height"] <= 845, f"transport y={tb['y']:.0f} h={tb['height']:.0f}")
    m.click("#btn-controls"); m.wait_for_timeout(800); check("mobile: controls sheet reachable", m.locator("#reset").is_visible()); m.screenshot(path=str(OUT/"mobile_controls.png"))
    check("no console/page errors", not logs, "; ".join(logs)[:300]); b.close()
print(f"\n{sum(res)}/{len(res)} checks passed"); sys.exit(0 if all(res) else 1)
