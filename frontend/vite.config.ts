import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const BACKEND_PORT = process.env.KB_BACKEND_PORT || "8765";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Must match the port in scripts/dev.ts and the README (8765).
      // The previous value (8000) was the FastAPI default and was a
      // straight typo vs. the dev orchestration.
      "/api": `http://127.0.0.1:${BACKEND_PORT}`
    }
  }
});
