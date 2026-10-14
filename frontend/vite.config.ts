import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:10000',
      '/auth': 'http://127.0.0.1:10000',
      '/ws': {
        target: 'ws://127.0.0.1:10000',
        ws: true,
      },
    },
  },
});
