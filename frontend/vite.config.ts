import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Em produção o Traefik serve o front em / e o backend em /api na MESMA origem.
// Aqui replicamos isso no dev server para o código não precisar saber a diferença.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
