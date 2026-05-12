import type { Edge, Node } from "@xyflow/react";
import type { ConnectionConfigField } from "../../types";
import { Input } from "@/components/ui/input";
import { IamSimSpecFormField } from "./MinioIamManagerModal";
import { S3SimulatedIdentityField } from "./S3SimulatedIdentityField";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export interface ConfigSchemaDiagramContext {
  nodeId: string;
  nodes: Node[];
  edges: Edge[];
}

interface ConfigSchemaFormProps {
  fields: ConnectionConfigField[];
  values: Record<string, any>;
  onChange: (key: string, value: any) => void;
  /** When set, enables diagram-aware fields (e.g. S3 simulated identity from linked MinIO). */
  diagramContext?: ConfigSchemaDiagramContext | null;
}

export default function ConfigSchemaForm({ fields, values, onChange, diagramContext }: ConfigSchemaFormProps) {
  if (fields.length === 0) return null;

  return (
    <div className="space-y-2">
      {fields.map((field) => {
        const value = values[field.key] ?? field.default ?? "";
        return (
          <div key={field.key}>
            <label className="text-xs text-muted-foreground block mb-0.5">
              {field.label}
              {field.required && <span className="text-destructive ml-0.5">*</span>}
            </label>
            {field.description && (
              <p className="text-[10px] text-muted-foreground/70 mb-1">{field.description}</p>
            )}
            {field.type === "boolean" ? (
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={value === true || value === "true"}
                  onChange={(e) => onChange(field.key, e.target.checked)}
                  className="rounded border-border"
                />
                <span className="text-xs text-foreground">{field.label}</span>
              </label>
            ) : field.type === "select" && field.options.length > 0 ? (
              <Select value={String(value)} onValueChange={(v) => onChange(field.key, v)}>
                <SelectTrigger className="w-full h-7 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {field.options.map((opt) => (
                    <SelectItem key={opt} value={opt}>
                      {opt}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : field.type === "number" ? (
              <Input
                type="number"
                value={value}
                onChange={(e) => onChange(field.key, e.target.value)}
                className="h-7 text-xs"
              />
            ) : field.type === "iam_sim_spec" ? (
              <IamSimSpecFormField
                omitHeading
                value={value === undefined || value === null ? "" : String(value)}
                onChange={(v) => onChange(field.key, v)}
              />
            ) : field.type === "s3_simulated_identity" && diagramContext ? (
              <S3SimulatedIdentityField
                omitHeading
                browserNodeId={diagramContext.nodeId}
                nodes={diagramContext.nodes}
                edges={diagramContext.edges}
                value={value === undefined || value === null ? "" : String(value)}
                onChange={(v) => onChange(field.key, v)}
              />
            ) : field.type === "s3_simulated_identity" ? (
              <Input
                type="text"
                value={value}
                onChange={(e) => onChange(field.key, e.target.value)}
                className="h-7 text-xs font-mono"
                placeholder="Access key (connect MinIO with IAM simulation for a picker)"
              />
            ) : field.type === "textarea" ? (
              <textarea
                value={value === undefined || value === null ? "" : String(value)}
                onChange={(e) => onChange(field.key, e.target.value)}
                rows={10}
                spellCheck={false}
                className="w-full min-h-[140px] rounded-md border border-input bg-background px-2 py-1.5 text-xs font-mono leading-snug text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
            ) : (
              <Input
                type="text"
                value={value}
                onChange={(e) => onChange(field.key, e.target.value)}
                className="h-7 text-xs"
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
