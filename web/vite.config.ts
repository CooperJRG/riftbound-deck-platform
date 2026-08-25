import { defineConfig } from "vite";

// The dev server proxies /api to the Python app, so the browser sees one origin and
// no CORS is involved in the normal development loop.
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8020",
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
