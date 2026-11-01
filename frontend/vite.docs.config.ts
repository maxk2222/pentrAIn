// Docs-media dev server — same app, but proxies to the dedicated capture
// backend on :8010 instead of the default :8000 dev instance.
// Used by docs/media/capture.py; run from this directory:
//   npx vite --config vite.docs.config.ts
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: { target: "es2022" },
  optimizeDeps: {
    // @novnc/novnc uses top-level await — dev optimizer must allow es2022 too
    esbuildOptions: { target: "es2022" },
  },
  server: {
    port: 5199,
    proxy: {
      "/api": { target: "http://localhost:8010", changeOrigin: true, ws: true },
      "/ws": { target: "ws://localhost:8010", ws: true },
    },
  },
});
