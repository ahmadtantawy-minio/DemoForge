import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const SCREENSHOT_DIR = path.join(__dirname, '..', 'screenshots', 'validation');
const REPORT_PATH = path.join(__dirname, '..', 'template-validation-report.html');
const API = 'http://localhost:9210';
const APP = 'http://localhost:3000';

interface TemplateResult {
  id: string;
  name: string;
  tier: string;
  containers: number;
  deploy1: 'PASS' | 'FAIL' | 'SKIP';
  deploy1_detail: string;
  deploy2: 'PASS' | 'FAIL' | 'SKIP';
  deploy2_detail: string;
  screenshot1?: string;
  screenshot2?: string;
  errors: string[];
}

// Get all templates from API
async function getTemplates(): Promise<any[]> {
  const res = await fetch(`${API}/api/templates`);
  const data = await res.json();
  return data.templates;
}

// Cleanup all demos via API
async function cleanupAllDemos() {
  const res = await fetch(`${API}/api/demos`);
  const data = await res.json();
  for (const demo of data.demos) {
    if (demo.status === 'running' || demo.status === 'deploying') {
      await fetch(`${API}/api/demos/${demo.id}/stop`, { method: 'POST' });
      await new Promise(r => setTimeout(r, 5000));
    }
    await fetch(`${API}/api/demos/${demo.id}`, { method: 'DELETE' });
    await new Promise(r => setTimeout(r, 2000));
  }
}

// Wait for deploy to complete (success or failure)
async function waitForDeploy(page: Page, timeoutMs = 300000): Promise<{ success: boolean; detail: string }> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    // Check for success
    const doneBtn = page.getByRole('button', { name: 'Done' });
    if (await doneBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
      return { success: true, detail: 'Deployment successful' };
    }
    // Check for failure
    const failText = page.locator('text=Deployment failed').first();
    if (await failText.isVisible({ timeout: 1000 }).catch(() => false)) {
      const errorText = await failText.textContent() || 'Unknown error';
      return { success: false, detail: errorText };
    }
    await page.waitForTimeout(3000);
  }
  return { success: false, detail: 'Timeout waiting for deploy' };
}

test.describe.serial('Template Validation', () => {
  let results: TemplateResult[] = [];

  test.beforeAll(async () => {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
    await cleanupAllDemos();
  });

  test.afterAll(async () => {
    generateReport(results);
  });

  // Since Playwright doesn't support dynamic test generation easily,
  // we run all templates in a single test
  test('Validate all templates', async ({ page }) => {
    test.setTimeout(0); // No timeout for the full suite

    const templates = await getTemplates();
    console.log(`\nValidating ${templates.length} templates...\n`);

    for (let i = 0; i < templates.length; i++) {
      const t = templates[i];
      const result: TemplateResult = {
        id: t.id,
        name: t.name,
        tier: t.tier || '?',
        containers: t.container_count || 0,
        deploy1: 'SKIP',
        deploy1_detail: '',
        deploy2: 'SKIP',
        deploy2_detail: '',
        errors: [],
      };

      console.log(`[${i + 1}/${templates.length}] ${t.name} (${t.tier}, ${t.container_count}c)`);

      try {
        // 1. Navigate to Templates page
        await page.goto(`${APP}/templates`);
        await page.waitForTimeout(2000);

        // Find the template's tier tab if needed
        const tierTab = page.getByRole('tab', { name: new RegExp(t.tier, 'i') });
        if (await tierTab.isVisible({ timeout: 3000 }).catch(() => false)) {
          await tierTab.click();
          await page.waitForTimeout(1000);
        }

        // 2. Click "Create Demo" for this template
        const createBtn = page.getByRole('button', { name: `Create demo from template: ${t.name}` });
        // Scroll to it first
        await createBtn.scrollIntoViewIfNeeded();
        await createBtn.click();

        // Wait for navigation to designer
        await page.waitForURL(/\/demo\//, { timeout: 10000 });
        await page.waitForTimeout(3000);

        // 3. Deploy #1
        console.log(`  Deploy #1...`);
        const deployBtn = page.getByRole('button', { name: 'Deploy' });
        await deployBtn.click();

        const deploy1 = await waitForDeploy(page, 300000);
        if (deploy1.success) {
          result.deploy1 = 'PASS';
          result.deploy1_detail = deploy1.detail;
          // Dismiss overlay
          const doneBtn = page.getByRole('button', { name: 'Done' });
          await doneBtn.click().catch(() => {});
          await page.waitForTimeout(2000);
        } else {
          result.deploy1 = 'FAIL';
          result.deploy1_detail = deploy1.detail;
          result.errors.push(`Deploy1: ${deploy1.detail}`);
          // Try to close error overlay
          const closeBtn = page.getByRole('button', { name: 'Close' });
          await closeBtn.click().catch(() => {});
        }

        // Screenshot after deploy1
        const ss1 = path.join(SCREENSHOT_DIR, `${t.id}-deploy1.png`);
        await page.screenshot({ path: ss1, fullPage: false });
        result.screenshot1 = `${t.id}-deploy1.png`;

        // 4. Stop #1
        console.log(`  Stop #1...`);
        if (result.deploy1 === 'PASS') {
          const stopBtn = page.getByRole('button', { name: 'Stop' });
          if (await stopBtn.isEnabled({ timeout: 3000 }).catch(() => false)) {
            await stopBtn.click();
            await page.waitForTimeout(8000);
          }
        }

        // 5. Deploy #2 (redeploy)
        if (result.deploy1 === 'PASS') {
          console.log(`  Deploy #2...`);
          await page.waitForTimeout(5000); // Extra wait for cleanup
          const deployBtn2 = page.getByRole('button', { name: 'Deploy' });
          if (await deployBtn2.isEnabled({ timeout: 5000 }).catch(() => false)) {
            await deployBtn2.click();
            const deploy2 = await waitForDeploy(page, 300000);
            if (deploy2.success) {
              result.deploy2 = 'PASS';
              result.deploy2_detail = deploy2.detail;
              const doneBtn2 = page.getByRole('button', { name: 'Done' });
              await doneBtn2.click().catch(() => {});
              await page.waitForTimeout(2000);
            } else {
              result.deploy2 = 'FAIL';
              result.deploy2_detail = deploy2.detail;
              result.errors.push(`Deploy2: ${deploy2.detail}`);
              const closeBtn2 = page.getByRole('button', { name: 'Close' });
              await closeBtn2.click().catch(() => {});
            }

            // Screenshot after deploy2
            const ss2 = path.join(SCREENSHOT_DIR, `${t.id}-deploy2.png`);
            await page.screenshot({ path: ss2, fullPage: false });
            result.screenshot2 = `${t.id}-deploy2.png`;

            // Stop #2
            console.log(`  Stop #2...`);
            const stopBtn2 = page.getByRole('button', { name: 'Stop' });
            if (await stopBtn2.isEnabled({ timeout: 3000 }).catch(() => false)) {
              await stopBtn2.click();
              await page.waitForTimeout(8000);
            }
          } else {
            result.deploy2 = 'FAIL';
            result.deploy2_detail = 'Deploy button not enabled after stop';
            result.errors.push('Deploy2: button not enabled');
          }
        }

        // 6. Delete via API (fastest cleanup)
        const demoId = new URL(page.url()).pathname.split('/').pop();
        if (demoId && demoId.length === 8) {
          await fetch(`${API}/api/demos/${demoId}/stop`, { method: 'POST' }).catch(() => {});
          await new Promise(r => setTimeout(r, 5000));
          await fetch(`${API}/api/demos/${demoId}`, { method: 'DELETE' }).catch(() => {});
          await new Promise(r => setTimeout(r, 3000));
        }

      } catch (err: any) {
        result.errors.push(`Exception: ${err.message?.slice(0, 200)}`);
        if (result.deploy1 === 'SKIP') result.deploy1 = 'FAIL';
        result.deploy1_detail = result.deploy1_detail || err.message?.slice(0, 100);
      }

      const status = result.deploy1 === 'PASS' && result.deploy2 === 'PASS' ? 'PASS' :
                     result.deploy1 === 'PASS' ? 'PARTIAL' : 'FAIL';
      console.log(`  → ${status}\n`);
      results.push(result);
    }
  });
});

function generateReport(results: TemplateResult[]) {
  const totalPass = results.filter(r => r.deploy1 === 'PASS' && r.deploy2 === 'PASS').length;
  const totalPartial = results.filter(r => r.deploy1 === 'PASS' && r.deploy2 !== 'PASS').length;
  const totalFail = results.filter(r => r.deploy1 !== 'PASS').length;
  const timestamp = new Date().toISOString().replace('T', ' ').slice(0, 19);

  // Read screenshots as base64
  function imgTag(filename?: string): string {
    if (!filename) return '';
    const filepath = path.join(SCREENSHOT_DIR, filename);
    if (!fs.existsSync(filepath)) return '';
    const data = fs.readFileSync(filepath).toString('base64');
    return `<img src="data:image/png;base64,${data}" style="max-width:100%;border-radius:8px;border:1px solid #334155;" />`;
  }

  let html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>DemoForge Template Validation Report</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; padding: 2rem; }
  h1 { font-size: 1.8rem; margin-bottom: 0.5rem; color: #f8fafc; text-align: center; }
  h2 { font-size: 1.3rem; margin: 2rem 0 1rem; color: #94a3b8; border-bottom: 1px solid #334155; padding-bottom: 0.5rem; }
  .header p { color: #64748b; text-align: center; }
  .summary { display: flex; gap: 1rem; justify-content: center; margin: 1.5rem 0; }
  .stat { background: #1e293b; border-radius: 12px; padding: 1.2rem 2rem; text-align: center; min-width: 120px; }
  .stat .num { font-size: 2rem; font-weight: 700; }
  .stat.pass .num { color: #22c55e; }
  .stat.fail .num { color: #ef4444; }
  .stat.total .num { color: #3b82f6; }
  .stat.partial .num { color: #f59e0b; }
  .stat .label { font-size: 0.8rem; color: #64748b; text-transform: uppercase; }
  .template-card { background: #1e293b; border-radius: 8px; margin: 1rem 0; overflow: hidden; }
  .template-header { padding: 1rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; }
  .template-name { font-weight: 600; color: #f8fafc; }
  .template-meta { font-size: 0.8rem; color: #64748b; }
  .badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
  .badge-pass { background: #052e16; color: #22c55e; }
  .badge-fail { background: #450a0a; color: #ef4444; }
  .badge-partial { background: #422006; color: #f59e0b; }
  .badge-skip { background: #1e293b; color: #64748b; }
  .screenshots { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; padding: 1rem; }
  .screenshots img { width: 100%; }
  .ss-label { font-size: 0.7rem; color: #64748b; margin-bottom: 0.3rem; }
  .errors { padding: 0.5rem 1rem 1rem; }
  .error-line { font-size: 0.8rem; color: #f87171; margin: 0.2rem 0; }
  .tier-badge { display: inline-block; padding: 0.2rem 0.8rem; border-radius: 999px; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; margin-right: 0.5rem; }
  .tier-essentials { background: #164e63; color: #67e8f9; }
  .tier-advanced { background: #3b0764; color: #c084fc; }
  .tier-experience { background: #422006; color: #fbbf24; }
  .footer { text-align: center; margin-top: 3rem; color: #475569; font-size: 0.8rem; }
</style>
</head>
<body>
<div class="header">
  <h1>DemoForge Template Validation Report</h1>
  <p>${timestamp} | Playwright Browser Validation | All images pre-cached</p>
</div>
<div class="summary">
  <div class="stat total"><div class="num">${results.length}</div><div class="label">Templates</div></div>
  <div class="stat pass"><div class="num">${totalPass}</div><div class="label">Full Pass</div></div>
  <div class="stat partial"><div class="num">${totalPartial}</div><div class="label">Partial</div></div>
  <div class="stat fail"><div class="num">${totalFail}</div><div class="label">Fail</div></div>
</div>`;

  for (const tier of ['essentials', 'advanced', 'experience']) {
    const tierResults = results.filter(r => r.tier === tier);
    if (tierResults.length === 0) continue;
    const tierPass = tierResults.filter(r => r.deploy1 === 'PASS' && r.deploy2 === 'PASS').length;
    const tierClass = tier === 'essentials' ? 'tier-essentials' : tier === 'advanced' ? 'tier-advanced' : 'tier-experience';

    html += `<h2><span class="${tierClass} tier-badge">${tier}</span> ${tierPass}/${tierResults.length} Pass</h2>`;

    for (const r of tierResults) {
      const overall = r.deploy1 === 'PASS' && r.deploy2 === 'PASS' ? 'pass' :
                      r.deploy1 === 'PASS' ? 'partial' : 'fail';
      html += `
<div class="template-card">
  <div class="template-header">
    <div>
      <span class="template-name">${r.name}</span>
      <span class="template-meta"> &middot; ${r.containers}c &middot; ${r.id}</span>
    </div>
    <div>
      <span class="badge badge-${r.deploy1 === 'PASS' ? 'pass' : r.deploy1 === 'FAIL' ? 'fail' : 'skip'}">D1: ${r.deploy1}</span>
      <span class="badge badge-${r.deploy2 === 'PASS' ? 'pass' : r.deploy2 === 'FAIL' ? 'fail' : 'skip'}">D2: ${r.deploy2}</span>
      <span class="badge badge-${overall}">${overall.toUpperCase()}</span>
    </div>
  </div>`;

      if (r.screenshot1 || r.screenshot2) {
        html += `<div class="screenshots">`;
        if (r.screenshot1) html += `<div><div class="ss-label">Deploy #1</div>${imgTag(r.screenshot1)}</div>`;
        if (r.screenshot2) html += `<div><div class="ss-label">Deploy #2 (Redeploy)</div>${imgTag(r.screenshot2)}</div>`;
        html += `</div>`;
      }

      if (r.errors.length > 0) {
        html += `<div class="errors">`;
        for (const e of r.errors) html += `<div class="error-line">${e}</div>`;
        html += `</div>`;
      }

      html += `</div>`;
    }
  }

  html += `<div class="footer">DemoForge Template Validation | ${results.length} templates | Playwright | ${timestamp}</div>
</body></html>`;

  fs.writeFileSync(REPORT_PATH, html);
  console.log(`\nReport written to ${REPORT_PATH}`);
}
