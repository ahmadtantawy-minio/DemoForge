import type { ConnectionConfigField } from "../../types";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface ConfigSchemaFormProps {
  fields: ConnectionConfigField[];
  values: Record<string, any>;
  onChange: (key: string, value: any) => void;
}

export default function ConfigSchemaForm({ fields, values, onChange }: ConfigSchemaFormProps) {
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
