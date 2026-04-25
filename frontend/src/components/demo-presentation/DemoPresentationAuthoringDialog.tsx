import { useEffect, useState, useCallback } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { fetchPresentation, savePresentation, type DemoPresentationPayload, type DemoSlidePayload } from "../../api/client";
import { toast } from "../../lib/toast";
import { Clapperboard, Plus, Trash2, Play } from "lucide-react";
import SlideExcalidrawCanvas from "./SlideExcalidrawCanvas";
import { emptyExcalidrawScene } from "./excalidrawScene";

function newSlideId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return `slide-${crypto.randomUUID().slice(0, 8)}`;
  return `slide-${Date.now().toString(36)}`;
}

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  demoId: string;
  readOnly?: boolean;
  onPresent: (section: "intro" | "outro", slides: DemoSlidePayload[]) => void;
};

export default function DemoPresentationAuthoringDialog({
  open,
  onOpenChange,
  demoId,
  readOnly = false,
  onPresent,
}: Props) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [intro, setIntro] = useState<DemoSlidePayload[]>([]);
  const [outro, setOutro] = useState<DemoSlidePayload[]>([]);
  /** Bumped after each successful fetch so embedded Excalidraw remounts from server data */
  const [loadGeneration, setLoadGeneration] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await fetchPresentation(demoId);
      setIntro(d.intro_slides?.length ? d.intro_slides : []);
      setOutro(d.outro_slides?.length ? d.outro_slides : []);
      setLoadGeneration((g) => g + 1);
    } catch {
      toast.error("Failed to load slides");
      setIntro([]);
      setOutro([]);
    } finally {
      setLoading(false);
    }
  }, [demoId]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const payload = (): DemoPresentationPayload => ({
    intro_slides: intro,
    outro_slides: outro,
  });

  const handleSave = async () => {
    if (readOnly) return;
    setSaving(true);
    try {
      await savePresentation(demoId, payload());
      toast.success("Intro/outro slides saved");
    } catch {
      toast.error("Failed to save slides");
    } finally {
      setSaving(false);
    }
  };

  const updateSlide = (
    which: "intro" | "outro",
    id: string,
    patch: Partial<Pick<DemoSlidePayload, "title" | "body_markdown" | "excalidraw_scene">>
  ) => {
    const set = which === "intro" ? setIntro : setOutro;
    set((slides) => slides.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  };

  const addSlide = (which: "intro" | "outro") => {
    const slide: DemoSlidePayload = { id: newSlideId(), title: "New slide", body_markdown: "" };
    if (which === "intro") setIntro((s) => [...s, slide]);
    else setOutro((s) => [...s, slide]);
  };

  const removeSlide = (which: "intro" | "outro", id: string) => {
    if (which === "intro") setIntro((s) => s.filter((x) => x.id !== id));
    else setOutro((s) => s.filter((x) => x.id !== id));
  };

  const addWhiteboard = (which: "intro" | "outro", id: string) => {
    updateSlide(which, id, { excalidraw_scene: emptyExcalidrawScene() });
  };

  const removeWhiteboard = (which: "intro" | "outro", id: string) => {
    updateSlide(which, id, { excalidraw_scene: null });
  };

  const renderEditor = (which: "intro" | "outro", slides: DemoSlidePayload[]) => (
    <div className="space-y-4 max-h-[55vh] overflow-y-auto pr-1">
      {slides.length === 0 && (
        <p className="text-sm text-muted-foreground">No slides yet. Add one to build your {which} sequence.</p>
      )}
      {slides.map((s, idx) => (
        <div key={s.id} className="rounded-lg border border-border bg-muted/20 p-3 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-muted-foreground font-medium">Slide {idx + 1}</span>
            {!readOnly && (
              <Button type="button" variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => removeSlide(which, s.id)}>
                <Trash2 className="w-3.5 h-3.5 text-red-400" />
              </Button>
            )}
          </div>
          <Input
            value={s.title || ""}
            onChange={(e) => updateSlide(which, s.id, { title: e.target.value })}
            placeholder="Title"
            disabled={readOnly}
            className="text-sm"
          />
          <textarea
            value={s.body_markdown || ""}
            onChange={(e) => updateSlide(which, s.id, { body_markdown: e.target.value })}
            placeholder="Body (markdown: use **bold** and line breaks)"
            disabled={readOnly}
            rows={5}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
          />
          {(s.excalidraw_scene != null || !readOnly) && (
            <div className="space-y-2 pt-1">
              <div className="text-xs font-medium text-muted-foreground">Whiteboard (Excalidraw)</div>
              {s.excalidraw_scene != null ? (
              <>
                <div className="h-[min(420px,45vh)] w-full overflow-hidden rounded-md border border-border bg-background">
                  <SlideExcalidrawCanvas
                    scene={s.excalidraw_scene as Record<string, unknown>}
                    remountKey={loadGeneration}
                    mode={readOnly ? "present" : "edit"}
                    className="h-full w-full"
                    onSceneChange={
                      readOnly
                        ? undefined
                        : (scene) => {
                            updateSlide(which, s.id, { excalidraw_scene: scene });
                          }
                    }
                  />
                </div>
                {!readOnly && (
                  <Button type="button" variant="outline" size="sm" onClick={() => removeWhiteboard(which, s.id)}>
                    Remove whiteboard
                  </Button>
                )}
              </>
            ) : (
              !readOnly && (
                <Button type="button" variant="outline" size="sm" onClick={() => addWhiteboard(which, s.id)}>
                  Add whiteboard
                </Button>
              )
            )}
            </div>
          )}
        </div>
      ))}
      {!readOnly && (
        <Button type="button" variant="outline" size="sm" className="gap-1" onClick={() => addSlide(which)}>
          <Plus className="w-3.5 h-3.5" /> Add slide
        </Button>
      )}
    </div>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Clapperboard className="w-5 h-5" />
            Demo intro / outro slides
          </DialogTitle>
        </DialogHeader>
        {loading ? (
          <p className="text-sm text-muted-foreground py-8 text-center">Loading…</p>
        ) : (
          <Tabs defaultValue="intro" className="flex-1 min-h-0 flex flex-col">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="intro">Intro ({intro.length})</TabsTrigger>
              <TabsTrigger value="outro">Outro ({outro.length})</TabsTrigger>
            </TabsList>
            <TabsContent value="intro" className="mt-3 flex-1 min-h-0">
              {renderEditor("intro", intro)}
              {intro.length > 0 && (
                <div className="mt-3 flex justify-end">
                  <Button type="button" variant="secondary" size="sm" className="gap-1" onClick={() => onPresent("intro", intro)}>
                    <Play className="w-3.5 h-3.5" /> Present intro
                  </Button>
                </div>
              )}
            </TabsContent>
            <TabsContent value="outro" className="mt-3 flex-1 min-h-0">
              {renderEditor("outro", outro)}
              {outro.length > 0 && (
                <div className="mt-3 flex justify-end">
                  <Button type="button" variant="secondary" size="sm" className="gap-1" onClick={() => onPresent("outro", outro)}>
                    <Play className="w-3.5 h-3.5" /> Present outro
                  </Button>
                </div>
              )}
            </TabsContent>
          </Tabs>
        )}
        <DialogFooter className="gap-2 sm:gap-2 flex-col sm:flex-row sm:justify-end border-t border-border pt-3">
          {!readOnly && (
            <Button type="button" onClick={handleSave} disabled={saving || loading}>
              {saving ? "Saving…" : "Save"}
            </Button>
          )}
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
