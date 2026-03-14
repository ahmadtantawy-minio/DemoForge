import { proxyUrl } from "../../api/client";
import { Button } from "@/components/ui/button";
import { X } from "lucide-react";

interface Props {
  path: string;
  name: string;
  onClose: () => void;
}

export default function WebUIFrame({ path, name, onClose }: Props) {
  const url = proxyUrl(path);
  return (
    <div className="flex flex-col w-full h-full">
      <div className="flex items-center justify-between px-3 py-1.5 bg-muted border-b border-border">
        <span className="text-sm font-medium text-foreground">{name}</span>
        <div className="flex items-center gap-2">
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-primary hover:underline"
          >
            Pop out
          </a>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={onClose}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
      <iframe
        src={url}
        className="flex-1 w-full border-0"
        title={name}
      />
    </div>
  );
}
