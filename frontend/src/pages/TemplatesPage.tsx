import { useState, useEffect } from "react";
import { useDemoStore } from "../stores/demoStore";
import TemplateGallery from "../components/templates/TemplateGallery";

export function TemplatesPage() {
  const { setCurrentPage, setActiveDemoId, currentPage } = useDemoStore();
  const [loadKey, setLoadKey] = useState(0);

  useEffect(() => {
    if (currentPage === "templates") setLoadKey((k) => k + 1);
  }, [currentPage]);

  const handleDemoCreated = (demoId: string) => {
    setActiveDemoId(demoId);
    setCurrentPage("designer");
  };

  return (
    <div data-testid="templates-page" className="h-full overflow-auto bg-background">
      <div className="max-w-6xl mx-auto px-8 py-8">
        <h1 className="text-2xl font-bold text-card-foreground mb-6">Templates</h1>
        <TemplateGallery onCreateDemo={handleDemoCreated} loadKey={loadKey} />
      </div>
    </div>
  );
}
