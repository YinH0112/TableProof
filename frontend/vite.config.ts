import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { cpSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

// PDF processing assets remain local, including the worker, CMaps and fonts.
function pdfAssets() {
  return {
    name: 'local-pdf-assets',
    buildStart() {
      const target = resolve('public/pdf-assets');
      mkdirSync(target, { recursive: true });
      cpSync(resolve('node_modules/pdfjs-dist/LICENSE'), resolve(target, 'LICENSE'));
      for (const folder of ['cmaps', 'standard_fonts', 'wasm']) {
        cpSync(resolve(`node_modules/pdfjs-dist/${folder}`), resolve(target, folder), { recursive: true });
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), pdfAssets()],
  server: { proxy: { '/api': 'http://127.0.0.1:8765' } },
  build: { chunkSizeWarningLimit: 1200 },
});
