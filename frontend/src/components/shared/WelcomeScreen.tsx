import { useState, useEffect } from "react";
import { useDemoStore } from "../../stores/demoStore";
import { createDemo, fetchDemos, fetchTemplates, createFromTemplate } from "../../api/client";
import { toast } from "sonner";
import type { DemoTemplate } from "../../types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Plus, FileText } from "lucide-react";
import DemoSelectorModal from "./DemoSelectorModal";

export default function WelcomeScreen() {
  const { setDemos, setActiveDemoId, setActiveView } = useDemoStore();
  const [creating, setCreating] = useState(false);
  const [newDemoName, setNewDemoName] = useState("");
  const [templates, setTemplates] = useState<DemoTemplate[]>([]);
  const [demoSelectorOpen, setDemoSelectorOpen] = useState(false);

  useEffect(() => {
    fetchTemplates().then((res) => setTemplates(res.templates)).catch(() => {});
  }, []);

  const handleCreate = async () => {
    if (!newDemoName.trim()) return;
    try {
      const demo = await createDemo(newDemoName.trim());
      const res = await fetchDemos();
      setDemos(res.demos);
      setActiveDemoId(demo.id);
      setActiveView("diagram");
      setCreating(false);
      setNewDemoName("");
      toast.success(`Demo "${newDemoName.trim()}" created`);
    } catch (err: any) {
      toast.error("Failed to create demo", { description: err.message });
    }
  };

  const handleCreateFromTemplate = async (templateId: string) => {
    try {
      const demo = await createFromTemplate(templateId);
      const res = await fetchDemos();
      setDemos(res.demos);
      setActiveDemoId(demo.id);
      setActiveView("diagram");
      toast.success("Demo created from template");
    } catch (err: any) {
      toast.error("Failed to create from template", { description: err.message });
    }
  };

  return (
    <div className="flex-1 flex items-center justify-center h-full bg-background">
      <div className="flex flex-col items-center gap-6 max-w-md text-center">
        <div className="flex items-center gap-3 mb-2">
          <svg width="40" height="40" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="6" y="18" width="14" height="10" rx="2" fill="#C72C48" opacity="0.4"/>
            <rect x="10" y="11" width="14" height="10" rx="2" fill="#C72C48" opacity="0.7"/>
            <rect x="14" y="4" width="14" height="10" rx="2" fill="#C72C48"/>
          </svg>
          <h1 className="text-3xl font-bold text-foreground">DemoForge</h1>
        </div>

        <p className="text-muted-foreground text-sm">
          Select a demo to get started or create a new one.
        </p>

        <div className="flex flex-col gap-3 w-full">
          {creating ? (
            <div className="flex items-center gap-2">
              <Input
                autoFocus
                value={newDemoName}
                onChange={(e) => setNewDemoName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCreate();
                  if (e.key === "Escape") { setCreating(false); setNewDemoName(""); }
                }}
                placeholder="Demo name..."
                className="h-9 text-sm"
              />
              <Button onClick={handleCreate} size="sm">Create</Button>
              <Button onClick={() => { setCreating(false); setNewDemoName(""); }} variant="ghost" size="sm">Cancel</Button>
            </div>
          ) : (
            <div className="flex items-center gap-2 justify-center">
              <Button
                onClick={() => setDemoSelectorOpen(true)}
                variant="outline"
                size="sm"
                className="gap-2"
              >
                <FileText className="w-4 h-4" />
                Select Demo
              </Button>

              <Button
                onClick={() => setCreating(true)}
                size="sm"
                className="gap-2"
              >
                <Plus className="w-4 h-4" />
                Create New Demo
              </Button>

              {templates.length > 0 && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="outline" size="sm">
                      From Template
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="center" className="w-56">
                    {templates.map((t) => (
                      <DropdownMenuItem key={t.id} onSelect={() => handleCreateFromTemplate(t.id)}>
                        <div>
                          <div className="font-medium">{t.name}</div>
                          <div className="text-xs text-muted-foreground">{t.description}</div>
                        </div>
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </div>
          )}
        </div>
      </div>

      <DemoSelectorModal open={demoSelectorOpen} onOpenChange={setDemoSelectorOpen} />
    </div>
  );
}
