import { defineConfig } from '@playwright/test';
import { resolve, join } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const python = process.env.TABLEPROOF_PYTHON || join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const baseURL = process.env.TABLEPROOF_E2E_URL || 'http://127.0.0.1:18765';

export default defineConfig({
  testDir: './tests',
  outputDir: '../output/playwright/test-results',
  timeout: 45_000,
  workers: 1,
  reporter: [['list'], ['html', { outputFolder: '../output/playwright/report', open: 'never' }]],
  use: { baseURL, viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: process.env.TABLEPROOF_E2E_URL ? undefined : {
    command: `"${python}" -m tableproof --port 18765 --data-dir "${join(root, 'output/playwright/e2e-data')}" --no-browser`,
    cwd: root, url: `${baseURL}/api/health`, reuseExistingServer: false, timeout: 30_000,
  },
});
