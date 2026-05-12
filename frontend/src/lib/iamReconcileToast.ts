import { fetchIamReconcileReport } from "../api/client";
import { toast } from "./toast";

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** After deploy/start/topology apply, show a toast when mc-shell logged ``DEMOFORGE_IAM_REPORT``. */
export async function showIamReconcileToastIfApplicable(demoId: string): Promise<void> {
  try {
    // mc-shell init.sh sleeps 15s then retries aliases — IAM + report line appear later than deploy "complete".
    await sleep(4000);
    let r = await fetchIamReconcileReport(demoId);
    if (!r.enabled && r.reason === "mc_shell_not_found") return;
    for (let n = 0; n < 10 && !r.enabled && r.reason === "no_iam_report"; n++) {
      await sleep(3500);
      r = await fetchIamReconcileReport(demoId);
    }
    if (!r.enabled) return;

    const title = "IAM simulation applied";
    const lines = [
      `Policies: ${r.policies_provisioned}/${r.policies_expected} provisioned, ${r.policies_unprovisioned} unprovisioned, ${r.policies_failed} failed`,
      `Users: ${r.users_provisioned}/${r.users_expected} provisioned, ${r.users_unprovisioned} unprovisioned, ${r.users_failed} failed`,
      `Policy attaches: ${r.attaches_provisioned}/${r.attaches_expected} provisioned, ${r.attaches_unprovisioned} unprovisioned, ${r.attaches_failed} failed`,
    ];
    if (r.errors.length) {
      lines.push(`Errors: ${r.errors.join(" · ")}`);
    }
    const description = lines.join("\n");
    const hasIssue =
      r.policies_failed + r.users_failed + r.attaches_failed > 0 ||
      r.policies_unprovisioned + r.users_unprovisioned + r.attaches_unprovisioned > 0 ||
      r.errors.length > 0;
    if (hasIssue) {
      toast.warning(title, { description, duration: 14000 });
    } else {
      toast.success(title, { description, duration: 9000 });
    }
  } catch {
    // optional UX — ignore report failures
  }
}
