import React, { useEffect, useCallback, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import type { DemoSlidePayload } from "../../api/client";
import { SlideBodyView } from "./renderSlideBody";
import SlideExcalidrawCanvas from "./SlideExcalidrawCanvas";

type Props = {
  open: boolean;
  /** "intro" | "outro" — shown in chrome */
  section: "intro" | "outro";
  slides: DemoSlidePayload[];
  onClose: () => void;
};

export default function DemoPresentationPresenter({ open, section, slides, onClose }: Props) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (open) setIndex(0);
  }, [open, slides]);

  const slide = slides[index];
  const last = slides.length - 1;
  const scene = slide?.excalidraw_scene as Record<string, unknown> | null | undefined;
  const showBoard = scene != null && Array.isArray(scene.elements);

  const goPrev = useCallback(() => setIndex((i) => Math.max(0, i - 1)), []);
  const goNext = useCallback(() => setIndex((i) => Math.min(last, i + 1)), [last]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
      if (e.key === "ArrowRight" || e.key === "PageDown") {
        e.preventDefault();
        goNext();
      }
      if (e.key === "ArrowLeft" || e.key === "PageUp") {
        e.preventDefault();
        goPrev();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, goNext, goPrev]);

  if (!open || slides.length === 0) return null;

  return createPortal(
    <div className="fixed inset-0 z-[20000] flex flex-col bg-zinc-950 text-zinc-50">
      <header className="flex items-center justify-between px-6 py-3 border-b border-zinc-800 shrink-0">
        <span className="text-xs uppercase tracking-wider text-zinc-400">
          {section === "intro" ? "Intro" : "Outro"} &middot; slide {index + 1} / {slides.length}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="p-2 rounded-md hover:bg-zinc-800 text-zinc-300"
          title="Close (Esc)"
        >
          <X className="w-5 h-5" />
        </button>
      </header>
      <main className="flex-1 flex min-h-0 flex-col items-stretch px-4 py-6 md:px-12 overflow-hidden">
        <div className="shrink-0 text-center mb-4 md:mb-6">
          <h1 className="text-2xl md:text-4xl font-semibold text-zinc-50 max-w-4xl mx-auto leading-tight">
            {slide?.title || "Untitled slide"}
          </h1>
        </div>
        {showBoard ? (
          <div className="flex flex-1 min-h-0 flex-col gap-4">
            {(slide?.body_markdown || "").trim().length > 0 && (
              <SlideBodyView
                markdown={slide?.body_markdown || ""}
                className="shrink-0 text-sm md:text-lg text-zinc-300 text-center max-w-3xl mx-auto leading-relaxed"
              />
            )}
            <div className="flex-1 min-h-[200px] w-full max-w-[min(100%,1400px)] mx-auto rounded-lg border border-zinc-800 overflow-hidden bg-zinc-900">
              <SlideExcalidrawCanvas
                key={`present-${index}`}
                scene={scene}
                remountKey={index}
                mode="present"
                className="h-full w-full"
              />
            </div>
          </div>
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center overflow-auto">
            <SlideBodyView
              markdown={slide?.body_markdown || ""}
              className="text-lg md:text-2xl text-zinc-300 text-center max-w-3xl leading-relaxed"
            />
          </div>
        )}
      </main>
      <footer className="flex items-center justify-center gap-4 px-6 py-4 border-t border-zinc-800 shrink-0 bg-zinc-900/80">
        <button
          type="button"
          onClick={goPrev}
          disabled={index <= 0}
          className="flex items-center gap-2 px-4 py-2 rounded-md bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 disabled:pointer-events-none text-sm"
        >
          <ChevronLeft className="w-4 h-4" /> Previous
        </button>
        <button
          type="button"
          onClick={goNext}
          disabled={index >= last}
          className="flex items-center gap-2 px-4 py-2 rounded-md bg-zinc-100 text-zinc-900 hover:bg-white disabled:opacity-40 disabled:pointer-events-none text-sm font-medium"
        >
          Next <ChevronRight className="w-4 h-4" />
        </button>
        <span className="text-xs text-zinc-500 ml-4 hidden sm:inline">Esc to exit &middot; arrow keys</span>
      </footer>
    </div>,
    document.body
  );
}
