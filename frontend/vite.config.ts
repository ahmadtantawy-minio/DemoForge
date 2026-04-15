import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

const port = parseInt(process.env.VITE_PORT || "3000");
const backendUrl = process.env.VITE_BACKEND_URL || "http://localhost:9210";

export default defineConfig({
  plugins: [react()],
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
      "/api": { target: backendUrl, changeOrigin: true },
      "/ws": { target: backendUrl.replace(/^http/, "ws"), changeOrigin: true, ws: true },
    },
  },
});
