import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

/**
 * The console's build.
 *
 * The dev proxy is the load-bearing part. The browser only ever talks to this
 * origin, and `/api` is forwarded to the analytics API — so the front end has no
 * knowledge of where the warehouse lives, no credential of its own, and nothing
 * to leak. In a deployment the same path is served by an ingress rule; the
 * application code does not change between the two.
 */
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // One root configuration drives Python, Docker and the browser bundle. Only
  // VITE_* values are exposed to client code; SMTP credentials stay server-side.
  envDir: "..",
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "./src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.TRANSFEROPS_API ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
      "/assistant": {
        target: process.env.TRANSFEROPS_AGENT ?? "http://127.0.0.1:8100",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/assistant/, ""),
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    rollupOptions: {
      output: {
        // Split the two large, rarely-changing vendors out of the app chunk, so
        // a deploy that only touches a screen does not invalidate a megabyte of
        // charting library in everyone's browser cache.
        manualChunks: {
          auth: ["keycloak-js"],
          charts: ["recharts"],
          router: ["@tanstack/react-router", "@tanstack/react-query"],
        },
      },
    },
  },
});
