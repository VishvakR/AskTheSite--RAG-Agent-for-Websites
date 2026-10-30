import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const API_TARGET = process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000";

// Proxying in dev keeps the client's API_BASE empty, so requests are
// same-origin and no CORS round-trip is needed while developing.
const API_ROUTES = [
  "/health",
  "/models",
  "/workspaces",
  "/jobs",
  "/docs",
  "/openapi.json",
];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: Object.fromEntries(
      API_ROUTES.map((route) => [
        route,
        { target: API_TARGET, changeOrigin: true },
      ]),
    ),
  },
});
