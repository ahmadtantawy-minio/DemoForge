/** Helpers for MinIO IAM simulation spec (`MINIO_IAM_SIM_SPEC`) — policies + users. */

export interface IamSimPolicy {
  name: string;
  document: Record<string, unknown>;
}

export interface IamSimUser {
  access_key: string;
  secret_key: string;
  policies: string[];
  label?: string | undefined;
}

export interface IamSimSpec {
  policies: IamSimPolicy[];
  users: IamSimUser[];
}

const DEFAULT_POLICY_DOC: Record<string, unknown> = {
  Version: "2012-10-17",
  Statement: [
    {
      Effect: "Allow",
      Action: ["s3:ListAllMyBuckets"],
      Resource: ["arn:aws:s3:::*"],
    },
  ],
};

export function emptyIamSimSpec(): IamSimSpec {
  return { policies: [], users: [] };
}

/**
 * True when JSON declares a non-empty `policies` or `users` array (matches backend
 * `effective_iam_sim_spec`). Placeholder `{}` / empty arrays do not count as IAM-enabled.
 */
export function iamSimSpecRawHasContent(raw: string | undefined | null): boolean {
  const s = (raw ?? "").trim();
  if (!s) return false;
  try {
    const o = JSON.parse(s) as { policies?: unknown; users?: unknown };
    if (!o || typeof o !== "object") return false;
    const hasP = Array.isArray(o.policies) && o.policies.length > 0;
    const hasU = Array.isArray(o.users) && o.users.length > 0;
    return hasP || hasU;
  } catch {
    return false;
  }
}

export function tryParseIamSimSpec(raw: string | undefined | null): IamSimSpec | null {
  const s = (raw ?? "").trim();
  if (!s) return null;
  try {
    const o = JSON.parse(s) as unknown;
    if (!o || typeof o !== "object") return null;
    const policiesIn = (o as { policies?: unknown }).policies;
    const usersIn = (o as { users?: unknown }).users;
    const policies: IamSimPolicy[] = [];
    if (Array.isArray(policiesIn)) {
      for (const p of policiesIn) {
        if (!p || typeof p !== "object") continue;
        const name = String((p as { name?: unknown }).name ?? "").trim();
        const doc = (p as { document?: unknown }).document;
        if (!name || !doc || typeof doc !== "object") continue;
        policies.push({ name, document: doc as Record<string, unknown> });
      }
    }
    const users: IamSimUser[] = [];
    if (Array.isArray(usersIn)) {
      for (const u of usersIn) {
        if (!u || typeof u !== "object") continue;
        const access_key = String((u as { access_key?: unknown }).access_key ?? (u as { name?: unknown }).name ?? "").trim();
        const secret_key = String((u as { secret_key?: unknown }).secret_key ?? (u as { secret?: unknown }).secret ?? "").trim();
        if (!access_key || !secret_key) continue;
        let pols = (u as { policies?: unknown }).policies;
        if (typeof pols === "string") pols = pols.split(",").map((x) => x.trim()).filter(Boolean);
        const policiesArr = Array.isArray(pols) ? pols.map((x) => String(x).trim()).filter(Boolean) : [];
        const label = (u as { label?: unknown }).label;
        users.push({
          access_key,
          secret_key,
          policies: policiesArr,
          label: typeof label === "string" && label.trim() ? label.trim() : undefined,
        });
      }
    }
    return { policies, users };
  } catch {
    return null;
  }
}

export function summarizeIamSimSpec(raw: string | undefined | null): string {
  const p = tryParseIamSimSpec(raw);
  if (!p) {
    const t = (raw ?? "").trim();
    return t ? "Invalid or non-JSON spec" : "—";
  }
  if (p.policies.length === 0 && p.users.length === 0) return "—";
  return `${p.policies.length} role(s), ${p.users.length} user(s)`;
}

export function serializeIamSimSpec(spec: IamSimSpec, pretty = true): string {
  const policyNames = new Set(spec.policies.map((p) => p.name.trim()).filter(Boolean));
  const policies = spec.policies
    .map((p) => ({ name: p.name.trim(), document: p.document }))
    .filter((p) => p.name);
  const users = spec.users
    .map((u) => ({
      access_key: u.access_key.trim(),
      secret_key: u.secret_key.trim(),
      ...(u.label ? { label: u.label.trim() } : {}),
      policies: u.policies.map((x) => x.trim()).filter((x) => policyNames.has(x)),
    }))
    .filter((u) => u.access_key && u.secret_key);
  const out: IamSimSpec = { policies, users };
  return pretty ? JSON.stringify(out, null, 2) : JSON.stringify(out);
}

export function defaultPolicyDocumentText(): string {
  return JSON.stringify(DEFAULT_POLICY_DOC, null, 2);
}

const AK_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";

function randomFromAlphabet(length: number, alphabet: string): string {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  let out = "";
  for (let i = 0; i < length; i++) {
    out += alphabet[bytes[i]! % alphabet.length]!;
  }
  return out;
}

function randomHexBytes(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** New S3-style access key (20 chars) and secret (64 hex = 32 bytes) for IAM simulation users. */
export function generateIamSimAccessSecretPair(): { access_key: string; secret_key: string } {
  return {
    access_key: randomFromAlphabet(20, AK_ALPHABET),
    secret_key: randomHexBytes(32),
  };
}
