#!/usr/bin/env python3
"""Deploy each passing template, screenshot via headless Playwright, generate HTML report."""

import json, time, os, sys, base64, urllib.request, urllib.error
from datetime import datetime

API = "http://localhost:9210"
APP = "http://localhost:3000"
SS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "screenshots", "validation")
RESULTS = os.path.join(SS_DIR, "results.json")
REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "template-validation-report.html")
os.makedirs(SS_DIR, exist_ok=True)

def api(method, path, timeout=300):
    req = urllib.request.Request(f"{API}{path}", method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300] if e.fp else ""
        try: return json.loads(body), e.code
        except: return {"detail": body}, e.code
    except: return {}, 0

def screenshot(url, filepath):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(url, wait_until="networkidle", timeout=30000)
        pg.wait_for_timeout(5000)
        pg.screenshot(path=filepath)
        b.close()

def main():
    with open(RESULTS) as f:
        results = json.load(f)

    passing = [r for r in results if r["overall"] == "PASS"]
    print(f"Screenshotting {len(passing)} templates...\n")

    for i, r in enumerate(passing):
        tid = r["id"]
        print(f"[{i+1}/{len(passing)}] {r['name']}...", end=" ", flush=True)

        d, c = api("POST", f"/api/demos/from-template/{tid}", timeout=30)
        if c not in (200, 201):
            print("CREATE FAIL"); continue
        did = d.get("id", "")

        d, c = api("POST", f"/api/demos/{did}/deploy", timeout=300)
        if d.get("status") != "running":
            print("DEPLOY FAIL")
            api("POST", f"/api/demos/{did}/stop", timeout=15); time.sleep(3)
            api("DELETE", f"/api/demos/{did}", timeout=10); time.sleep(2); continue

        time.sleep(12)
        ss = os.path.join(SS_DIR, f"{tid}-deploy1.png")
        try:
            screenshot(f"{APP}/demo/{did}", ss)
            r["screenshot1"] = f"{tid}-deploy1.png"
            print("OK")
        except Exception as e:
            print(f"SS FAIL: {e}")

        api("POST", f"/api/demos/{did}/stop", timeout=30); time.sleep(5)
        api("DELETE", f"/api/demos/{did}", timeout=10); time.sleep(3)

    with open(RESULTS, "w") as f:
        json.dump(results, f, indent=2)

    # Generate report
    gen_report(results)

def gen_report(results):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    tp = sum(1 for r in results if r["overall"] == "PASS")
    tpa = sum(1 for r in results if r["overall"] == "PARTIAL")
    tf = sum(1 for r in results if r["overall"] == "FAIL")

    def img(fn):
        if not fn: return ""
        fp = os.path.join(SS_DIR, fn)
        if not os.path.isfile(fp): return f'<div style="padding:1rem;color:#64748b;background:#1e293b;border-radius:8px;text-align:center">No screenshot</div>'
        d = base64.b64encode(open(fp,"rb").read()).decode()
        return f'<img src="data:image/png;base64,{d}" style="max-width:100%;border-radius:8px;border:1px solid #334155"/>'

    h = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>DemoForge Validation</title>
<style>*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;padding:2rem}}
h1{{font-size:1.8rem;color:#f8fafc;text-align:center;margin-bottom:.5rem}}h2{{font-size:1.2rem;color:#94a3b8;border-bottom:1px solid #334155;padding-bottom:.5rem;margin:2rem 0 1rem}}
.sub{{color:#64748b;text-align:center}}.summary{{display:flex;gap:1rem;justify-content:center;margin:1.5rem 0}}
.st{{background:#1e293b;border-radius:12px;padding:1rem 2rem;text-align:center;min-width:110px}}.st .n{{font-size:2rem;font-weight:700}}.st .l{{font-size:.75rem;color:#64748b;text-transform:uppercase}}
.pass .n{{color:#22c55e}}.fail .n{{color:#ef4444}}.total .n{{color:#3b82f6}}.partial .n{{color:#f59e0b}}
.card{{background:#1e293b;border-radius:8px;margin:1rem 0;overflow:hidden}}.card-h{{padding:1rem;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #334155}}
.card-n{{font-weight:600;color:#f8fafc}}.card-m{{font-size:.8rem;color:#64748b}}.badge{{display:inline-block;padding:.15rem .5rem;border-radius:4px;font-size:.7rem;font-weight:600;margin-left:.3rem}}
.bp{{background:#052e16;color:#22c55e}}.bf{{background:#450a0a;color:#ef4444}}.bpa{{background:#422006;color:#f59e0b}}.bs{{background:#1e293b;color:#64748b}}
.ss{{padding:1rem}}.ss img{{width:100%;border-radius:8px}}.ss-l{{font-size:.7rem;color:#64748b;margin-bottom:.3rem}}
.err{{padding:.5rem 1rem 1rem}}.err-l{{font-size:.8rem;color:#f87171}}.tb{{display:inline-block;padding:.2rem .8rem;border-radius:999px;font-size:.7rem;font-weight:600;text-transform:uppercase;margin-right:.5rem}}
.te{{background:#164e63;color:#67e8f9}}.ta{{background:#3b0764;color:#c084fc}}.tx{{background:#422006;color:#fbbf24}}
.footer{{text-align:center;margin-top:3rem;color:#475569;font-size:.8rem}}</style></head><body>
<h1>DemoForge Template Validation Report</h1><p class="sub">{ts} | Playwright Screenshots | All images pre-cached</p>
<div class="summary"><div class="st total"><div class="n">{len(results)}</div><div class="l">Templates</div></div>
<div class="st pass"><div class="n">{tp}</div><div class="l">Pass</div></div>
<div class="st partial"><div class="n">{tpa}</div><div class="l">Partial</div></div>
<div class="st fail"><div class="n">{tf}</div><div class="l">Fail</div></div></div>"""

    for tier in ("essentials","advanced","experience"):
        tr = [r for r in results if r["tier"]==tier]
        if not tr: continue
        tc = {"essentials":"te","advanced":"ta","experience":"tx"}[tier]
        tp2 = sum(1 for r in tr if r["overall"]=="PASS")
        h += f'<h2><span class="tb {tc}">{tier}</span>{tp2}/{len(tr)} Pass</h2>'
        for r in tr:
            o = r["overall"].lower()
            d1c = "bp" if r["deploy1"]=="PASS" else "bf" if r["deploy1"]=="FAIL" else "bs"
            d2c = "bp" if r["deploy2"]=="PASS" else "bf" if r["deploy2"]=="FAIL" else "bs"
            oc = "bp" if o=="pass" else "bf" if o=="fail" else "bpa"
            h += f'<div class="card"><div class="card-h"><div><span class="card-n">{r["name"]}</span><span class="card-m"> · {r["containers"]}c · {r["id"]}</span></div>'
            h += f'<div><span class="badge {d1c}">D1:{r["deploy1"]}</span><span class="badge {d2c}">D2:{r["deploy2"]}</span><span class="badge {oc}">{r["overall"]}</span></div></div>'
            if r.get("screenshot1"):
                h += f'<div class="ss"><div class="ss-l">Deployed</div>{img(r["screenshot1"])}</div>'
            if r["errors"]:
                h += '<div class="err">'+''.join(f'<div class="err-l">{e}</div>' for e in r["errors"])+'</div>'
            h += '</div>'

    h += f'<div class="footer">DemoForge | {len(results)} templates | {ts}</div></body></html>'
    with open(REPORT, "w") as f: f.write(h)
    print(f"\nReport: {REPORT}")

if __name__ == "__main__":
    main()
