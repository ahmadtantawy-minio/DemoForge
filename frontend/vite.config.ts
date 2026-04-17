/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

const port = parseInt(process.env.VITE_PORT || "3000");
const backendUrl = process.env.VITE_BACKEND_URL || "http://localhost:9210";

export default defineConfig({
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
