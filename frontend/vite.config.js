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
  // Component tests need somewhere to mount. jsdom is deliberately bare: it
  // ships no speechSynthesis and no SpeechRecognition, which makes it exactly
  // the unsupported browser SR-01 is written for -- so the degraded path is
  // the default a test gets, and the supported one is the case that has to be
  // set up. The pure-logic and stylesheet tests are unaffected by running in
  // a DOM; `globals` stays off so every test keeps importing from vitest.
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
  },
});
