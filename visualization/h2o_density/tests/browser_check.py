#!/usr/bin/env python3
"""Headless-Chromium smoke test.  Needs: pip install playwright && playwright install chromium.
Serves visualization/h2o_density over HTTP, exercises every control, saves screenshots to ./tests/out/ (created on run)."""
import hashlib, http.server, json, sys, threading, functools
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[1]; OUT = Path(__file__).parent/"out"; OUT.mkdir(exist_ok=True)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT)))
srv.RequestHandlerClass.log_message = lambda *a: None
threading.Thread(target=srv.serve_forever, daemon=True).start(); URL = f"http://127.0.0.1:{srv.server_port}/web/index.html?still"
res = []
def check(name, ok, extra=""): res.append((name, bool(ok), extra)); print(("PASS " if ok else "FAIL ") + name, extra)
def sig(page): return hashlib.md5(page.evaluate("document.getElementById('gl').toDataURL()").encode()).hexdigest()
def shot(page, path):
    page.screenshot(path=path, timeout=180000)
def wait_frames(page, n=1):
    """Let the viewer settle: input handled, interaction-quality frame done, full-quality frame drawn."""
    page.wait_for_timeout(450)
    page.wait_for_function("window.__viewer && window.__viewer.S.scale===1 && !window.__viewer.S.dirty && document.getElementById('progress').hidden", timeout=180000)
    page.wait_for_timeout(250)
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={"width": 1000, "height": 640}); logs = []
    pg.on("console", lambda m: logs.append(m.text) if m.type in ("error", "warning") and "ERR_NAME_NOT_RESOLVED" not in m.text and "fonts.g" not in m.text else None); pg.on("pageerror", lambda e: logs.append(str(e)))
    pg.goto(URL); pg.wait_for_function("window.__viewer && window.__viewer.S.ds", timeout=120000); wait_frames(pg, 2)
    man = json.loads((ROOT/"data/manifest.json").read_text())
    check("manifest lists 3 geometries x CASCI", len(man["datasets"]) == 3 and all(d["source_kind"] == "casci" for d in man["datasets"]))
    for d in man["datasets"]:
        n = d["shape_xyz"]; sz = (ROOT/"data"/d["file"]).stat().st_size
        check(f"data file size {d['file']}", sz == n[0]*n[1]*n[2]*2, f"{sz} bytes")
        check(f"normalization {d['id']}", abs(d["checks"]["trace_PS"]-10) < 1e-8 and abs(d["checks"]["audit_grid_sum_h0p06"]-10) < 2e-3, f"trPS={d['checks']['trace_PS']:.8f} audit={d['checks']['audit_grid_sum_h0p06']:.5f}")
    check("WebGL2 + shader compiled, no JS errors", not pg.evaluate("window.__errors.length"), str(pg.evaluate("window.__errors")))
    hl = pg.inner_text("#headline"); check("headline states asymmetric stretch, e/bohr³, not probability", all(s in hl for s in ["Asymmetric", "e/bohr³", "not a probability density"]), hl[:90])
    check("VQE option disabled with reason", pg.locator("input[value=vqe]").is_disabled() and "PUCCSD" in pg.inner_text("#sources"))
    seen = set()
    for g in [d["geometry_id"] for d in man["datasets"]]:
        pg.locator(f"input[name=geom][value='{g}']").check(); pg.wait_for_function(f"window.__viewer.S.ds.geometry_id==='{g}'", timeout=120000); wait_frames(pg, 2)
        s = sig(pg); seen.add(s); shot(pg, str(OUT/f"desktop_{g}.png"))
        check(f"geometry {g} loads and renders", pg.inner_text("#headline").count(f"{float(g[3:]):.2f} Å") == 1 and not pg.evaluate("window.__errors.length"))
    check("three geometries render different images", len(seen) == 3)
    pg.locator("input[name=geom][value='r2-2.20']").check(); pg.wait_for_function("window.__viewer.S.ds.geometry_id==='r2-2.20'"); wait_frames(pg, 2); base = sig(pg)
    box = pg.locator("#gl").bounding_box(); cx, cy = box["x"]+box["width"]/2, box["y"]+box["height"]/2
    pg.mouse.move(cx, cy); pg.mouse.down(); pg.mouse.move(cx+120, cy+40, steps=6); pg.mouse.up(); wait_frames(pg, 2); wait_frames(pg, 1)
    c = pg.evaluate("({...window.__viewer.cam})"); check("rotate by drag", sig(pg) != base and abs(c["yaw"]-0.65) > 0.5, f"yaw={c['yaw']:.2f} pitch={c['pitch']:.2f}")
    d0 = pg.evaluate("window.__viewer.cam.dist"); pg.mouse.wheel(0, -400); wait_frames(pg, 2); d1 = pg.evaluate("window.__viewer.cam.dist"); check("zoom by wheel", d1 < d0, f"{d0:.1f}->{d1:.1f}")
    t0 = pg.evaluate("window.__viewer.cam.target.slice()"); pg.keyboard.down("Shift"); pg.mouse.move(cx, cy); pg.mouse.down(); pg.mouse.move(cx+80, cy-50, steps=5); pg.mouse.up(); pg.keyboard.up("Shift"); wait_frames(pg, 2)
    t1 = pg.evaluate("window.__viewer.cam.target"); check("pan by shift-drag", max(abs(a-b) for a, b in zip(t0, t1)) > 0.3, f"{[round(x,2) for x in t0]}->{[round(x,2) for x in t1]}")
    pg.locator("#gl").focus(); pg.keyboard.press("ArrowLeft"); pg.keyboard.press("+"); wait_frames(pg, 2); check("keyboard rotate/zoom", pg.evaluate("window.__viewer.cam.dist") < d1)
    shot(pg, str(OUT/"desktop_interacted.png"))
    pg.click("#btn-controls"); pg.click("#reset"); wait_frames(pg, 2); wait_frames(pg, 1); c = pg.evaluate("({...window.__viewer.cam})")
    check("reset restores view", abs(c["yaw"]-0.65) < 1e-6 and abs(c["dist"]-17) < 1e-6 and abs(c["pitch"]-0.45) < 1e-6)
    before = sig(pg); pg.locator("#iso").evaluate("e=>{e.value=-0.5;e.dispatchEvent(new Event('input'))}"); wait_frames(pg, 2); wait_frames(pg, 1); a = sig(pg); check("isosurface slider changes render", a != before and "0.32" in pg.inner_text("#isov"), pg.inner_text("#isov"))
    for sid, v in [("vol", 0.9), ("slc", 0.8), ("sop", 1)]:
        pre = sig(pg); pg.locator(f"#{sid}").evaluate(f"e=>{{e.value={v};e.dispatchEvent(new Event('input'))}}"); wait_frames(pg, 2); wait_frames(pg, 1); check(f"{sid} slider changes render", sig(pg) != pre)
    shot(pg, str(OUT/"desktop_display_controls.png"))
    m = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, has_touch=True, is_mobile=True).new_page(); m.on("pageerror", lambda e: logs.append(str(e)))
    m.goto(URL); m.wait_for_function("window.__viewer && window.__viewer.S.ds", timeout=120000); wait_frames(m, 2); shot(m, str(OUT/"mobile_top.png"))
    ov = m.evaluate("document.documentElement.scrollWidth - window.innerWidth"); gb = m.locator("#gl").bounding_box()
    check("mobile: no horizontal overflow, canvas fits width", ov <= 0 and gb["width"] <= 391, f"overflow={ov}, canvas={gb['width']:.0f}x{gb['height']:.0f}")
    m.evaluate("0"); shot(m, str(OUT/"mobile_controls.png"))
    m.click("#btn-controls"); m.wait_for_timeout(700); check("mobile: controls reachable", m.locator("#reset").is_visible() and m.locator("input[name=geom]").first.is_visible())
    check("no console/page errors", not logs, "; ".join(logs)[:300])
    b.close()
fails = [r for r in res if not r[1]]; print(f"\n{len(res)-len(fails)}/{len(res)} checks passed"); sys.exit(1 if fails else 0)
