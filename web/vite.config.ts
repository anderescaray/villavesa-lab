/// <reference types="vitest/config" />
import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv, type PluginOption } from 'vite';
import { mockApi } from './mocks/mock-api';

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ''), ...process.env };
  const useMock = env.VITE_MOCK_API === '1';
  const apiTarget = env.VITE_API_PROXY ?? 'http://localhost:8000';
  const plugins: PluginOption[] = [react()];
  if (useMock) plugins.push(mockApi());
  const proxy = useMock ? undefined : { '/api': { target: apiTarget, changeOrigin: true } };

  return {
    plugins,
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    server: { port: 3000, strictPort: true, host: true, proxy },
    preview: { port: 3000, strictPort: true, host: true, proxy },
    build: {
      target: 'es2022',
      sourcemap: true,
      chunkSizeWarningLimit: 1200,
      rollupOptions: {
        output: {
          manualChunks: {
            maplibre: ['maplibre-gl'],
            deck: ['@deck.gl/core', '@deck.gl/layers', '@deck.gl/mapbox'],
          },
        },
      },
    },
    test: {
      environment: 'node',
      include: ['src/**/*.test.ts'],
    },
  };
});
