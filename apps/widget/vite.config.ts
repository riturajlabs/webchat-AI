import { resolve } from 'node:path';
import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    lib: {
      entry: resolve(__dirname, 'src/index.ts'),
      name: 'WebChatWidget',
      formats: ['es', 'umd', 'iife'],
      fileName: (format) => {
        // Content-hashed names: `webchat-widget.iife.min.<hash>.js` etc. so a
        // CDN can cache them immutable for a year (a content-addressed bundle
        // is never stale). `scripts/copy-stable.mjs` also emits stable-name
        // copies for package entry points, dev/e2e and the check scripts.
        if (format === 'es') return 'webchat-widget.[hash].js';
        if (format === 'umd') return 'webchat-widget.umd.[hash].cjs';
        return 'webchat-widget.iife.min.[hash].js';
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
