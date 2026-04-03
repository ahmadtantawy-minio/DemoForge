import { useState } from "react";
import { toast } from "../../lib/toast";
import type { CredentialInfo } from "../../types";

interface Props {
  credentials: CredentialInfo[];
}

export default function CredentialDisplay({ credentials }: Props) {
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});

  const copyToClipboard = (value: string) => {
    navigator.clipboard.writeText(value);
    toast.success("Copied!");
  };

  if (credentials.length === 0) return null;

  return (
    <div className="mt-2 border-t border-border pt-2">
      <div className="text-xs font-semibold text-muted-foreground mb-1">Credentials</div>
      {credentials.map((cred) => (
        <div key={cred.key} className="flex items-center gap-2 text-xs mb-1">
          <span className="text-muted-foreground w-24 truncate" title={cred.label}>
            {cred.label}:
          </span>
          <span className="font-mono text-foreground flex-1 truncate">
            {revealed[cred.key] ? cred.value : "••••••••"}
          </span>
          <button
            onClick={() => setRevealed((prev) => ({ ...prev, [cred.key]: !prev[cred.key] }))}
            className="text-muted-foreground hover:text-foreground text-[10px] transition-colors"
          >
            {revealed[cred.key] ? "hide" : "show"}
          </button>
          <button
            onClick={() => copyToClipboard(cred.value)}
            className="text-muted-foreground hover:text-primary text-[10px] transition-colors"
            title="Copy to clipboard"
          >
            copy
          </button>
        </div>
      ))}
    </div>
  );
}
