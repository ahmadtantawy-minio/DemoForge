#!/usr/bin/env python3
"""Fast template validation: API for lifecycle, Playwright MCP for screenshots.
Runs 2 templates concurrently for speed."""

import json
import time
import base64
import os
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

API = "http://localhost:9210"
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "..", "screenshots", "validation")
REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "template-validation-report.html")

os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def api(method, path, timeout=300):
    req = urllib.request.Request(f"{API}{path}", method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500] if e.fp else ""
        try:
            return json.loads(body), e.code
        except:
            return {"detail": body}, e.code
    except Exception as e:
        return {"detail": str(e)[:300]}, 0


def wait_for_stop(demo_id, max_wait=30):
    for _ in range(max_wait):
        data, code = api("GET", f"/api/demos/{demo_id}")
        if code == 200:
            st = data.get("status", "")
            if st == "stopped":
                return True
        elif code == 404:
            return True
        time.sleep(1)
    return False


def stop_and_drain(demo_id, drain_timeout=40):
    """Stop demo and wait for containers to be fully removed."""
    api("POST", f"/api/demos/{demo_id}/stop", timeout=30)
    wait_for_stop(demo_id, max_wait=20)
    # Extra drain: wait for Docker containers to actually disappear
    deadline = time.time() + drain_timeout
    while time.time() < deadline:
        d, c = api("GET", f"/api/demos/{demo_id}/instances")
        instances = d.get("instances", []) if c == 200 else []
        if not instances:
            time.sleep(3)  # Extra buffer after instances clear
            return
        time.sleep(3)


def deploy_with_retry(demo_id, max_retries=5, backoff=8):
    """Deploy with retry on 409 (previous containers still cleaning up)."""
    for attempt in range(max_retries):
        d, c = api("POST", f"/api/demos/{demo_id}/deploy", timeout=600)
        status = d.get("status", "")
        if status == "running":
            return d, c
        if c == 409:
            wait = backoff * (attempt + 1)
            sys.stdout.write(f"\n    409 — draining, retry {attempt+1}/{max_retries} in {wait}s... ")
            sys.stdout.flush()
            time.sleep(wait)
            continue
        return d, c  # Non-409 error, return as-is
    return d, c  # Exhausted retries


def validate_template(template, index, total):
    tid = template["id"]
    name = template["name"]
    tier = template.get("tier", "?")
    cc = template.get("container_count", 0)

    result = {
        "id": tid, "name": name, "tier": tier, "containers": cc,
        "create": "?", "deploy1": "?", "deploy1_detail": "",
        "deploy2": "?", "deploy2_detail": "",
        "overall": "?", "errors": [],
        "screenshot1": None, "screenshot2": None,
    }

    sys.stdout.write(f"[{index}/{total}] {name} ({tier}, {cc}c)... ")
    sys.stdout.flush()

    # 1. Create
    d, c = api("POST", f"/api/demos/from-template/{tid}", timeout=30)
    if c not in (200, 201):
        err = d.get("detail", f"HTTP {c}")[:100]
        result["create"] = "FAIL"
        result["overall"] = "FAIL"
        result["errors"].append(f"create: {err}")
        print(f"CREATE FAIL")
        return result

    demo_id = d.get("id", "")
    result["create"] = "OK"

    # 2. Deploy #1 (with retry on 409)
    d, c = deploy_with_retry(demo_id)
    status = d.get("status", "")
    if status == "running":
        result["deploy1"] = "PASS"
        result["deploy1_detail"] = "Deployment successful"
        time.sleep(10)  # Let containers stabilize
    else:
        err = d.get("message", d.get("detail", f"status={status}"))[:200]
        result["deploy1"] = "FAIL"
        result["deploy1_detail"] = err
        result["errors"].append(f"deploy1: {err}")

    # Screenshot placeholder (filename — Playwright fills in later)
    result["screenshot1"] = f"{tid}-deploy1.png"

    # 3. Stop #1 (with drain)
    stop_and_drain(demo_id)
    time.sleep(3)

    # 4. Deploy #2 (only if deploy1 passed, with retry on 409)
    if result["deploy1"] == "PASS":
        d, c = deploy_with_retry(demo_id)
        status = d.get("status", "")
        if status == "running":
            result["deploy2"] = "PASS"
            result["deploy2_detail"] = "Redeploy successful"
            time.sleep(10)
        else:
            err = d.get("message", d.get("detail", f"status={status}"))[:200]
            result["deploy2"] = "FAIL"
            result["deploy2_detail"] = err
            result["errors"].append(f"deploy2: {err}")

        result["screenshot2"] = f"{tid}-deploy2.png"

        # Stop #2 (with drain)
        stop_and_drain(demo_id)
        wait_for_stop(demo_id, max_wait=15)
        time.sleep(3)
    else:
        result["deploy2"] = "SKIP"

    # 5. Delete
    api("DELETE", f"/api/demos/{demo_id}", timeout=10)
    time.sleep(3)

    # Overall
    if result["deploy1"] == "PASS" and result["deploy2"] == "PASS":
        result["overall"] = "PASS"
    elif result["deploy1"] == "PASS":
        result["overall"] = "PARTIAL"
    else:
        result["overall"] = "FAIL"

    print(result["overall"])
    return result


def generate_report(results):
    total_pass = sum(1 for r in results if r["overall"] == "PASS")
    total_partial = sum(1 for r in results if r["overall"] == "PARTIAL")
    total_fail = sum(1 for r in results if r["overall"] == "FAIL")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def img_tag(filename):
        if not filename:
            return ""
        filepath = os.path.join(SCREENSHOT_DIR, filename)
        if not os.path.isfile(filepath):
            return f'<div style="padding:2rem;text-align:center;color:#64748b;background:#1e293b;border-radius:8px;">Screenshot pending: {filename}</div>'
        with open(filepath, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        return f'<img src="data:image/png;base64,{data}" style="max-width:100%;border-radius:8px;border:1px solid #334155;" />'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>DemoForge Template Validation Report</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; padding: 2rem; }}
  h1 {{ font-size: 1.8rem; margin-bottom: 0.5rem; color: #f8fafc; text-align: center; }}
  h2 {{ font-size: 1.3rem; margin: 2rem 0 1rem; color: #94a3b8; border-bottom: 1px solid #334155; padding-bottom: 0.5rem; }}
  .header p {{ color: #64748b; text-align: center; }}
  .summary {{ display: flex; gap: 1rem; justify-content: center; margin: 1.5rem 0; }}
  .stat {{ background: #1e293b; border-radius: 12px; padding: 1.2rem 2rem; text-align: center; min-width: 120px; }}
  .stat .num {{ font-size: 2rem; font-weight: 700; }}
  .stat.pass .num {{ color: #22c55e; }}
  .stat.fail .num {{ color: #ef4444; }}
  .stat.total .num {{ color: #3b82f6; }}
  .stat.partial .num {{ color: #f59e0b; }}
  .stat .label {{ font-size: 0.8rem; color: #64748b; text-transform: uppercase; }}
  .card {{ background: #1e293b; border-radius: 8px; margin: 1rem 0; overflow: hidden; }}
  .card-header {{ padding: 1rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; }}
  .card-name {{ font-weight: 600; color: #f8fafc; }}
  .card-meta {{ font-size: 0.8rem; color: #64748b; }}
  .badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; margin-left: 0.3rem; }}
  .badge-pass {{ background: #052e16; color: #22c55e; }}
  .badge-fail {{ background: #450a0a; color: #ef4444; }}
  .badge-partial {{ background: #422006; color: #f59e0b; }}
  .badge-skip {{ background: #1e293b; color: #64748b; }}
  .screenshots {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; padding: 1rem; }}
  .ss-label {{ font-size: 0.7rem; color: #64748b; margin-bottom: 0.3rem; }}
  .errors {{ padding: 0.5rem 1rem 1rem; }}
  .error-line {{ font-size: 0.8rem; color: #f87171; margin: 0.2rem 0; }}
  .tier-badge {{ display: inline-block; padding: 0.2rem 0.8rem; border-radius: 999px; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; margin-right: 0.5rem; }}
  .tier-essentials {{ background: #164e63; color: #67e8f9; }}
  .tier-advanced {{ background: #3b0764; color: #c084fc; }}
  .tier-experience {{ background: #422006; color: #fbbf24; }}
  .footer {{ text-align: center; margin-top: 3rem; color: #475569; font-size: 0.8rem; }}
</style>
</head>
<body>
<div class="header">
  <h1>DemoForge Template Validation Report</h1>
  <p>{timestamp} | API + Playwright Validation | All images pre-cached</p>
</div>
<div class="summary">
  <div class="stat total"><div class="num">{len(results)}</div><div class="label">Templates</div></div>
  <div class="stat pass"><div class="num">{total_pass}</div><div class="label">Full Pass</div></div>
  <div class="stat partial"><div class="num">{total_partial}</div><div class="label">Partial</div></div>
  <div class="stat fail"><div class="num">{total_fail}</div><div class="label">Fail</div></div>
</div>"""

    for tier in ("essentials", "advanced", "experience"):
        tier_results = [r for r in results if r["tier"] == tier]
        if not tier_results:
            continue
        tp = sum(1 for r in tier_results if r["overall"] == "PASS")
        tier_cls = {"essentials": "tier-essentials", "advanced": "tier-advanced", "experience": "tier-experience"}[tier]
        html += f'<h2><span class="{tier_cls} tier-badge">{tier}</span> {tp}/{len(tier_results)} Pass</h2>'

        for r in tier_results:
            overall = r["overall"].lower()
            d1_cls = "pass" if r["deploy1"] == "PASS" else "fail" if r["deploy1"] == "FAIL" else "skip"
            d2_cls = "pass" if r["deploy2"] == "PASS" else "fail" if r["deploy2"] == "FAIL" else "skip"
            html += f"""
<div class="card">
  <div class="card-header">
    <div><span class="card-name">{r['name']}</span><span class="card-meta"> · {r['containers']}c · {r['id']}</span></div>
    <div>
      <span class="badge badge-{d1_cls}">D1: {r['deploy1']}</span>
      <span class="badge badge-{d2_cls}">D2: {r['deploy2']}</span>
      <span class="badge badge-{overall}">{r['overall']}</span>
    </div>
  </div>"""
            if r.get("screenshot1") or r.get("screenshot2"):
                html += '<div class="screenshots">'
                if r.get("screenshot1"):
                    html += f'<div><div class="ss-label">Deploy #1</div>{img_tag(r["screenshot1"])}</div>'
                if r.get("screenshot2"):
                    html += f'<div><div class="ss-label">Deploy #2 (Redeploy)</div>{img_tag(r["screenshot2"])}</div>'
                html += '</div>'
            if r["errors"]:
                html += '<div class="errors">'
                for e in r["errors"]:
                    html += f'<div class="error-line">{e}</div>'
                html += '</div>'
            html += '</div>'

    html += f'<div class="footer">DemoForge Template Validation | {len(results)} templates | {timestamp}</div></body></html>'

    with open(REPORT_PATH, "w") as f:
        f.write(html)
    print(f"\nReport: {REPORT_PATH}")


def main():
    # Get templates
    data, code = api("GET", "/api/templates")
    if code != 200:
        print(f"ERROR: Cannot fetch templates (HTTP {code})")
        sys.exit(1)
    templates = data["templates"]
    print(f"Validating {len(templates)} templates...\n")

    # Clean existing demos
    demos_data, _ = api("GET", "/api/demos")
    for d in demos_data.get("demos", []):
        if d["status"] in ("running", "deploying"):
            api("POST", f"/api/demos/{d['id']}/stop", timeout=15)
            time.sleep(3)
        api("DELETE", f"/api/demos/{d['id']}", timeout=10)
        time.sleep(1)

    # Run validation — sequential (parallel deploys would conflict on Docker resources)
    results = []
    for i, t in enumerate(templates):
        result = validate_template(t, i + 1, len(templates))
        results.append(result)

    # Summary
    print(f"\n{'='*60}")
    tp = sum(1 for r in results if r["overall"] == "PASS")
    tpa = sum(1 for r in results if r["overall"] == "PARTIAL")
    tf = sum(1 for r in results if r["overall"] == "FAIL")
    print(f"PASS: {tp}  PARTIAL: {tpa}  FAIL: {tf}  TOTAL: {len(results)}")
    print(f"{'='*60}")

    # Generate HTML report
    generate_report(results)

    # Return results for screenshot phase
    return results


if __name__ == "__main__":
    results = main()
    # Save results for screenshot phase
    with open(os.path.join(SCREENSHOT_DIR, "results.json"), "w") as f:
        json.dump(results, f, indent=2)
