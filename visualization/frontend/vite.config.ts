import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5173,
    proxy: {
      // REST API → backend :8000
      "/api": {
        target: "http://localhost:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      // WebSocket → backend :8000
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
  build: {
    // Target modern browsers only — skips unnecessary transpilation and polyfills.
    target: "esnext",
    // Split vendor code from app code so the browser can cache them separately.
    // Note: Vite 8+ uses rolldown which requires manualChunks as a function.
    rollupOptions: {
      output: {
        manualChunks: (id: string) => {
          if (id.includes("node_modules/svelte")) return "svelte";
        },
      },
    },
  },
});
