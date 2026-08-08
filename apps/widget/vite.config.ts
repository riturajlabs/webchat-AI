import { resolve } from 'node:path';
import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    lib: {
      entry: resolve(__dirname, 'src/index.ts'),
      name: 'WebChatWidget',
      formats: ['es', 'umd', 'iife'],
      fileName: (format) => {
        if (format === 'es') return 'webchat-widget.js';
        if (format === 'umd') return 'webchat-widget.umd.cjs';
        return 'webchat-widget.iife.min.js';
      },
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
