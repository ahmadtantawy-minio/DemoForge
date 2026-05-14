/**
 * Shared classification + parsing for Dev Logs → Integrations and LogViewer MinIO integration stream.
 */

export type IntegrationDomain = "site_replication" | "ilm_tiering" | "other";

const SITE_PAT =
  /\bcluster-site-replication\b|\bsite-replication\b|\bmc\s+admin\s+replicate\b|\bsite\s+replication\b/i;
const ILM_PAT =
  /\bcluster-tiering\b|\bmc\s+ilm\b|\bilm\s+rule\b|\bilm\s+tier\b|\bremote\s+tier\b|\btier\s+add\b/i;

export function classifyIntegrationDomain(text: string): IntegrationDomain {
  const h = text;
  if (SITE_PAT.test(h)) return "site_replication";
  if (ILM_PAT.test(h)) return "ilm_tiering";
  return "other";
}

export function stripInlineCmdFromMessage(message: string): string {
  return message.replace(/\s*\|\s*cmd:\s*[^\n|]+/i, "").trim();
}

export function parseIntegrationDetails(details: string | undefined): {
  command: string | null;
  output: string | null;
} {
  if (!details?.trim()) return { command: null, output: null };
  const t = details.trim();

  const parts = t.split(/\n\n(?:OUTPUT|Output)\s*\n/i);
  if (parts.length === 2) {
    const head = parts[0];
    const out = parts[1].trim();
    if (/^(COMMAND|Command)\s*\n/i.test(head)) {
      const cmd = head.replace(/^(COMMAND|Command)\s*\n/i, "").trim();
      return { command: cmd || null, output: out || null };
    }
  }

  if (/^command:\s*\n/i.test(t)) {
    const body = t.replace(/^command:\s*\n/i, "");
    const idx = body.indexOf("\n\n");
    if (idx >= 0) {
      return {
        command: body.slice(0, idx).trim() || null,
        output: body.slice(idx + 2).trim() || null,
      };
    }
    return { command: body.trim() || null, output: null };
  }

  if (/^(COMMAND|Command)\s*\n/i.test(t)) {
    const cmd = t.replace(/^(COMMAND|Command)\s*\n/i, "").trim();
    return { command: cmd || null, output: null };
  }

  if (/^(OUTPUT|Output)\s*\n/i.test(t)) {
    return { command: null, output: t.replace(/^(OUTPUT|Output)\s*\n/i, "").trim() || null };
  }

  return { command: null, output: t };
}

export function buildStructuredIntegrationDetails(
  command: string | undefined,
  output: string | undefined,
): string | undefined {
  const c = command?.trim();
  const o = output?.trim();
  if (c && o) return `COMMAND\n${c}\n\nOUTPUT\n${o}`;
  if (c) return `COMMAND\n${c}`;
  if (o) return `OUTPUT\n${o}`;
  return undefined;
}
