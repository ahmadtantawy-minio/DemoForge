/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";
import { readFileSync } from "fs";

const port = parseInt(process.env.VITE_PORT || "3000");
const backendUrl = process.env.VITE_BACKEND_URL || "http://localhost:9210";

const uiPackageVersion = (() => {
  try {
    const pkg = JSON.parse(readFileSync(path.resolve(__dirname, "package.json"), "utf-8")) as { version?: string };
    return typeof pkg.version === "string" && pkg.version.trim() ? pkg.version.trim() : "unknown";
  } catch {
    return "unknown";
  }
})();

export default defineConfig({
  define: {
    __DF_UI_PKG_VERSION__: JSON.stringify(uiPackageVersion),
  },
  plugins: [react()],
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "0.0.0.0",
    port: port,
    hmr: {
      clientPort: port,
    },
    proxy: {
      // /proxy/* is served by the API at /proxy/ (not under /api/)
      "/proxy": { target: backendUrl, changeOrigin: true, ws: true },
      "/api": { target: backendUrl, changeOrigin: true, ws: true },
      "/ws": { target: backendUrl.replace(/^http/, "ws"), changeOrigin: true, ws: true },
    },
  },
});
