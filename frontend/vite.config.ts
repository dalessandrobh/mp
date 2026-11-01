import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Em produção o Traefik serve o front em / e o backend em /api na MESMA origem.
// Aqui replicamos isso no dev server para o código não precisar saber a diferença.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // API_PROXY_TARGET permite apontar o dev server para um backend em outra porta.
      "/api": { target: process.env.API_PROXY_TARGET ?? "http://localhost:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
