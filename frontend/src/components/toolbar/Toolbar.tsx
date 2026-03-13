import { useState } from "react";
import { useDemoStore } from "../../stores/demoStore";
import { createDemo, deployDemo, stopDemo, fetchDemos } from "../../api/client";

export default function Toolbar() {
  const { demos, activeDemoId, activeView, setActiveDemoId, setDemos, setActiveView, updateDemoStatus } = useDemoStore();
  const [creating, setCreating] = useState(false);
  const [newDemoName, setNewDemoName] = useState("");
  const [loading, setLoading] = useState<"deploy" | "stop" | null>(null);

  const activeDemo = demos.find((d) => d.id === activeDemoId);

  const handleCreate = async () => {
    if (!newDemoName.trim()) return;
    const demo = await createDemo(newDemoName.trim());
    const res = await fetchDemos();
    setDemos(res.demos);
    setActiveDemoId(demo.id);
    setCreating(false);
    setNewDemoName("");
  };

  const handleDeploy = async () => {
    if (!activeDemoId) return;
    setLoading("deploy");
    updateDemoStatus(activeDemoId, "deploying");
    try {
      const res = await deployDemo(activeDemoId);
      updateDemoStatus(activeDemoId, res.status as any);
    } catch {
      updateDemoStatus(activeDemoId, "error");
    } finally {
      setLoading(null);
    }
  };

  const handleStop = async () => {
    if (!activeDemoId) return;
    setLoading("stop");
    try {
      await stopDemo(activeDemoId);
      updateDemoStatus(activeDemoId, "stopped");
    } catch {
      // ignore
    } finally {
      setLoading(null);
    }
  };

  const statusColor: Record<string, string> = {
    running: "text-green-400",
    deploying: "text-yellow-400",
    error: "text-red-400",
    stopped: "text-gray-400",
  };

  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-gray-900 border-b border-gray-700 text-white text-sm">
      <span className="font-bold text-blue-400 mr-2">DemoForge</span>

      <select
        value={activeDemoId ?? ""}
        onChange={(e) => setActiveDemoId(e.target.value || null)}
        className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-white"
      >
        <option value="">-- Select Demo --</option>
        {demos.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name}
          </option>
        ))}
      </select>

      {creating ? (
        <div className="flex items-center gap-1">
          <input
            autoFocus
            value={newDemoName}
            onChange={(e) => setNewDemoName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
            placeholder="Demo name"
            className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-white"
          />
          <button onClick={handleCreate} className="px-2 py-1 bg-blue-600 rounded text-xs hover:bg-blue-500">
            Create
          </button>
          <button onClick={() => setCreating(false)} className="px-2 py-1 bg-gray-600 rounded text-xs hover:bg-gray-500">
            Cancel
          </button>
        </div>
      ) : (
        <button
          onClick={() => setCreating(true)}
          className="px-2 py-1 bg-gray-700 rounded text-xs hover:bg-gray-600"
        >
          + New Demo
        </button>
      )}

      {activeDemo && (
        <span className={`text-xs ml-1 ${statusColor[activeDemo.status] ?? "text-gray-400"}`}>
          {activeDemo.status}
        </span>
      )}

      <div className="flex-1" />

      <div className="flex items-center gap-1 bg-gray-700 rounded p-0.5">
        <button
          onClick={() => setActiveView("diagram")}
          className={`px-3 py-1 rounded text-xs transition-colors ${activeView === "diagram" ? "bg-gray-900 text-white" : "text-gray-400 hover:text-white"}`}
        >
          Diagram
        </button>
        <button
          onClick={() => setActiveView("control-plane")}
          className={`px-3 py-1 rounded text-xs transition-colors ${activeView === "control-plane" ? "bg-gray-900 text-white" : "text-gray-400 hover:text-white"}`}
        >
          Control Plane
        </button>
      </div>

      <button
        onClick={handleDeploy}
        disabled={!activeDemoId || loading !== null}
        className="px-3 py-1 bg-green-600 rounded text-xs hover:bg-green-500 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {loading === "deploy" ? "Deploying..." : "Deploy"}
      </button>

      <button
        onClick={handleStop}
        disabled={!activeDemoId || loading !== null}
        className="px-3 py-1 bg-red-700 rounded text-xs hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {loading === "stop" ? "Stopping..." : "Stop"}
      </button>
    </div>
  );
}
