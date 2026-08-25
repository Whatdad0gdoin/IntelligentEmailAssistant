import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api to Flask so the browser sees a single origin.
// That keeps the JWT off cross-origin preflights during development and means
// no API base URL is hardcoded in the client (spec section 1).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://localhost:5000",
        changeOrigin: true,
      },
    },
  },
});
