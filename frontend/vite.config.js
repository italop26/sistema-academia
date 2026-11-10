import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  envDir: '..',
  server: {
    port: 5174,
    strictPort: true,
    allowedHosts: ['frontend'],
    proxy: {
      '/api': {
        target: process.env.API_PROXY_TARGET || 'http://localhost:8002',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
});
