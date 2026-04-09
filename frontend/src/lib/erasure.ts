export function computeErasureSetSize(totalDrives: number): number {
  for (let d = 16; d >= 2; d--) {
    if (totalDrives % d === 0) return d;
  }
  return totalDrives;
}

export function computeECOptions(setSize: number): { value: number; label: string }[] {
  const maxParity = Math.floor(setSize / 2);
  return Array.from({ length: maxParity - 1 }, (_, i) => {
    const p = i + 2;
    const data = setSize - p;
    return { value: p, label: `EC:${p} (${data} data + ${p} parity, tolerates ${p} failures)` };
  });
}

export interface ErasureStats {
  setSize: number; numSets: number; dataShards: number; parityShards: number;
  usableRatio: number; rawTb: number; usableTb: number;
  driveTolerance: number; readQuorum: number; writeQuorum: number;
}

export function computePoolErasureStats(
  nodeCount: number, drivesPerNode: number, ecParity: number, diskSizeTb: number
): ErasureStats {
  const totalDrives = nodeCount * drivesPerNode;
  const setSize = computeErasureSetSize(totalDrives);
  const numSets = totalDrives / setSize;
  const dataShards = Math.max(0, setSize - ecParity);
  const usableRatio = dataShards / setSize;
  const rawTb = totalDrives * diskSizeTb;
  const usableTb = totalDrives >= 4 && dataShards > 0 ? Math.round(rawTb * usableRatio) : 0;
  const writeQuorum = dataShards === ecParity ? dataShards + 1 : dataShards;
  return { setSize, numSets, dataShards, parityShards: ecParity, usableRatio, rawTb, usableTb, driveTolerance: ecParity, readQuorum: dataShards, writeQuorum };
}
