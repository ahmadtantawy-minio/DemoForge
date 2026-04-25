import { lazy, Suspense, useCallback, useRef } from "react";
import { toExcalidrawInitialData, buildPersistedScene, pickPersistableAppState, excalidrawChangeSignature } from "./excalidrawScene";

import "@excalidraw/excalidraw/index.css";

const Excalidraw = lazy(() => import("@excalidraw/excalidraw").then((m) => ({ default: m.Excalidraw })));

type Props = {
  /** Serialized scene from the demo slide */
  scene: Record<string, unknown> | null | undefined;
  /** Bump when server reload should replace canvas contents */
  remountKey?: string | number;
  mode: "edit" | "present";
  className?: string;
  onSceneChange?: (scene: Record<string, unknown>) => void;
};

export default function SlideExcalidrawCanvas({ scene, remountKey = 0, mode, className, onSceneChange }: Props) {
  const lastRemount = useRef(remountKey);
  const initialDataRef = useRef(toExcalidrawInitialData(scene ?? null));
  /** Prevents React↔Excalidraw feedback loops: onChange also runs after parent re-renders (see excalidraw#3014). */
  const sceneSignatureRef = useRef<string>("");
  const onSceneChangeRef = useRef(onSceneChange);
  onSceneChangeRef.current = onSceneChange;

  if (lastRemount.current !== remountKey) {
    lastRemount.current = remountKey;
    initialDataRef.current = toExcalidrawInitialData(scene ?? null);
    sceneSignatureRef.current = "";
  }

  const stableOnChange = useCallback((elements: readonly unknown[], appState: unknown, files: unknown) => {
    const cb = onSceneChangeRef.current;
    if (!cb) return;
    const appSlice = pickPersistableAppState(appState as Record<string, unknown>);
    const sig = excalidrawChangeSignature(elements, appSlice, files);
    if (sig === sceneSignatureRef.current) return;
    sceneSignatureRef.current = sig;
    try {
      cb(
        buildPersistedScene(
          elements,
          appState as unknown as Record<string, unknown>,
          files as unknown as Record<string, unknown>
        )
      );
    } catch {
      /* ignore stringify / serialization edge cases */
    }
  }, []);

  return (
    <div className={className ?? "h-full w-full min-h-[280px]"}>
      <Suspense
        fallback={
          <div className="flex h-full min-h-[inherit] w-full items-center justify-center rounded-md border border-border bg-muted/30 text-sm text-muted-foreground">
            Loading whiteboard…
          </div>
        }
      >
        <Excalidraw
          key={String(remountKey)}
          initialData={initialDataRef.current}
          viewModeEnabled={mode === "present"}
          zenModeEnabled={mode === "present"}
          gridModeEnabled={false}
          detectScroll={false}
          onChange={mode === "edit" && onSceneChange ? stableOnChange : undefined}
        />
      </Suspense>
    </div>
  );
}
