import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import {
  defaultPolicyDocumentText,
  emptyIamSimSpec,
  generateIamSimAccessSecretPair,
  serializeIamSimSpec,
  summarizeIamSimSpec,
  tryParseIamSimSpec,
  type IamSimSpec,
} from "./minioIamSimSpec";

function newRowId(): string {
  return `r-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

interface RoleRow {
  id: string;
  name: string;
  documentText: string;
}

interface UserRow {
  id: string;
  accessKey: string;
  secretKey: string;
  label: string;
  policyNames: string[];
}

function specToRows(spec: IamSimSpec | null): { roles: RoleRow[]; users: UserRow[] } {
  if (!spec) return { roles: [], users: [] };
  const roles: RoleRow[] = spec.policies.map((p) => ({
    id: newRowId(),
    name: p.name,
    documentText: JSON.stringify(p.document, null, 2),
  }));
  const users: UserRow[] = spec.users.map((u) => ({
    id: newRowId(),
    accessKey: u.access_key,
    secretKey: u.secret_key,
    label: u.label ?? "",
    policyNames: [...u.policies],
  }));
  return { roles, users };
}

function rowsToSpec(roles: RoleRow[], users: UserRow[]): IamSimSpec {
  const policies = roles
    .filter((r) => r.name.trim())
    .map((r) => {
      let document: Record<string, unknown> = {};
      try {
        const parsed = JSON.parse(r.documentText || "{}");
        document = parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : {};
      } catch {
        document = {};
      }
      return { name: r.name.trim(), document };
    });
  const validNames = new Set(policies.map((p) => p.name));
  const usersOut = users
    .filter((u) => u.accessKey.trim() && u.secretKey.trim())
    .map((u) => ({
      access_key: u.accessKey.trim(),
      secret_key: u.secretKey.trim(),
      label: u.label.trim() || undefined,
      policies: u.policyNames.filter((n) => validNames.has(n)),
    }));
  return { policies, users: usersOut };
}

export interface MinioIamManagerModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialJson: string;
  onSave: (json: string) => void;
  title?: string;
}

export function MinioIamManagerModal({
  open,
  onOpenChange,
  initialJson,
  onSave,
  title = "IAM Manager",
}: MinioIamManagerModalProps) {
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [selectedRoleId, setSelectedRoleId] = useState<string | null>(null);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [jsonError, setJsonError] = useState<string | null>(null);

  const roleNames = useMemo(() => roles.map((r) => r.name.trim()).filter(Boolean), [roles]);
  const selectedRole = useMemo(() => roles.find((r) => r.id === selectedRoleId) ?? null, [roles, selectedRoleId]);
  const selectedUser = useMemo(() => users.find((u) => u.id === selectedUserId) ?? null, [users, selectedUserId]);

  useEffect(() => {
    if (!open) return;
    const parsed = tryParseIamSimSpec(initialJson);
    const { roles: r, users: u } = specToRows(parsed ?? emptyIamSimSpec());
    setRoles(r);
    setUsers(u);
    setSelectedRoleId(r[0]?.id ?? null);
    setSelectedUserId(u[0]?.id ?? null);
    setJsonError(parsed === null && (initialJson ?? "").trim() ? "Previous value was invalid JSON — started empty." : null);
  }, [open, initialJson]);

  useEffect(() => {
    setSelectedRoleId((sel) => (sel && roles.some((r) => r.id === sel) ? sel : roles[0]?.id ?? null));
  }, [roles]);

  useEffect(() => {
    setSelectedUserId((sel) => (sel && users.some((u) => u.id === sel) ? sel : users[0]?.id ?? null));
  }, [users]);

  const addRole = () => {
    const id = newRowId();
    setRoles((prev) => [...prev, { id, name: `role-${prev.length + 1}`, documentText: defaultPolicyDocumentText() }]);
    setSelectedRoleId(id);
  };

  const removeRole = (id: string) => {
    const victim = roles.find((r) => r.id === id);
    const removedName = victim?.name.trim() ?? "";
    setRoles((prev) => prev.filter((r) => r.id !== id));
    if (removedName) {
      setUsers((prev) =>
        prev.map((u) => ({
          ...u,
          policyNames: u.policyNames.filter((n) => n !== removedName),
        })),
      );
    }
  };

  const addUser = () => {
    const id = newRowId();
    setUsers((prev) => [...prev, { id, accessKey: "", secretKey: "", label: "", policyNames: [] }]);
    setSelectedUserId(id);
  };

  const removeUser = (id: string) => {
    setUsers((prev) => prev.filter((u) => u.id !== id));
  };

  const handleSave = () => {
    const spec = rowsToSpec(roles, users);
    const names = spec.policies.map((p) => p.name);
    const dup = names.find((n, i) => names.indexOf(n) !== i);
    if (dup) {
      setJsonError(`Duplicate role name: ${dup}`);
      return;
    }
    setJsonError(null);
    onSave(serializeIamSimSpec(spec, true));
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[min(92vh,780px)] max-h-[92vh] w-[min(100vw-1.5rem,920px)] max-w-[920px] flex-col gap-0 overflow-hidden p-0 sm:max-w-[920px]">
        <DialogHeader className="shrink-0 border-b border-border px-4 pb-3 pt-4">
          <DialogTitle className="text-base">{title}</DialogTitle>
          <p className="pt-1 text-[11px] font-normal text-muted-foreground">
            Use <strong className="font-medium text-foreground">Roles</strong> and <strong className="font-medium text-foreground">Users</strong>{" "}
            tabs. Pick an item in the list to edit it — long JSON scrolls inside the editor only. This updates{" "}
            <span className="font-mono text-foreground/90">MINIO_IAM_SIM_SPEC</span>.
          </p>
        </DialogHeader>

        {jsonError && (
          <div className="shrink-0 border-b border-border px-4 py-2">
            <div className="rounded-md border border-amber-500/25 bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-600 dark:text-amber-400">
              {jsonError}
            </div>
          </div>
        )}

        <Tabs defaultValue="roles" className="flex min-h-0 flex-1 flex-col px-4 pb-2 pt-2">
          <TabsList className="h-8 w-fit shrink-0 gap-1 p-0.5">
            <TabsTrigger value="roles" className="h-7 px-3 text-xs">
              Roles ({roles.length})
            </TabsTrigger>
            <TabsTrigger value="users" className="h-7 px-3 text-xs">
              Users ({users.length})
            </TabsTrigger>
          </TabsList>

          <TabsContent
            value="roles"
            className="mt-2 flex min-h-0 flex-1 flex-col overflow-hidden outline-none data-[state=inactive]:hidden"
          >
            <div className="flex min-h-0 flex-1 gap-3 overflow-hidden">
              <div className="flex w-[11.5rem] shrink-0 flex-col gap-2 rounded-md border border-border bg-muted/25 p-2">
                <Button type="button" variant="secondary" size="sm" className="h-7 shrink-0 text-xs" onClick={addRole}>
                  Add role
                </Button>
                <div className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-0.5">
                  {roles.length === 0 ? (
                    <p className="px-1 text-[10px] leading-snug text-muted-foreground">No roles yet.</p>
                  ) : (
                    roles.map((r) => (
                      <button
                        key={r.id}
                        type="button"
                        onClick={() => setSelectedRoleId(r.id)}
                        className={cn(
                          "flex w-full items-center justify-between gap-1 rounded border px-2 py-1.5 text-left text-[11px] transition-colors",
                          selectedRoleId === r.id
                            ? "border-primary/50 bg-primary/10 text-foreground"
                            : "border-transparent bg-background/80 text-muted-foreground hover:bg-muted",
                        )}
                      >
                        <span className="min-w-0 truncate font-mono">{r.name.trim() || "—"}</span>
                      </button>
                    ))
                  )}
                </div>
              </div>

              <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2 overflow-hidden">
                {!selectedRole ? (
                  <p className="text-[11px] text-muted-foreground">Add a role, then select it to edit the policy JSON.</p>
                ) : (
                  <>
                    <div className="flex shrink-0 flex-wrap items-end gap-2">
                      <div className="min-w-0 flex-1 space-y-1">
                        <label className="text-[10px] font-medium uppercase text-muted-foreground">Role name</label>
                        <Input
                          value={selectedRole.name}
                          onChange={(e) =>
                            setRoles((prev) =>
                              prev.map((x) => (x.id === selectedRole.id ? { ...x, name: e.target.value } : x)),
                            )
                          }
                          className="h-8 font-mono text-xs"
                          placeholder="e.g. read-demo-bucket"
                        />
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-8 shrink-0 text-xs text-destructive hover:text-destructive"
                        onClick={() => removeRole(selectedRole.id)}
                      >
                        Remove
                      </Button>
                    </div>
                    <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden">
                      <label className="shrink-0 text-[10px] font-medium uppercase text-muted-foreground">
                        Policy document (JSON)
                      </label>
                      <textarea
                        value={selectedRole.documentText}
                        onChange={(e) =>
                          setRoles((prev) =>
                            prev.map((x) => (x.id === selectedRole.id ? { ...x, documentText: e.target.value } : x)),
                          )
                        }
                        spellCheck={false}
                        className="min-h-0 flex-1 resize-none overflow-auto rounded-md border border-input bg-background px-2 py-1.5 font-mono text-[11px] leading-snug"
                      />
                    </div>
                  </>
                )}
              </div>
            </div>
          </TabsContent>

          <TabsContent
            value="users"
            className="mt-2 flex min-h-0 flex-1 flex-col overflow-hidden outline-none data-[state=inactive]:hidden"
          >
            <div className="flex min-h-0 flex-1 gap-3 overflow-hidden">
              <div className="flex w-[11.5rem] shrink-0 flex-col gap-2 rounded-md border border-border bg-muted/25 p-2">
                <Button type="button" variant="secondary" size="sm" className="h-7 shrink-0 text-xs" onClick={addUser}>
                  Add user
                </Button>
                <div className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-0.5">
                  {users.length === 0 ? (
                    <p className="px-1 text-[10px] leading-snug text-muted-foreground">No users yet.</p>
                  ) : (
                    users.map((u) => (
                      <button
                        key={u.id}
                        type="button"
                        onClick={() => setSelectedUserId(u.id)}
                        className={cn(
                          "flex w-full flex-col gap-0.5 rounded border px-2 py-1.5 text-left text-[11px] transition-colors",
                          selectedUserId === u.id
                            ? "border-primary/50 bg-primary/10 text-foreground"
                            : "border-transparent bg-background/80 text-muted-foreground hover:bg-muted",
                        )}
                      >
                        <span className="truncate font-mono">{u.accessKey.trim() || "(new user)"}</span>
                        {u.label.trim() ? (
                          <span className="truncate text-[10px] text-muted-foreground">{u.label.trim()}</span>
                        ) : null}
                      </button>
                    ))
                  )}
                </div>
              </div>

              <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2 overflow-y-auto">
                {!selectedUser ? (
                  <p className="text-[11px] text-muted-foreground">Add a user, then select them to set keys and roles.</p>
                ) : (
                  <>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[10px] font-medium uppercase text-muted-foreground">User</span>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs text-destructive hover:text-destructive"
                        onClick={() => removeUser(selectedUser.id)}
                      >
                        Remove
                      </Button>
                    </div>
                    <div className="grid shrink-0 grid-cols-1 gap-2 sm:grid-cols-2">
                      <div className="space-y-1">
                        <label className="text-[10px] text-muted-foreground">Access key</label>
                        <Input
                          value={selectedUser.accessKey}
                          onChange={(e) =>
                            setUsers((prev) =>
                              prev.map((x) => (x.id === selectedUser.id ? { ...x, accessKey: e.target.value } : x)),
                            )
                          }
                          className="h-8 font-mono text-xs"
                          autoComplete="off"
                        />
                      </div>
                      <div className="space-y-1">
                        <label className="text-[10px] text-muted-foreground">Secret key</label>
                        <Input
                          type="password"
                          value={selectedUser.secretKey}
                          onChange={(e) =>
                            setUsers((prev) =>
                              prev.map((x) => (x.id === selectedUser.id ? { ...x, secretKey: e.target.value } : x)),
                            )
                          }
                          className="h-8 font-mono text-xs"
                          autoComplete="new-password"
                        />
                      </div>
                      <div className="sm:col-span-2">
                        <Button
                          type="button"
                          variant="secondary"
                          size="sm"
                          className="h-7 text-xs"
                          onClick={() => {
                            const { access_key, secret_key } = generateIamSimAccessSecretPair();
                            setUsers((prev) =>
                              prev.map((x) =>
                                x.id === selectedUser.id ? { ...x, accessKey: access_key, secretKey: secret_key } : x,
                              ),
                            );
                          }}
                        >
                          Generate new access & secret key
                        </Button>
                        <p className="mt-1 text-[10px] text-muted-foreground">
                          Overwrites the fields above. Save to diagram and redeploy (or apply topology) for MinIO to pick up new keys.
                        </p>
                      </div>
                      <div className="space-y-1 sm:col-span-2">
                        <label className="text-[10px] text-muted-foreground">Label (optional)</label>
                        <Input
                          value={selectedUser.label}
                          onChange={(e) =>
                            setUsers((prev) =>
                              prev.map((x) => (x.id === selectedUser.id ? { ...x, label: e.target.value } : x)),
                            )
                          }
                          className="h-8 text-xs"
                          placeholder="S3 browser identity list"
                        />
                      </div>
                    </div>
                    <div className="min-h-0 shrink-0 space-y-1.5 border-t border-border pt-2">
                      <span className="text-[10px] font-medium uppercase text-muted-foreground">Assigned roles</span>
                      {roleNames.length === 0 ? (
                        <p className="text-[10px] text-muted-foreground">Define roles on the Roles tab first.</p>
                      ) : (
                        <div className="flex max-h-[min(200px,28vh)] flex-wrap gap-x-4 gap-y-2 overflow-y-auto">
                          {roleNames.map((name) => (
                            <label key={`${selectedUser.id}-${name}`} className="inline-flex cursor-pointer items-center gap-2 text-xs">
                              <input
                                type="checkbox"
                                className="rounded border-border accent-primary"
                                checked={selectedUser.policyNames.includes(name)}
                                onChange={(e) => {
                                  const on = e.target.checked;
                                  setUsers((prev) =>
                                    prev.map((row) => {
                                      if (row.id !== selectedUser.id) return row;
                                      const set = new Set(row.policyNames);
                                      if (on) set.add(name);
                                      else set.delete(name);
                                      return { ...row, policyNames: [...set] };
                                    }),
                                  );
                                }}
                              />
                              <span className="font-mono text-[11px]">{name}</span>
                            </label>
                          ))}
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>
            </div>
          </TabsContent>
        </Tabs>

        <DialogFooter className="shrink-0 gap-2 border-t border-border px-4 py-3 sm:gap-2">
          <Button type="button" variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" size="sm" onClick={handleSave}>
            Save to diagram
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export interface IamSimSpecFormFieldProps {
  value: string;
  onChange: (json: string) => void;
  disabled?: boolean;
  /** When true, do not render label/description (parent already shows schema label/help). */
  omitHeading?: boolean;
  label?: string;
  description?: string;
}

export function IamSimSpecFormField({
  value,
  onChange,
  disabled,
  omitHeading,
  label = "IAM simulation",
  description,
}: IamSimSpecFormFieldProps) {
  const [open, setOpen] = useState(false);
  const summary = summarizeIamSimSpec(value);

  return (
    <div>
      {!omitHeading && (
        <>
          <label className="mb-0.5 block text-xs text-muted-foreground">{label}</label>
          {description ? <p className="mb-1 text-[10px] text-muted-foreground/70">{description}</p> : null}
        </>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs tabular-nums text-foreground">{summary}</span>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          className="h-7 text-xs"
          disabled={disabled}
          onClick={() => setOpen(true)}
        >
          Open IAM Manager…
        </Button>
        {!disabled && (value ?? "").trim() ? (
          <Button type="button" variant="ghost" size="sm" className="h-7 text-xs text-muted-foreground" onClick={() => onChange("")}>
            Clear
          </Button>
        ) : null}
      </div>
      <MinioIamManagerModal open={open} onOpenChange={setOpen} initialJson={value} onSave={onChange} />
    </div>
  );
}
