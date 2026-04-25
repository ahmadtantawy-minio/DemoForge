/** Shape stored in DemoSlide.excalidraw_scene (JSON-serializable). */

import type { ExcalidrawInitialDataState } from "@excalidraw/excalidraw/types";

export const DEMOFORGE_EXCALIDRAW_SOURCE = "demoforge";

export function emptyExcalidrawScene(): Record<string, unknown> {
  return {
    type: "excalidraw",
    version: 2,
    source: DEMOFORGE_EXCALIDRAW_SOURCE,
    elements: [],
    appState: {},
    files: {},
  };
}

function asRecord(v: unknown): Record<string, unknown> | null {
  return v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

/** Subset of appState we persist to keep payloads smaller and avoid stale UI state. */
export function pickPersistableAppState(appState: Record<string, unknown>): Record<string, unknown> {
  const keys = ["viewBackgroundColor", "theme", "scrollX", "scrollY", "zoom", "gridSize"] as const;
  const out: Record<string, unknown> = {};
  for (const k of keys) {
    if (k in appState) out[k] = appState[k];
  }
  return out;
}

export function buildPersistedScene(
  elements: readonly unknown[],
  appState: Record<string, unknown>,
  files: Record<string, unknown>
): Record<string, unknown> {
  return {
    type: "excalidraw",
    version: 2,
    source: DEMOFORGE_EXCALIDRAW_SOURCE,
    elements: JSON.parse(JSON.stringify(elements)),
    appState: JSON.parse(JSON.stringify(pickPersistableAppState(appState))),
    files: JSON.parse(JSON.stringify(files || {})),
  };
}

export function toExcalidrawInitialData(scene: Record<string, unknown> | null | undefined): ExcalidrawInitialDataState {
  if (!scene) return { elements: [], appState: {}, files: {} };
  const elements = Array.isArray(scene.elements) ? scene.elements : [];
  const app = asRecord(scene.appState) ?? {};
  const files = asRecord(scene.files) ?? {};
  return { elements, appState: app, files } as ExcalidrawInitialDataState;
}

/** Cheap fingerprint for onChange dedupe (avoids importing Excalidraw on the main bundle). */
export function excalidrawChangeSignature(
  elements: readonly unknown[],
  appSlice: Record<string, unknown>,
  files: unknown
): string {
  const elSig = Array.isArray(elements)
    ? elements
        .map((el) => {
          const o = el && typeof el === "object" && !Array.isArray(el) ? (el as Record<string, unknown>) : {};
          return `${o.id ?? ""}:${o.version ?? 0}:${o.versionNonce ?? 0}`;
        })
        .join("|")
    : "";
  const filesRec = files && typeof files === "object" && !Array.isArray(files) ? (files as Record<string, { version?: number }>) : {};
  const fileSig = Object.keys(filesRec)
    .sort()
    .map((id) => `${id}:${filesRec[id]?.version ?? 0}`)
    .join("|");
  return `${elSig}::${JSON.stringify(appSlice)}::${fileSig}`;
}
