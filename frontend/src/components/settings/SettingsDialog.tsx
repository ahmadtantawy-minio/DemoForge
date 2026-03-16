import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Settings, Key, Bot, Palette, Loader2, Eye, EyeOff, Sun, Moon } from "lucide-react";
import { toast } from "sonner";
import {
  fetchLicenseStatus,
  setLicense,
  deleteLicense,
  getLlmConfig,
  setLlmConfig,
} from "../../api/client";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type Tab = "general" | "licenses" | "llm";

// ── General Tab ──────────────────────────────────────────────────────────────

function GeneralTab() {
  const [isDark, setIsDark] = useState(
    document.documentElement.classList.contains("dark")
  );

  const toggleTheme = () => {
    const html = document.documentElement;
    const next = !html.classList.contains("dark");
    html.classList.toggle("dark", next);
    localStorage.setItem("demoforge-theme", next ? "dark" : "light");
    setIsDark(next);
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-semibold text-foreground mb-1">General</h3>
        <p className="text-xs text-muted-foreground">Application preferences</p>
      </div>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-medium text-foreground">Theme</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              Switch between light and dark mode
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="h-8 gap-2"
            onClick={toggleTheme}
          >
            {isDark ? (
              <>
                <Sun className="w-3.5 h-3.5" />
                Light
              </>
            ) : (
              <>
                <Moon className="w-3.5 h-3.5" />
                Dark
              </>
            )}
          </Button>
        </div>
      </div>

      <div className="border-t border-border pt-4">
        <div className="text-xs text-muted-foreground space-y-1">
          <div className="font-medium text-foreground">DemoForge v1.0</div>
          <div>Demo orchestration and deployment platform</div>
        </div>
      </div>
    </div>
  );
}

// ── Licenses Tab ─────────────────────────────────────────────────────────────

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

function LicensesTab() {
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

  useEffect(() => { load(); }, []);

  const handleSave = async () => {
    if (!editing) return;
    if (!editing.value.trim()) { toast.error("License key cannot be empty"); return; }
    setEditing((prev) => prev && { ...prev, saving: true });
    try {
      await setLicense(editing.licenseId, editing.value.trim(), editing.label);
      toast.success(`License "${editing.label}" saved`);
      setEditing(null);
      load();
    } catch {
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
    } catch {
      setEditing((prev) => prev && { ...prev, saving: false });
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-foreground mb-1">License Management</h3>
        <p className="text-xs text-muted-foreground">Configure license keys for enterprise components</p>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      )}

      {error && <div className="text-xs text-destructive px-1">{error}</div>}

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
                  onClick={() =>
                    setEditing({
                      licenseId: entry.license_id,
                      label: entry.label,
                      value: "",
                      showKey: false,
                      saving: false,
                    })
                  }
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
                    {editing.showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                <div className="flex items-center gap-2">
                  <Button size="sm" className="h-7 text-xs px-3" onClick={handleSave} disabled={editing.saving}>
                    {editing.saving ? <Loader2 className="w-3 h-3 animate-spin" /> : "Save"}
                  </Button>
                  <Button size="sm" variant="ghost" className="h-7 text-xs px-3" onClick={() => setEditing(null)} disabled={editing.saving}>
                    Cancel
                  </Button>
                  {entry.configured && (
                    <Button size="sm" variant="destructive" className="h-7 text-xs px-3 ml-auto" onClick={handleRemove} disabled={editing.saving}>
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

// ── LLM Tab ───────────────────────────────────────────────────────────────────

function LlmTab() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [config, setConfig] = useState({
    endpoint: "http://host.docker.internal:11434",
    model: "qwen2.5:14b",
    api_type: "ollama",
  });

  useEffect(() => {
    getLlmConfig()
      .then((res) => setConfig({ endpoint: res.endpoint, model: res.model, api_type: res.api_type }))
      .catch(() => {/* use defaults */})
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await setLlmConfig(config);
      toast.success("LLM configuration saved");
      setTestResult(null);
    } catch (e: any) {
      toast.error("Failed to save LLM config", { description: e.message });
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await fetch(`${config.endpoint}/api/tags`);
      if (res.ok) {
        setTestResult({ ok: true, message: "Connection successful" });
      } else {
        setTestResult({ ok: false, message: `HTTP ${res.status}` });
      }
    } catch (e: any) {
      setTestResult({ ok: false, message: e.message || "Connection failed" });
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-sm font-semibold text-foreground mb-1">AI / LLM Configuration</h3>
        <p className="text-xs text-muted-foreground">Configure the language model used for AI features</p>
      </div>

      <div className="space-y-3">
        <div>
          <label className="text-xs text-muted-foreground block mb-1.5">Endpoint URL</label>
          <Input
            value={config.endpoint}
            onChange={(e) => setConfig({ ...config, endpoint: e.target.value })}
            placeholder="http://host.docker.internal:11434"
            className="h-8 text-sm"
          />
        </div>

        <div>
          <label className="text-xs text-muted-foreground block mb-1.5">Model Name</label>
          <Input
            value={config.model}
            onChange={(e) => setConfig({ ...config, model: e.target.value })}
            placeholder="qwen2.5:14b"
            className="h-8 text-sm"
          />
        </div>

        <div>
          <label className="text-xs text-muted-foreground block mb-1.5">API Type</label>
          <Select
            value={config.api_type}
            onValueChange={(v) => setConfig({ ...config, api_type: v })}
          >
            <SelectTrigger className="h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ollama">Ollama</SelectItem>
              <SelectItem value="openai">OpenAI-compatible</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {testResult && (
        <div
          className={`text-xs px-3 py-2 rounded border ${
            testResult.ok
              ? "bg-green-600/10 text-green-400 border-green-600/30"
              : "bg-red-600/10 text-red-400 border-red-600/30"
          }`}
        >
          {testResult.message}
        </div>
      )}

      <div className="flex items-center gap-2 pt-1">
        <Button size="sm" className="h-8 text-xs px-4" onClick={handleSave} disabled={saving}>
          {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : "Save"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="h-8 text-xs px-4"
          onClick={handleTest}
          disabled={testing}
        >
          {testing ? <Loader2 className="w-3 h-3 animate-spin mr-1.5" /> : null}
          Test Connection
        </Button>
      </div>
    </div>
  );
}

// ── Main Dialog ───────────────────────────────────────────────────────────────

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "general", label: "General", icon: <Palette className="w-4 h-4" /> },
  { id: "licenses", label: "Licenses", icon: <Key className="w-4 h-4" /> },
  { id: "llm", label: "AI / LLM", icon: <Bot className="w-4 h-4" /> },
];

export default function SettingsDialog({ open, onOpenChange }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>("general");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl p-0 gap-0 overflow-hidden">
        <DialogHeader className="px-5 py-4 border-b border-border">
          <DialogTitle className="text-base flex items-center gap-2">
            <Settings className="w-4 h-4" />
            Settings
          </DialogTitle>
        </DialogHeader>

        <div className="flex min-h-[420px]">
          {/* Left nav */}
          <div className="w-40 shrink-0 border-r border-border bg-muted/30 py-2">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`w-full flex items-center gap-2.5 px-4 py-2.5 text-xs font-medium transition-colors text-left ${
                  activeTab === tab.id
                    ? "bg-background text-foreground border-r-2 border-primary"
                    : "text-muted-foreground hover:text-foreground hover:bg-background/50"
                }`}
              >
                {tab.icon}
                {tab.label}
              </button>
            ))}
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0 p-5 overflow-y-auto max-h-[500px]">
            {activeTab === "general" && <GeneralTab />}
            {activeTab === "licenses" && <LicensesTab />}
            {activeTab === "llm" && <LlmTab />}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
