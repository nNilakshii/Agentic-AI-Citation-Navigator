import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * `base` matters for GitHub Pages: a *project* site is served from
 * /<repo>/, so assets built against "/" all 404. Set BASE_PATH at build time
 * (the Pages workflow does) and leave it unset for local dev.
 */
export default defineConfig({
  base: process.env.BASE_PATH ?? "/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // The reader API and the backend health check both live on the backend.
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.js",
    css: false,
  },
});
