import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const backendUrl = env.BACKEND_URL || env.VITE_API_URL || 'http://127.0.0.1:7860';
  const port = Number(env.PORT) || 3000;

  return {
    root: '.',
    server: {
      port,
      open: false,
      proxy: {
        '/api': {
          target: backendUrl,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
    },
  };
});
