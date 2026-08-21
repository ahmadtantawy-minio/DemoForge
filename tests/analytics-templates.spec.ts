/**
 * Focused Playwright validation for analytics templates (ClickHouse / OpenSearch / HDFS+Hive)
 * against a local `make dev-start-gcp` stack (UI :3001, API :9211).
 */
import { test, expect, Page } from '@playwright/test';

const API = process.env.DEMOFORGE_API_URL || 'http://localhost:9211';
const APP = process.env.DEMOFORGE_APP_URL || 'http://localhost:3001';

const TARGET_TEMPLATE_IDS = (
  process.env.ANALYTICS_TEMPLATE_IDS ||
  'clickhouse-aistor-olap,opensearch-aistor-snapshots,hdfs-hive-minio-sql'
)
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);

const REQUIRED_COMPONENTS = ['clickhouse', 'opensearch', 'hive-metastore', 'hdfs', 'minio', 'trino'];

async function waitForDeploy(
  page: Page,
  demoId: string,
  timeoutMs = 420000,
): Promise<{ success: boolean; detail: string }> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const doneBtn = page.getByRole('button', { name: 'Done' });
    if (await doneBtn.isVisible({ timeout: 500 }).catch(() => false)) {
      return { success: true, detail: 'Deployment successful (UI Done)' };
    }
    const successText = page.locator('text=Deployment successful').first();
    if (await successText.isVisible({ timeout: 500 }).catch(() => false)) {
      return { success: true, detail: 'Deployment successful (UI banner)' };
    }
    const failText = page.locator('text=Deployment failed').first();
    if (await failText.isVisible({ timeout: 500 }).catch(() => false)) {
      const errorText = (await failText.textContent()) || 'Unknown error';
      return { success: false, detail: errorText };
    }
    // Overlay may auto-dismiss; confirm via instances API
    try {
      const inst = await fetch(`${API}/api/demos/${demoId}/instances`);
      if (inst.ok) {
        const data = await inst.json();
        const status = data.status;
        const instances = data.instances || [];
        if (status === 'running' && instances.length > 0) {
          const allHealthy = instances.every((i: any) => (i.health || i.status) === 'healthy');
          if (allHealthy) {
            return { success: true, detail: `API running with ${instances.length} healthy instances` };
          }
        }
        if (status === 'error' || status === 'failed') {
          return { success: false, detail: `API status=${status}` };
        }
      }
    } catch {
      /* ignore transient API errors during deploy */
    }
    await page.waitForTimeout(3000);
  }
  return { success: false, detail: 'Timeout waiting for deploy' };
}

async function cleanupDemo(demoId: string) {
  const withTimeout = async (url: string, init?: RequestInit, ms = 20000) => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), ms);
    try {
      return await fetch(url, { ...init, signal: ctrl.signal });
    } catch {
      return null;
    } finally {
      clearTimeout(timer);
    }
  };

  await withTimeout(`${API}/api/demos/${demoId}/stop`, { method: 'POST' }, 20000);
  for (let i = 0; i < 45; i++) {
    const inst = await withTimeout(`${API}/api/demos/${demoId}/instances`, undefined, 5000);
    if (!inst || !inst.ok) break;
    try {
      const data = await inst.json();
      if (data.status !== 'running' && data.status !== 'stopping' && data.status !== 'deploying') break;
    } catch {
      break;
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  await withTimeout(`${API}/api/demos/${demoId}`, { method: 'DELETE' }, 20000);
  await new Promise((r) => setTimeout(r, 1000));
}

test.describe.serial('Analytics templates (dev-gcp)', () => {
  test('API readiness flags components and templates', async () => {
    const health = await fetch(`${API}/api/health`).catch(() => null);
    expect(health?.ok, `Backend not reachable at ${API}`).toBeTruthy();

    const compRes = await fetch(`${API}/api/readiness/components`);
    expect(compRes.ok).toBeTruthy();
    const compData = await compRes.json();
    const byId = Object.fromEntries((compData.components || []).map((c: any) => [c.component_id || c.id, c]));

    for (const id of REQUIRED_COMPONENTS) {
      const entry = byId[id];
      expect(entry, `missing readiness entry for ${id}`).toBeTruthy();
      expect(entry.fa_ready, `${id} should be fa_ready`).toBe(true);
    }

    const tplRes = await fetch(`${API}/api/readiness/templates`);
    expect(tplRes.ok).toBeTruthy();
    const tplData = await tplRes.json();
    const templates = tplData.templates || [];
    for (const id of TARGET_TEMPLATE_IDS) {
      const t = templates.find((x: any) => x.template_id === id || x.id === id);
      expect(t, `missing template readiness for ${id}`).toBeTruthy();
      expect(t.is_fa_ready, `${id} should be is_fa_ready`).toBe(true);
    }

    const listRes = await fetch(`${API}/api/templates`);
    expect(listRes.ok).toBeTruthy();
    const listData = await listRes.json();
    const listed = listData.templates || [];
    for (const id of TARGET_TEMPLATE_IDS) {
      expect(
        listed.some((t: any) => t.id === id),
        `${id} should appear in /api/templates`,
      ).toBe(true);
    }
  });

  test('Create and deploy each analytics template once', async ({ page }) => {
    test.setTimeout(0);

    const listRes = await fetch(`${API}/api/templates`);
    const listed = ((await listRes.json()).templates || []) as any[];

    for (const id of TARGET_TEMPLATE_IDS) {
      const meta = listed.find((t) => t.id === id);
      expect(meta, `template ${id} not listed`).toBeTruthy();
      console.log(`\n=== Deploy ${meta.name} (${id}) ===`);

      await page.goto(`${APP}/templates`);
      await page.waitForTimeout(2000);

      const tier = meta.tier || 'essentials';
      const tierTab = page.getByRole('tab', { name: new RegExp(tier, 'i') });
      if (await tierTab.isVisible({ timeout: 3000 }).catch(() => false)) {
        await tierTab.click();
        await page.waitForTimeout(800);
      }

      const createBtn = page.getByRole('button', { name: `Create demo from template: ${meta.name}` });
      await createBtn.scrollIntoViewIfNeeded();
      await createBtn.click();
      await page.waitForURL(/\/demo\//, { timeout: 15000 });
      await page.waitForTimeout(2500);
      const demoId = new URL(page.url()).pathname.split('/').filter(Boolean).pop() || '';
      expect(demoId.length).toBeGreaterThanOrEqual(6);

      const deployBtn = page.getByRole('button', { name: 'Deploy' });
      await expect(deployBtn).toBeEnabled({ timeout: 10000 });
      await deployBtn.click();

      const result = await waitForDeploy(page, demoId, 480000);
      console.log(`  → ${result.success ? 'PASS' : 'FAIL'}: ${result.detail}`);
      expect(result.success, `${id} deploy failed: ${result.detail}`).toBe(true);

      await page.getByRole('button', { name: 'Done' }).click().catch(() => {});
      await page.getByRole('button', { name: 'Close' }).click().catch(() => {});
      await page.waitForTimeout(1500);

      // Instances should report running containers for the demo
      const instRes = await fetch(`${API}/api/demos/${demoId}/instances`);
      expect(instRes.ok).toBeTruthy();
      const instData = await instRes.json();
      expect((instData.instances || []).length, `${id} expected instances`).toBeGreaterThan(0);

      await cleanupDemo(demoId);
    }
  });
});
