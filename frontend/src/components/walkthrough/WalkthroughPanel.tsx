import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Check, ChevronLeft, ChevronRight, X, BookOpen } from "lucide-react";

export interface WalkthroughStep {
  step: string;
  description: string;
}

interface Props {
  steps: WalkthroughStep[];
  onClose: () => void;
}

export default function WalkthroughPanel({ steps, onClose }: Props) {
  const [currentStep, setCurrentStep] = useState(0);
  const [completedSteps, setCompletedSteps] = useState<Set<number>>(new Set());

  if (steps.length === 0) {
    return (
      <div className="w-full h-full flex flex-col bg-card border-l border-border">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2">
            <BookOpen className="w-4 h-4 text-primary" />
            <span className="text-sm font-semibold text-foreground">Walkthrough</span>
          </div>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 flex items-center justify-center p-4">
          <p className="text-sm text-muted-foreground text-center">
            No walkthrough steps available for this demo.
          </p>
        </div>
      </div>
    );
  }

  const completedCount = completedSteps.size;
  const progressPct = Math.round((completedCount / steps.length) * 100);

  const handleMarkComplete = () => {
    setCompletedSteps((prev) => {
      const next = new Set(prev);
      next.add(currentStep);
      return next;
    });
    if (currentStep < steps.length - 1) {
      setCurrentStep((s) => s + 1);
    }
  };

  const handlePrev = () => setCurrentStep((s) => Math.max(0, s - 1));
  const handleNext = () => setCurrentStep((s) => Math.min(steps.length - 1, s + 1));

  return (
    <div className="w-full h-full flex flex-col bg-card border-l border-border overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-2">
          <BookOpen className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold text-foreground">Walkthrough</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            Step {currentStep + 1} of {steps.length}
          </span>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-1 bg-muted flex-shrink-0">
        <div
          className="h-full bg-primary transition-all duration-300"
          style={{ width: `${progressPct}%` }}
        />
      </div>

      {/* Step list */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-1">
        {steps.map((s, i) => {
          const isActive = i === currentStep;
          const isCompleted = completedSteps.has(i);

          return (
            <button
              key={i}
              onClick={() => setCurrentStep(i)}
              className={`w-full text-left rounded-lg p-3 transition-colors ${
                isActive
                  ? "bg-primary/10 border border-primary/30"
                  : "hover:bg-muted/50 border border-transparent"
              }`}
            >
              <div className="flex items-start gap-3">
                {/* Step circle / connector */}
                <div className="flex flex-col items-center flex-shrink-0 mt-0.5">
                  <div
                    className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold flex-shrink-0 ${
                      isCompleted
                        ? "bg-green-500/20 text-green-400 border border-green-500/40"
                        : isActive
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted text-muted-foreground"
                    }`}
                  >
                    {isCompleted ? <Check className="w-3 h-3" /> : i + 1}
                  </div>
                  {i < steps.length - 1 && (
                    <div className="w-px h-4 bg-border mt-1" />
                  )}
                </div>

                {/* Step content */}
                <div className="min-w-0 flex-1 pb-3">
                  <p
                    className={`text-sm leading-tight ${
                      isCompleted
                        ? "line-through text-muted-foreground"
                        : isActive
                        ? "font-semibold text-foreground"
                        : "text-foreground/80"
                    }`}
                  >
                    {s.step}
                  </p>
                  {isActive && (
                    <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
                      {s.description}
                    </p>
                  )}
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Footer navigation */}
      <div className="flex-shrink-0 border-t border-border px-3 py-3 space-y-2">
        <Button
          size="sm"
          className="w-full h-8 text-xs"
          onClick={handleMarkComplete}
          disabled={completedSteps.has(currentStep)}
        >
          <Check className="w-3.5 h-3.5 mr-1.5" />
          {completedSteps.has(currentStep) ? "Completed" : "Mark Complete"}
        </Button>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            className="flex-1 h-8 text-xs"
            onClick={handlePrev}
            disabled={currentStep === 0}
          >
            <ChevronLeft className="w-3.5 h-3.5 mr-1" />
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="flex-1 h-8 text-xs"
            onClick={handleNext}
            disabled={currentStep === steps.length - 1}
          >
            Next
            <ChevronRight className="w-3.5 h-3.5 ml-1" />
          </Button>
        </div>
        <p className="text-[10px] text-muted-foreground text-center">
          {completedCount} of {steps.length} steps completed
        </p>
      </div>
    </div>
  );
}
