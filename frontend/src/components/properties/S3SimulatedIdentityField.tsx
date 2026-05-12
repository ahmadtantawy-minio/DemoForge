import { useMemo } from "react";
import type { Edge, Node } from "@xyflow/react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  getS3FileBrowserPeerIamSpecRaw,
  getS3SimulatedIdentityOptions,
  peerHasIamSimulation,
  S3_SIMULATED_IDENTITY_FIRST,
} from "./s3FileBrowserPeerIam";

/** Internal select values (never collide with IAM access keys). */
const SEL_ROOT = "__df_sel_root__";
const SEL_FIRST = "__df_sel_first__";
const SEL_CUSTOM = "__df_sel_custom__";

export interface S3SimulatedIdentityFieldProps {
  browserNodeId: string;
  nodes: Node[];
  edges: Edge[];
  value: string;
  onChange: (accessKeyOrEmpty: string) => void;
  label?: string;
  description?: string;
  /** When true, do not render label/description (parent schema form already shows them). */
  omitHeading?: boolean;
  disabled?: boolean;
}

export function S3SimulatedIdentityField({
  browserNodeId,
  nodes,
  edges,
  value,
  onChange,
  label = "Simulated IAM user",
  description,
  omitHeading = false,
  disabled,
}: S3SimulatedIdentityFieldProps) {
  const specRaw = useMemo(() => getS3FileBrowserPeerIamSpecRaw(browserNodeId, nodes, edges), [browserNodeId, nodes, edges]);
  const baseOptions = useMemo(() => getS3SimulatedIdentityOptions(specRaw), [specRaw]);
  const hasSim = peerHasIamSimulation(specRaw);
  const rootLabel = baseOptions.find((o) => o.value === "")?.label ?? "Root (MinIO administrator)";
  const firstOption = baseOptions.find((o) => o.value === S3_SIMULATED_IDENTITY_FIRST);
  const userAkOptions = useMemo(
    () => baseOptions.filter((o) => o.value && o.value !== S3_SIMULATED_IDENTITY_FIRST),
    [baseOptions],
  );
  const useSelect = hasSim && userAkOptions.length > 0;

  const current = (value ?? "").trim();
  const matchesUserAk = userAkOptions.some((u) => u.value === current);
  const selectModel = useMemo(() => {
    if (!useSelect) return SEL_ROOT;
    if (current === S3_SIMULATED_IDENTITY_FIRST) return SEL_FIRST;
    if (current === "" || current === "__root__") return SEL_ROOT;
    if (matchesUserAk) return current;
    return SEL_CUSTOM;
  }, [useSelect, current, matchesUserAk, userAkOptions]);

  return (
    <div className="space-y-1.5">
      {!omitHeading ? (
        <>
          <label className="text-xs text-muted-foreground block">{label}</label>
          {description ? <p className="text-[10px] text-muted-foreground/70 mb-1">{description}</p> : null}
        </>
      ) : null}

      {!hasSim ? (
        <p className="text-[10px] text-muted-foreground border border-dashed border-border rounded-md px-2 py-2">
          Connect this browser to MinIO (S3 or load-balanced edge). When that MinIO defines{" "}
          <span className="font-mono">IAM simulation</span>, you can pick a simulated user here; deploy injects that user&apos;s
          credentials into the browser automatically.
        </p>
      ) : null}

      {useSelect && !disabled ? (
        <div className="space-y-2">
          <Select
            value={selectModel}
            onValueChange={(v) => {
              if (v === SEL_ROOT) onChange("");
              else if (v === SEL_FIRST) onChange(S3_SIMULATED_IDENTITY_FIRST);
              else if (v === SEL_CUSTOM) {
                if (matchesUserAk) onChange("");
              } else onChange(v);
            }}
          >
            <SelectTrigger className="w-full h-8 text-xs">
              <SelectValue placeholder="Choose user" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={SEL_ROOT}>{rootLabel}</SelectItem>
              {firstOption ? (
                <SelectItem value={SEL_FIRST}>{firstOption.label}</SelectItem>
              ) : null}
              {userAkOptions.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
              <SelectItem value={SEL_CUSTOM}>Custom access key…</SelectItem>
            </SelectContent>
          </Select>
          {selectModel === SEL_CUSTOM ? (
            <div className="space-y-1">
              <label className="text-[10px] text-muted-foreground">Access key (must match a user in IAM simulation)</label>
              <Input
                className="h-8 text-xs font-mono"
                value={current}
                onChange={(e) => onChange(e.target.value)}
                placeholder="accessKey"
                autoComplete="off"
              />
            </div>
          ) : null}
        </div>
      ) : (
        <Input
          className="h-8 text-xs font-mono"
          disabled={disabled}
          value={current}
          onChange={(e) => onChange(e.target.value)}
          placeholder={
            hasSim
              ? "Leave empty for root, __first__ for first IAM user, or enter an access key"
              : "Optional — simulated user access key"
          }
          autoComplete="off"
        />
      )}

      {hasSim && useSelect ? (
        <p className="text-[10px] text-muted-foreground">
          Unset / empty = <strong className="font-medium text-foreground">Root</strong> (default, backward compatible).{" "}
          <span className="font-mono">__first__</span> = first simulated user. On deploy, DemoForge sets{" "}
          <span className="font-mono">S3_ACCESS_KEY</span> / <span className="font-mono">S3_SECRET_KEY</span> and the identity map.
        </p>
      ) : null}
    </div>
  );
}
