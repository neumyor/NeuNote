import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowLeft,
  BookOpenCheck,
  Database,
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
  Sparkles,
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
  const [stats, setStats] = useState<Stats>({ papers: 0, needs_review: 0, profiled: 0, tags: 0 });
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedPaperId, setSelectedPaperId] = useState("");
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);
  const [query, setQuery] = useState("");
  const [selectedTag, setSelectedTag] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
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
  }

  async function loadJobs(kbRoot = savedRoot) {
    if (!kbRoot) return;
    const params = `?root=${encodeURIComponent(kbRoot)}`;
    const data = await request<{ jobs: Job[] }>(`/api/jobs${params}`);
    setJobs(data.jobs);
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
            authorCounts={authorCounts} dailyActivity={dailyActivity}
            openProfile={openProfile} uploadPapers={uploadPapers}
            busy={busy} uploadProgress={uploadProgress}
          />
        )}
        {page === "library" && (
          <LibraryPage
            papers={papers} filteredPapers={filteredPapers} tagCounts={tagCounts}
            query={query} setQuery={setQuery}
            selectedTag={selectedTag} setSelectedTag={setSelectedTag}
            statusFilter={statusFilter} setStatusFilter={setStatusFilter}
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
        <Database size={20} />
        <span><strong>Readinglist</strong><small>{paperCount} papers</small></span>
      </button>
      <nav>
        <button className={page === "dashboard" ? "active" : ""} onClick={() => setPage("dashboard")}><Gauge size={16} /> Dashboard</button>
        <button className={page === "library" || page === "profile" ? "active" : ""} onClick={() => setPage("library")}><Library size={16} /> Library</button>
        <button className={page === "jobs" ? "active" : ""} onClick={() => setPage("jobs")}><Play size={16} /> Jobs {jobCount > 0 ? jobCount : ""}</button>
        <button className={page === "settings" ? "active" : ""} onClick={() => setPage("settings")}><Settings size={16} /> Settings</button>
      </nav>
    </header>
  );
}

// ── Dashboard ────────────────────────────────────────────────────────

function DashboardPage(props: {
  stats: Stats; papers: Paper[];
  tagCounts: [string, number][];
  authorCounts: [string, number][];
  dailyActivity: Map<string, number>;
  openProfile: (id: string) => void;
  uploadPapers: (e: React.ChangeEvent<HTMLInputElement>) => void;
  busy: string; uploadProgress: string;
}) {
  return (
    <div className="dashboard-page">
      <section className="page-heading inline">
        <div>
          <h1>Dashboard</h1>
          <p>{props.stats.papers} papers · {props.stats.profiled} profiled · {props.stats.tags} tags</p>
        </div>
        <UploadControl busy={props.busy} uploadProgress={props.uploadProgress} uploadPapers={props.uploadPapers} />
      </section>
      <section className="metric-grid">
        <Metric icon={<FileText size={18} />} label="Papers" value={props.stats.papers} />
        <Metric icon={<BookOpenCheck size={18} />} label="Profiled" value={props.stats.profiled} />
        <Metric icon={<Sparkles size={18} />} label="Needs review" value={props.stats.needs_review} />
        <Metric icon={<Database size={18} />} label="Tags" value={props.stats.tags} />
      </section>
      <section className="dashboard-charts">
        <div className="panel chart-panel">
          <h2>Tags Distribution</h2>
          <TagChart tagCounts={props.tagCounts} />
        </div>
        <div className="panel chart-panel">
          <h2>Top Authors</h2>
          <AuthorChart authorCounts={props.authorCounts} />
        </div>
        <div className="panel chart-panel chart-wide">
          <h2>Activity</h2>
          <ActivityHeatmap dailyActivity={props.dailyActivity} />
        </div>
      </section>
    </div>
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

// ── Activity Heatmap ─────────────────────────────────────────────────

function ActivityHeatmap({ dailyActivity }: { dailyActivity: Map<string, number> }) {
  const today = new Date();
  const weeks = 20;
  const days: { date: string; count: number }[] = [];
  for (let w = weeks - 1; w >= 0; w--) {
    for (let d = 6; d >= 0; d--) {
      const dt = new Date(today);
      dt.setDate(dt.getDate() - (w * 7 + (6 - d)));
      days.push({ date: dt.toISOString().slice(0, 10), count: dailyActivity.get(dt.toISOString().slice(0, 10)) ?? 0 });
    }
  }
  const maxCount = Math.max(1, ...days.map((d) => d.count));
  const color = (count: number) => {
    if (count === 0) return "var(--rail)";
    const p = count / maxCount;
    if (p < 0.25) return "#bfd6c2";
    if (p < 0.5) return "#7baa82";
    if (p < 0.75) return "#4d7a56";
    return "#1f3328";
  };
  const dayLabels = ["", "Mon", "", "Wed", "", "Fri", ""];

  return (
    <div className="heatmap-wrap">
      <div className="heatmap-inner">
        <div className="heatmap-y-labels">
          {dayLabels.map((l, i) => <span key={i}>{l}</span>)}
        </div>
        <div className="heatmap-cells">
          {Array.from({ length: weeks }, (_, w) => (
            <div className="heatmap-week" key={w}>
              {Array.from({ length: 7 }, (_, d) => {
                const day = days[w * 7 + d];
                const dt = new Date(day.date + "T00:00:00");
                const showMonth = dt.getDate() <= 7;
                return (
                  <div className="heatmap-cell-wrap" key={d}>
                    <div
                      className="heatmap-cell"
                      style={{ background: color(day.count) }}
                      title={`${day.date}: ${day.count} updates`}
                    />
                    {showMonth && d === 0 && (
                      <span className="heatmap-month">{dt.toLocaleString("en", { month: "short" })}</span>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
      <div className="heatmap-legend">
        <span>Less</span>
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="legend-cell" style={{ background: i === 0 ? "var(--rail)" : color((i / 4) * maxCount) }} />
        ))}
        <span>More</span>
      </div>
    </div>
  );
}

// ── Upload ───────────────────────────────────────────────────────────

function UploadControl({ busy, uploadProgress, uploadPapers }: { busy: string; uploadProgress: string; uploadPapers: (e: React.ChangeEvent<HTMLInputElement>) => void }) {
  return (
    <label className="upload-button">
      <Upload size={16} />
      <span>{busy === "upload" ? `Uploading ${uploadProgress}` : "Upload PDFs"}</span>
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
  openProfile: (id: string) => void; uploadPapers: (e: React.ChangeEvent<HTMLInputElement>) => void;
  refresh: () => void; busy: string; uploadProgress: string;
  paperJobs: Map<string, Job>; enrichAll: () => void;
}) {
  return (
    <div className="library-page">
      <section className="page-heading inline">
        <div>
          <h1>Library</h1>
          <p>{props.filteredPapers.length}/{props.papers.length} papers visible</p>
        </div>
        <div className="toolbar">
          <UploadControl busy={props.busy} uploadProgress={props.uploadProgress} uploadPapers={props.uploadPapers} />
          <button onClick={props.refresh}><RefreshCw size={16} /> Refresh</button>
          <button onClick={props.enrichAll} disabled={props.busy === "enrich-all"}>
            <Sparkles size={16} /> Enrich all
          </button>
        </div>
      </section>
      <section className="library-controls">
        <label className="search-box">
          <Search size={16} />
          <input value={props.query} onChange={(e) => props.setQuery(e.target.value)} placeholder="Search title, author, venue, tag..." />
        </label>
        <select value={props.statusFilter} onChange={(e) => props.setStatusFilter(e.target.value)}>
          <option value="all">All states</option>
          <option value="review">Needs review</option>
          <option value="unread">Unread</option>
          <option value="reading">Reading</option>
          <option value="read">Read</option>
          <option value="profiled">Profiled</option>
        </select>
      </section>
      <section className="filter-bar">
        <button className={props.selectedTag === "all" ? "active" : ""} onClick={() => props.setSelectedTag("all")}>All {props.papers.length}</button>
        {props.tagCounts.map(([tag, count]) => (
          <button className={props.selectedTag === tag ? "active" : ""} key={tag} onClick={() => props.setSelectedTag(tag)}>{tag} {count}</button>
        ))}
      </section>
      <section className="table-wrap">
        <table className="paper-table">
          <thead>
            <tr>
              <th>Paper</th><th>Year</th><th>Status</th><th>Job</th><th>Priority</th><th>Tags</th><th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {props.filteredPapers.map((p) => {
              const job = props.paperJobs.get(p.id);
              const jobRunning = job && ["queued", "running"].includes(job.status);
              return (
                <tr key={p.id} onClick={() => props.openProfile(p.id)}>
                  <td><strong>{p.title || p.id}</strong><small>{p.id}</small></td>
                  <td>{p.year ?? "?"}</td>
                  <td>
                    <span className={p.needs_review ? "pill warn" : "pill"}>
                      {p.needs_review ? "review" : p.reading_status ?? "unread"}
                    </span>
                  </td>
                  <td>
                    {jobRunning
                      ? <span className="pill running" title={`${job.stage} ${job.progress}%`}>{job.progress}%</span>
                      : job?.status === "completed"
                        ? <span className="pill">done</span>
                        : <span className="pill muted">-</span>}
                  </td>
                  <td>{p.priority ?? "normal"}</td>
                  <td><TagLine tags={p.tags ?? []} /></td>
                  <td>{shortDate(p.updated_at)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {props.filteredPapers.length === 0 && <div className="empty">No papers match the current filters.</div>}
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
      <section className="page-heading inline">
        <div>
          <button className="ghost-button" onClick={props.goBack}><ArrowLeft size={16} /> Back</button>
          <h1>{paper.title || paper.id}</h1>
          <p>{paper.id} · {paper.pages ?? "?"} pages · {paper.status}</p>
        </div>
        <div className="toolbar">
          <button onClick={() => props.openPdf(paper)}><ExternalLink size={16} /> PDF</button>
          <button onClick={() => props.enrichPaper(paper.id)} disabled={jobRunning}>
            {jobRunning ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
            {jobRunning ? ` Enriching ${props.paperJob?.progress ?? 0}%` : " Enrich"}
          </button>
          <button onClick={handleTranslate} disabled={props.busy === "translate"}>
            {props.busy === "translate" ? <Loader2 className="spin" size={16} /> : showChinese ? "EN" : "中"}
            {showChinese ? "英文" : "中文"}
          </button>
          <button className="danger-button" onClick={() => props.deletePaper(paper.id)} disabled={props.busy === "delete"}>
            {props.busy === "delete" ? <Loader2 className="spin" size={16} /> : <Trash2 size={16} />} Delete
          </button>
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
          <h2>Summary</h2>
          <Field label="One sentence" value={showChinese && hasZh ? (paper.translations?.one_sentence as string) : paper.one_sentence} />
          <Field label="Problem" value={showChinese && hasZh ? (paper.translations?.problem as string) : paper.problem} />
          <ListField label="Contributions" values={showChinese && hasZh ? (paper.translations?.contributions as string[] || []) : (paper.contributions ?? [])} />
          <ListField label="Method" values={showChinese && hasZh ? (paper.translations?.method as string[] || []) : (paper.method ?? [])} />
          <ListField label="Experiments" values={showChinese && hasZh ? (paper.translations?.experiments as string[] || []) : (paper.experiments ?? [])} />
          <ListField label="Limitations" values={showChinese && hasZh ? (paper.translations?.limitations as string[] || []) : (paper.limitations ?? [])} />
          <Field label="Abstract" value={showChinese && hasZh ? (paper.translations?.abstract as string) : paper.abstract} />
        </article>
        <aside className="profile-side">
          <section className="panel">
            <h2>Identity</h2>
            <Info label="Authors" value={(paper.authors ?? []).join(", ") || "Unknown"} />
            <Info label="Year" value={String(paper.year ?? "?")} />
            <Info label="Venue" value={paper.venue || "-"} />
            <Info label="DOI" value={paper.doi || "-"} />
            <Info label="arXiv" value={paper.arxiv_id || "-"} />
          </section>
          <section className="panel">
            <h2>Management</h2>
            <label className="label-stack">
              Reading status
              <select value={paper.reading_status ?? "unread"} onChange={(e) => props.updatePaper(paper.id, { reading_status: e.target.value })}>
                <option value="unread">Unread</option>
                <option value="reading">Reading</option>
                <option value="read">Read</option>
              </select>
            </label>
            <label className="label-stack">
              Priority
              <select value={paper.priority ?? "normal"} onChange={(e) => props.updatePaper(paper.id, { priority: e.target.value })}>
                <option value="low">Low</option>
                <option value="normal">Normal</option>
                <option value="high">High</option>
              </select>
            </label>
            <label className="checkbox-row">
              <input type="checkbox" checked={Boolean(paper.needs_review)} onChange={(e) => props.updatePaper(paper.id, { needs_review: e.target.checked })} />
              Needs review
            </label>
            <label className="label-stack">
              Tags
              <textarea value={tagDraft} onChange={(e) => setTagDraft(e.target.value)} rows={3} />
            </label>
            <button onClick={() => props.updatePaper(paper.id, { tags: splitTags(tagDraft) })} disabled={props.busy === "save"}>Save tags</button>
          </section>
          <section className="panel">
            <h2>Review Notes</h2>
            <textarea value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} rows={4} placeholder="Add a short review note" />
            <button onClick={() => { props.updatePaper(paper.id, { review_note: reviewNote }); setReviewNote(""); }} disabled={!reviewNote.trim() || props.busy === "save"}>
              Add note
            </button>
            <ul className="note-list">
              {(paper.review_notes ?? []).map((note, i) => <li key={`note-${i}`}>{note}</li>)}
            </ul>
          </section>
          <section className="panel">
            <h2>Notes</h2>
            <textarea value={notesDraft} onChange={(e) => setNotesDraft(e.target.value)} rows={12} />
            <button onClick={() => props.updatePaper(paper.id, { notes: notesDraft })} disabled={props.busy === "save"}>Save notes</button>
          </section>
          <section className="panel">
            <h2>Info</h2>
            <Info label="Source" value={paper.source_pdf ?? "-"} />
            <Info label="Confidence" value={paper.confidence ?? "medium"} />
            <Info label="Created" value={paper.created_at ?? "-"} />
            <Info label="Updated" value={paper.updated_at ?? "-"} />
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
          <h1>Jobs</h1>
          <p>Background enrichment jobs. Max concurrency configured in Settings.</p>
        </div>
        <div className="toolbar">
          {finishedCount > 0 && (
            <button onClick={cleanupJobs} disabled={busy === "cleanup"}>
              {busy === "cleanup" ? <Loader2 className="spin" size={16} /> : <Trash2 size={16} />}
              Clear {finishedCount} finished
            </button>
          )}
          <button onClick={refresh}><RefreshCw size={16} /> Refresh</button>
        </div>
      </section>
      <section className="jobs-list">
        {jobs.length === 0 && <div className="empty">No jobs yet. Upload papers or click "Enrich all" to start.</div>}
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
                    {busy === `cancel-${job.id}` ? <Loader2 className="spin" size={15} /> : <XCircle size={15} />} Cancel
                  </button>
                  <button className="danger-button" onClick={() => deleteJob(job.id)} disabled={busy === `delete-${job.id}`}>
                    {busy === `delete-${job.id}` ? <Loader2 className="spin" size={15} /> : <Trash2 size={15} />} Delete
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
        <h1>Settings</h1>
        <p>Configure the knowledge root and enrichment settings.</p>
      </section>
      <section className="settings-grid">
        <div className="panel">
          <label className="label"><FolderCog size={16} /> Knowledge Root</label>
          <div className="root-row">
            <input value={props.root} onChange={(e) => props.setRoot(e.target.value)} placeholder="/path/to/kb" />
          </div>
          <p className="hint">Directory containing papers/ and originals/papers/.</p>
        </div>
        <div className="panel">
          <label className="label"><KeyRound size={16} /> Agent API</label>
          <input value={props.claudeEndpoint} onChange={(e) => props.setClaudeEndpoint(e.target.value)} placeholder="Endpoint / base URL (optional)" />
          <input value={props.claudeApiKey} onChange={(e) => props.setClaudeApiKey(e.target.value)} type="password" placeholder="API key" />
          <input value={props.claudeModel} onChange={(e) => props.setClaudeModel(e.target.value)} placeholder="Model, e.g. sonnet" />
        </div>
        <div className="panel">
          <label className="label"><Play size={16} /> Parallel Enrichment</label>
          <label className="label-stack">
            Max concurrent jobs
            <input type="number" min={1} max={20} value={props.maxConcurrency} onChange={(e) => props.setMaxConcurrency(Number(e.target.value) || 1)} />
          </label>
          <p className="hint">How many papers to enrich in parallel. 4–8 recommended.</p>
        </div>
      </section>
      <button onClick={props.saveRoot} disabled={props.busy === "root"} className="save-settings-btn">
        {props.busy === "root" ? <Loader2 className="spin" size={16} /> : null}
        Save settings
      </button>
    </div>
  );
}

// ── mount ────────────────────────────────────────────────────────────

createRoot(document.getElementById("root")!).render(<App />);
