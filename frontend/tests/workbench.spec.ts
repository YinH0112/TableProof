import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs';
import type { BBox, Project } from '../src/types';

const root = resolve(import.meta.dirname, '../..');
const manifest = JSON.parse(readFileSync(resolve(root, 'samples/manifest.json'), 'utf8')) as { fixtures: { id: string; filename: string; tableBbox: BBox; expected: { anchor: { text: string; bbox: BBox } } }[] };

async function rendered(page: Page) {
  await expect(page.getByTestId('pdf-page')).toBeVisible();
  await expect(page.locator('.pdf-loading')).toHaveCount(0);
  await expect.poll(() => page.locator('canvas').evaluate(canvas => canvas.width)).toBeGreaterThan(0);
}

async function viewportFor(file: string, page: Page) {
  const task = getDocument({ data: new Uint8Array(readFileSync(resolve(root, 'samples', file))) });
  const pdf = await task.promise;
  const pdfPage = await pdf.getPage(1);
  const paper = await page.getByTestId('pdf-page').boundingBox();
  if (!paper) throw new Error('Missing rendered paper');
  const base = pdfPage.getViewport({ scale: 1 });
  const viewport = pdfPage.getViewport({ scale: paper.width / base.width });
  return { task, viewport, paper };
}

async function drawRaw(page: Page, file: string, bbox: BBox) {
  await rendered(page);
  const { task, viewport, paper } = await viewportFor(file, page);
  const points = [[bbox[0], bbox[1]], [bbox[2], bbox[1]], [bbox[0], bbox[3]], [bbox[2], bbox[3]]].map(([x, y]) => viewport.convertToViewportPoint(x, y));
  const x0 = Math.min(...points.map(point => point[0])), y0 = Math.min(...points.map(point => point[1]));
  const x1 = Math.max(...points.map(point => point[0])), y1 = Math.max(...points.map(point => point[1]));
  await page.mouse.move(paper.x + x0, paper.y + y0); await page.mouse.down();
  await page.mouse.move(paper.x + x1, paper.y + y1, { steps: 12 }); await page.mouse.up();
  await task.destroy();
}

async function upload(page: Page, filename: string) {
  await page.getByTestId('file-input').setInputFiles(resolve(root, 'samples', filename));
  await rendered(page);
}

test('sample import, extract, source evidence, edit, review, export, reload and undo', async ({ page, context }, info) => {
  const browserErrors: string[] = [];
  const externalRequests: string[] = [];
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (['http:', 'https:'].includes(url.protocol) && !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) {
      externalRequests.push(url.href);
      await route.abort('internetdisconnected');
    } else {
      await route.continue();
    }
  });
  page.on('pageerror', error => browserErrors.push(error.message));
  await page.goto('/');
  await page.getByTestId('demo-button').click();
  await rendered(page);
  await drawRaw(page, 'multiheader.pdf', [47, 507, 553, 713]);
  await page.getByTestId('extract-button').click();
  await expect(page.getByTestId('cell-value-0-0')).toContainText('Aqueous group');
  await page.getByTestId('cell-value-2-1').click();
  await expect(page.getByTestId('original-value')).toHaveText('00007');
  await expect(page.locator('.pdf-highlight')).not.toHaveCount(0);
  await page.getByTestId('current-value').fill('00008');
  await page.getByTestId('save-value').click();
  await expect(page.getByTestId('cell-value-2-1')).toHaveText('00008');
  await expect(page.getByTestId('original-value')).toHaveText('00007');
  await page.getByTestId('review-cell').click();
  await expect(page.getByTestId('cell-2-1').locator('.cell-status')).toHaveClass(/is-reviewed/);
  const downloadEvent = page.waitForEvent('download');
  await page.getByTestId('export-button').click();
  const download = await downloadEvent;
  const file = info.outputPath('evidence.xlsx'); await download.saveAs(file);
  expect(readFileSync(file).subarray(0, 2).toString()).toBe('PK');
  await expect(page.getByRole('status')).toContainText('downloaded');
  await page.screenshot({ path: resolve(root, 'output/playwright/workbench-reviewed.png'), fullPage: true });
  await page.getByRole('status').getByRole('button', { name: 'Dismiss' }).click();
  await page.evaluate(() => {
    window.scrollTo(0, 0);
    for (const selector of ['.data-pane', '.pdf-scroll', '.table-scroll']) {
      const element = document.querySelector(selector);
      if (element) element.scrollTop = 0;
    }
  });
  await expect(page.getByRole('button', { name: 'Zoom in', exact: true })).toBeInViewport();
  await page.screenshot({ path: resolve(root, 'output/playwright/workbench-overview.png'), fullPage: true });
  await page.reload(); await rendered(page);
  await page.getByTestId('cell-value-2-1').click();
  await expect(page.getByTestId('current-value')).toHaveValue('00008');
  await expect(page.getByTestId('original-value')).toHaveText('00007');
  await page.getByTestId('undo').click();
  await expect(page.getByTestId('cell-2-1').locator('.cell-status')).not.toHaveClass(/is-reviewed/);
  await expect(page.getByTestId('undo')).toBeEnabled(); await page.getByTestId('undo').click();
  await expect(page.getByTestId('cell-value-2-1')).toHaveText('00007');
  await page.getByTestId('redo').click();
  await expect(page.getByTestId('cell-value-2-1')).toHaveText('00008');
  await page.getByRole('button', { name: 'Switch language / 切换语言' }).click();
  await expect(page.getByTestId('export-button')).toContainText('导出 Excel');
  expect(browserErrors).toEqual([]);
  expect(externalRequests).toEqual([]);
});

test('merge and split preserve evidence; re-extraction keeps an earlier table version', async ({ page }) => {
  await page.goto('/'); await upload(page, 'ruled.pdf');
  await drawRaw(page, 'ruled.pdf', [47, 507, 553, 713]); await page.getByTestId('extract-button').click();
  await expect(page.getByTestId('cell-value-1-1')).toHaveText('00123');
  await page.getByTestId('cell-1-0').getByRole('checkbox').check();
  await page.getByTestId('cell-1-1').getByRole('checkbox').check();
  await page.getByTestId('merge-button').click();
  await expect(page.getByTestId('cell-1-0')).toHaveAttribute('colspan', '2');
  await page.getByTestId('cell-value-1-0').click(); await page.getByTestId('split-button').click();
  await page.getByRole('dialog').getByRole('button', { name: 'Split cell', exact: true }).click();
  await expect(page.getByTestId('cell-value-1-0')).toHaveText('A');
  await expect(page.getByTestId('cell-value-1-1')).toHaveText('00123');
  await page.getByRole('button', { name: 'Re-extract table', exact: true }).click();
  await page.getByTestId('extract-button').click();
  await expect(page.getByRole('tab')).toHaveCount(1);
  await page.getByRole('checkbox', { name: 'Show earlier versions' }).check();
  await expect(page.getByRole('tab')).toHaveCount(2);
});

for (const id of ['ruled', 'rotated_90', 'rotated_180', 'rotated_270_crop', 'crop_nonzero']) {
  test(`source highlight matches independent known drawing coordinates: ${id}, DPR 2 and zoom`, async ({ page }) => {
    const fixture = manifest.fixtures.find(item => item.id === id)!;
    await page.goto('/'); await upload(page, fixture.filename);
    await drawRaw(page, fixture.filename, [fixture.tableBbox[0] - 3, fixture.tableBbox[1] - 3, fixture.tableBbox[2] + 3, fixture.tableBbox[3] + 3]);
    await page.getByTestId('extract-button').click();
    await expect(page.locator('.extracted-table td')).not.toHaveCount(0);
    const projectId = await page.evaluate(() => localStorage.getItem('tableproof-project'));
    const project = await (await page.request.get(`/api/projects/${projectId}`)).json() as Project;
    const character = project.pages[0].chars.find(char => char.text === fixture.expected.anchor.text && Math.abs(char.bbox[0] - fixture.expected.anchor.bbox[0]) < .2 && Math.abs(char.bbox[1] - fixture.expected.anchor.bbox[1]) < .2);
    expect(character).toBeTruthy();
    const sourceCell = project.tables.at(-1)!.cells.find(cell => cell.sourceRefs.some(ref => ref.charIds?.includes(character!.id)))!;
    await page.getByTestId(`cell-value-${sourceCell.row}-${sourceCell.col}`).click();
    for (const zoom of [1, 1.15]) {
      if (zoom > 1) { await page.getByRole('button', { name: 'Zoom in', exact: true }).click(); await rendered(page); }
      const { task, viewport, paper } = await viewportFor(fixture.filename, page);
      const raw = fixture.expected.anchor.bbox;
      const points = [[raw[0], raw[1]], [raw[2], raw[1]], [raw[0], raw[3]], [raw[2], raw[3]]].map(([x, y]) => viewport.convertToViewportPoint(x, y));
      const expected = { x: paper.x + Math.min(...points.map(p => p[0])), y: paper.y + Math.min(...points.map(p => p[1])), width: Math.max(...points.map(p => p[0])) - Math.min(...points.map(p => p[0])), height: Math.max(...points.map(p => p[1])) - Math.min(...points.map(p => p[1])) };
      const measured = await page.locator(`[data-char-id="${character!.id}"]`).boundingBox();
      expect(measured).toBeTruthy();
      for (const key of ['x', 'y', 'width', 'height'] as const) expect(Math.abs(measured![key] - expected[key]), `${id} ${key} at zoom ${zoom}`).toBeLessThanOrEqual(1);
      await task.destroy();
    }
  });
}

test('a pending import can be cancelled and an invalid PDF shows a recoverable error', async ({ page }) => {
  await page.goto('/');
  let cancelled = false;
  await page.route('**/api/demo', route => route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ jobId: 'test-pending-job' }) }));
  await page.route('**/api/jobs/test-pending-job', route => {
    if (route.request().method() === 'DELETE') { cancelled = true; return route.fulfill({ json: { status: 'cancelled' } }); }
    return route.fulfill({ json: { status: 'running', progress: 35 } });
  });
  await page.getByTestId('demo-button').click();
  await expect(page.getByTestId('cancel-import')).toBeEnabled(); await page.getByTestId('cancel-import').click();
  await expect(page.getByRole('dialog')).toHaveCount(0); expect(cancelled).toBe(true);
  await expect(page.getByTestId('demo-button')).toBeEnabled();
  await page.getByTestId('file-input').setInputFiles({ name: 'broken.pdf', mimeType: 'application/pdf', buffer: Buffer.from('this is not a PDF') });
  await expect(page.getByRole('alert')).toBeVisible(); await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByTestId('demo-button')).toBeEnabled();
});

test('unsaved export waits for confirmed save; failed saves and conflicts preserve the draft', async ({ page }) => {
  await page.goto('/'); await upload(page, 'ruled.pdf');
  await drawRaw(page, 'ruled.pdf', [47, 507, 553, 713]); await page.getByTestId('extract-button').click();
  await expect(page.getByTestId('cell-value-1-1')).toHaveText('00123');
  await page.getByTestId('cell-value-1-1').click(); await page.getByTestId('current-value').fill('00999');
  await expect(page.locator('.save-state')).toContainText('Unsaved value');
  await page.getByTestId('cell-value-1-0').click();
  await expect(page.getByRole('dialog')).toContainText('Save your cell edit?');
  await page.getByRole('button', { name: 'Keep editing', exact: true }).click();
  await expect(page.getByTestId('current-value')).toHaveValue('00999');
  let exportRequests = 0;
  page.on('request', request => { if (request.url().endsWith('/export.xlsx')) exportRequests++; });
  const failSave = async (route: import('@playwright/test').Route) => route.fulfill({ status: 503, json: { detail: 'SAVE_TEST_FAILURE' } });
  await page.route('**/api/projects/*/operations', failSave);
  await page.getByTestId('export-button').click();
  await page.getByRole('dialog').getByRole('button', { name: 'Save value', exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('SAVE_TEST_FAILURE');
  await expect(page.getByTestId('current-value')).toHaveValue('00999'); expect(exportRequests).toBe(0);
  await page.unroute('**/api/projects/*/operations', failSave);
  const download = page.waitForEvent('download');
  await page.getByRole('dialog').getByRole('button', { name: 'Save value', exact: true }).click(); await download;
  await expect(page.getByRole('dialog')).toHaveCount(0);
  const id = await page.evaluate(() => localStorage.getItem('tableproof-project'));
  let current = await (await page.request.get(`/api/projects/${id}`)).json() as Project;
  const target = current.tables[0].cells.find(cell => cell.row === 1 && cell.col === 1)!;
  expect(target.value).toBe('00999'); expect(exportRequests).toBe(1);
  await page.getByTestId('current-value').fill('01111');
  await page.request.post(`/api/projects/${id}/operations`, { data: { version: current.version, operation: { type: 'edit', tableId: current.tables[0].id, cellId: target.id, value: 'REMOTE' } } });
  await page.getByTestId('save-value').click();
  await expect(page.getByRole('alert')).toContainText('changed in another window');
  await expect(page.getByTestId('current-value')).toHaveValue('01111');
  await expect(page.getByTestId('cell-value-1-1')).toHaveText('REMOTE');
  await page.getByTestId('save-value').click(); await expect(page.getByTestId('cell-value-1-1')).toHaveText('01111');
  await page.getByTestId('current-value').fill('discard this'); await page.getByTestId('cell-value-1-0').click();
  await page.getByRole('dialog').getByRole('button', { name: 'Discard edit', exact: true }).click();
  await expect(page.getByTestId('current-value')).toHaveValue('A');
});
