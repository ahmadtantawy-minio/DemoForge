/// <reference types="vite/client" />

/** Injected by Vite (`vite.config.ts` define) — npm package version of the UI. */
declare const __DF_UI_PKG_VERSION__: string;

interface ImportMetaEnv {
  /** Git describe at Vite build — same source as backend /api/version when images are built via hub-push. */
  readonly VITE_DEMOFORGE_RELEASE_VERSION: string;
}
