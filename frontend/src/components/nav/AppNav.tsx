import { Home, LayoutDashboard, FileText, HardDrive, ShieldCheck, Users, Wifi, Settings, Sun, Moon } from "lucide-react";
import { useState, useEffect } from "react";
import { useDemoStore, type PageKey } from "../../stores/demoStore";

const baseTopItems: { key: PageKey; icon: typeof Home; label: string }[] = [
  { key: "home", icon: Home, label: "Home" },
  { key: "designer", icon: LayoutDashboard, label: "Designer" },
  { key: "templates", icon: FileText, label: "Templates" },
  { key: "images", icon: HardDrive, label: "Images" },
];

const bottomItems: { key: PageKey; icon: typeof Settings; label: string }[] = [
  { key: "connectivity", icon: Wifi, label: "Healthcheck" },
  { key: "settings", icon: Settings, label: "Settings" },
];

export default function AppNav() {
  const currentPage = useDemoStore((s) => s.currentPage);
  const setCurrentPage = useDemoStore((s) => s.setCurrentPage);
  const faMode = useDemoStore((s) => s.faMode);
  const hubLocal = useDemoStore((s) => s.hubLocal);
  const [appVersion, setAppVersion] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/version")
      .then((r) => r.json())
      .then((d) => setAppVersion(d.version ?? null))
      .catch(() => {});
  }, []);

  const modeLabel = faMode !== "dev" ? "FA" : hubLocal ? "D-LOC" : "D-GCP";
  const modeLabelClass = faMode !== "dev"
    ? "text-zinc-400 bg-zinc-800"
    : hubLocal
      ? "text-emerald-400 bg-emerald-400/10"
      : "text-amber-400 bg-amber-400/10";

  const topItems = faMode === "dev"
    ? [
        ...baseTopItems,
        { key: "readiness" as PageKey, icon: ShieldCheck, label: "Readiness" },
        { key: "fa-management" as PageKey, icon: Users, label: "FA Mgmt" },
      ]
    : baseTopItems;

  return (
    <nav className="flex flex-col items-center w-[80px] flex-shrink-0 bg-zinc-950 border-r border-zinc-800 py-2">
      {/* Logo */}
      <div className="w-7 h-7 rounded-md bg-[#C72C48] flex items-center justify-center mb-1">
        <span className="text-white font-bold text-xs">DF</span>
      </div>
      <span className={`text-[8px] font-bold px-1.5 py-0.5 rounded leading-none ${modeLabelClass} ${faMode !== "dev" && appVersion ? "mb-0.5" : "mb-2"}`}>
        {modeLabel}
      </span>
      {faMode !== "dev" && appVersion && (
        <span className="text-[7px] text-zinc-400 leading-none mb-2 px-1 text-center" title={appVersion}>
          {appVersion}
        </span>
      )}

      {/* Top nav items */}
      <div className="flex flex-col items-center gap-1 flex-1">
        {topItems.map(({ key, icon: Icon, label }) => {
          const active = currentPage === key;
          return (
            <button
              key={key}
              data-testid={`nav-item-${key}`}
              onClick={() => setCurrentPage(key)}
              className={`flex flex-col items-center justify-center w-[70px] h-10 rounded-md transition-colors ${
                active
                  ? "bg-zinc-800 border border-zinc-700"
                  : "hover:bg-zinc-800/50 border border-transparent"
              }`}
            >
              <Icon size={18} className={active ? "text-zinc-100" : "text-zinc-400"} />
              <span className={`text-[9px] leading-tight mt-0.5 ${active ? "text-zinc-100" : "text-zinc-400"}`}>
                {label}
              </span>
            </button>
          );
        })}
      </div>

      {/* Theme toggle + Bottom nav items */}
      <div className="flex flex-col items-center gap-1">
        <button
          onClick={() => {
            const html = document.documentElement;
            const isDark = html.classList.contains("dark");
            html.classList.toggle("dark", !isDark);
            localStorage.setItem("demoforge-theme", isDark ? "light" : "dark");
          }}
          className="flex flex-col items-center justify-center w-10 h-10 rounded-md transition-colors hover:bg-zinc-800/50 border border-transparent"
          title="Toggle theme"
        >
          <Sun size={18} className="text-zinc-400 hidden dark:block" />
          <Moon size={18} className="text-zinc-400 block dark:hidden" />
          <span className="text-[9px] leading-tight mt-0.5 text-zinc-400">Theme</span>
        </button>
        {bottomItems.map(({ key, icon: Icon, label }) => {
          const active = currentPage === key;
          return (
            <button
              key={key}
              data-testid={`nav-item-${key}`}
              onClick={() => setCurrentPage(key)}
              className={`flex flex-col items-center justify-center w-[70px] h-10 rounded-md transition-colors ${
                active
                  ? "bg-zinc-800 border border-zinc-700"
                  : "hover:bg-zinc-800/50 border border-transparent"
              }`}
            >
              <Icon size={18} className={active ? "text-zinc-100" : "text-zinc-400"} />
              <span
                className={`text-[9px] leading-tight mt-0.5 ${
                  active ? "text-zinc-100" : "text-zinc-400"
                }`}
              >
                {label}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
