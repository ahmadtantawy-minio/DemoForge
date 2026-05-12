/**
 * Erasure coding helpers for MinIO-style pools.
 *
 * MinIO `MINIO_STORAGE_CLASS_STANDARD=EC:<P>` sets **parity shard count P** only.
 * For UX we show full stripe geometry as **EC &lt;stripe_drives&gt;:&lt;parity_drives&gt;**
 * where `stripe_drives` is one erasure set (see `effectiveStripeSize` / `computeErasureSetSize`).
 */

const MAX_AUTO_STRIPE = 16;

export function computeErasureSetSize(totalDrives: number): number {
  for (let d = MAX_AUTO_STRIPE; d >= 2; d--) {
    if (totalDrives % d === 0) return d;
  }
  return totalDrives;
}

/** Divisors of `totalDrives` in 4..min(16,total) that support at least one valid STANDARD EC parity. */
export function validStripeSizesForTotal(totalDrives: number): number[] {
  const cap = Math.min(MAX_AUTO_STRIPE, totalDrives);
  const out: number[] = [];
  for (let d = cap; d >= 4; d--) {
    if (totalDrives % d !== 0) continue;
    if (validMinioStandardParities(d).length === 0) continue;
    out.push(d);
  }
  return out.sort((a, b) => b - a);
}

/** Drives per erasure stripe for EC rules: explicit `preferred` when valid, else auto (`computeErasureSetSize`). */
export function effectiveStripeSize(totalDrives: number, preferred: number | null | undefined): number {
  if (preferred != null && preferred > 0 && totalDrives % preferred === 0) {
    if (validMinioStandardParities(preferred).length > 0) return preferred;
  }
  return computeErasureSetSize(totalDrives);
}

/** Value safe to persist, or `null` when unset / invalid for this total drive count. */
export function canonicalErasureStripeDrivesPref(
  totalDrives: number,
  preferred: number | null | undefined,
): number | null {
  if (preferred == null || preferred <= 0 || totalDrives % preferred !== 0) return null;
  if (validMinioStandardParities(preferred).length === 0) return null;
  return preferred;
}

/** STANDARD parity P must satisfy 2 ≤ P ≤ floor(stripeSize/2) (MinIO erasure docs). */
export function validMinioStandardParities(stripeSize: number): number[] {
  const maxParity = Math.floor(stripeSize / 2);
  const out: number[] = [];
  for (let p = 2; p <= maxParity; p++) out.push(p);
  return out;
}

/** Default STANDARD parity for a stripe (MinIO table: ≤5 → 2, 6–7 → 3, ≥8 → 4), clamped to valid. */
export function minioDefaultStandardParity(stripeSize: number): number {
  const opts = validMinioStandardParities(stripeSize);
  if (opts.length === 0) return 1;
  const prefer = stripeSize <= 5 ? 2 : stripeSize <= 7 ? 3 : 4;
  if (opts.includes(prefer)) return prefer;
  return opts[opts.length - 1];
}

/** Snap parity to the nearest valid STANDARD value for this stripe size. */
export function clampParityToValidStripe(stripeSize: number, parity: number): number {
  const opts = validMinioStandardParities(stripeSize);
  if (opts.length === 0) return Math.max(1, Math.min(parity, Math.max(1, Math.floor(stripeSize / 2))));
  if (opts.includes(parity)) return parity;
  return opts.reduce((best, p) => (Math.abs(p - parity) < Math.abs(best - parity) ? p : best), opts[0]);
}

/** Human label: `EC 8:4` — stripe drive count and parity drive count. */
export function formatMinioEcStripeShort(stripeSize: number, parity: number): string {
  return `EC ${stripeSize}:${parity}`;
}

/** Longer label for dropdown rows. */
export function formatMinioEcStripeDescription(stripeSize: number, parity: number): string {
  const data = stripeSize - parity;
  return `${formatMinioEcStripeShort(stripeSize, parity)} — ${data} data + ${parity} parity per stripe; maps to MINIO_STORAGE_CLASS_STANDARD=EC:${parity}`;
}

export interface MinioEcSettingOption {
  /** Parity count P (stored as `ecParity` / sent to backend as `ec_parity`). */
  value: number;
  shortLabel: string;
  label: string;
}

/** Valid EC settings for one erasure stripe of size `stripeSize` drives. */
export function minioEcSettingOptions(stripeSize: number): MinioEcSettingOption[] {
  return validMinioStandardParities(stripeSize).map((p) => ({
    value: p,
    shortLabel: formatMinioEcStripeShort(stripeSize, p),
    label: formatMinioEcStripeDescription(stripeSize, p),
  }));
}

/** @deprecated use `minioEcSettingOptions` */
export function computeECOptions(setSize: number): { value: number; label: string }[] {
  return minioEcSettingOptions(setSize).map((o) => ({ value: o.value, label: o.label }));
}

export interface ErasureStats {
  setSize: number;
  numSets: number;
  dataShards: number;
  parityShards: number;
  usableRatio: number;
  rawTb: number;
  usableTb: number;
  driveTolerance: number;
  readQuorum: number;
  writeQuorum: number;
}

export function computePoolErasureStats(
  nodeCount: number,
  drivesPerNode: number,
  ecParity: number,
  diskSizeTb: number,
  erasureStripeDrives?: number | null,
): ErasureStats {
  const totalDrives = nodeCount * drivesPerNode;
  const setSize = effectiveStripeSize(totalDrives, erasureStripeDrives);
  const numSets = totalDrives / setSize;
  const dataShards = Math.max(0, setSize - ecParity);
  const usableRatio = dataShards / setSize;
  const rawTb = totalDrives * diskSizeTb;
  const usableTb = totalDrives >= 4 && dataShards > 0 ? Math.round(rawTb * usableRatio) : 0;
  const writeQuorum = dataShards === ecParity ? dataShards + 1 : dataShards;
  return {
    setSize,
    numSets,
    dataShards,
    parityShards: ecParity,
    usableRatio,
    rawTb,
    usableTb,
    driveTolerance: ecParity,
    readQuorum: dataShards,
    writeQuorum,
  };
}
