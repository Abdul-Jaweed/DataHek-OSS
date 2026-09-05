import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/auth': 'http://localhost:8000',
      '/settings': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/ask': 'http://localhost:8000',
      '/connections': 'http://localhost:8000',
      '/conversations': 'http://localhost:8000',
      '/prompts': 'http://localhost:8000',
      '/evaluations': 'http://localhost:8000',
    },
  },
  build: { outDir: 'dist' },
});