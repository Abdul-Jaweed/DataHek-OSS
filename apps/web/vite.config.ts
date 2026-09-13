import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const apiTarget = process.env.API_PROXY_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/auth': apiTarget,
      '/settings': apiTarget,
      '/health': apiTarget,
      '/ask': apiTarget,
      '/connections': apiTarget,
      '/conversations': apiTarget,
      '/prompts': apiTarget,
      '/evaluations': apiTarget,
      '/approvals': apiTarget,
    },
  },
  build: { outDir: 'dist' },
});