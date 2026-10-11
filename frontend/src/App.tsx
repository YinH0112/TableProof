import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, operate, request } from './api';
import { dictionary } from './i18n';
import PdfPane from './PdfPane';
import type { BBox, Cell, Job, Language, Operation, Project, ProjectSummary, Region, SelectionMode, SourceRef, Table } from './types';

type IconName = 'upload' | 'folder' | 'arrow' | 'file' | 'download' | 'undo' | 'redo' | 'check' | 'close' | 'left' | 'right' | 'plus' | 'minus' | 'target' | 'merge' | 'split' | 'eye' | 'shield' | 'grid' | 'edit';
function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, React.ReactNode> = {
    upload: <><path d="M12 16V3m-5 5 5-5 5 5" /><path d="M4 14v6h16v-6" /></>,
    folder: <path d="M3 7V4h6l3 3h9v13H3Z" />,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
    file: <><path d="M6 3h8l4 4v14H6Z" /><path d="M14 3v5h4M9 12h6m-6 4h6" /></>,
    download: <><path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4" /></>,
    undo: <path d="m7 4-4 4 4 4M3 8h10a7 7 0 0 1 0 14" />,
    redo: <path d="m17 4 4 4-4 4m4-4H11a7 7 0 0 0 0 14" />,
    check: <path d="m5 12 4 4L19 6" />, close: <path d="m6 6 12 12M18 6 6 18" />,
    left: <path d="m15 5-7 7 7 7" />, right: <path d="m9 5 7 7-7 7" />,
    plus: <path d="M12 5v14M5 12h14" />, minus: <path d="M5 12h14" />,
    target: <><rect x="3" y="3" width="18" height="18" rx="3" /><path d="M12 7v10M7 12h10" /></>,
    merge: <><path d="M3 3h18v18H3ZM3 12h4m10 0h4m-12-3 3 3-3 3m6-6-3 3 3 3" /></>,
    split: <><path d="M3 3h18v18H3ZM12 3v18m-5-12-3 3 3 3m10-6 3 3-3 3" /></>,
    eye: <><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></>,
    shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z" /><path d="m8 12 3 3 5-6" /></>,
    grid: <><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M3 9h18M3 15h18M9 3v18M15 3v18" /></>,
    edit: <><path d="m16 3 5 5-12 12-6 1 1-6Z" /><path d="m13 6 5 5" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function activeTables(project: Project) {
  const superseded = new Set(project.tables.map(table => table.supersedes).filter(Boolean));
  return project.tables.filter(table => !superseded.has(table.id));
}

function rectangle(cells: Cell[]) {
  if (cells.length < 2) return false;
  const r0 = Math.min(...cells.map(c => c.row)), c0 = Math.min(...cells.map(c => c.col));
  const r1 = Math.max(...cells.map(c => c.row + c.rowSpan)), c1 = Math.max(...cells.map(c => c.col + c.colSpan));
  const covered = new Set<string>();
  for (const cell of cells) for (let row = cell.row; row < cell.row + cell.rowSpan; row++) for (let col = cell.col; col < cell.col + cell.colSpan; col++) {
    const key = `${row},${col}`;
    if (covered.has(key)) return false;
    covered.add(key);
  }
  return covered.size === (r1 - r0) * (c1 - c0);
}

function errorMessage(error: unknown) { return error instanceof Error ? error.message : String(error); }
function readableError(message: string, language: Language) {
  const messages: Record<string, [string, string]> = {
    NO_TEXT: ['This PDF has no extractable text. Scanned pages need OCR before import.', '此 PDF 没有可提取文字。扫描页面需先经过 OCR 处理。'],
    ENCRYPTED_PDF: ['Encrypted PDFs are unsupported. Import a decrypted copy.', '暂不支持加密 PDF，请导入已解密的副本。'],
    INVALID_PDF: ['This file could not be parsed as a PDF. Check the file and try another copy.', '无法解析此 PDF。请检查文件，或尝试另一份副本。'],
    EMPTY_REGION: ['No text was found in this selection. Draw a region around the table or text.', '选区内没有找到文字，请重新框选表格或文字区域。'],
    NO_DETECTED_GRID: ['No reliable table grid was detected. Adjust the region or add column guides.', '未识别到可靠表格网格，请调整选区或添加列分隔线。'],
    PDF_TOO_LARGE: ['This file exceeds the 100 MB import limit.', '此文件超过 100 MB 导入限制。'],
    EMPTY_FILE: ['The selected file is empty.', '选中的文件为空。'],
    SAMPLE_NOT_INSTALLED: ['The sample PDF is unavailable. You can still import your own PDF.', '示例 PDF 不可用，仍可导入自己的 PDF。'],
    IMPORT_FAILED: ['Import failed. Check the PDF and try again.', '导入失败，请检查 PDF 并重试。'],
  };
  const match = messages[message.split(':')[0]];
  return match ? match[language === 'zh' ? 1 : 0] : message;
}
function normalizeBBox(value: BBox) { return value.map(number => Math.round(number * 100) / 100) as BBox; }

export default function App() {
  const [language, setLanguage] = useState<Language>(() => localStorage.getItem('tableproof-language') === 'zh' ? 'zh' : 'en');
  const t = dictionary(language);
  const [project, setProject] = useState<Project | null>(null), [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectList, setProjectList] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [toast, setToast] = useState('');
  const [page, setPage] = useState(1), [zoom, setZoom] = useState(1), [mode, setMode] = useState<SelectionMode>('table');
  const [region, setRegion] = useState<Region | null>(null), [guideMode, setGuideMode] = useState(false), [guides, setGuides] = useState<number[]>([]), [reextractId, setReextractId] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null), [activeCellId, setActiveCellId] = useState<string | null>(null), [selected, setSelected] = useState<string[]>([]);
  const [highlights, setHighlights] = useState<SourceRef[]>([]), [showVersions, setShowVersions] = useState(false), [draft, setDraft] = useState('');
  const [splitDialog, setSplitDialog] = useState<{ cell: Cell; axis: 'row' | 'col'; at: number; first: string; second: string; custom: boolean } | null>(null);
  const [renameDialog, setRenameDialog] = useState(false), [renameValue, setRenameValue] = useState('');
  const [importState, setImportState] = useState<{ id: string | null; progress: number } | null>(null), [dragOver, setDragOver] = useState(false);
  const projectRef = useRef<Project | null>(null), preserveDraft = useRef<string | null>(null);
  const [pendingAction, setPendingAction] = useState<{ run: () => void } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null), importAbort = useRef<AbortController | null>(null), tableRef = useRef<HTMLDivElement>(null);
  const locked = busy || !!importState;
  const tables = project ? activeTables(project) : [];
  const table = project?.tables.find(value => value.id === activeId) ?? null;
  const cell = table?.cells.find(value => value.id === activeCellId) ?? null;
  const archived = !!table && !tables.some(value => value.id === table.id);
  const selectedCells = table?.cells.filter(value => selected.includes(value.id)) ?? [];
  const dirty = !!cell && draft !== cell.value;
  function guard(run: () => void) { if (dirty) setPendingAction({ run }); else run(); }
  const pageInfo = project?.pages.find(value => value.number === page);
  const visibleTables = showVersions ? project?.tables ?? [] : tables;

  const refreshProjects = useCallback(async () => {
    const items = await request<ProjectSummary[]>('/api/projects');
    setProjects(items);
  }, []);

  function loadProject(next: Project) {
    projectRef.current = next; setProject(next); setActiveId(activeTables(next)[0]?.id ?? null);
    setPage(1); setZoom(1); setRegion(null); setGuides([]); setReextractId(null); setHighlights([]); setSelected([]); setActiveCellId(null); setProjectList(false);
    localStorage.setItem('tableproof-project', next.id);
  }

  useEffect(() => {
    let alive = true;
    void refreshProjects().catch(cause => { if (alive) setError(errorMessage(cause)); });
    const saved = localStorage.getItem('tableproof-project');
    if (saved) {
      setBusy(true);
      void request<Project>(`/api/projects/${saved}`).then(next => { if (alive) loadProject(next); }).catch(cause => {
        if (cause instanceof ApiError && cause.status === 404) localStorage.removeItem('tableproof-project');
        else if (alive) setError(errorMessage(cause));
      }).finally(() => { if (alive) setBusy(false); });
    }
    return () => { alive = false; };
  }, [refreshProjects]);

  useEffect(() => {
    localStorage.setItem('tableproof-language', language); document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
  }, [language]);

  useEffect(() => { if (preserveDraft.current && preserveDraft.current === cell?.id) { preserveDraft.current = null; return; } preserveDraft.current = null; setDraft(cell?.value ?? ''); }, [cell?.id, cell?.value]);
  useEffect(() => { const listener = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ''; } }; window.addEventListener('beforeunload', listener); return () => window.removeEventListener('beforeunload', listener); }, [dirty]);
  useEffect(() => { if (!toast) return; const timeout = window.setTimeout(() => setToast(''), 8000); return () => window.clearTimeout(timeout); }, [toast]);

  const modalOpen = !!(projectList || renameDialog || splitDialog || pendingAction || importState);
  useEffect(() => {
    if (!modalOpen) return;
    const dialogs = document.querySelectorAll<HTMLElement>('[role="dialog"]');
    const dialog = dialogs[dialogs.length - 1];
    if (!dialog) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex="0"]'));
    dialog.tabIndex = -1; (focusable()[0] ?? dialog).focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      const items = focusable();
      if (!items.length) { event.preventDefault(); dialog.focus(); return; }
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', keydown);
    return () => { document.removeEventListener('keydown', keydown); if (previousFocus?.isConnected) previousFocus.focus(); };
  }, [modalOpen, projectList, renameDialog, !!splitDialog, !!pendingAction, !!importState]);

  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy && !importState) { setPendingAction(null); setSplitDialog(null); setRenameDialog(false); setProjectList(false); }
    };
    document.addEventListener('keydown', escape); return () => document.removeEventListener('keydown', escape);
  }, [busy, importState]);

  function openProject(id: string) { guard(() => void doOpenProject(id)); }
  async function doOpenProject(id: string) {
    if (locked) return;
    setBusy(true); setError('');
    try { loadProject(await request<Project>(`/api/projects/${id}`)); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  function beginImport(file?: File) { guard(() => void doBeginImport(file)); }
  async function doBeginImport(file?: File) {
    if (locked) return;
    if (file && !file.name.toLowerCase().endsWith('.pdf')) { setError(language === 'zh' ? '请选择 PDF 文件。' : 'Please choose a PDF file.'); return; }
    const controller = new AbortController(); importAbort.current = controller;
    setImportState({ id: null, progress: 0 }); setError('');
    try {
      const form = new FormData(); if (file) form.append('file', file);
      const start = await request<{ jobId: string }>(file ? '/api/projects' : '/api/demo', file ? { method: 'POST', body: form, signal: controller.signal } : { signal: controller.signal });
      setImportState({ id: start.jobId, progress: 0 });
      for (;;) {
        if (controller.signal.aborted) return;
        const job = await request<Job>(`/api/jobs/${start.jobId}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setImportState({ id: start.jobId, progress: job.progress || 0 });
        if (job.status === 'complete') {
          if (!job.projectId) throw new Error(t.importFailed);
          const next = await request<Project>(`/api/projects/${job.projectId}`, { signal: controller.signal });
          if (!controller.signal.aborted) { loadProject(next); await refreshProjects(); }
          break;
        }
        if (job.status === 'failed') throw new Error(job.error || t.importFailed);
        if (job.status === 'cancelled') { setToast(t.cancelDone); break; }
        await new Promise<void>(resolve => window.setTimeout(resolve, 350));
      }
    } catch (cause) { if (!controller.signal.aborted) setError(errorMessage(cause)); }
    finally { if (importAbort.current === controller) { setImportState(null); importAbort.current = null; } }
  }

  async function cancelImport() {
    if (!importState?.id) return;
    const current = importState.id;
    try {
      const response = await fetch(`/api/jobs/${current}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      importAbort.current?.abort(); importAbort.current = null; setImportState(null); setToast(t.cancelDone);
    } catch (cause) { setError(errorMessage(cause)); }
  }

  async function mutation(action: (current: Project) => Promise<Project>, after?: (next: Project) => void) {
    if (!projectRef.current || locked) return false;
    setBusy(true); setError('');
    try {
      const next = await action(projectRef.current); projectRef.current = next; setProject(next);
      const nextCell = next.tables.flatMap(value => value.cells).find(value => value.id === activeCellId);
      setHighlights(nextCell?.sourceRefs ?? []);
      if (activeId && !next.tables.some(value => value.id === activeId)) setActiveId(activeTables(next).at(-1)?.id ?? null);
      after?.(next);
      void refreshProjects().catch(() => {}); return true;
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        try {
          const latest = await request<Project>(`/api/projects/${project!.id}`); preserveDraft.current = dirty ? activeCellId : null; projectRef.current = latest; setProject(latest); setSelected([]);
          const latestCell = latest.tables.flatMap(value => value.cells).find(value => value.id === activeCellId); setHighlights(latestCell?.sourceRefs ?? []);
          if (activeId && !latest.tables.some(value => value.id === activeId)) setActiveId(activeTables(latest)[0]?.id ?? null);
          setError(t.conflict);
        } catch (refreshError) { setError(errorMessage(refreshError)); }
      } else setError(errorMessage(cause));
      return false;
    } finally { setBusy(false); }
  }

  function operation(value: Operation, after?: (next: Project) => void) { const run = () => void mutation(current => operate(current, value), after); if (value.type === 'edit') run(); else guard(run); }
  async function savePending() { if (!pendingAction || !cell || !table) return; const action = pendingAction.run; const saved = await mutation(current => operate(current, { type: 'edit', tableId: table.id, cellId: cell.id, value: draft })); if (saved) { setPendingAction(null); action(); } }

  function extract() { guard(() => void doExtract()); }
  async function doExtract() {
    if (!region || mode !== 'table') return;
    const supersedes = reextractId ?? undefined;
    await mutation(current => request<Project>(`/api/projects/${current.id}/tables`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version: current.version, page: region.page, bbox: normalizeBBox(region.bbox), ...(guides.length ? { columnLines: [...guides].sort((a, b) => a - b) } : {}), ...(supersedes ? { supersedes } : {}) }),
    }), next => {
      const added = next.tables.find(value => !project?.tables.some(previous => previous.id === value.id));
      setActiveId(added?.id ?? activeTables(next).at(-1)?.id ?? null); setActiveCellId(null); setSelected([]); setRegion(null); setGuides([]); setGuideMode(false); setReextractId(null);
    });
  }

  function chooseTable(value: Table) { guard(() => doChooseTable(value)); }
  function doChooseTable(value: Table) {
    setActiveId(value.id); setPage(value.page); setActiveCellId(null); setSelected([]); setRegion(null); setGuides([]); setGuideMode(false); setReextractId(null);
    setHighlights([{ fileHash: project!.fileHash, page: value.page, bbox: value.bbox }]);
  }

  function chooseCell(value: Cell) { guard(() => doChooseCell(value)); }
  function doChooseCell(value: Cell) {
    setActiveCellId(value.id); setHighlights(value.sourceRefs);
    if (value.sourceRefs[0]) setPage(value.sourceRefs[0].page);
  }

  function selectCell(id: string) { setSelected(previous => previous.includes(id) ? previous.filter(value => value !== id) : [...previous, id]); }
  function navigatePage(value: number) { setPage(value); setRegion(null); setGuides([]); setGuideMode(false); setReextractId(null); }

  function exportExcel() { guard(() => void doExportExcel()); }
  async function doExportExcel() {
    if (!project || locked) return;
    setBusy(true); setError('');
    try {
      const response = await fetch(`/api/projects/${project.id}/export.xlsx`);
      if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || t.exportFailed); }
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${project.name.replace(/\.pdf$/i, '')}.xlsx`; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000); setToast(t.exported);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  function startSplit() {
    const target = selectedCells.length === 1 ? selectedCells[0] : selectedCells.length === 0 ? cell : null;
    if (!target || (target.rowSpan < 2 && target.colSpan < 2)) { setError(t.splitGuard); return; }
    const axis = target.colSpan > 1 ? 'col' : 'row';
    setSplitDialog({ cell: target, axis, at: (axis === 'col' ? target.col : target.row) + 1, first: target.value, second: '', custom: target.value !== target.originalText });
  }

  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (!project || locked || !event.ctrlKey && !event.metaKey || event.key.toLowerCase() !== 'z') return;
      const target = event.target as HTMLElement;
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
      event.preventDefault();
      if (event.shiftKey ? project.redoStack?.length : project.undoStack?.length) void operation({ type: event.shiftKey ? 'redo' : 'undo' });
    };
    window.addEventListener('keydown', listener); return () => window.removeEventListener('keydown', listener);
  });

  return <div className="app-shell">
    <header className="app-header">
      <div className="brand"><span className="brand-mark"><Icon name="grid" size={22} /></span><div><strong>{t.product}</strong><span>{t.subtitle}</span></div></div>
      <div className="header-actions">
        <span className="local-badge"><span />{t.local}</span>
        <button className="quiet" disabled={locked} onClick={() => { setProjectList(true); void refreshProjects().catch(cause => setError(errorMessage(cause))); }}><Icon name="folder" /><span>{t.projects}</span></button>
        <button className="quiet" disabled={locked} onClick={() => fileInput.current?.click()}><Icon name="upload" /><span>{t.import}</span></button>
        <button className="language" aria-label="Switch language / 切换语言" onClick={() => setLanguage(language === 'en' ? 'zh' : 'en')}>{language === 'en' ? '中文' : 'EN'}</button>
      </div>
    </header>
    <input ref={fileInput} type="file" accept=".pdf,application/pdf" className="sr-only" data-testid="file-input" onChange={event => { const file = event.target.files?.[0]; if (file) void beginImport(file); event.target.value = ''; }} />

    {error && <div className="error-banner" role="alert"><div><strong>{t.errorTitle}</strong><span>{readableError(error, language)}</span></div><button className="icon-button" aria-label={t.dismiss} onClick={() => setError('')}><Icon name="close" /></button></div>}
    {toast && <div className="toast" role="status"><Icon name="check" /><span>{toast}</span><button className="icon-button" aria-label={t.dismiss} onClick={() => setToast('')}><Icon name="close" /></button></div>}

    {!project && <main className="welcome">
      <div className="welcome-copy"><div className="eyebrow">PDF → TABLE → EVIDENCE</div><h1>{t.emptyTitle}</h1><p>{t.emptyBody}</p><div className="steps">{(['step1', 'step2', 'step3'] as const).map((key, index) => <div key={key}><span className="step-number">0{index + 1}</span><div><strong>{t[key]}</strong><p>{t[`${key}body`]}</p></div></div>)}</div></div>
      <div className={`dropzone ${dragOver ? 'drag-over' : ''}`} onDragOver={event => { event.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)} onDrop={event => { event.preventDefault(); setDragOver(false); if (event.dataTransfer.files[0]) void beginImport(event.dataTransfer.files[0]); }}>
        <div className="document-illustration"><div className="illustration-heading" /><div className="illustration-line" /><div className="illustration-line short" /><div className="illustration-table"><span /><span /><span /><span /><span /><span /><span /><span /><span /></div><span className="illustration-proof"><Icon name="check" size={16} /></span></div>
        <h2>{t.dropTitle}</h2><p>{t.dropBody}</p><button className="primary" disabled={locked} onClick={() => fileInput.current?.click()}><Icon name="upload" />{t.import}<Icon name="arrow" /></button>
        <button className="sample-button" disabled={locked} data-testid="demo-button" onClick={() => void beginImport()}>{t.demo}<Icon name="right" size={14} /></button>
        <div className="privacy-note"><Icon name="shield" size={15} />{t.dropNote}</div>
      </div>
    </main>}

    {project && <>
      <section className="project-bar">
        <div className="project-heading"><Icon name="file" size={21} /><div><button className="project-name" disabled={locked} title={t.rename} onClick={() => { setRenameValue(project.name); setRenameDialog(true); }}>{project.name}<Icon name="edit" size={13} /></button><span>{t.projectVersion} {project.version} <i>·</i> {tables.length} {t.tableCount}</span></div></div>
        <div className="project-actions"><div className="history-buttons"><button className="icon-button" data-testid="undo" title={t.undo} aria-label={t.undo} disabled={locked || !project.undoStack?.length} onClick={() => void operation({ type: 'undo' })}><Icon name="undo" /></button><button className="icon-button" data-testid="redo" title={t.redo} aria-label={t.redo} disabled={locked || !project.redoStack?.length} onClick={() => void operation({ type: 'redo' })}><Icon name="redo" /></button></div><span className="save-state">{dirty ? <span className="dirty-state">{t.unsaved}</span> : busy ? <><span className="spinner small" />{t.busy}</> : <><Icon name="check" size={14} />{language === 'zh' ? '已保存' : 'Saved'}</>}</span><button className="primary compact" data-testid="export-button" disabled={locked || !tables.length} onClick={() => void exportExcel()}><Icon name="download" />{t.export}</button></div>
      </section>
      <main className="workbench">
        <section className="source-pane" aria-label={t.source}>
          <div className="pane-heading"><div><span className="pane-number">01</span><h2>{t.source}</h2></div><span className="pill">PDF</span></div>
          <div className="pdf-toolbar"><div className="page-controls"><button className="icon-button" title={t.previous} aria-label={t.previous} disabled={page <= 1 || locked} onClick={() => navigatePage(page - 1)}><Icon name="left" size={16} /></button><label>{t.page} <input aria-label={t.page} type="number" min={1} max={project.pages.length} value={page} onChange={event => { const value = Number(event.target.value); if (value >= 1 && value <= project.pages.length) navigatePage(value); }} /> <span>/ {project.pages.length}</span></label><button className="icon-button" title={t.next} aria-label={t.next} disabled={page >= project.pages.length || locked} onClick={() => navigatePage(page + 1)}><Icon name="right" size={16} /></button></div><div className="zoom-controls"><button className="icon-button" title={t.zoomOut} aria-label={t.zoomOut} disabled={zoom <= .5} onClick={() => setZoom(value => Math.max(.5, value - .15))}><Icon name="minus" size={15} /></button><button className="zoom-value" title={t.fit} onClick={() => setZoom(1)}>{Math.round(zoom * 100)}%</button><button className="icon-button" title={t.zoomIn} aria-label={t.zoomIn} disabled={zoom >= 3} onClick={() => setZoom(value => Math.min(3, value + .15))}><Icon name="plus" size={15} /></button></div></div>
          <div className="selection-tools"><div className="segmented">{(['table', 'caption', 'note', 'unit'] as const).map(value => <button key={value} disabled={locked || value !== 'table' && (!table || archived)} className={mode === value ? 'active' : ''} data-testid={`mode-${value}`} onClick={() => { setMode(value); setRegion(null); setGuides([]); setGuideMode(false); setReextractId(null); }}>{t[value]}</button>)}</div><span>{mode === 'table' ? t.selectHint : t.contextHint}</span></div>
          {pageInfo?.mappingReliable === false && <div className="mapping-warning"><Icon name="eye" size={16} />{t.mappingWarning}</div>}
          <PdfPane projectId={project.id} page={page} pageInfo={pageInfo} zoom={zoom} region={region} highlights={highlights} guides={guides} guideMode={guideMode}
            onRegion={value => { if (!locked) { setRegion(value); setGuides([]); setHighlights([]); } }} onGuide={x => setGuides(previous => { const nearby = previous.find(value => Math.abs(value - x) < 4); return nearby === undefined ? [...previous, Math.round(x * 100) / 100] : previous.filter(value => value !== nearby); })} t={t} />
          <div className="region-actions"><div className="region-status">{region ? <><span className="selection-dot" />{t.selection} · {t.page} {region.page}</> : <span>{t.selectHint}</span>}</div><div>{mode === 'table' && <button className={`quiet guide-toggle ${guideMode ? 'active' : ''}`} disabled={!region || locked || !pageInfo?.transform} title={t.columnsHint} onClick={() => setGuideMode(value => !value)}><Icon name="split" size={15} />{t.columns}{guides.length > 0 && <span>{guides.length}</span>}</button>}{region && <button className="quiet" disabled={locked} onClick={() => { setRegion(null); setGuides([]); setGuideMode(false); setReextractId(null); }}>{t.clear}</button>}<button className="primary compact" data-testid="extract-button" disabled={!region || locked || mode !== 'table' && (!table || archived)} onClick={() => { if (mode === 'table') void extract(); else if (table && region) void operation({ type: 'context', tableId: table.id, kind: mode, page: region.page, bbox: normalizeBBox(region.bbox) }, () => setRegion(null)); }}>{mode === 'table' ? reextractId ? t.reextract : t.extract : t.attach}<Icon name="arrow" size={16} /></button></div></div>
          {guideMode && <div className="guide-help">{t.columnsHint}</div>}
        </section>

        <section className="data-pane" aria-label={t.data}>
          <div className="pane-heading"><div><span className="pane-number">02</span><h2>{t.data}</h2></div><label className="version-toggle"><input type="checkbox" checked={showVersions} onChange={event => setShowVersions(event.target.checked)} />{t.allVersions}</label></div>
          {visibleTables.length > 0 && <div className="table-tabs" role="tablist" aria-label={t.data}>{visibleTables.map((value, index) => <button key={value.id} role="tab" aria-selected={activeId === value.id} className={`${activeId === value.id ? 'active' : ''} ${!tables.some(current => current.id === value.id) ? 'archived' : ''}`} disabled={locked} onClick={() => chooseTable(value)}><Icon name="grid" size={15} />{t.table} {index + 1}<span>{t.page} {value.page}</span>{!tables.some(current => current.id === value.id) && <Icon name="eye" size={12} />}</button>)}</div>}
          {!table && <div className="table-empty"><span><Icon name="grid" size={28} /></span><h3>{t.tablesEmpty}</h3><p>{t.tablesEmptyBody}</p><div className="empty-grid" aria-hidden="true"><span /><span /><span /><span /><span /><span /><span /><span /><span /></div></div>}
          {table && <>
            <div className="table-summary"><div><strong>{table.rowCount} × {table.colCount}</strong><span>{table.cells.length} {t.cells}</span>{archived && <span className="old-version">{t.oldVersion}</span>}</div><div><span className="review-meter"><span style={{ width: `${table.cells.length ? table.cells.filter(value => value.reviewed).length / table.cells.length * 100 : 0}%` }} /></span><span>{table.cells.filter(value => value.reviewed).length}/{table.cells.length} {t.reviewed}</span></div></div>
            <div className="cell-tools"><label className="select-all"><input type="checkbox" aria-label={t.selectAll} checked={!!table.cells.length && selected.length === table.cells.length} disabled={locked || archived} onChange={event => setSelected(event.target.checked ? table.cells.map(value => value.id) : [])} /><span>{selected.length} {t.selected}</span></label><div><button className="quiet" disabled={locked || archived || !selected.length} onClick={() => void operation({ type: 'review', tableId: table.id, cellIds: selected, reviewed: true })}><Icon name="check" size={15} />{t.reviewSelected}</button><button className="icon-button" title={t.mergeGuard} aria-label={t.merge} disabled={locked || archived || !rectangle(selectedCells)} data-testid="merge-button" onClick={() => void operation({ type: 'merge', tableId: table.id, cellIds: selected }, () => { setSelected([]); setActiveCellId(null); })}><Icon name="merge" size={17} /></button><button className="icon-button" title={t.split} aria-label={t.split} disabled={locked || archived || !((selectedCells.length === 1 ? selectedCells[0] : selectedCells.length === 0 ? cell : null)?.rowSpan! > 1 || (selectedCells.length === 1 ? selectedCells[0] : selectedCells.length === 0 ? cell : null)?.colSpan! > 1)} data-testid="split-button" onClick={startSplit}><Icon name="split" size={17} /></button><button className="icon-button" title={t.redraw} aria-label={t.redraw} disabled={locked || archived} onClick={() => { setMode('table'); setPage(table.page); setRegion({ page: table.page, bbox: table.bbox }); setGuides([]); setGuideMode(false); setReextractId(table.id); }}><Icon name="target" size={17} /></button></div></div>
            <div className="table-scroll" ref={tableRef}><table className="extracted-table"><tbody>{Array.from({ length: table.rowCount }, (_, row) => <tr key={row}>{Array.from({ length: table.colCount }, (_, col) => {
              const value = table.cells.find(item => item.row === row && item.col === col);
              if (!value) return null;
              return <td key={value.id} rowSpan={value.rowSpan} colSpan={value.colSpan} className={`${activeCellId === value.id ? 'focused' : ''} ${selected.includes(value.id) ? 'selected' : ''} ${value.value !== value.originalText ? 'edited' : ''}`} data-testid={`cell-${row}-${col}`}>
                <div className="cell-content"><input type="checkbox" className="cell-checkbox" aria-label={`${t.selected} ${row + 1}, ${col + 1}`} checked={selected.includes(value.id)} disabled={locked || archived} onChange={() => selectCell(value.id)} /><button className="cell-value" onClick={() => chooseCell(value)} data-testid={`cell-value-${row}-${col}`}>{value.value || <span className="empty-value">—</span>}</button><span className={`cell-status ${value.reviewed ? 'is-reviewed' : ''}`} title={value.reviewed ? t.reviewed : t.unreviewed}>{value.reviewed ? <Icon name="check" size={12} /> : <span />}</span></div>
              </td>;
            })}</tr>)}</tbody></table></div>
            <div className="table-footnote"><Icon name="shield" size={13} />{t.proofHint}<button disabled={locked || archived} onClick={() => { setMode('table'); setPage(table.page); setRegion({ page: table.page, bbox: table.bbox }); setGuides([]); setGuideMode(true); setReextractId(table.id); }}>{t.reextract}</button></div>

            <div className="evidence-panel"><div className="section-label"><Icon name="target" size={16} /><h3>{t.evidence}</h3>{cell && <span>R{cell.row + 1} · C{cell.col + 1}</span>}</div>
              {!cell ? <p className="placeholder-copy">{t.clickCell}</p> : <>
                <div className="evidence-values"><div><label>{t.original}</label><div className="original-value" data-testid="original-value">{cell.originalText || '—'}</div></div><div><label htmlFor="current-value">{t.current}{cell.value !== cell.originalText && <span className="edited-label">{t.changed}</span>}</label><textarea id="current-value" data-testid="current-value" value={draft} disabled={locked || archived} rows={2} onChange={event => setDraft(event.target.value)} /></div></div>
                <div className="evidence-actions"><div><span className={`status-pill ${cell.reviewed ? 'checked' : ''}`}>{cell.reviewed ? <Icon name="check" size={12} /> : <span className="status-dot" />}{cell.reviewed ? t.reviewed : t.unreviewed}</span><button className="quiet" disabled={locked || !cell.sourceRefs.length} onClick={() => { setHighlights(cell.sourceRefs); if (cell.sourceRefs[0]) setPage(cell.sourceRefs[0].page); }}><Icon name="target" size={14} />{t.locate}</button></div><div><button className="quiet" data-testid="review-cell" disabled={locked || archived} onClick={() => void operation({ type: 'review', tableId: table.id, cellIds: [cell.id], reviewed: !cell.reviewed })}><Icon name="check" size={15} />{cell.reviewed ? t.resetReview : t.markReviewed}</button><button className="secondary compact" data-testid="save-value" disabled={locked || archived || draft === cell.value} onClick={() => void operation({ type: 'edit', tableId: table.id, cellId: cell.id, value: draft })}>{t.save}</button></div></div>
                <details className="source-refs"><summary>{t.refs} <span>{cell.sourceRefs.length}</span></summary>{!cell.sourceRefs.length ? <p>{t.noRefs}</p> : cell.sourceRefs.map((ref, index) => <button key={index} onClick={() => { setPage(ref.page); setHighlights([ref]); }}>{t.page} {ref.page}<code>{ref.bbox.map(value => value.toFixed(1)).join(', ')}</code><Icon name="right" size={13} /></button>)}</details>
              </>}
            </div>
            <div className="context-panel"><div className="section-label"><Icon name="file" size={16} /><h3>{t.contexts}</h3></div>{!table.contexts?.length ? <p className="placeholder-copy">{t.contextsEmpty}</p> : table.contexts.map(context => <button key={context.id} className="context-item" onClick={() => { setHighlights(context.sourceRefs); if (context.sourceRefs[0]) setPage(context.sourceRefs[0].page); }}><span>{t[context.kind]}</span><p>{context.text}</p><Icon name="target" size={15} /></button>)}{table.omittedText?.text && <div className="omitted-panel"><div className="section-label"><Icon name="eye" size={16} /><h3>{t.omitted}</h3></div><p>{t.omittedHint}</p><button className="context-item" onClick={() => { setHighlights(table.omittedText!.sourceRefs); if (table.omittedText!.sourceRefs[0]) setPage(table.omittedText!.sourceRefs[0].page); }}><p>{table.omittedText.text}</p><Icon name="target" size={15} /></button></div>}</div>
          </>}
        </section>
      </main>
    </>}

    {importState && <div className="modal-backdrop"><section className="modal import-modal" role="dialog" aria-modal="true" aria-labelledby="import-title"><div className="import-icon"><Icon name="file" size={27} /></div><h2 id="import-title">{t.progress}</h2><p>{t.dropNote}</p><div className="progress-track"><span style={{ width: `${Math.max(3, importState.progress)}%` }} /></div><div className="progress-text"><span>{importState.id ? `${Math.round(importState.progress)}%` : t.uploadPhase}</span><span className="spinner small" /></div><button className="secondary" data-testid="cancel-import" disabled={!importState.id} onClick={() => void cancelImport()}>{t.cancel}</button></section></div>}
    {projectList && <div className="modal-backdrop" onClick={event => { if (event.target === event.currentTarget) setProjectList(false); }}><section className="modal projects-modal" role="dialog" aria-modal="true" aria-labelledby="projects-title"><div className="modal-heading"><h2 id="projects-title">{t.projects}</h2><button className="icon-button" aria-label={t.close} onClick={() => setProjectList(false)}><Icon name="close" /></button></div><p>{t.projectListHint}</p><div className="project-list">{!projects.length && <p>{t.noProjects}</p>}{projects.map(value => <button key={value.id} disabled={locked} onClick={() => void openProject(value.id)}><span className="project-list-icon"><Icon name="file" /></span><div><strong>{value.name}</strong><span>{t.version} {value.version} · {new Date(value.updatedAt).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US')}</span></div><Icon name="right" size={16} /></button>)}</div></section></div>}
    {renameDialog && <div className="modal-backdrop"><form className="modal" role="dialog" aria-modal="true" onSubmit={event => { event.preventDefault(); if (renameValue.trim()) void operation({ type: 'rename', name: renameValue.trim() }, () => setRenameDialog(false)); }}><div className="modal-heading"><h2>{t.rename}</h2><button type="button" className="icon-button" aria-label={t.close} onClick={() => setRenameDialog(false)}><Icon name="close" /></button></div><input className="form-input" autoFocus value={renameValue} onChange={event => setRenameValue(event.target.value)} /><div className="modal-actions"><button type="button" className="quiet" onClick={() => setRenameDialog(false)}>{t.cancel}</button><button className="primary" disabled={locked || !renameValue.trim()}>{t.save}</button></div></form></div>}
    {splitDialog && <div className="modal-backdrop"><form className="modal" role="dialog" aria-modal="true" onSubmit={event => { event.preventDefault(); if (table) void operation({ type: 'split', tableId: table.id, cellId: splitDialog.cell.id, axis: splitDialog.axis, at: splitDialog.at, ...(splitDialog.custom ? { values: [splitDialog.first, splitDialog.second] } : {}) }, () => { setSplitDialog(null); setSelected([]); setActiveCellId(null); }); }}><div className="modal-heading"><h2>{t.splitTitle}</h2><button type="button" className="icon-button" aria-label={t.close} onClick={() => setSplitDialog(null)}><Icon name="close" /></button></div><label className="form-label">{t.splitAxis}<select className="form-input" value={splitDialog.axis} onChange={event => { const axis = event.target.value as 'row' | 'col'; setSplitDialog({ ...splitDialog, axis, at: (axis === 'col' ? splitDialog.cell.col : splitDialog.cell.row) + 1 }); }}><option value="col" disabled={splitDialog.cell.colSpan < 2}>{t.col}</option><option value="row" disabled={splitDialog.cell.rowSpan < 2}>{t.row}</option></select></label><label className="form-label">{t.splitAt}<input className="form-input" type="number" min={(splitDialog.axis === 'col' ? splitDialog.cell.col : splitDialog.cell.row) + 1} max={splitDialog.axis === 'col' ? splitDialog.cell.col + splitDialog.cell.colSpan - 1 : splitDialog.cell.row + splitDialog.cell.rowSpan - 1} value={splitDialog.at} onChange={event => setSplitDialog({ ...splitDialog, at: Number(event.target.value) })} /></label><label className="split-choice"><input type="checkbox" checked={splitDialog.custom} disabled={splitDialog.cell.value !== splitDialog.cell.originalText} onChange={event => setSplitDialog({ ...splitDialog, custom: event.target.checked })} />{t.splitManual}</label>{!splitDialog.custom && <p className="split-hint">{t.splitAuto}</p>}<label className="form-label">{t.splitFirst}<input className="form-input" disabled={!splitDialog.custom} value={splitDialog.custom ? splitDialog.first : ''} onChange={event => setSplitDialog({ ...splitDialog, first: event.target.value })} /></label><label className="form-label">{t.splitSecond}<input className="form-input" disabled={!splitDialog.custom} value={splitDialog.custom ? splitDialog.second : ''} onChange={event => setSplitDialog({ ...splitDialog, second: event.target.value })} /></label><div className="modal-actions"><button type="button" className="quiet" onClick={() => setSplitDialog(null)}>{t.cancel}</button><button className="primary" disabled={locked}>{t.split}</button></div></form></div>}
    {pendingAction && <div className="modal-backdrop"><section className="modal dirty-modal" role="dialog" aria-modal="true"><h2>{t.unsavedTitle}</h2><p>{t.unsavedBody}</p>{error && <p className="modal-error" role="alert">{readableError(error, language)}</p>}<div className="pending-preview">{draft}</div><div className="modal-actions"><button className="quiet" disabled={busy} onClick={() => setPendingAction(null)}>{t.stay}</button><button className="secondary" disabled={busy} onClick={() => { const action = pendingAction.run; setDraft(cell?.value ?? ''); setPendingAction(null); action(); }}>{t.discard}</button><button className="primary" disabled={busy} onClick={() => void savePending()}>{t.save}</button></div></section></div>}
    <footer className="app-footer"><span>{t.product} <i>·</i> {t.subtitle}</span><span><Icon name="shield" size={13} />{language === 'zh' ? '本地处理 · 人工复核 · 可追溯导出' : 'Local processing · Human review · Traceable export'}</span></footer>
  </div>;
}
