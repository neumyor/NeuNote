import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowDownUp,
  ArrowLeft,
  Archive,
  BookOpenCheck,
  Bookmark,
  CheckCircle2,
  Clock3,
  Copy,
  ExternalLink,
  FileText,
  FolderCog,
  Gauge,
  KeyRound,
  Library,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Tags,
  Trash2,
  Upload,
  XCircle,
} from "lucide-react";
import "./styles.css";

type Page = "dashboard" | "library" | "profile" | "jobs" | "settings";

type Paper = {
  id: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string;
  doi: string;
  arxiv_id: string;
  source_pdf: string;
  pages: number | null;
  tags: string[];
  status: string;
  confidence: string;
  reading_status: string;
  priority: string;
  needs_review: boolean;
  abstract: string;
  one_sentence: string;
  problem: string;
  contributions: string[];
  method: string[];
  experiments: string[];
  limitations: string[];
  notes: string;
  review_notes: string[];
  agent_reviews: any[];
  translations?: Record<string, string | string[]>;
  created_at: string;
  updated_at: string;
};

type Stats = {
  papers: number;
  needs_review: number;
  profiled: number;
  tags: number;
  duplicate_groups: number;
  duplicate_papers: number;
};

type DuplicateGroup = {
  papers: Paper[];
  keep_id: string;
  duplicate_count: number;
};

type Job = {
  id: string;
  paper_id: string;
  title: string;
  status: string;
  stage: string;
  progress: number;
  created_at?: string;
  updated_at?: string;
  started_at?: string | null;
  completed_at?: string | null;
  events?: { time: string; message: string }[];
};

const API = "";

function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const [root, setRoot] = useState("");
  const [savedRoot, setSavedRoot] = useState("");
  const [claudeApiKey, setClaudeApiKey] = useState("");
  const [claudeEndpoint, setClaudeEndpoint] = useState("");
  const [claudeModel, setClaudeModel] = useState("sonnet");
  const [maxConcurrency, setMaxConcurrency] = useState(4);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [stats, setStats] = useState<Stats>({ papers: 0, needs_review: 0, profiled: 0, tags: 0, duplicate_groups: 0, duplicate_papers: 0 });
  const [jobs, setJobs] = useState<Job[]>([]);
  const [duplicates, setDuplicates] = useState<DuplicateGroup[]>([]);
  const [selectedPaperId, setSelectedPaperId] = useState("");
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);
  const [query, setQuery] = useState("");
  const [selectedTag, setSelectedTag] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sortBy, setSortBy] = useState<"year" | "added" | "title">("added");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [uploadProgress, setUploadProgress] = useState("");

  const activeJobCount = jobs.filter((j) => j.status === "queued" || j.status === "running").length;

  const tagCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const p of papers) {
      for (const tag of p.tags ?? []) counts.set(tag, (counts.get(tag) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [papers]);

  // Map paper_id → active job for per-paper status
  const paperJobs = useMemo(() => {
    const map = new Map<string, Job>();
    for (const j of jobs) {
      const existing = map.get(j.paper_id);
      if (!existing || (j.updated_at ?? "") > (existing.updated_at ?? "")) {
        map.set(j.paper_id, j);
      }
    }
    return map;
  }, [jobs]);

  const filteredPapers = useMemo(() => {
    const terms = query.trim().toLowerCase();
    return papers.filter((p) => {
      const title = p.title ?? p.id;
      const matchesQuery = !terms || [
        title, p.id, p.venue ?? "", (p.authors ?? []).join(" "), (p.tags ?? []).join(" "),
      ].some((v) => v.toLowerCase().includes(terms));
      const matchesTag = selectedTag === "all" || (p.tags ?? []).includes(selectedTag);
      const matchesStatus = statusFilter === "all"
        || (statusFilter === "review" && p.needs_review)
        || (statusFilter === "issues" && p.needs_review)
        || p.reading_status === statusFilter
        || p.status === statusFilter;
      return matchesQuery && matchesTag && matchesStatus;
    });
  }, [papers, query, selectedTag, statusFilter]);

  const sortedPapers = useMemo(() => {
    const list = [...filteredPapers];
    if (sortBy === "year") {
      list.sort((a, b) => (b.year ?? 0) - (a.year ?? 0) || (a.title ?? a.id).localeCompare(b.title ?? b.id));
    } else if (sortBy === "title") {
      list.sort((a, b) => (a.title ?? a.id).localeCompare(b.title ?? b.id));
    } else {
      // added: newest first (by created_at)
      list.sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
    }
    return list;
  }, [filteredPapers, sortBy]);

  const authorCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const p of papers) {
      for (const a of p.authors ?? []) counts.set(a, (counts.get(a) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 15);
  }, [papers]);

  const dailyActivity = useMemo(() => {
    const map = new Map<string, number>();
    for (const p of papers) {
      const d = (p.updated_at ?? p.created_at ?? "").slice(0, 10);
      if (d) map.set(d, (map.get(d) ?? 0) + 1);
    }
    return map;
  }, [papers]);

  useEffect(() => { void loadConfig(); }, []);

  useEffect(() => {
    if (!savedRoot || activeJobCount === 0) return;
    const timer = window.setInterval(() => {
      void loadJobs();
      void loadPapers();
      void loadDuplicates();
    }, 1600);
    return () => window.clearInterval(timer);
  }, [savedRoot, activeJobCount]);

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${API}${path}`, init);
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail ?? detail; } catch { /* */ }
      throw new Error(detail);
    }
    return res.json() as Promise<T>;
  }

  async function loadConfig() {
    setError("");
    const data = await request<{ root: string; claude_api_key?: string; claude_endpoint?: string; claude_model?: string; max_concurrency?: number }>("/api/config");
    setRoot(data.root);
    setSavedRoot(data.root);
    setClaudeApiKey(data.claude_api_key ?? "");
    setClaudeEndpoint(data.claude_endpoint ?? "");
    setClaudeModel(data.claude_model ?? "sonnet");
    setMaxConcurrency(data.max_concurrency ?? 4);
    await loadPapers(data.root);
    await loadJobs(data.root);
    await loadDuplicates(data.root);
  }

  async function loadPapers(kbRoot = savedRoot) {
    if (!kbRoot) return;
    const params = `?root=${encodeURIComponent(kbRoot)}`;
    const data = await request<{ papers: Paper[]; stats: Stats }>(`/api/papers${params}`);
    setPapers(data.papers);
    setStats(data.stats);
    if (selectedPaperId) {
      const next = data.papers.find((p) => p.id === selectedPaperId) ?? null;
      setSelectedPaper(next);
    }
    void loadDuplicates(kbRoot);
  }

  async function loadJobs(kbRoot = savedRoot) {
    if (!kbRoot) return;
    const params = `?root=${encodeURIComponent(kbRoot)}`;
    const data = await request<{ jobs: Job[] }>(`/api/jobs${params}`);
    setJobs(data.jobs);
  }

  async function loadDuplicates(kbRoot = savedRoot) {
    if (!kbRoot) return;
    const params = `?root=${encodeURIComponent(kbRoot)}`;
    const data = await request<{ groups: DuplicateGroup[] }>(`/api/duplicates${params}`);
    setDuplicates(data.groups);
  }

  async function cleanupDuplicates() {
    setBusy("cleanup-duplicates");
    setError("");
    try {
      const params = `?root=${encodeURIComponent(savedRoot)}`;
      await request(`/api/duplicates/cleanup${params}`, { method: "POST" });
      await loadPapers();
      await loadDuplicates();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy("");
    }
  }

  async function saveRoot() {
    setBusy("root");
    setError("");
    try {
      const data = await request<{ root: string }>("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root, claude_api_key: claudeApiKey, claude_endpoint: claudeEndpoint, claude_model: claudeModel, max_concurrency: maxConcurrency }),
      });
      setSavedRoot(data.root);
      setRoot(data.root);
      await loadPapers(data.root);
      await loadJobs(data.root);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy("");
    }
  }

  async function uploadPapers(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []).filter((f) => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf"));
    if (!files.length || !savedRoot) return;
    setBusy("upload");
    setError("");
    setUploadProgress(`0/${files.length}`);
    try {
      for (let i = 0; i < files.length; i++) {
        const form = new FormData();
        form.append("file", files[i]);
        form.append("root", savedRoot);
        form.append("auto_enrich", "true");
        setUploadProgress(`${i + 1}/${files.length}`);
        await request("/api/papers/upload", { method: "POST", body: form });
      }
      await loadPapers();
      await loadJobs();
      setPage("jobs");
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      event.target.value = "";
      setUploadProgress("");
      setBusy("");
    }
  }

  async function openProfile(paperId: string) {
    setBusy("profile");
    setError("");
    setSelectedPaperId(paperId);
    setPage("profile");
    try {
      const params = savedRoot ? `?root=${encodeURIComponent(savedRoot)}` : "";
      const data = await request<{ paper: Paper }>(`/api/papers/${encodeURIComponent(paperId)}${params}`);
      setSelectedPaper(data.paper);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy("");
    }
  }

  async function enrichPaper(paperId: string) {
    setError("");
    try {
      const params = savedRoot ? `?root=${encodeURIComponent(savedRoot)}` : "";
      await request(`/api/papers/${encodeURIComponent(paperId)}/enrich`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root: savedRoot }),
      });
      await loadJobs();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }

  async function translatePaper(paperId: string) {
    setBusy("translate");
    setError("");
    try {
      const data = await request<{ translations: Record<string, string | string[]> }>(
        `/api/papers/${encodeURIComponent(paperId)}/translate`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ root: savedRoot }) }
      );
      if (selectedPaper && selectedPaper.id === paperId) {
        setSelectedPaper({ ...selectedPaper, translations: data.translations });
      }
      await loadPapers();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy("");
    }
  }

  async function enrichAll() {
    setBusy("enrich-all");
    setError("");
    try {
      await request("/api/papers/enrich-all", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root: savedRoot }),
      });
      await loadJobs();
      setPage("jobs");
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy("");
    }
  }

  async function deletePaper(paperId: string) {
    if (!window.confirm(`Delete "${selectedPaper?.title ?? paperId}"? This removes the paper entry and its source PDF.`)) return;
    setBusy("delete");
    setError("");
    try {
      const params = savedRoot ? `?root=${encodeURIComponent(savedRoot)}` : "";
      await request(`/api/papers/${encodeURIComponent(paperId)}${params}`, { method: "DELETE" });
      setSelectedPaperId("");
      setSelectedPaper(null);
      await loadPapers();
      setPage("library");
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy("");
    }
  }

  async function updatePaper(paperId: string, patch: Record<string, unknown>) {
    setBusy("save");
    setError("");
    try {
      const data = await request<{ paper: Paper }>(`/api/papers/${encodeURIComponent(paperId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root: savedRoot, ...patch }),
      });
      setSelectedPaper(data.paper);
      await loadPapers();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy("");
    }
  }

  async function cancelJob(jobId: string) {
    setBusy(`cancel-${jobId}`);
    setError("");
    try {
      await request(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root: savedRoot }),
      });
      await loadJobs();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy("");
    }
  }

  async function deleteJob(jobId: string) {
    setBusy(`delete-${jobId}`);
    setError("");
    try {
      const params = savedRoot ? `?root=${encodeURIComponent(savedRoot)}` : "";
      await request(`/api/jobs/${encodeURIComponent(jobId)}${params}`, { method: "DELETE" });
      await loadJobs();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy("");
    }
  }

  async function cleanupJobs() {
    setBusy("cleanup");
    setError("");
    try {
      const params = savedRoot ? `?root=${encodeURIComponent(savedRoot)}` : "";
      await request(`/api/jobs/cleanup${params}`, { method: "DELETE" });
      await loadJobs();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy("");
    }
  }

  function openPdf(paper: Paper) {
    const params = savedRoot ? `?root=${encodeURIComponent(savedRoot)}` : "";
    window.open(`${API}/api/papers/${encodeURIComponent(paper.id)}/pdf${params}`, "_blank", "noopener,noreferrer");
  }

  return (
    <main className="app">
      <AppNav page={page} setPage={setPage} paperCount={stats.papers} jobCount={activeJobCount} />
      <section className="page-shell">
        {error && <div className="error global-error">{error}</div>}
        {page === "dashboard" && (
          <DashboardPage
            stats={stats} papers={papers} tagCounts={tagCounts}
            authorCounts={authorCounts}
            openProfile={openProfile} uploadPapers={uploadPapers}
            busy={busy} uploadProgress={uploadProgress}
            duplicates={duplicates} cleanupDuplicates={cleanupDuplicates}
          />
        )}
        {page === "library" && (
          <LibraryPage
            papers={papers} filteredPapers={sortedPapers} tagCounts={tagCounts}
            query={query} setQuery={setQuery}
            selectedTag={selectedTag} setSelectedTag={setSelectedTag}
            statusFilter={statusFilter} setStatusFilter={setStatusFilter}
            sortBy={sortBy} setSortBy={setSortBy}
            openProfile={openProfile} uploadPapers={uploadPapers}
            refresh={() => { loadPapers(); loadJobs(); }}
            busy={busy} uploadProgress={uploadProgress}
            paperJobs={paperJobs} enrichAll={enrichAll}
          />
        )}
        {page === "profile" && (
          <ProfilePage
            paper={selectedPaper} busy={busy}
            goBack={() => setPage("library")}
            enrichPaper={enrichPaper} translatePaper={translatePaper}
            updatePaper={updatePaper}
            deletePaper={deletePaper} openPdf={openPdf}
            paperJob={selectedPaperId ? paperJobs.get(selectedPaperId) : undefined}
          />
        )}
        {page === "jobs" && (
          <JobsPage jobs={jobs} refresh={() => loadJobs()} cancelJob={cancelJob} deleteJob={deleteJob} cleanupJobs={cleanupJobs} busy={busy} />
        )}
        {page === "settings" && (
          <SettingsPage
            root={root} setRoot={setRoot}
            claudeEndpoint={claudeEndpoint} setClaudeEndpoint={setClaudeEndpoint}
            claudeApiKey={claudeApiKey} setClaudeApiKey={setClaudeApiKey}
            claudeModel={claudeModel} setClaudeModel={setClaudeModel}
            maxConcurrency={maxConcurrency} setMaxConcurrency={setMaxConcurrency}
            busy={busy} saveRoot={saveRoot}
          />
        )}
      </section>
    </main>
  );
}

// ── Nav ──────────────────────────────────────────────────────────────

function AppNav({ page, setPage, paperCount, jobCount }: { page: Page; setPage: (p: Page) => void; paperCount: number; jobCount: number }) {
  return (
    <header className="app-nav">
      <button className="brand-button" onClick={() => setPage("dashboard")}>
        <img src="/neunote-icon.svg" alt="" width={28} height={28} className="brand-mark" />
        <span><strong>NeuNote</strong><small>{paperCount} entries archived</small></span>
      </button>
      <nav>
        <button className={page === "dashboard" ? "active" : ""} onClick={() => setPage("dashboard")}><Gauge size={16} /> 档案总览</button>
        <button className={page === "library" || page === "profile" ? "active" : ""} onClick={() => setPage("library")}><Library size={16} /> 文献档案</button>
        <button className={page === "jobs" ? "active" : ""} onClick={() => setPage("jobs")}><Play size={16} /> 整理队列 {jobCount > 0 ? jobCount : ""}</button>
        <button className={page === "settings" ? "active" : ""} onClick={() => setPage("settings")}><Settings size={16} /> 设置</button>
      </nav>
    </header>
  );
}

// ── Dashboard ────────────────────────────────────────────────────────

function DashboardPage(props: {
  stats: Stats; papers: Paper[];
  tagCounts: [string, number][];
  authorCounts: [string, number][];
  openProfile: (id: string) => void;
  uploadPapers: (e: React.ChangeEvent<HTMLInputElement>) => void;
  busy: string; uploadProgress: string;
  duplicates: DuplicateGroup[]; cleanupDuplicates: () => void;
}) {
  return (
    <div className="dashboard-page">
      <section className="page-heading inline">
        <div>
          <p className="kicker">纽记</p>
          <h1>文献档案</h1>
          <p>{props.stats.papers} 篇文献 · {props.stats.profiled} 篇已整理 · {props.stats.tags} 个主题标签</p>
        </div>
        <UploadControl busy={props.busy} uploadProgress={props.uploadProgress} uploadPapers={props.uploadPapers} />
      </section>
      <section className="metric-grid">
        <Metric icon={<FileText size={18} />} label="馆藏文献" value={props.stats.papers} />
        <Metric icon={<BookOpenCheck size={18} />} label="已建档" value={props.stats.profiled} />
        <Metric icon={<Sparkles size={18} />} label="待校阅" value={props.stats.needs_review} />
        <Metric icon={<Tags size={18} />} label="主题标签" value={props.stats.tags} />
      </section>
      <section className="dashboard-layout">
        <article className="panel recent-panel">
          <div className="panel-title-row">
            <h2>最近翻阅</h2>
            <span>RECENT FOLIOS</span>
          </div>
          <div className="recent-stack">
            {props.papers.slice(0, 5).map((paper) => (
              <button className="recent-item" key={paper.id} onClick={() => props.openProfile(paper.id)}>
                <span>{paper.year ?? "n.d."}</span>
                <strong>{paper.title || paper.id}</strong>
                <small>{(paper.authors ?? []).slice(0, 3).join(", ") || "Unknown author"}</small>
              </button>
            ))}
            {props.papers.length === 0 && <EmptyState title="档案尚未启封" body="归档第一篇 PDF 后，这里会出现最近整理和翻阅的文献。" />}
          </div>
        </article>
        <div className="panel chart-panel">
          <div className="panel-title-row">
            <h2>主题分布</h2>
            <span>INDEX TERMS</span>
          </div>
          <TagChart tagCounts={props.tagCounts} />
        </div>
        <div className="panel chart-panel">
          <div className="panel-title-row">
            <h2>作者索引</h2>
            <span>AUTHOR CARDS</span>
          </div>
          <AuthorChart authorCounts={props.authorCounts} />
        </div>
      </section>
      {props.duplicates.length > 0 && (
        <DuplicatesSection
          duplicates={props.duplicates}
          openProfile={props.openProfile}
          cleanupDuplicates={props.cleanupDuplicates}
          busy={props.busy}
        />
      )}
    </div>
  );
}

// ── Duplicates Section ───────────────────────────────────────────────

function DuplicatesSection(props: {
  duplicates: DuplicateGroup[];
  openProfile: (id: string) => void;
  cleanupDuplicates: () => void;
  busy: string;
}) {
  const totalDupes = props.duplicates.reduce((sum, g) => sum + g.duplicate_count, 0);
  return (
    <section className="duplicates-section">
      <div className="panel duplicates-panel">
        <div className="duplicates-header">
          <div className="panel-title-row">
            <Copy size={17} />
            <h2>潜在重复文献</h2>
            <span className="duplicates-badge">{props.duplicates.length} 组 · {totalDupes} 篇</span>
          </div>
          <button
            className="danger-button"
            onClick={props.cleanupDuplicates}
            disabled={props.busy === "cleanup-duplicates"}
          >
            {props.busy === "cleanup-duplicates" ? <Loader2 className="spin" size={14} /> : <Trash2 size={14} />}
            一键删除重复文献
          </button>
        </div>
        <div className="duplicates-grid">
          {props.duplicates.map((group) => (
            <div className="duplicate-group-card" key={group.keep_id}>
              <div className="duplicate-group-header">
                <span className="pill warn">{group.duplicate_count} 篇疑似重复</span>
              </div>
              <ul className="duplicate-paper-list">
                {group.papers.map((paper) => (
                  <li key={paper.id} className={paper.id === group.keep_id ? "keep" : "remove"}>
                    <button
                      className="duplicate-paper-btn"
                      onClick={() => props.openProfile(paper.id)}
                    >
                      <span className="dup-indicator">
                        {paper.id === group.keep_id ? "保留" : "重复"}
                      </span>
                      <span className="dup-title">{paper.title || paper.id}</span>
                      <span className="dup-meta">
                        {(paper.authors ?? []).slice(0, 2).join(", ") || "Unknown"}
                        {paper.year ? ` · ${paper.year}` : ""}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return (
    <article className="metric">
      <div>{icon}</div><span>{label}</span><strong>{value}</strong>
    </article>
  );
}

// ── Tag Chart ────────────────────────────────────────────────────────

function TagChart({ tagCounts }: { tagCounts: [string, number][] }) {
  const max = tagCounts[0]?.[1] ?? 1;
  return (
    <div className="bar-chart">
      {tagCounts.map(([tag, count]) => (
        <div className="bar-row" key={tag}>
          <span className="bar-label">{tag}</span>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${(count / max) * 100}%` }} />
          </div>
          <span className="bar-value">{count}</span>
        </div>
      ))}
    </div>
  );
}

// ── Author Chart ─────────────────────────────────────────────────────

function AuthorChart({ authorCounts }: { authorCounts: [string, number][] }) {
  const max = authorCounts[0]?.[1] ?? 1;
  return (
    <div className="bar-chart">
      {authorCounts.map(([author, count]) => (
        <div className="bar-row" key={author}>
          <span className="bar-label">{author}</span>
          <div className="bar-track">
            <div className="bar-fill author-fill" style={{ width: `${(count / max) * 100}%` }} />
          </div>
          <span className="bar-value">{count}</span>
        </div>
      ))}
    </div>
  );
}


// ── Upload ───────────────────────────────────────────────────────────

function UploadControl({ busy, uploadProgress, uploadPapers }: { busy: string; uploadProgress: string; uploadPapers: (e: React.ChangeEvent<HTMLInputElement>) => void }) {
  return (
    <label className="upload-button">
      {busy === "upload" ? <Loader2 className="spin" size={16} /> : <Upload size={16} />}
      <span>{busy === "upload" ? `归档中 ${uploadProgress}` : "归档新文献"}</span>
      <input type="file" accept="application/pdf" multiple onChange={uploadPapers} disabled={busy === "upload"} />
    </label>
  );
}

// ── Library ──────────────────────────────────────────────────────────

function LibraryPage(props: {
  papers: Paper[]; filteredPapers: Paper[]; tagCounts: [string, number][];
  query: string; setQuery: (v: string) => void;
  selectedTag: string; setSelectedTag: (v: string) => void;
  statusFilter: string; setStatusFilter: (v: string) => void;
  sortBy: string; setSortBy: (v: "year" | "added" | "title") => void;
  openProfile: (id: string) => void; uploadPapers: (e: React.ChangeEvent<HTMLInputElement>) => void;
  refresh: () => void; busy: string; uploadProgress: string;
  paperJobs: Map<string, Job>; enrichAll: () => void;
}) {
  return (
    <div className="library-page">
      <section className="page-heading inline">
        <div>
          <p className="kicker">Archive Catalogue</p>
          <h1>文献目录</h1>
          <p>当前显示 {props.filteredPapers.length}/{props.papers.length} 张目录卡</p>
        </div>
        <div className="toolbar">
          <UploadControl busy={props.busy} uploadProgress={props.uploadProgress} uploadPapers={props.uploadPapers} />
          <button onClick={props.refresh}><RefreshCw size={16} /> 刷新</button>
          <button onClick={props.enrichAll} disabled={props.busy === "enrich-all"}>
            <Sparkles size={16} /> 批量整理
          </button>
        </div>
      </section>
      <section className="library-controls">
        <label className="search-box">
          <Search size={16} />
          <input value={props.query} onChange={(e) => props.setQuery(e.target.value)} placeholder="检索题名、作者、期刊、标签..." />
        </label>
        <label className="select-shell">
          <SlidersHorizontal size={15} />
          <select value={props.statusFilter} onChange={(e) => props.setStatusFilter(e.target.value)}>
            <option value="all">全部状态</option>
            <option value="review">待校阅</option>
            <option value="unread">未读</option>
            <option value="reading">阅读中</option>
            <option value="read">已读</option>
            <option value="profiled">已建档</option>
          </select>
        </label>
        <label className="select-shell">
          <ArrowDownUp size={15} />
          <select value={props.sortBy} onChange={(e) => props.setSortBy(e.target.value as "year" | "added" | "title")}>
            <option value="added">最近添加</option>
            <option value="year">发表年份</option>
            <option value="title">标题 A–Z</option>
          </select>
        </label>
      </section>
      <section className="filter-bar">
        <button className={props.selectedTag === "all" ? "active" : ""} onClick={() => props.setSelectedTag("all")}>全部 {props.papers.length}</button>
        {props.tagCounts.map(([tag, count]) => (
          <button className={props.selectedTag === tag ? "active" : ""} key={tag} onClick={() => props.setSelectedTag(tag)}>{tag} {count}</button>
        ))}
      </section>
      <section className="catalogue-grid">
        {props.filteredPapers.map((p, index) => {
          const job = props.paperJobs.get(p.id);
          const jobRunning = job && ["queued", "running"].includes(job.status);
          return (
            <article className="paper-card" key={p.id} style={{ animationDelay: `${Math.min(index * 18, 180)}ms` }}>
              <button className="paper-card-main" onClick={() => props.openProfile(p.id)}>
                <span className="paper-year">{p.year ?? "n.d."}</span>
                <strong>{p.title || p.id}</strong>
                <small>{(p.authors ?? []).slice(0, 4).join(", ") || "Unknown author"}</small>
                <p>{p.one_sentence || p.abstract || "摘要尚未整理。打开文献卡片后可补充摘要、笔记与标签。"}</p>
              </button>
              <div className="paper-card-meta">
                <span className={p.needs_review ? "pill warn" : "pill"}>
                  {p.needs_review ? "待校阅" : statusLabel(p.reading_status ?? "unread")}
                </span>
                {jobRunning
                  ? <span className="pill running" title={`${job.stage} ${job.progress}%`}>{job.progress}%</span>
                  : job?.status === "completed"
                    ? <span className="pill"><CheckCircle2 size={12} /> 已整理</span>
                    : <span className="pill muted"><Clock3 size={12} /> 静置</span>}
                <span className="pill muted">{shortDate(p.updated_at)}</span>
              </div>
              <TagLine tags={p.tags ?? []} />
            </article>
          );
        })}
        {props.filteredPapers.length === 0 && (
          <EmptyState title="档案中暂未找到匹配的文献" body="试试调整关键词、阅读状态或主题标签。" />
        )}
      </section>
    </div>
  );
}

function TagLine({ tags }: { tags: string[] }) {
  if (!tags.length) return <span className="muted">-</span>;
  return <div className="tag-line">{tags.slice(0, 5).map((t) => <span key={t}>{t}</span>)}</div>;
}

function shortDate(value?: string) {
  if (!value) return "-";
  return value.slice(0, 10);
}

function statusLabel(value: string) {
  if (value === "reading") return "阅读中";
  if (value === "read") return "已读";
  return "未读";
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="empty-state">
      <Archive size={28} />
      <strong>{title}</strong>
      <p>{body}</p>
    </div>
  );
}

// ── Profile ──────────────────────────────────────────────────────────

function ProfilePage(props: {
  paper: Paper | null; busy: string;
  goBack: () => void; enrichPaper: (id: string) => void;
  translatePaper: (id: string) => void;
  updatePaper: (id: string, patch: Record<string, unknown>) => void;
  deletePaper: (id: string) => void; openPdf: (p: Paper) => void;
  paperJob?: Job;
}) {
  const paper = props.paper;
  const [tagDraft, setTagDraft] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [notesDraft, setNotesDraft] = useState("");
  const [showChinese, setShowChinese] = useState(false);

  useEffect(() => {
    if (paper) {
      setTagDraft((paper.tags ?? []).join(", "));
      setReviewNote("");
      setNotesDraft(paper.notes ?? "");
      setShowChinese(false);
    }
  }, [paper?.id]);

  if (!paper || props.busy === "profile") {
    return <div className="loading-state"><Loader2 className="spin" size={20} /> Loading paper...</div>;
  }

  const hasZh = Boolean(paper.translations && Object.keys(paper.translations).length > 0);
  const jobRunning = props.paperJob && ["queued", "running"].includes(props.paperJob.status);

  async function handleTranslate() {
    if (showChinese) {
      setShowChinese(false);
      return;
    }
    if (!hasZh) {
      await props.translatePaper(paper!.id);
    }
    setShowChinese(true);
  }

  return (
    <div className="profile-page">
      <section className="page-heading">
        <div className="page-heading-bar">
          <button className="ghost-button" onClick={props.goBack}><ArrowLeft size={16} /> Back</button>
          <div className="profile-actions">
            <button className="action-button" onClick={() => props.openPdf(paper)}><ExternalLink size={15} /> 打开 PDF</button>
            <button className="action-button" onClick={() => props.enrichPaper(paper.id)} disabled={jobRunning}>
              {jobRunning ? <Loader2 className="spin" size={15} /> : <RefreshCw size={15} />}
              {jobRunning ? `整理中 ${props.paperJob?.progress ?? 0}%` : "重新整理"}
            </button>
            <button className="action-button" onClick={handleTranslate} disabled={props.busy === "translate"}>
              {props.busy === "translate" ? <Loader2 className="spin" size={15} /> : null}
              {showChinese ? "English" : "中文"}
            </button>
            <button className="danger-button" onClick={() => props.deletePaper(paper.id)} disabled={props.busy === "delete"}>
              {props.busy === "delete" ? <Loader2 className="spin" size={15} /> : <Trash2 size={15} />} 删除
            </button>
          </div>
        </div>
        <div>
          <p className="kicker">Journal Article Folio</p>
          <h1>{paper.title || paper.id}</h1>
          <p>{paper.id} · {paper.pages ?? "?"} pages · {paper.status}</p>
        </div>
      </section>
      {jobRunning && props.paperJob && (
        <section className="panel job-inline">
          <div className="progress-track"><div className="progress-fill" style={{ width: `${props.paperJob.progress ?? 0}%` }} /></div>
          <p>{props.paperJob.stage} · {props.paperJob.progress ?? 0}%</p>
        </section>
      )}
      <section className="profile-layout">
        <article className="panel profile-main">
          <div className="reader-heading">
            <Bookmark size={18} />
            <h2>文献摘录</h2>
          </div>
          <Field label="一句话摘要" value={showChinese && hasZh ? (paper.translations?.one_sentence as string) : paper.one_sentence} />
          <Field label="研究问题" value={showChinese && hasZh ? (paper.translations?.problem as string) : paper.problem} />
          <ListField label="主要贡献" values={showChinese && hasZh ? (paper.translations?.contributions as string[] || []) : (paper.contributions ?? [])} />
          <ListField label="方法" values={showChinese && hasZh ? (paper.translations?.method as string[] || []) : (paper.method ?? [])} />
          <ListField label="实验" values={showChinese && hasZh ? (paper.translations?.experiments as string[] || []) : (paper.experiments ?? [])} />
          <ListField label="局限" values={showChinese && hasZh ? (paper.translations?.limitations as string[] || []) : (paper.limitations ?? [])} />
          <Field label="摘要" value={showChinese && hasZh ? (paper.translations?.abstract as string) : paper.abstract} />
        </article>
        <aside className="profile-side">
          <section className="panel">
            <h2>题录</h2>
            <Info label="作者" value={(paper.authors ?? []).join(", ") || "Unknown"} />
            <Info label="年份" value={String(paper.year ?? "?")} />
            <Info label="来源" value={paper.venue || "-"} />
            <Info label="DOI" value={paper.doi || "-"} />
            <Info label="arXiv" value={paper.arxiv_id || "-"} />
          </section>
          <section className="panel">
            <h2>馆藏管理</h2>
            <label className="label-stack">
              阅读状态
              <select value={paper.reading_status ?? "unread"} onChange={(e) => props.updatePaper(paper.id, { reading_status: e.target.value })}>
                <option value="unread">未读</option>
                <option value="reading">阅读中</option>
                <option value="read">已读</option>
              </select>
            </label>
            <label className="label-stack">
              优先级
              <select value={paper.priority ?? "normal"} onChange={(e) => props.updatePaper(paper.id, { priority: e.target.value })}>
                <option value="low">低</option>
                <option value="normal">普通</option>
                <option value="high">高</option>
              </select>
            </label>
            <label className="checkbox-row">
              <input type="checkbox" checked={Boolean(paper.needs_review)} onChange={(e) => props.updatePaper(paper.id, { needs_review: e.target.checked })} />
              需要校阅
            </label>
            <label className="label-stack">
              标签
              <textarea value={tagDraft} onChange={(e) => setTagDraft(e.target.value)} rows={3} />
            </label>
            <button onClick={() => props.updatePaper(paper.id, { tags: splitTags(tagDraft) })} disabled={props.busy === "save"}>保存标签</button>
          </section>
          <section className="panel">
            <h2>校阅札记</h2>
            <textarea value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} rows={4} placeholder="添加一条简短校阅札记" />
            <button onClick={() => { props.updatePaper(paper.id, { review_note: reviewNote }); setReviewNote(""); }} disabled={!reviewNote.trim() || props.busy === "save"}>
              添加札记
            </button>
            <ul className="note-list">
              {(paper.review_notes ?? []).map((note, i) => <li key={`note-${i}`}>{note}</li>)}
            </ul>
          </section>
          <section className="panel">
            <h2>边注</h2>
            <textarea value={notesDraft} onChange={(e) => setNotesDraft(e.target.value)} rows={12} />
            <button onClick={() => props.updatePaper(paper.id, { notes: notesDraft })} disabled={props.busy === "save"}>保存边注</button>
          </section>
          <section className="panel">
            <h2>档案信息</h2>
            <Info label="来源文件" value={paper.source_pdf ?? "-"} />
            <Info label="置信度" value={paper.confidence ?? "medium"} />
            <Info label="创建" value={paper.created_at ?? "-"} />
            <Info label="更新" value={paper.updated_at ?? "-"} />
          </section>
        </aside>
      </section>
    </div>
  );
}

function Field({ label, value }: { label: string; value?: string }) {
  return (
    <section className="field-block">
      <h3>{label}</h3>
      <p>{value || "Not extracted yet."}</p>
    </section>
  );
}

function ListField({ label, values }: { label: string; values: string[] }) {
  return (
    <section className="field-block">
      <h3>{label}</h3>
      {values.length ? <ul>{values.map((v, i) => <li key={`${label}-${i}`}>{v}</li>)}</ul> : <p>Not extracted yet.</p>}
    </section>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="info-row"><span>{label}</span><strong>{value}</strong></div>;
}

function splitTags(value: string): string[] {
  return [...new Set(value.split(",").map((t) => t.trim()).filter(Boolean))];
}

// ── Jobs ─────────────────────────────────────────────────────────────

function JobsPage({ jobs, refresh, cancelJob, deleteJob, cleanupJobs, busy }: {
  jobs: Job[]; refresh: () => void;
  cancelJob: (id: string) => void; deleteJob: (id: string) => void;
  cleanupJobs: () => void; busy: string;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  const finishedCount = jobs.filter((j) => ["completed", "failed", "cancelled"].includes(j.status)).length;

  return (
    <div className="jobs-page">
      <section className="page-heading inline">
        <div>
          <p className="kicker">Typesetting Queue</p>
          <h1>整理队列</h1>
          <p>后台文献整理任务，并发数量可在设置中调整。</p>
        </div>
        <div className="toolbar">
          {finishedCount > 0 && (
            <button onClick={cleanupJobs} disabled={busy === "cleanup"}>
              {busy === "cleanup" ? <Loader2 className="spin" size={16} /> : <Trash2 size={16} />}
              清理 {finishedCount} 项
            </button>
          )}
          <button onClick={refresh}><RefreshCw size={16} /> 刷新</button>
        </div>
      </section>
      <section className="jobs-list">
        {jobs.length === 0 && <EmptyState title="排字台暂时空闲" body="归档 PDF 或批量整理后，任务进度会在这里显示。" />}
        {jobs.map((job) => {
          const isExpanded = expanded.has(job.id);
          const hasEvents = (job.events ?? []).length > 0;
          return (
            <article className={`job-card ${job.status}`} key={job.id}>
              <div className="job-card-header">
                <div>
                  <h2>{job.title}</h2>
                  <p>{job.paper_id} · {job.stage}</p>
                </div>
                <span className="job-status">{job.status}</span>
              </div>
              <div className="job-progress-row">
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${Math.max(0, Math.min(100, job.progress || 0))}%` }} />
                </div>
                <span className="job-meta">{job.progress || 0}%</span>
                <div className="job-actions">
                  {hasEvents && (
                    <button className="ghost-button job-toggle-btn" onClick={() => toggle(job.id)} title={isExpanded ? "Collapse" : "Expand"}>
                      {isExpanded ? "▲" : "▼"}
                    </button>
                  )}
                  <button onClick={() => cancelJob(job.id)} disabled={["completed", "failed", "cancelled"].includes(job.status) || busy === `cancel-${job.id}`}>
                    {busy === `cancel-${job.id}` ? <Loader2 className="spin" size={15} /> : <XCircle size={15} />} 取消
                  </button>
                  <button className="danger-button" onClick={() => deleteJob(job.id)} disabled={busy === `delete-${job.id}`}>
                    {busy === `delete-${job.id}` ? <Loader2 className="spin" size={15} /> : <Trash2 size={15} />} 删除
                  </button>
                </div>
              </div>
              {isExpanded && hasEvents && (
                <ul className="job-events">
                  {(job.events ?? []).map((ev, i) => (
                    <li key={`${job.id}-${i}`}><span>{ev.time}</span>{ev.message}</li>
                  ))}
                </ul>
              )}
            </article>
          );
        })}
      </section>
    </div>
  );
}

// ── Settings ─────────────────────────────────────────────────────────

function SettingsPage(props: {
  root: string; setRoot: (v: string) => void;
  claudeEndpoint: string; setClaudeEndpoint: (v: string) => void;
  claudeApiKey: string; setClaudeApiKey: (v: string) => void;
  claudeModel: string; setClaudeModel: (v: string) => void;
  maxConcurrency: number; setMaxConcurrency: (v: number) => void;
  busy: string; saveRoot: () => void;
}) {
  return (
    <div className="settings-page">
      <section className="page-heading">
        <p className="kicker">Press Settings</p>
        <h1>设置</h1>
        <p>配置文献库根目录与自动整理服务。</p>
      </section>
      <section className="settings-grid">
        <div className="panel">
          <label className="label"><FolderCog size={16} /> 文献库根目录</label>
          <div className="root-row">
            <input value={props.root} onChange={(e) => props.setRoot(e.target.value)} placeholder="/path/to/kb" />
          </div>
          <p className="hint">包含 papers/ 与 originals/papers/ 的目录。</p>
        </div>
        <div className="panel">
          <label className="label"><KeyRound size={16} /> Agent API</label>
          <input value={props.claudeEndpoint} onChange={(e) => props.setClaudeEndpoint(e.target.value)} placeholder="Endpoint / base URL (optional)" />
          <input value={props.claudeApiKey} onChange={(e) => props.setClaudeApiKey(e.target.value)} type="password" placeholder="API key" />
          <input value={props.claudeModel} onChange={(e) => props.setClaudeModel(e.target.value)} placeholder="Model, e.g. sonnet" />
        </div>
        <div className="panel">
          <label className="label"><Play size={16} /> 并行整理</label>
          <label className="label-stack">
            最大并发任务
            <input type="number" min={1} max={20} value={props.maxConcurrency} onChange={(e) => props.setMaxConcurrency(Number(e.target.value) || 1)} />
          </label>
          <p className="hint">同时整理的文献数量，通常建议 4–8。</p>
        </div>
      </section>
      <button onClick={props.saveRoot} disabled={props.busy === "root"} className="save-settings-btn">
        {props.busy === "root" ? <Loader2 className="spin" size={16} /> : null}
        保存设置
      </button>
    </div>
  );
}

// ── mount ────────────────────────────────────────────────────────────

createRoot(document.getElementById("root")!).render(<App />);
