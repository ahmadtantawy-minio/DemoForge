import { useEffect, useState } from "react";
import { fetchLicenseStatus, setLicense, deleteLicense } from "../../api/client";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Eye, EyeOff, Loader2 } from "lucide-react";

interface LicenseEntry {
  license_id: string;
  label: string;
  description: string;
  component_id: string;
  component_name: string;
  required: boolean;
  configured: boolean;
}

interface EditState {
  licenseId: string;
  label: string;
  value: string;
  showKey: boolean;
  saving: boolean;
}

export default function LicenseSettings() {
  const [licenses, setLicenses] = useState<LicenseEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<EditState | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchLicenseStatus()
      .then((res) => setLicenses(res))
      .catch((e) => {
        if (e.message?.includes("404") || e.message?.includes("API error 404")) {
          setLicenses([]);
        } else {
          setError("Could not load license status.");
        }
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const startEdit = (entry: LicenseEntry) => {
    setEditing({
      licenseId: entry.license_id,
      label: entry.label,
      value: "",
      showKey: false,
      saving: false,
    });
  };

  const cancelEdit = () => setEditing(null);

  const handleSave = async () => {
    if (!editing) return;
    if (!editing.value.trim()) {
      toast.error("License key cannot be empty");
      return;
    }
    setEditing((prev) => prev && { ...prev, saving: true });
    try {
      await setLicense(editing.licenseId, editing.value.trim(), editing.label);
      toast.success(`License "${editing.label}" saved`);
      setEditing(null);
      load();
    } catch (e: any) {
      setEditing((prev) => prev && { ...prev, saving: false });
    }
  };

  const handleRemove = async () => {
    if (!editing) return;
    setEditing((prev) => prev && { ...prev, saving: true });
    try {
      await deleteLicense(editing.licenseId);
      toast.success(`License "${editing.label}" removed`);
      setEditing(null);
      load();
    } catch (e: any) {
      setEditing((prev) => prev && { ...prev, saving: false });
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-foreground">License Management</h2>
        <p className="text-xs text-muted-foreground mt-0.5">
          Configure license keys for enterprise components
        </p>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      )}

      {error && (
        <div className="text-xs text-destructive px-1">{error}</div>
      )}

      {!loading && !error && licenses.length === 0 && (
        <div className="text-xs text-muted-foreground text-center py-6">
          No license requirements found
        </div>
      )}

      {!loading && !error && licenses.map((entry) => (
        <Card key={entry.license_id} className="bg-card border border-border">
          <CardContent className="p-4 space-y-3">
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-foreground">{entry.label}</span>
                  {entry.configured ? (
                    <Badge className="bg-green-600/20 text-green-400 border-green-600/30 hover:bg-green-600/20">
                      Configured
                    </Badge>
                  ) : (
                    <Badge className="bg-red-600/20 text-red-400 border-red-600/30 hover:bg-red-600/20">
                      Missing
                    </Badge>
                  )}
                </div>
                {entry.description && (
                  <p className="text-xs text-muted-foreground mt-0.5">{entry.description}</p>
                )}
                {entry.component_name && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Required by: {entry.component_name}
                  </p>
                )}
              </div>
              {editing?.licenseId !== entry.license_id && (
                <Button
                  size="sm"
                  variant="secondary"
                  className="h-7 text-xs px-3 shrink-0"
                  onClick={() => startEdit(entry)}
                >
                  {entry.configured ? "Edit" : "Configure"}
                </Button>
              )}
            </div>

            {editing?.licenseId === entry.license_id && (
              <div className="space-y-2 pt-1 border-t border-border">
                <div className="text-xs text-muted-foreground font-medium">{editing.label}</div>
                <div className="relative">
                  <Input
                    type={editing.showKey ? "text" : "password"}
                    placeholder="Enter license key"
                    value={editing.value}
                    onChange={(e) =>
                      setEditing((prev) => prev && { ...prev, value: e.target.value })
                    }
                    className="pr-9 h-8 text-sm"
                    disabled={editing.saving}
                  />
                  <button
                    type="button"
                    onClick={() =>
                      setEditing((prev) => prev && { ...prev, showKey: !prev.showKey })
                    }
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    tabIndex={-1}
                  >
                    {editing.showKey ? (
                      <EyeOff className="w-4 h-4" />
                    ) : (
                      <Eye className="w-4 h-4" />
                    )}
                  </button>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    className="h-7 text-xs px-3"
                    onClick={handleSave}
                    disabled={editing.saving}
                  >
                    {editing.saving ? <Loader2 className="w-3 h-3 animate-spin" /> : "Save"}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 text-xs px-3"
                    onClick={cancelEdit}
                    disabled={editing.saving}
                  >
                    Cancel
                  </Button>
                  {entry.configured && (
                    <Button
                      size="sm"
                      variant="destructive"
                      className="h-7 text-xs px-3 ml-auto"
                      onClick={handleRemove}
                      disabled={editing.saving}
                    >
                      Remove
                    </Button>
                  )}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
