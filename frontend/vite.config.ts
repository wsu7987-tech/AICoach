import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api/admin": "http://127.0.0.1:8000",
      "/api/v1": "http://127.0.0.1:8000",
      "/api/v2": "http://127.0.0.1:8000",
    },
  },
});
