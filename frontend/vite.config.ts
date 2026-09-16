import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const BACKEND_HTTP = "http://127.0.0.1:8100";
const BACKEND_WS = "ws://127.0.0.1:8100";

// Dev-mode proxy so the app can use relative URLs ("/api", "/video", "/ws")
// in both `vite dev` and the production build served by the backend itself.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: BACKEND_HTTP, changeOrigin: true },
      "/video": { target: BACKEND_HTTP, changeOrigin: true },
      "/frame.jpg": { target: BACKEND_HTTP, changeOrigin: true },
      "/ws": { target: BACKEND_WS, ws: true },
    },
  },
});
