import { resolve } from 'node:path';
import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    lib: {
      entry: resolve(__dirname, 'src/index.ts'),
      name: 'WebChatWidget',
      formats: ['es', 'umd'],
      fileName: (format) => (format === 'es' ? 'webchat-widget.js' : 'webchat-widget.umd.cjs'),
    },
    target: 'es2019',
    minify: 'esbuild',
    sourcemap: true,
    rollupOptions: {
      output: {
        // Global target for UMD consumers: window.WebChatWidget
        exports: 'named',
      },
    },
  },
});
