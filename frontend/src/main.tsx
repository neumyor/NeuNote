import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import "katex/dist/katex.min.css";
import {
  ArrowDownUp,
  ArrowLeft,
  Archive,
  BookOpen,
  BookOpenCheck,
  Bookmark,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CloudUpload,
  Copy,
  Download,
  Bot,
  ExternalLink,
  FileText,
  FolderCog,
  Gauge,
  Globe,
  GitBranch,
  HardDrive,
  KeyRound,
  Languages,
  Library,
  Loader2,
  MessageCircle,
  Minus,
  MoreHorizontal,
  Play,
  Plus,
  RefreshCw,
  Search,
  SendHorizontal,
  Server,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Square,
  Tags,
  Trash2,
  Upload,
  UserRound,
  Wrench,
  XCircle,
  Zap,
} from "lucide-react";
import "./styles.css";

type Page = "dashboard" | "library" | "review-search" | "profile" | "chat" | "jobs" | "settings";
type SummaryLanguage = "en" | "zh";
type MinerUExtractionMode = "auto" | "precision" | "flash";
type CoreConcept = { concept: string; explanation: string };
type TranslatedCoreConcept = { concept_en: string; concept_zh?: string; explanation_zh: string };
type KeyFigure = {
  title: string;
  page: number;
  caption?: string;
  reason?: string;
  image_path?: string;
};
type TranslatedKeyFigure = {
  title_en?: string;
  title_zh?: string;
  caption_en?: string;
  caption_zh?: string;
  reason_en?: string;
  reason_zh?: string;
};

type Paper = {
  id: string;
  title: string;
  authors: string[];
  author_affiliations?: string[];
  year: number | null;
  venue: string;
  doi: string;
  arxiv_id: string;
  source_pdf: string;
  paper_url?: string;
  pdf_url?: string;
  download_status?: "not_downloaded" | "downloading" | "downloaded" | "failed";
  download_error?: string;
  downloaded_at?: string | null;
  index_status?: "not_indexed" | "indexing" | "indexed" | "failed";
  index_error?: string;
  indexed_at?: string | null;
  pages: number | null;
  tags: string[];
  status: string;
  confidence: string;
  reading_status: string;
  priority: string;
  needs_review: boolean;
  abstract: string;
  core_concepts?: CoreConcept[];
  key_figures?: KeyFigure[];
  one_sentence: string;
  problem: string;
  contributions: string[];
  method: string[];
  experiments: string[];
  limitations: string[];
  notes: string;
  review_notes: string[];
  agent_reviews: any[];
  translations?: Record<string, unknown>;
  translation_meta?: { engine?: string; model?: string | null; updated_at?: string };
  created_at: string;
  updated_at: string;
  last_read_at?: string;
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
  kind?: "enrichment" | "metadata_search" | "metadata_import" | "pdf_download" | "fulltext_index";
  status: string;
  stage: string;
  progress: number;
  created_at?: string;
  updated_at?: string;
  started_at?: string | null;
  completed_at?: string | null;
  attempts?: number;
  last_error?: string | null;
  pause_reason?: string | null;
  events?: { time: string; message: string }[];
};

type QueueStatus = {
  paused: boolean;
  updated_at?: string;
  counts?: Record<string, number>;
  running_job_ids?: string[];
};

type ChatSessionSummary = {
  id: string;
  title: string;
  created_at?: string;
  updated_at?: string;
  message_count: number;
};

type SyncStatus = {
  enabled: boolean;
  available: boolean;
  repository: boolean;
  branch?: string;
  remote?: string;
  remote_configured?: boolean;
  pending_files?: number;
  paths: string[];
  last_commit?: string;
  detail: string;
  message?: string;
  inventory?: {
    paper_records: number;
    pdf_files: number;
    figure_files: number;
    chat_sessions: number;
    complete: boolean;
    invalid_papers: string[];
    missing_pdf_references: string[];
    missing_figure_references: string[];
  };
  auto_sync?: {
    enabled: boolean;
    interval_minutes: number;
    running: boolean;
    last_attempt_at?: string | null;
    last_success_at?: string | null;
    last_error?: string | null;
    next_sync_at?: string | null;
  };
};

type ChatToolCall = {
  id: string;
  name: string;
  input?: unknown;
  result?: unknown;
  detail?: string;
  resultDetail?: string;
  isError?: boolean;
  state: "running" | "done";
};

type ChatSegment =
  | { id: string; type: "text"; content: string }
  | { id: string; type: "tool"; tool: ChatToolCall };

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  paperIds?: string[];
  tools?: ChatToolCall[];
  segments?: ChatSegment[];
  pending?: boolean;
};

const API = "";

function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const [profileReturnPage, setProfileReturnPage] = useState<Page>("library");
  const [root, setRoot] = useState("");
  const [savedRoot, setSavedRoot] = useState("");
  const [claudeApiKey, setClaudeApiKey] = useState("");
  const [claudeEndpoint, setClaudeEndpoint] = useState("");
  const [claudeModel, setClaudeModel] = useState("sonnet");
  const [translationEngine, setTranslationEngine] = useState<"local" | "llm">("llm");
  const [defaultSummaryLanguage, setDefaultSummaryLanguage] = useState<SummaryLanguage>("en");
  const [mineruApiToken, setMineruApiToken] = useState("");
  const [mineruExtractionMode, setMineruExtractionMode] = useState<MinerUExtractionMode>("auto");
  const [mineruModel, setMineruModel] = useState<"vlm" | "pipeline">("vlm");
  const [mineruAllowRemote, setMineruAllowRemote] = useState(true);
  const [maxConcurrency, setMaxConcurrency] = useState(4);
  const [syncMode, setSyncMode] = useState<"local" | "git">("local");
  const [gitRemote, setGitRemote] = useState("origin");
  const [gitRemoteUrl, setGitRemoteUrl] = useState("");
  const [gitBranch, setGitBranch] = useState("main");
  const [gitSyncPdfs, setGitSyncPdfs] = useState(false);
  const [gitSyncChats, setGitSyncChats] = useState(false);
  const [gitAutoSync, setGitAutoSync] = useState(false);
  const [gitSyncIntervalMinutes, setGitSyncIntervalMinutes] = useState(10);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [stats, setStats] = useState<Stats>({ papers: 0, needs_review: 0, profiled: 0, tags: 0, duplicate_groups: 0, duplicate_papers: 0 });
  const [jobs, setJobs] = useState<Job[]>([]);
  const [queueStatus, setQueueStatus] = useState<QueueStatus>({ paused: false });
  const [duplicates, setDuplicates] = useState<DuplicateGroup[]>([]);
  const [selectedPaperId, _setSelectedPaperId] = useState("");
  const [selectedPaper, _setSelectedPaper] = useState<Paper | null>(null);
  // Wrap setSelectedPaperId so the ref updates *synchronously* in the same
  // tick as the state setter, with no useEffect-induced render-cycle delay.
  const selectedPaperIdRef = useRef(selectedPaperId);
  const setSelectedPaperId = (id: string) => {
    selectedPaperIdRef.current = id;
    _setSelectedPaperId(id);
  };
  // Mirror selectedPaper the same way: async callbacks (translatePaper,
  // updatePaper, ...) need the *latest* paper object when they spread it,
  // not a stale-closure snapshot from the render they were defined in.
  const selectedPaperRef = useRef<Paper | null>(selectedPaper);
  const setSelectedPaper = (p: Paper | null) => {
    selectedPaperRef.current = p;
    _setSelectedPaper(p);
  };
  // Guard: only write selectedPaper if the user is still viewing the same
  // paper. Async fetches that resolve after the user has navigated away
  // must not clobber the now-current view.
  const setSelectedPaperIfCurrent = (paperId: string, p: Paper | null) => {
    if (selectedPaperIdRef.current === paperId) setSelectedPaper(p);
  };
  // Monotonic sequence number for openProfile() calls. A stale fetch that
  // resolves after a newer click must not clobber the newer paper's state.
  const openProfileSeq = useRef(0);
  const activeJobRefreshInFlight = useRef(false);
  const [query, setQuery] = useState("");
  const [selectedTag, setSelectedTag] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sortBy, setSortBy] = useState<"year" | "added" | "title">("added");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [uploadProgress, setUploadProgress] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatSessionId, setChatSessionId] = useState<string | null>(null);
  const [chatSessions, setChatSessions] = useState<ChatSessionSummary[]>([]);
  const [mentionedPaperIds, setMentionedPaperIds] = useState<string[]>([]);
  const [mentionedTags, setMentionedTags] = useState<string[]>([]);
  const chatAbortRef = useRef<AbortController | null>(null);

  const activeJobCount = jobs.filter((j) => ["queued", "running", "paused"].includes(j.status)).length;

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
    const refreshActiveJobs = () => {
      if (activeJobRefreshInFlight.current) return;
      activeJobRefreshInFlight.current = true;
      void Promise.all([loadJobs(), loadPapers()])
        .catch((err) => setError(String((err as Error).message ?? err)))
        .finally(() => { activeJobRefreshInFlight.current = false; });
    };
    refreshActiveJobs();
    const timer = window.setInterval(refreshActiveJobs, 1600);
    return () => window.clearInterval(timer);
  }, [savedRoot, activeJobCount]);

  useEffect(() => {
    if (page !== "settings" || !savedRoot) return;
    void loadSyncStatus(savedRoot);
    const timer = window.setInterval(() => { void loadSyncStatus(savedRoot); }, 5000);
    return () => window.clearInterval(timer);
  }, [page, savedRoot]);

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
    const data = await request<{
      root: string;
      claude_api_key?: string;
      claude_endpoint?: string;
      claude_model?: string;
      max_concurrency?: number;
      translation_engine?: "local" | "llm";
      default_summary_language?: SummaryLanguage;
      mineru_api_token?: string;
      mineru_extraction_mode?: MinerUExtractionMode;
      mineru_model?: "vlm" | "pipeline";
      mineru_allow_remote?: boolean;
      sync_mode?: "local" | "git";
      git_remote?: string;
      git_remote_url?: string;
      git_branch?: string;
      git_sync_pdfs?: boolean;
      git_sync_chats?: boolean;
      git_auto_sync?: boolean;
      git_sync_interval_minutes?: number;
    }>("/api/config");
    setRoot(data.root);
    setSavedRoot(data.root);
    setClaudeApiKey(data.claude_api_key ?? "");
    setClaudeEndpoint(data.claude_endpoint ?? "");
    setClaudeModel(data.claude_model ?? "sonnet");
    setMaxConcurrency(data.max_concurrency ?? 4);
    setTranslationEngine(data.translation_engine ?? "local");
    setDefaultSummaryLanguage(data.default_summary_language ?? "en");
    setMineruApiToken(data.mineru_api_token ?? "");
    setMineruExtractionMode(data.mineru_extraction_mode ?? "auto");
    setMineruModel(data.mineru_model ?? "vlm");
    setMineruAllowRemote(data.mineru_allow_remote ?? true);
    setSyncMode(data.sync_mode ?? "local");
    setGitRemote(data.git_remote ?? "origin");
    setGitRemoteUrl(data.git_remote_url ?? "");
    setGitBranch(data.git_branch ?? "main");
    setGitSyncPdfs(data.git_sync_pdfs ?? false);
    setGitSyncChats(data.git_sync_chats ?? false);
    setGitAutoSync(data.git_auto_sync ?? false);
    setGitSyncIntervalMinutes(data.git_sync_interval_minutes ?? 10);
    await loadPapers(data.root);
    await loadJobs(data.root);
    await loadDuplicates(data.root);
    await loadSessions(data.root);
    await loadSyncStatus(data.root);
  }

  async function loadSyncStatus(kbRoot = savedRoot) {
    if (!kbRoot) return;
    const params = `?root=${encodeURIComponent(kbRoot)}`;
    const data = await request<SyncStatus>(`/api/sync/status${params}`);
    setSyncStatus(data);
  }

  async function loadPapers(kbRoot = savedRoot) {
    if (!kbRoot) return;
    const params = `?root=${encodeURIComponent(kbRoot)}`;
    const data = await request<{ papers: Paper[]; stats: Stats }>(`/api/papers${params}`);
    setPapers(data.papers);
    setStats(data.stats);
    // Read the live id from the ref so that this interval-driven refresh
    // syncs whichever paper the user is *currently* viewing, not whichever
    // paper they were viewing when the interval was registered.
    const liveId = selectedPaperIdRef.current;
    if (liveId) {
      const next = data.papers.find((p) => p.id === liveId) ?? null;
      const selected = selectedPaperRef.current;
      // /api/papers returns compact list records. Keep the full detail record
      // that is already on screen and only refresh its list-level fields.
      if (selected && next) setSelectedPaper({ ...selected, ...next });
    }
  }

  async function loadJobs(kbRoot = savedRoot) {
    if (!kbRoot) return;
    const params = `?root=${encodeURIComponent(kbRoot)}`;
    const data = await request<{ jobs: Job[]; queue?: QueueStatus }>(`/api/jobs${params}`);
    setJobs(data.jobs);
    if (data.queue) setQueueStatus(data.queue);
  }

  async function loadSessions(kbRoot = savedRoot) {
    if (!kbRoot) return;
    const params = `?root=${encodeURIComponent(kbRoot)}`;
    const data = await request<{ sessions: ChatSessionSummary[] }>(`/api/sessions${params}`);
    setChatSessions(data.sessions);
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
      const data = await request<{
        root: string;
        translation_engine?: "local" | "llm";
        default_summary_language?: SummaryLanguage;
        mineru_extraction_mode?: MinerUExtractionMode;
        mineru_model?: "vlm" | "pipeline";
        mineru_allow_remote?: boolean;
      }>("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          root,
          claude_api_key: claudeApiKey,
          claude_endpoint: claudeEndpoint,
          claude_model: claudeModel,
          max_concurrency: maxConcurrency,
          translation_engine: translationEngine,
          default_summary_language: defaultSummaryLanguage,
          mineru_api_token: mineruApiToken,
          mineru_extraction_mode: mineruExtractionMode,
          mineru_model: mineruModel,
          mineru_allow_remote: mineruAllowRemote,
          sync_mode: syncMode,
          git_remote: gitRemote,
          git_remote_url: gitRemoteUrl,
          git_branch: gitBranch,
          git_sync_pdfs: gitSyncPdfs,
          git_sync_chats: gitSyncChats,
          git_auto_sync: gitAutoSync,
          git_sync_interval_minutes: gitSyncIntervalMinutes,
        }),
      });
      setSavedRoot(data.root);
      setRoot(data.root);
      if (data.translation_engine) setTranslationEngine(data.translation_engine);
      if (data.default_summary_language) setDefaultSummaryLanguage(data.default_summary_language);
      if (data.mineru_extraction_mode) setMineruExtractionMode(data.mineru_extraction_mode);
      if (data.mineru_model) setMineruModel(data.mineru_model);
      if (typeof data.mineru_allow_remote === "boolean") setMineruAllowRemote(data.mineru_allow_remote);
      await loadPapers(data.root);
      await loadDuplicates(data.root);
      await loadJobs(data.root);
      await loadSessions(data.root);
      await loadSyncStatus(data.root);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy("");
    }
  }

  async function syncNow() {
    setBusy("git-sync");
    setError("");
    try {
      await request("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          root, claude_api_key: claudeApiKey, claude_endpoint: claudeEndpoint,
          claude_model: claudeModel, max_concurrency: maxConcurrency,
          translation_engine: translationEngine,
          default_summary_language: defaultSummaryLanguage,
          mineru_api_token: mineruApiToken,
          mineru_extraction_mode: mineruExtractionMode,
          mineru_model: mineruModel,
          mineru_allow_remote: mineruAllowRemote,
          sync_mode: syncMode,
          git_remote: gitRemote, git_remote_url: gitRemoteUrl,
          git_branch: gitBranch, git_sync_pdfs: gitSyncPdfs,
          git_sync_chats: gitSyncChats,
          git_auto_sync: gitAutoSync,
          git_sync_interval_minutes: gitSyncIntervalMinutes,
        }),
      });
      const data = await request<SyncStatus>("/api/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root }),
      });
      setSyncStatus(data);
      await loadPapers(root);
      await loadSessions(root);
      await loadSyncStatus(root);
    } catch (err) {
      setError(String((err as Error).message ?? err));
      await loadSyncStatus(root).catch(() => undefined);
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
      await loadDuplicates();
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
    // Bump the sequence; any earlier in-flight call will see the mismatch
    // when its fetch resolves and bail out instead of clobbering state.
    const seq = ++openProfileSeq.current;
    setBusy("profile");
    setError("");
    if (page !== "profile") setProfileReturnPage(page);
    setSelectedPaperId(paperId);
    setPage("profile");
    try {
      const params = savedRoot ? `?root=${encodeURIComponent(savedRoot)}` : "";
      const data = await request<{ paper: Paper }>(`/api/papers/${encodeURIComponent(paperId)}${params}`);
      if (seq !== openProfileSeq.current) return; // stale, newer click won
      setSelectedPaper(data.paper);
      // Marking a paper as read writes the whole YAML record. It is useful,
      // but must not keep the detail page in its loading state.
      void request<{ paper: Paper }>(`/api/papers/${encodeURIComponent(paperId)}/viewed`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root: savedRoot }),
      }).then((viewed) => {
        if (seq !== openProfileSeq.current) return;
        setSelectedPaper(viewed.paper);
        setPapers((prev) => prev.map((paper) => (
          paper.id === paperId ? { ...paper, ...viewed.paper } : paper
        )));
      }).catch(() => undefined);
    } catch (err) {
      if (seq !== openProfileSeq.current) return; // stale, don't surface error
      setError(String((err as Error).message ?? err));
    } finally {
      if (seq === openProfileSeq.current) setBusy("");
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

  async function downloadPaper(paper: Paper) {
    const url = paper.pdf_url?.trim();
    if (!url) { setError("这篇论文没有可用的 PDF 链接。"); return; }
    setError("");
    try {
      const proposed = await request<{ action: { id: string } }>("/api/librarian/download/propose", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root: savedRoot, paper_ids: [paper.id] }),
      });
      if (!window.confirm(`确认下载《${paper.title || paper.id}》的 PDF？`)) return;
      await request(`/api/librarian/actions/${encodeURIComponent(proposed.action.id)}/confirm-download`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root: savedRoot }),
      });
      await loadJobs(); await loadPapers(); setPage("jobs");
    } catch (err) { setError(String((err as Error).message ?? err)); }
  }

  async function indexPaper(paper: Paper) {
    setError("");
    try {
      await request(`/api/papers/${encodeURIComponent(paper.id)}/index`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root: savedRoot }),
      });
      await loadJobs(); setPage("jobs");
    } catch (err) { setError(String((err as Error).message ?? err)); }
  }

  async function confirmLibrarianAction(action: { action_id: string; kind?: string; candidate_count?: number }) {
    const isDownload = action.kind === "pdf_download";
    const label = isDownload ? "下载所列 PDF" : `将 ${action.candidate_count ?? "这些"} 篇论文元信息加入馆藏`;
    if (!window.confirm(`图书管理员请求确认：${label}？`)) return;
    const endpoint = isDownload ? "confirm-download" : "confirm-import";
    await request(`/api/librarian/actions/${encodeURIComponent(action.action_id)}/${endpoint}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ root: savedRoot }),
    });
    await loadPapers(); await loadJobs();
  }

  async function translatePaper(paperId: string) {
    setBusy("translate");
    setError("");
    try {
      const data = await request<{ paper?: Paper; translations: Record<string, unknown>; translation_meta?: Paper["translation_meta"] }>(
        `/api/papers/${encodeURIComponent(paperId)}/translate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            root: savedRoot,
            translation_engine: translationEngine,
            claude_api_key: claudeApiKey,
            claude_endpoint: claudeEndpoint,
            claude_model: claudeModel,
          }),
        }
      );
      // Spread from selectedPaperRef (live) so concurrent fields updated by
      // loadPapers during the await aren't clobbered. Guard on id to avoid
      // clobbering a different paper the user has navigated to.
      if (selectedPaperIdRef.current === paperId && selectedPaperRef.current) {
        setSelectedPaper(data.paper ?? {
          ...selectedPaperRef.current,
          translations: data.translations,
          translation_meta: data.translation_meta,
        });
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

  async function enrichSelectedPapers(paperIds: string[]) {
    if (!paperIds.length) return;
    setBusy("enrich-selected");
    setError("");
    try {
      await request("/api/papers/enrich-batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root: savedRoot, paper_ids: paperIds }),
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
      // Guard: don't clobber selectedPaper if the user has navigated away.
      setSelectedPaperIfCurrent(paperId, data.paper);
      await loadPapers();
    } catch (err) {
      setError(String((err as Error).message ?? err));
      throw err;
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

  async function jobAction(jobId: string, action: "pause" | "resume" | "retry") {
    setBusy(`${action}-${jobId}`);
    setError("");
    try {
      await request(`/api/jobs/${encodeURIComponent(jobId)}/${action}`, {
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

  async function setQueuePaused(paused: boolean) {
    setBusy(paused ? "pause-queue" : "resume-queue");
    setError("");
    try {
      await request(paused ? "/api/jobs/pause" : "/api/jobs/resume", {
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

  async function batchJobAction(jobIds: string[], action: "pause" | "resume" | "retry" | "cancel") {
    if (!jobIds.length) return;
    setBusy(`batch-${action}`);
    setError("");
    try {
      await request(`/api/jobs/batch/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root: savedRoot, job_ids: jobIds }),
      });
      await loadJobs();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy("");
    }
  }

  async function cancelAllJobs() {
    setBusy("cancel-all");
    setError("");
    try {
      await request("/api/jobs/cancel-all", {
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

  function openPaperChat(paper: Paper) {
    setMentionedPaperIds([paper.id]);
    setMentionedTags([]);
    setChatMessages([]);
    setChatSessionId(null);
    setError("");
    setPage("chat");
  }

  function openGeneralChat() {
    setMentionedPaperIds([]);
    setMentionedTags([]);
    setChatMessages([]);
    setChatSessionId(null);
    setError("");
    setPage("chat");
  }

  async function loadChatSession(sessionId: string) {
    setBusy("chat-session");
    setError("");
    try {
      const params = savedRoot ? `?root=${encodeURIComponent(savedRoot)}` : "";
      const data = await request<{ session: any }>(`/api/sessions/${encodeURIComponent(sessionId)}${params}`);
      const messages = (data.session?.messages ?? []).map(sessionMessageToChatMessage);
      setChatSessionId(data.session?.id ?? sessionId);
      setChatMessages(messages);
      setMentionedPaperIds(extractSessionPaperIds(data.session));
      setMentionedTags([]);
      setPage("chat");
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy("");
    }
  }

  async function deleteChatSession(sessionId: string) {
    if (!window.confirm("删除这段对话？此操作会移除本地历史记录。")) return;
    setBusy(`delete-session-${sessionId}`);
    setError("");
    try {
      const params = savedRoot ? `?root=${encodeURIComponent(savedRoot)}` : "";
      const data = await request<{ sessions: ChatSessionSummary[] }>(`/api/sessions/${encodeURIComponent(sessionId)}${params}`, {
        method: "DELETE",
      });
      setChatSessions(data.sessions);
      if (chatSessionId === sessionId) {
        setChatSessionId(null);
        setChatMessages([]);
        setMentionedPaperIds([]);
        setMentionedTags([]);
      }
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy("");
    }
  }

  function stopChat() {
    chatAbortRef.current?.abort();
    chatAbortRef.current = null;
    setBusy("");
    setChatMessages((prev) => prev.map((m) => m.pending ? { ...m, pending: false } : m));
  }

  async function sendChatMessage(question: string) {
    if (!question.trim() || busy === "chat") return;
    const paperIds = expandMentionedPaperIds(papers, mentionedPaperIds, mentionedTags);
    const userMessage: ChatMessage = { id: `user-${Date.now()}`, role: "user", content: question.trim(), paperIds };
    const assistantId = `assistant-${Date.now()}`;
    const assistantMessage: ChatMessage = { id: assistantId, role: "assistant", content: "", tools: [], segments: [], pending: true };
    setChatMessages((prev) => [...prev, userMessage, assistantMessage]);
    setBusy("chat");
    setError("");

    const controller = new AbortController();
    chatAbortRef.current = controller;
    try {
      const response = await fetch(`${API}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          root: savedRoot,
          session_id: chatSessionId,
          paper_ids: paperIds,
          tag_mentions: mentionedTags,
          question: question.trim(),
          claude_api_key: claudeApiKey,
          claude_endpoint: claudeEndpoint,
          claude_model: claudeModel,
        }),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        let detail = response.statusText;
        try { detail = (await response.json()).detail ?? detail; } catch { /* */ }
        throw new Error(detail);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() ?? "";
        for (const chunk of chunks) {
          const dataLine = chunk.split("\n").find((line) => line.startsWith("data:"));
          if (!dataLine) continue;
          const payload = JSON.parse(dataLine.slice(5).trim()) as Record<string, any>;
          if (payload.type === "session" && payload.session?.id) {
            setChatSessionId(payload.session.id);
          } else if (payload.type === "delta") {
            const delta = String(payload.delta ?? "");
            setChatMessages((prev) => prev.map((m) => (
              m.id === assistantId ? appendTextSegment(m, delta) : m
            )));
          } else if (payload.type === "tool") {
            const tool: ChatToolCall = {
              id: String(payload.id ?? `${payload.name}-${Date.now()}`),
              name: String(payload.name ?? "tool"),
              input: payload.input,
              detail: payload.detail,
              state: "running",
            };
            setChatMessages((prev) => prev.map((m) => (
              m.id === assistantId
                ? { ...m, tools: [...(m.tools ?? []), tool], segments: [...(m.segments ?? []), { id: tool.id, type: "tool", tool }] }
                : m
            )));
          } else if (payload.type === "tool_result") {
            const toolId = String(payload.tool_use_id ?? "");
            setChatMessages((prev) => prev.map((m) => (
              m.id === assistantId
                ? {
                    ...m,
                    tools: (m.tools ?? []).map((tool) => (
                      tool.id === toolId ? completeToolCall(tool, payload) : tool
                    )),
                    segments: (m.segments ?? []).map((segment) => (
                      segment.type === "tool" && segment.tool.id === toolId
                        ? { ...segment, tool: completeToolCall(segment.tool, payload) }
                        : segment
                    )),
                  }
                : m
            )));
            const action = extractLibrarianAction(payload.result);
            if (action) void confirmLibrarianAction(action).catch((err) => setError(String((err as Error).message ?? err)));
          } else if (payload.type === "done") {
            if (payload.session?.id) setChatSessionId(payload.session.id);
            void loadSessions();
            setChatMessages((prev) => prev.map((m) => (
              m.id === assistantId ? { ...m, pending: false } : m
            )));
          } else if (payload.type === "error") {
            throw new Error(String(payload.detail ?? "Chat failed."));
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError(String((err as Error).message ?? err));
        setChatMessages((prev) => prev.map((m) => (
          m.id === assistantId
            ? { ...m, content: m.content || "抱歉，当前对话请求失败。", pending: false }
            : m
        )));
      }
    } finally {
      if (chatAbortRef.current === controller) chatAbortRef.current = null;
      setBusy("");
    }
  }

  return (
    <main className="app">
      <AppNav page={page} setPage={setPage} openChat={openGeneralChat} paperCount={stats.papers} jobCount={activeJobCount} />
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
            paperJobs={paperJobs} enrichAll={enrichAll} enrichSelectedPapers={enrichSelectedPapers}
            openReviewSearch={() => setPage("review-search")}
          />
        )}
        {page === "review-search" && (
          <ReviewNotesSearchPage
            papers={papers}
            openProfile={openProfile}
            goBack={() => setPage("library")}
          />
        )}
        {page === "profile" && (
          <ProfilePage
            paper={selectedPaper} busy={busy}
            goBack={() => setPage(profileReturnPage)}
            openChat={openPaperChat}
            enrichPaper={enrichPaper} translatePaper={translatePaper}
            updatePaper={updatePaper}
            deletePaper={deletePaper} openPdf={openPdf}
            downloadPaper={downloadPaper} indexPaper={indexPaper}
            paperJob={selectedPaperId ? paperJobs.get(selectedPaperId) : undefined}
            tagCounts={tagCounts}
            defaultSummaryLanguage={defaultSummaryLanguage}
            translationEngine={translationEngine}
            kbRoot={savedRoot}
          />
        )}
        {page === "chat" && (
          <ChatPage
            papers={papers}
            sessions={chatSessions}
            activeSessionId={chatSessionId}
            mentionedPaperIds={mentionedPaperIds}
            setMentionedPaperIds={setMentionedPaperIds}
            mentionedTags={mentionedTags}
            setMentionedTags={setMentionedTags}
            messages={chatMessages}
            kbRoot={savedRoot}
            busy={busy}
            newChat={openGeneralChat}
            openSession={loadChatSession}
            deleteSession={deleteChatSession}
            openPdf={openPdf}
            sendMessage={sendChatMessage}
            stopChat={stopChat}
          />
        )}
        {page === "jobs" && (
          <JobsPage
            jobs={jobs}
            queueStatus={queueStatus}
            refresh={() => loadJobs()}
            cancelJob={cancelJob}
            cancelAllJobs={cancelAllJobs}
            pauseJob={(id) => jobAction(id, "pause")}
            resumeJob={(id) => jobAction(id, "resume")}
            retryJob={(id) => jobAction(id, "retry")}
            setQueuePaused={setQueuePaused}
            batchJobAction={batchJobAction}
            deleteJob={deleteJob}
            cleanupJobs={cleanupJobs}
            busy={busy}
          />
        )}
        {page === "settings" && (
          <SettingsPage
            root={root} setRoot={setRoot}
            claudeEndpoint={claudeEndpoint} setClaudeEndpoint={setClaudeEndpoint}
            claudeApiKey={claudeApiKey} setClaudeApiKey={setClaudeApiKey}
            claudeModel={claudeModel} setClaudeModel={setClaudeModel}
            maxConcurrency={maxConcurrency} setMaxConcurrency={setMaxConcurrency}
            translationEngine={translationEngine} setTranslationEngine={setTranslationEngine}
            defaultSummaryLanguage={defaultSummaryLanguage} setDefaultSummaryLanguage={setDefaultSummaryLanguage}
            mineruApiToken={mineruApiToken} setMineruApiToken={setMineruApiToken}
            mineruExtractionMode={mineruExtractionMode} setMineruExtractionMode={setMineruExtractionMode}
            mineruModel={mineruModel} setMineruModel={setMineruModel}
            mineruAllowRemote={mineruAllowRemote} setMineruAllowRemote={setMineruAllowRemote}
            syncMode={syncMode} setSyncMode={setSyncMode}
            gitRemote={gitRemote} setGitRemote={setGitRemote}
            gitRemoteUrl={gitRemoteUrl} setGitRemoteUrl={setGitRemoteUrl}
            gitBranch={gitBranch} setGitBranch={setGitBranch}
            gitSyncPdfs={gitSyncPdfs} setGitSyncPdfs={setGitSyncPdfs}
            gitSyncChats={gitSyncChats} setGitSyncChats={setGitSyncChats}
            gitAutoSync={gitAutoSync} setGitAutoSync={setGitAutoSync}
            gitSyncIntervalMinutes={gitSyncIntervalMinutes} setGitSyncIntervalMinutes={setGitSyncIntervalMinutes}
            syncStatus={syncStatus} syncNow={syncNow}
            busy={busy} saveRoot={saveRoot}
          />
        )}
      </section>
    </main>
  );
}

// ── Nav ──────────────────────────────────────────────────────────────

function AppNav({ page, setPage, openChat, paperCount, jobCount }: {
  page: Page;
  setPage: (p: Page) => void;
  openChat: () => void;
  paperCount: number;
  jobCount: number;
}) {
  return (
    <header className="app-nav">
      <button className="brand-button" onClick={() => setPage("dashboard")}>
        <img src="/neunote-icon.svg" alt="" width={28} height={28} className="brand-mark" />
        <span><strong>纽记 NeuNote</strong><small>已收录 {paperCount} 篇文献</small></span>
      </button>
      <nav>
        <button className={page === "dashboard" ? "active" : ""} onClick={() => setPage("dashboard")}><Gauge size={16} /> 档案总览</button>
        <button className={["library", "review-search", "profile"].includes(page) ? "active" : ""} onClick={() => setPage("library")}><Library size={16} /> 文献档案</button>
        <button className={page === "chat" ? "active" : ""} onClick={openChat}><MessageCircle size={16} /> 图书管理员</button>
        <button className={page === "jobs" ? "active" : ""} onClick={() => setPage("jobs")}>
          <Play size={16} /> 整理队列
          {jobCount > 0 && <span className="nav-count">{jobCount}</span>}
        </button>
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
  const recentPapers = [...props.papers]
    .filter((paper) => Boolean(paper.last_read_at))
    .sort((a, b) => (b.last_read_at ?? "").localeCompare(a.last_read_at ?? ""))
    .slice(0, 5);

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
            <span>最近翻阅</span>
          </div>
          <div className="recent-stack">
            {recentPapers.map((paper) => (
              <button className="recent-item" key={paper.id} onClick={() => props.openProfile(paper.id)}>
                <span>{paper.year ?? "n.d."}</span>
                <strong>{paper.title || paper.id}</strong>
                <small>{(paper.authors ?? []).slice(0, 3).join(", ") || "Unknown author"}</small>
              </button>
            ))}
            {recentPapers.length === 0 && <EmptyState title="暂无翻阅记录" body="打开一篇论文详情后，这里会显示最近翻阅的文献。" />}
          </div>
        </article>
        <div className="panel chart-panel">
          <div className="panel-title-row">
            <h2>主题分布</h2>
            <span>主题索引</span>
          </div>
          <TagChart tagCounts={props.tagCounts} />
        </div>
        <div className="panel chart-panel">
          <div className="panel-title-row">
            <h2>作者索引</h2>
            <span>作者索引</span>
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
      <span>{busy === "upload" ? `归档中 ${uploadProgress}` : "上传文献"}</span>
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
  paperJobs: Map<string, Job>; enrichAll: () => void; enrichSelectedPapers: (ids: string[]) => void; openReviewSearch: () => void;
}) {
  const [selectedPaperIds, setSelectedPaperIds] = useState<Set<string>>(new Set());
  const visibleIds = props.filteredPapers.map((paper) => paper.id);
  const selectedVisibleCount = visibleIds.filter((id) => selectedPaperIds.has(id)).length;
  const selectedIds = Array.from(selectedPaperIds);

  function togglePaperSelection(id: string) {
    setSelectedPaperIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function toggleVisibleSelection() {
    setSelectedPaperIds((prev) => {
      const next = new Set(prev);
      const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => next.has(id));
      for (const id of visibleIds) {
        if (allVisibleSelected) next.delete(id);
        else next.add(id);
      }
      return next;
    });
  }

  function startSelectedEnrichment() {
    props.enrichSelectedPapers(selectedIds);
    setSelectedPaperIds(new Set());
  }

  return (
    <div className="library-page">
      <section className="page-heading inline">
        <div>
          <p className="kicker">文献档案目录</p>
          <h1>文献目录</h1>
          <p>当前显示 {props.filteredPapers.length}/{props.papers.length} 张目录卡</p>
        </div>
        <div className="toolbar">
          <UploadControl busy={props.busy} uploadProgress={props.uploadProgress} uploadPapers={props.uploadPapers} />
          <button className="icon-button toolbar-icon-button" onClick={props.refresh} aria-label="刷新文献目录" title="刷新文献目录">
            <RefreshCw size={16} />
          </button>
          <details className="action-menu">
            <summary aria-label="更多文献操作" title="更多文献操作"><MoreHorizontal size={18} /></summary>
            <div className="action-menu-popover">
              <button onClick={props.enrichAll} disabled={props.busy === "enrich-all"}>
                <Sparkles size={16} /> 批量整理全部文献
              </button>
              <button onClick={props.openReviewSearch}>
                <Search size={16} /> 搜索校阅札记
              </button>
            </div>
          </details>
        </div>
      </section>
      <section className="library-bulk-bar">
        <label className="bulk-select-toggle">
          <input
            type="checkbox"
            checked={visibleIds.length > 0 && selectedVisibleCount === visibleIds.length}
            onChange={toggleVisibleSelection}
          />
          <span>{selectedIds.length ? `已选择 ${selectedIds.length} 篇` : "多选文献"}</span>
        </label>
        <div className="bulk-actions">
          {selectedIds.length > 0 && (
            <>
              <button type="button" onClick={startSelectedEnrichment} disabled={props.busy === "enrich-selected"}>
                {props.busy === "enrich-selected" ? <Loader2 className="spin" size={15} /> : <Sparkles size={15} />}
                整理所选
              </button>
              <button type="button" className="ghost-button" onClick={() => setSelectedPaperIds(new Set())}>清除选择</button>
            </>
          )}
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
          const jobRunning = job && ["queued", "running", "paused"].includes(job.status);
          return (
            <article className="paper-card" key={p.id} style={{ animationDelay: `${Math.min(index * 18, 180)}ms` }}>
              <label className="paper-select-check" title="选择文献">
                <input
                  type="checkbox"
                  checked={selectedPaperIds.has(p.id)}
                  onChange={() => togglePaperSelection(p.id)}
                  onClick={(event) => event.stopPropagation()}
                />
              </label>
              <button className="paper-card-main" onClick={() => props.openProfile(p.id)}>
                <span className="paper-year">{p.year ?? "n.d."}</span>
                <strong>{p.title || p.id}</strong>
                <small>{(p.authors ?? []).slice(0, 4).join(", ") || "Unknown author"}</small>
                <p>{p.one_sentence || p.abstract || "摘要尚未整理。打开文献卡片后可补充摘要、笔记与标签。"}</p>
              </button>
              <div className="paper-card-meta">
                {p.needs_review && <span className="pill warn">待校阅</span>}
                <span className={`pill ${p.download_status === "failed" ? "warn" : "muted"}`}>{downloadStatusLabel(p.download_status)}</span>
                {p.download_status === "downloaded" && <span className={`pill ${p.index_status === "failed" ? "warn" : "muted"}`}>{indexStatusLabel(p.index_status)}</span>}
                {jobRunning
                  ? <span className="pill running" title={`${job.stage} ${job.progress}%`}>{job.progress}%</span>
                  : job?.status === "completed"
                    ? <span className="pill"><CheckCircle2 size={12} /> 已整理</span>
                    : null}
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

type ReviewSearchHit = {
  paper: Paper;
  note: ReviewNote;
  noteIndex: number;
  snippet: string;
  score: number;
};

function ReviewNotesSearchPage({ papers, openProfile, goBack }: {
  papers: Paper[];
  openProfile: (id: string) => void;
  goBack: () => void;
}) {
  const [query, setQuery] = useState("");
  const noteCount = useMemo(() => papers.reduce((sum, paper) => sum + normalizeReviewNotes(paper.review_notes).length, 0), [papers]);
  const results = useMemo(() => searchReviewNotes(papers, query), [papers, query]);
  const terms = useMemo(() => tokenizeSearch(query), [query]);
  const hasQuery = query.trim().length > 0;

  return (
    <div className="review-search-page">
      <section className="review-search-hero">
        <button type="button" className="ghost-button back-button" onClick={goBack}>
          <ArrowLeft size={15} /> 返回文献档案
        </button>
        <div className="review-search-brand">
          <p className="kicker">校阅札记检索</p>
          <h1>校阅札记搜索</h1>
          <p>在 {papers.length} 篇论文的 {noteCount} 条校阅札记中检索。</p>
        </div>
        <label className="review-search-box">
          <Search size={22} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
            placeholder="搜索方法、问题、实验、局限或你的校阅判断..."
          />
        </label>
      </section>

      <section className="review-search-results">
        {hasQuery && (
          <div className="review-search-summary">
            <span>{results.length} 条结果</span>
            <small>点击任一卡片进入对应论文详情</small>
          </div>
        )}
        {!hasQuery && (
          <EmptyState title="输入关键词开始搜索" body="校阅札记正文、论文题名、作者和标签都会参与匹配。" />
        )}
        {hasQuery && results.length === 0 && (
          <EmptyState title="未找到相关校阅札记" body="换一个关键词，或先在论文详情页补充校阅札记。" />
        )}
        <div className="review-note-result-list">
          {results.map((hit) => (
            <button
              type="button"
              className="review-note-result-card"
              key={`${hit.paper.id}-${hit.noteIndex}-${hit.note.created_at ?? "note"}`}
              onClick={() => openProfile(hit.paper.id)}
            >
              <div className="review-note-result-meta">
                <span>{formatReviewTime(hit.note.created_at)}</span>
                <span>{hit.paper.year ?? "n.d."}</span>
              </div>
              <strong>{hit.paper.title || hit.paper.id}</strong>
              <small>{(hit.paper.authors ?? []).slice(0, 3).join(", ") || "Unknown author"}</small>
              <p><HighlightedText text={hit.snippet} terms={terms} /></p>
              <TagLine tags={hit.paper.tags ?? []} />
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

function searchReviewNotes(papers: Paper[], rawQuery: string): ReviewSearchHit[] {
  const terms = tokenizeSearch(rawQuery);
  if (!terms.length) return [];
  const hits: ReviewSearchHit[] = [];
  for (const paper of papers) {
    const haystackMeta = [
      paper.title,
      ...(paper.authors ?? []),
      ...(paper.tags ?? []),
      paper.venue,
      String(paper.year ?? ""),
    ].join(" ").toLowerCase();
    const notes = normalizeReviewNotes(paper.review_notes);
    notes.forEach((note, noteIndex) => {
      const text = note.text.trim();
      if (!text) return;
      const lowerText = text.toLowerCase();
      const matchedTerms = terms.filter((term) => lowerText.includes(term) || haystackMeta.includes(term));
      if (!matchedTerms.length) return;
      const textMatches = matchedTerms.filter((term) => lowerText.includes(term)).length;
      const metaMatches = matchedTerms.length - textMatches;
      hits.push({
        paper,
        note,
        noteIndex,
        snippet: makeSearchSnippet(text, matchedTerms),
        score: textMatches * 10 + metaMatches * 3 + Math.min(text.length / 240, 2),
      });
    });
  }
  return hits.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    return (b.note.created_at ?? "").localeCompare(a.note.created_at ?? "");
  });
}

function tokenizeSearch(raw: string): string[] {
  return Array.from(new Set(raw.toLowerCase().split(/[\s,，。；;：:、]+/).map((term) => term.trim()).filter(Boolean)));
}

function makeSearchSnippet(text: string, terms: string[]): string {
  const normalized = text.replace(/\s+/g, " ").trim();
  const lower = normalized.toLowerCase();
  const firstIndex = terms.reduce((best, term) => {
    const idx = lower.indexOf(term);
    if (idx < 0) return best;
    return best < 0 ? idx : Math.min(best, idx);
  }, -1);
  if (firstIndex < 0) return normalized.slice(0, 220);
  const start = Math.max(0, firstIndex - 80);
  const end = Math.min(normalized.length, firstIndex + 180);
  return `${start > 0 ? "..." : ""}${normalized.slice(start, end)}${end < normalized.length ? "..." : ""}`;
}

function HighlightedText({ text, terms }: { text: string; terms: string[] }) {
  if (!terms.length) return <>{text}</>;
  const pattern = new RegExp(`(${terms.map(escapeRegExp).join("|")})`, "ig");
  return (
    <>
      {text.split(pattern).map((part, i) => (
        terms.includes(part.toLowerCase())
          ? <mark key={`${part}-${i}`}>{part}</mark>
          : <React.Fragment key={`${part}-${i}`}>{part}</React.Fragment>
      ))}
    </>
  );
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function TagLine({ tags }: { tags: string[] }) {
  if (!tags.length) return <span className="muted">-</span>;
  return <div className="tag-line">{tags.slice(0, 5).map((t) => <span key={t}>{t}</span>)}</div>;
}

function shortDate(value?: string) {
  if (!value) return "-";
  return value.slice(0, 10);
}

function downloadStatusLabel(status?: Paper["download_status"]) {
  return ({ not_downloaded: "仅元信息", downloading: "下载中", downloaded: "已下载", failed: "下载失败" } as Record<string, string>)[status ?? "not_downloaded"];
}

function indexStatusLabel(status?: Paper["index_status"]) {
  return ({ not_indexed: "未索引", indexing: "索引中", indexed: "可全文检索", failed: "索引失败" } as Record<string, string>)[status ?? "not_indexed"];
}

function jobKindLabel(kind?: Job["kind"]) {
  return ({ enrichment: "论文整理", metadata_search: "网络检索", metadata_import: "元信息入馆", pdf_download: "PDF 下载", fulltext_index: "全文索引" } as Record<string, string>)[kind ?? "enrichment"];
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

// ── shared helpers (Layer 1) ─────────────────────────────────────

type ReviewNote = { text: string; created_at?: string | null };

function normalizeReviewNotes(input: unknown): ReviewNote[] {
  if (!Array.isArray(input)) return [];
  return input.map((item) => {
    if (typeof item === "string") return { text: item, created_at: null };
    if (item && typeof item === "object") {
      const o = item as Record<string, unknown>;
      return {
        text: String(o.text ?? ""),
        created_at: (o.created_at as string | null | undefined) ?? null,
      };
    }
    return { text: String(item), created_at: null };
  });
}

function reviewNotesEqual(a: ReviewNote[], b: ReviewNote[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i].text !== b[i].text) return false;
    if ((a[i].created_at ?? null) !== (b[i].created_at ?? null)) return false;
  }
  return true;
}

function tagSetEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const s = new Set(a);
  for (const x of b) if (!s.has(x)) return false;
  return true;
}

function slugifyTag(raw: string): string {
  return raw.trim().toLowerCase().replace(/\s+/g, "_");
}

function nowIso(): string {
  return new Date().toISOString();
}

function formatReviewTime(iso: string | null | undefined): string {
  if (!iso) return "时间未知";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "时间未知";
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) return `今天 ${d.toTimeString().slice(0, 5)}`;
  const sameYear = d.getFullYear() === now.getFullYear();
  return sameYear
    ? `${d.getMonth() + 1}/${d.getDate()} ${d.toTimeString().slice(0, 5)}`
    : `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
}

// ── TagEditor (chip-based, debounced auto-save, autocomplete) ─────

function TagEditor(props: {
  tags: string[];
  knownTags: string[];
  busy: boolean;
  onCommit: (next: string[]) => void;
}) {
  const [local, setLocal] = useState<string[]>(props.tags);
  const [input, setInput] = useState("");
  const [focused, setFocused] = useState(false);
  const lastSentRef = useRef<string[]>(props.tags);

  useEffect(() => {
    if (tagSetEqual(local, lastSentRef.current)) return;
    const t = window.setTimeout(() => {
      lastSentRef.current = local;
      props.onCommit(local);
    }, 500);
    return () => window.clearTimeout(t);
  }, [local]);

  const suggestions = useMemo(() => {
    const q = input.trim().toLowerCase();
    if (!q || !focused) return [];
    return props.knownTags
      .filter((t) => t !== q && t.startsWith(q) && !local.includes(t))
      .slice(0, 6);
  }, [input, props.knownTags, local, focused]);

  function commit(next: string[]) {
    const dedup = Array.from(new Set(next.map(slugifyTag).filter(Boolean)));
    setLocal(dedup);
  }

  function addTag(raw: string) {
    const t = slugifyTag(raw);
    if (!t || local.includes(t)) { setInput(""); return; }
    commit([...local, t]);
    setInput("");
  }

  function removeTag(t: string) {
    commit(local.filter((x) => x !== t));
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTag(input);
    } else if (e.key === "Backspace" && !input && local.length) {
      e.preventDefault();
      removeTag(local[local.length - 1]);
    } else if (e.key === "Escape") {
      setInput("");
    }
  }

  return (
    <div className="tag-editor">
      <div className="chip-row">
        {local.map((t) => (
          <span className="chip" key={t}>
            <span className="chip-text">{t}</span>
            <button
              className="chip-x"
              type="button"
              onClick={() => removeTag(t)}
              aria-label={`remove ${t}`}
            >×</button>
          </span>
        ))}
        <input
          className="chip-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          onFocus={() => setFocused(true)}
          onBlur={() => { setFocused(false); if (input.trim()) addTag(input); }}
          placeholder={local.length ? "" : "添加标签…"}
        />
      </div>
      {suggestions.length > 0 && (
        <ul className="chip-suggestions" role="listbox">
          {suggestions.map((s) => (
            <li key={s}>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => addTag(s)}
              >{s}</button>
            </li>
          ))}
        </ul>
      )}
      <div className="chip-hint">
        {props.busy ? "保存中…" : "Enter / 逗号 添加 · Backspace 删除 · Esc 取消"}
      </div>
    </div>
  );
}

// ── ReviewNotesEditor (timestamps, delete, edit, search) ──────────

function ReviewNotesEditor(props: {
  notes: ReviewNote[];
  busy: boolean;
  onCommit: (next: ReviewNote[]) => void;
}) {
  const [local, setLocal] = useState<ReviewNote[]>(props.notes);
  const [input, setInput] = useState("");
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [editingText, setEditingText] = useState("");
  const [filter, setFilter] = useState("");
  const lastSentRef = useRef<ReviewNote[]>(props.notes);

  useEffect(() => {
    if (reviewNotesEqual(local, lastSentRef.current)) return;
    const t = window.setTimeout(() => {
      lastSentRef.current = local;
      props.onCommit(local);
    }, 500);
    return () => window.clearTimeout(t);
  }, [local]);

  function add() {
    const text = input.trim();
    if (!text) return;
    setLocal([...local, { text, created_at: nowIso() }]);
    setInput("");
  }

  function removeAt(idx: number) {
    if (!window.confirm("删除这条校阅札记？")) return;
    setLocal(local.filter((_, i) => i !== idx));
  }

  function startEdit(idx: number) {
    setEditingIdx(idx);
    setEditingText(local[idx].text);
  }

  function commitEdit() {
    if (editingIdx === null) return;
    const text = editingText.trim();
    if (!text) return;
    const next = [...local];
    next[editingIdx] = { ...next[editingIdx], text };
    setLocal(next);
    setEditingIdx(null);
    setEditingText("");
  }

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return local;
    return local.filter((n) => n.text.toLowerCase().includes(q));
  }, [local, filter]);

  const ordered = useMemo(() => [...visible].reverse(), [visible]);

  return (
    <div className="review-notes-editor">
      <div className="review-notes-input">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              add();
            }
          }}
          rows={3}
          placeholder="写一条校阅札记…  (Cmd/Ctrl + Enter 添加)"
        />
        <button type="button" onClick={add} disabled={!input.trim() || props.busy}>
          添加札记
        </button>
      </div>
      {local.length > 0 && (
        <div className="review-notes-filter">
          <Search size={14} />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="过滤札记…"
          />
        </div>
      )}
      {ordered.length === 0 ? (
        local.length > 0 ? (
          <p className="muted small">没有匹配的札记</p>
        ) : (
          <p className="muted small">还没有校阅札记。</p>
        )
      ) : (
        <ul className="note-list">
          {ordered.map((n) => {
            const idx = local.indexOf(n);
            const isEditing = editingIdx === idx;
            return (
              <li className="note-item" key={`${n.created_at ?? "x"}-${idx}`}>
                {isEditing ? (
                  <>
                    <textarea
                      className="note-edit-area"
                      value={editingText}
                      onChange={(e) => setEditingText(e.target.value)}
                      rows={3}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) commitEdit();
                        if (e.key === "Escape") { setEditingIdx(null); setEditingText(""); }
                      }}
                    />
                    <div className="note-actions">
                      <button type="button" onClick={commitEdit} disabled={!editingText.trim()}>保存</button>
                      <button type="button" onClick={() => { setEditingIdx(null); setEditingText(""); }}>取消</button>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="note-body">
                      <p>{n.text}</p>
                      <small className="note-meta">{formatReviewTime(n.created_at)}</small>
                    </div>
                    <div className="note-actions">
                      <button type="button" className="ghost-button icon-button" onClick={() => startEdit(idx)} title="编辑" aria-label="edit">
                        <RefreshCw size={12} />
                      </button>
                      <button type="button" className="danger-button icon-button" onClick={() => removeAt(idx)} title="删除" aria-label="delete">
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ── Profile ──────────────────────────────────────────────────────────

function ProfilePage(props: {
  paper: Paper | null; busy: string;
  goBack: () => void; enrichPaper: (id: string) => void;
  openChat: (paper: Paper) => void;
  translatePaper: (id: string) => void;
  updatePaper: (id: string, patch: Record<string, unknown>) => Promise<void> | void;
  deletePaper: (id: string) => void; openPdf: (p: Paper) => void;
  downloadPaper: (p: Paper) => void; indexPaper: (p: Paper) => void;
  paperJob?: Job;
  tagCounts: [string, number][];
  defaultSummaryLanguage: SummaryLanguage;
  translationEngine: "local" | "llm";
  kbRoot: string;
}) {
  const paper = props.paper;
  const [showChinese, setShowChinese] = useState(false);
  const conceptTranslationRequestRef = useRef<string | null>(null);

  useEffect(() => {
    if (paper) setShowChinese(props.defaultSummaryLanguage === "zh");
  }, [paper?.id, props.defaultSummaryLanguage]);

  useEffect(() => {
    if (!paper || !showChinese) return;
    const concepts = paper.core_concepts ?? [];
    const translated = paper.translations?.core_concepts;
    const needsConceptTranslation = concepts.length > 0 && (!Array.isArray(translated) || translated.length < concepts.length);
    const translatedFigures = paper.translations?.key_figures;
    const figures = paper.key_figures ?? [];
    const needsFigureTranslation = figures.length > 0 && (!Array.isArray(translatedFigures) || translatedFigures.length < figures.length);
    const needsLlmRefresh = props.translationEngine === "llm" && paper.translation_meta?.engine !== "llm";
    if (!needsConceptTranslation && !needsFigureTranslation && !needsLlmRefresh) return;
    const requestKey = `${paper.id}:${concepts.length}:${paper.key_figures?.length ?? 0}:${props.translationEngine}`;
    if (conceptTranslationRequestRef.current === requestKey) return;
    conceptTranslationRequestRef.current = requestKey;
    void props.translatePaper(paper.id);
  }, [paper?.id, paper?.core_concepts?.length, paper?.key_figures?.length, paper?.translations?.core_concepts, paper?.translations?.key_figures, paper?.translation_meta?.engine, showChinese, props.translationEngine]);

  if (!paper || props.busy === "profile") {
    return <div className="loading-state"><Loader2 className="spin" size={20} /> 正在调取文献档案...</div>;
  }

  const hasZh = Boolean(paper.translations && Object.keys(paper.translations).length > 0);
  const effectiveChinese = showChinese && hasZh;
  const jobRunning = props.paperJob && ["queued", "running"].includes(props.paperJob.status);
  const figureVersion = paper.updated_at || "";

  async function handleTranslate() {
    if (effectiveChinese) {
      setShowChinese(false);
      return;
    }
    const concepts = paper!.core_concepts ?? [];
    const translated = paper!.translations?.core_concepts;
    const needsConceptTranslation = concepts.length > 0 && (!Array.isArray(translated) || translated.length < concepts.length);
    const translatedFigures = paper!.translations?.key_figures;
    const figures = paper!.key_figures ?? [];
    const needsFigureTranslation = figures.length > 0 && (!Array.isArray(translatedFigures) || translatedFigures.length < figures.length);
    const needsLlmRefresh = props.translationEngine === "llm" && paper!.translation_meta?.engine !== "llm";
    if (!hasZh || needsConceptTranslation || needsFigureTranslation || needsLlmRefresh) {
      await props.translatePaper(paper!.id);
    }
    setShowChinese(true);
  }

  return (
    <div className="profile-page">
      <section className="page-heading">
        <div className="page-heading-bar">
          <button className="ghost-button back-button" onClick={props.goBack}><ArrowLeft size={16} /> 返回来源页</button>
          <div className="profile-actions">
            <button className="chat-launch-button" onClick={() => props.openChat(paper)}>
              <MessageCircle size={15} /> 询问图书管理员
            </button>
            {paper.download_status === "downloaded" && paper.source_pdf
              ? <button className="action-button" onClick={() => props.openPdf(paper)}><ExternalLink size={15} /> 打开 PDF</button>
              : <button className="action-button" onClick={() => props.downloadPaper(paper)} disabled={!paper.pdf_url || paper.download_status === "downloading"}>
                  <Upload size={15} /> {paper.download_status === "downloading" ? "下载中" : "下载 PDF"}
                </button>}
            <details className="action-menu profile-action-menu">
              <summary aria-label="更多论文操作" title="更多论文操作"><MoreHorizontal size={18} /></summary>
              <div className="action-menu-popover">
                <button onClick={() => props.enrichPaper(paper.id)} disabled={jobRunning}>
                  {jobRunning ? <Loader2 className="spin" size={15} /> : <RefreshCw size={15} />}
                  {jobRunning ? `整理中 ${props.paperJob?.progress ?? 0}%` : "重新整理"}
                </button>
                <button onClick={() => props.indexPaper(paper)} disabled={paper.download_status !== "downloaded" || paper.index_status === "indexing"}>
                  <Search size={15} /> {paper.index_status === "indexing" ? "索引中" : "重建全文索引"}
                </button>
                <button onClick={handleTranslate} disabled={props.busy === "translate"}>
                  {props.busy === "translate" ? <Loader2 className="spin" size={15} /> : <Languages size={15} />}
                  {effectiveChinese ? "显示英文" : "翻译为中文"}
                </button>
                <div className="action-menu-separator" />
                <button className="menu-danger" onClick={() => props.deletePaper(paper.id)} disabled={props.busy === "delete"}>
                  {props.busy === "delete" ? <Loader2 className="spin" size={15} /> : <Trash2 size={15} />} 删除文献
                </button>
              </div>
            </details>
          </div>
        </div>
        <div>
          <p className="kicker">论文档案册</p>
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
          <KeyFigures
            figures={paper.key_figures ?? []}
            translatedFigures={effectiveChinese ? (paper.translations?.key_figures as TranslatedKeyFigure[] | undefined) : undefined}
            paperId={paper.id}
            kbRoot={props.kbRoot}
            cacheKey={figureVersion}
          />
          <ConceptTable
            concepts={paper.core_concepts ?? []}
            translatedConcepts={effectiveChinese ? (paper.translations?.core_concepts as TranslatedCoreConcept[] | undefined) : undefined}
          />
          <Field label="一句话摘要" value={effectiveChinese ? (paper.translations?.one_sentence as string) : paper.one_sentence} />
          <Field label="研究问题" value={effectiveChinese ? (paper.translations?.problem as string) : paper.problem} />
          <ListField label="主要贡献" values={effectiveChinese ? (paper.translations?.contributions as string[] || []) : (paper.contributions ?? [])} />
          <ListField label="方法" values={effectiveChinese ? (paper.translations?.method as string[] || []) : (paper.method ?? [])} />
          <ListField label="实验" values={effectiveChinese ? (paper.translations?.experiments as string[] || []) : (paper.experiments ?? [])} />
          <ListField label="局限" values={effectiveChinese ? (paper.translations?.limitations as string[] || []) : (paper.limitations ?? [])} />
          <Field label="摘要" value={effectiveChinese ? (paper.translations?.abstract as string) : paper.abstract} />
        </article>
        <aside className="profile-side">
          <section className="panel">
            <h2>题录</h2>
            <Info label="作者" value={(paper.authors ?? []).join(", ") || "Unknown"} />
            <Info label="团队" value={(paper.author_affiliations ?? []).join("; ") || "-"} />
            <Info label="年份" value={String(paper.year ?? "?")} />
            <Info label="来源" value={paper.venue || "-"} />
            <Info label="DOI" value={paper.doi || "-"} />
            <Info label="arXiv" value={paper.arxiv_id || "-"} />
            <Info label="论文页面" value={paper.paper_url || "-"} />
            <Info label="远程 PDF" value={paper.pdf_url || "-"} />
          </section>
          <section className="panel">
            <h2>校阅札记</h2>
            <ReviewNotesEditor
              key={paper.id}
              notes={normalizeReviewNotes(paper.review_notes)}
              busy={props.busy === "save"}
              onCommit={(next) => props.updatePaper(paper.id, { review_notes: next })}
            />
          </section>
          <section className="panel">
            <h2>馆藏管理</h2>
            <label className="label-stack">
              <span>标签</span>
              <TagEditor
                key={paper.id}
                tags={paper.tags ?? []}
                knownTags={props.tagCounts.map(([t]) => t)}
                busy={props.busy === "save"}
                onCommit={(next) => props.updatePaper(paper.id, { tags: next })}
              />
            </label>
          </section>
          <section className="panel">
            <h2>档案信息</h2>
            <Info label="来源文件" value={paper.source_pdf ?? "-"} />
            <Info label="下载状态" value={downloadStatusLabel(paper.download_status)} />
            <Info label="索引状态" value={indexStatusLabel(paper.index_status)} />
            {paper.download_error && <Info label="下载错误" value={paper.download_error} />}
            {paper.index_error && <Info label="索引错误" value={paper.index_error} />}
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
      {values.length ? <ul>{values.map((v, i) => <li key={`${label}-${i}`}>{v}</li>)}</ul> : <p>尚未整理此项内容。</p>}
    </section>
  );
}

function KeyFigures({ figures, translatedFigures, paperId, kbRoot, cacheKey }: {
  figures: KeyFigure[];
  translatedFigures?: TranslatedKeyFigure[];
  paperId: string;
  kbRoot: string;
  cacheKey: string;
}) {
  const [open, setOpen] = useState(false);
  const hasTranslation = Boolean(translatedFigures?.length);
  return (
    <section className="field-block figure-field collapsible-field">
      <button type="button" className="collapsible-field-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span>{open ? <ChevronDown size={16} /> : <ChevronRight size={16} />} 关键图示</span>
        <small>{figures.length ? `${figures.length} 张` : "暂无"}</small>
      </button>
      {open && (figures.length ? (
        <div className="collapsible-field-content">
          <div className="figure-strip">
            {figures.map((figure, i) => {
              const translated = hasTranslation ? translatedFigures?.[i] : undefined;
              const title = translated?.title_zh || figure.title || `Figure on page ${figure.page}`;
              const caption = translated?.caption_zh || figure.caption || "";
              const reason = translated?.reason_zh || figure.reason || "";
              const titleEn = translated?.title_en || figure.title || "";
              const captionEn = translated?.caption_en || figure.caption || "";
              const reasonEn = translated?.reason_en || figure.reason || "";
              return (
                <figure className="paper-figure" key={`${figure.page}-${i}`}>
                  {figure.image_path ? (
                    <img src={figureImageUrl(paperId, i, kbRoot, cacheKey)} alt={title} />
                  ) : (
                    <div className="figure-placeholder">Page {figure.page}</div>
                  )}
                  <figcaption>
                    <strong>{title}</strong>
                    <span>p. {figure.page}</span>
                    {hasTranslation && titleEn && titleEn !== title ? <em>{titleEn}</em> : null}
                    {caption ? <p>{caption}</p> : null}
                    {hasTranslation && captionEn && captionEn !== caption ? <p className="figure-original">{captionEn}</p> : null}
                    {reason ? <small>{reason}</small> : null}
                    {hasTranslation && reasonEn && reasonEn !== reason ? <small className="figure-original">{reasonEn}</small> : null}
                  </figcaption>
                </figure>
              );
            })}
          </div>
        </div>
      ) : <p>尚未整理此项内容。</p>)}
    </section>
  );
}

function ConceptTable({ concepts, translatedConcepts }: {
  concepts: CoreConcept[];
  translatedConcepts?: TranslatedCoreConcept[];
}) {
  const [open, setOpen] = useState(false);
  const rows = translatedConcepts?.length ? translatedConcepts : concepts;
  const isTranslated = Boolean(translatedConcepts?.length);
  return (
    <section className="field-block concept-field collapsible-field">
      <button type="button" className="collapsible-field-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span>{open ? <ChevronDown size={16} /> : <ChevronRight size={16} />} 核心概念定义</span>
        <small>{rows.length ? `${rows.length} 个` : "暂无"}</small>
      </button>
      {open && (rows.length ? (
        <div className="collapsible-field-content">
          <table className="concept-table">
            <thead>
              <tr>
                <th>概念</th>
                <th>通俗解释</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item, i) => (
                <tr key={`${isTranslated ? (item as TranslatedCoreConcept).concept_en : (item as CoreConcept).concept}-${i}`}>
                  <td>
                    {isTranslated ? (
                      <>
                        {(item as TranslatedCoreConcept).concept_zh || (item as TranslatedCoreConcept).concept_en}
                        <small>{(item as TranslatedCoreConcept).concept_en}</small>
                      </>
                    ) : (item as CoreConcept).concept}
                  </td>
                  <td>{isTranslated ? (item as TranslatedCoreConcept).explanation_zh : (item as CoreConcept).explanation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p>尚未整理此项内容。</p>)}
    </section>
  );
}

function figureImageUrl(paperId: string, figureIndex: number, kbRoot: string, cacheKey: string): string {
  const params = new URLSearchParams();
  if (kbRoot) params.set("root", kbRoot);
  if (cacheKey) params.set("v", cacheKey);
  const suffix = params.toString();
  return `${API}/api/papers/${encodeURIComponent(paperId)}/figures/${figureIndex}${suffix ? `?${suffix}` : ""}`;
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="info-row"><span>{label}</span><strong>{value}</strong></div>;
}

function splitTags(value: string): string[] {
  return [...new Set(value.split(",").map((t) => t.trim()).filter(Boolean))];
}

function sessionMessageToChatMessage(message: any, index: number): ChatMessage {
  const role = message?.role === "assistant" ? "assistant" : "user";
  const segments = Array.isArray(message?.segments)
    ? message.segments.map((segment: any, segmentIndex: number): ChatSegment | null => {
        if (segment?.type === "text") {
          return {
            id: `session-${index}-text-${segmentIndex}`,
            type: "text",
            content: String(segment.content ?? ""),
          };
        }
        if (segment?.type === "tool") {
          return {
            id: String(segment.id ?? `session-${index}-tool-${segmentIndex}`),
            type: "tool",
            tool: {
              id: String(segment.id ?? `session-${index}-tool-${segmentIndex}`),
              name: String(segment.title ?? segment.name ?? "tool"),
              detail: segment.detail,
              result: segment.archive_result,
              resultDetail: segment.result,
              isError: Boolean(segment.is_error),
              state: segment.result ? "done" : "done",
            },
          };
        }
        return null;
      }).filter(Boolean) as ChatSegment[]
    : undefined;
  return {
    id: `${role}-${message?.created_at ?? index}`,
    role,
    content: String(message?.content ?? ""),
    paperIds: Array.isArray(message?.paper_ids) ? message.paper_ids.filter(Boolean) : undefined,
    segments,
    pending: false,
  };
}

function extractLibrarianAction(result: unknown): { action_id: string; kind?: string; candidate_count?: number } | null {
  if (!Array.isArray(result)) return null;
  for (const block of result) {
    if (!block || typeof block !== "object" || (block as any).type !== "text") continue;
    try {
      const parsed = JSON.parse(String((block as any).text ?? ""));
      if (parsed?.requires_confirmation && parsed?.action_id) return parsed;
    } catch { /* ordinary tool text */ }
  }
  return null;
}

function extractSessionPaperIds(session: any): string[] {
  if (Array.isArray(session?.paper_ids)) return session.paper_ids.filter(Boolean);
  const messages = Array.isArray(session?.messages) ? session.messages : [];
  for (const message of [...messages].reverse()) {
    if (Array.isArray(message?.paper_ids)) return message.paper_ids.filter(Boolean);
  }
  return [];
}

function expandMentionedPaperIds(papers: Paper[], paperIds: string[], tags: string[]): string[] {
  const expanded: string[] = [];
  for (const paperId of paperIds) {
    if (paperId && !expanded.includes(paperId)) expanded.push(paperId);
  }
  const selectedTags = tags.map((tag) => tag.trim().toLowerCase()).filter(Boolean);
  if (!selectedTags.length) return expanded;
  for (const paper of papers) {
    const paperTags = new Set((paper.tags ?? []).map((tag) => tag.toLowerCase()));
    if (selectedTags.every((tag) => paperTags.has(tag)) && !expanded.includes(paper.id)) {
      expanded.push(paper.id);
    }
  }
  return expanded;
}

function formatDateShort(value?: string): string {
  if (!value) return "未知时间";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function MarkdownView({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
      {children}
    </ReactMarkdown>
  );
}

// ── Chat ─────────────────────────────────────────────────────────────

function ChatPage(props: {
  papers: Paper[];
  sessions: ChatSessionSummary[];
  activeSessionId: string | null;
  mentionedPaperIds: string[];
  setMentionedPaperIds: (ids: string[]) => void;
  mentionedTags: string[];
  setMentionedTags: (tags: string[]) => void;
  messages: ChatMessage[];
  kbRoot: string;
  busy: string;
  newChat: () => void;
  openSession: (sessionId: string) => void;
  deleteSession: (sessionId: string) => void;
  openPdf: (paper: Paper) => void;
  sendMessage: (question: string) => Promise<void> | void;
  stopChat: () => void;
}) {
  const [input, setInput] = useState("");
  const [mentionActive, setMentionActive] = useState(false);
  const [mentionQuery, setMentionQuery] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const composingRef = useRef(false);
  const justComposedRef = useRef(false);
  const isStreaming = props.busy === "chat";
  const paperById = useMemo(() => new Map(props.papers.map((paper) => [paper.id, paper])), [props.papers]);
  const tagCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const paper of props.papers) {
      for (const tag of paper.tags ?? []) counts.set(tag, (counts.get(tag) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [props.papers]);
  const expandedMentionedPaperIds = useMemo(
    () => expandMentionedPaperIds(props.papers, props.mentionedPaperIds, props.mentionedTags),
    [props.papers, props.mentionedPaperIds, props.mentionedTags],
  );
  const explicitMentionedPapers = props.mentionedPaperIds
    .map((id) => paperById.get(id))
    .filter(Boolean) as Paper[];
  const mentionedPapers = expandedMentionedPaperIds
    .map((id) => paperById.get(id))
    .filter(Boolean) as Paper[];
  const mentionedPaperCountFromTags = Math.max(0, expandedMentionedPaperIds.length - props.mentionedPaperIds.length);
  const mentionMatches = useMemo(() => {
    const term = mentionQuery.trim().toLowerCase();
    const tagMatches = tagCounts
      .filter(([tag]) => !props.mentionedTags.includes(tag))
      .filter(([tag]) => !term || tag.toLowerCase().includes(term))
      .slice(0, 5)
      .map(([tag, count]) => ({ type: "tag" as const, tag, count }));
    const paperMatches = props.papers.filter((paper) => {
      const haystack = `${paper.id} ${paper.title ?? ""} ${(paper.authors ?? []).join(" ")} ${(paper.tags ?? []).join(" ")}`.toLowerCase();
      return !term || haystack.includes(term);
    }).slice(0, Math.max(3, 8 - tagMatches.length))
      .map((paper) => ({ type: "paper" as const, paper }));
    return [...tagMatches, ...paperMatches];
  }, [mentionQuery, props.mentionedTags, props.papers, tagCounts]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [props.messages]);

  function send() {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    void props.sendMessage(text);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    const native = e.nativeEvent as KeyboardEvent;
    const isComposing = composingRef.current || justComposedRef.current || native.isComposing || native.keyCode === 229;
    if (e.key === "Enter" && !e.shiftKey && !isComposing) {
      e.preventDefault();
      send();
    }
  }

  function onInputChange(value: string) {
    setInput(value);
    const match = value.match(/(?:^|\s)@([^\s@]*)$/);
    setMentionActive(Boolean(match));
    setMentionQuery(match ? match[1] : "");
  }

  function addMention(paper: Paper) {
    if (!props.mentionedPaperIds.includes(paper.id)) {
      props.setMentionedPaperIds([...props.mentionedPaperIds, paper.id]);
    }
    clearMentionTrigger();
  }

  function addTagMention(tag: string) {
    if (!props.mentionedTags.includes(tag)) {
      props.setMentionedTags([...props.mentionedTags, tag]);
    }
    clearMentionTrigger();
  }

  function clearMentionTrigger() {
    setInput((current) => current.replace(/(?:^|\s)@([^\s@]*)$/, " ").replace(/\s{2,}/g, " "));
    setMentionActive(false);
    setMentionQuery("");
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  function removeMention(paperId: string) {
    props.setMentionedPaperIds(props.mentionedPaperIds.filter((id) => id !== paperId));
  }

  function removeTagMention(tag: string) {
    props.setMentionedTags(props.mentionedTags.filter((item) => item !== tag));
  }

  function onCompositionEnd() {
    composingRef.current = false;
    justComposedRef.current = true;
    window.setTimeout(() => {
      justComposedRef.current = false;
    }, 80);
  }

  const suggestions = [
    "总结已 mention 论文的核心贡献和局限。",
    "比较这些论文的方法差异和实验设计。",
    "帮我检索 2025 年 ICLR 中和 agent harness 相关的论文。",
  ];

  return (
    <div className="chat-page chat-module-page">
      <aside className="chat-history-panel">
        <div className="chat-history-head">
          <div>
            <p className="kicker">对话存档</p>
            <h2>历史对话</h2>
          </div>
          <button type="button" className="icon-button" onClick={props.newChat} aria-label="新对话" title="新对话">
            <Plus size={16} />
          </button>
        </div>
        <div className="chat-session-list">
          {props.sessions.length ? props.sessions.map((session) => (
            <div className={`chat-session-row ${session.id === props.activeSessionId ? "active" : ""}`} key={session.id}>
              <button
                type="button"
                className="chat-session-open"
                onClick={() => props.openSession(session.id)}
              >
                <strong>{session.title}</strong>
                <span>{session.message_count} 条消息 · {formatDateShort(session.updated_at)}</span>
              </button>
              <button
                type="button"
                className="icon-button chat-session-delete"
                onClick={() => props.deleteSession(session.id)}
                aria-label={`删除对话 ${session.title}`}
                title="删除对话"
                disabled={props.busy === `delete-session-${session.id}` || (props.busy === "chat" && session.id === props.activeSessionId)}
              >
                {props.busy === `delete-session-${session.id}` ? <Loader2 className="spin" size={14} /> : <Trash2 size={14} />}
              </button>
            </div>
          )) : (
            <p className="empty-note">暂无历史对话</p>
          )}
        </div>
      </aside>

      <section className="chat-main-panel">
        <section className="chat-topbar">
          <div className="chat-title">
            <p className="kicker">纽记图书管理员</p>
            <h1>检索、收藏并研读论文</h1>
            <p>{mentionedPapers.length ? `${mentionedPapers.length} 篇论文已 mention` : "未指定论文，可直接询问整个文献库"}</p>
          </div>
        </section>

        <section className="chat-shell">
          <div className="chat-scroll" ref={scrollRef}>
            {props.messages.length === 0 ? (
              <div className="chat-empty">
                <div className="chat-emblem"><MessageCircle size={28} /></div>
                <h2>{mentionedPapers.length ? "围绕 mention 论文开始提问" : "开始一个独立对话"}</h2>
                <div className="chat-suggestions">
                  {suggestions.map((item) => (
                    <button key={item} type="button" onClick={() => setInput(item)}>
                      {item}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              props.messages.map((message) => <ChatMessageView key={message.id} message={message} paperById={paperById} kbRoot={props.kbRoot} />)
            )}
          </div>
          <div className="chat-composer-wrap">
            <div className="mention-strip">
              {explicitMentionedPapers.map((paper) => (
                <span className="mention-chip" key={paper.id}>
                  <BookOpen size={13} />
                  <span>{paper.title || paper.id}</span>
                  <button type="button" onClick={() => removeMention(paper.id)} aria-label={`移除 ${paper.title || paper.id}`}>
                    <XCircle size={13} />
                  </button>
                </span>
              ))}
              {props.mentionedTags.map((tag) => (
                <span className="mention-chip tag-mention-chip" key={tag}>
                  <Tags size={13} />
                  <span>{tag}</span>
                  <button type="button" onClick={() => removeTagMention(tag)} aria-label={`移除 tag ${tag}`}>
                    <XCircle size={13} />
                  </button>
                </span>
              ))}
              <span className="mention-hint">
                输入 @ 可 mention 论文或 tag{props.mentionedTags.length ? `，tag 匹配 ${mentionedPaperCountFromTags} 篇` : ""}
              </span>
            </div>
            <div className="chat-composer">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => onInputChange(e.target.value)}
                onKeyDown={onKeyDown}
                onCompositionStart={() => { composingRef.current = true; }}
                onCompositionEnd={onCompositionEnd}
                placeholder="询问论文内容、方法、实验、局限，或输入 @ 搜索并 mention 论文…"
                rows={1}
                disabled={isStreaming}
              />
              {mentionActive && (
                <div className="mention-menu">
                  {mentionMatches.length ? mentionMatches.map((item) => (
                    <button
                      key={item.type === "tag" ? `tag-${item.tag}` : item.paper.id}
                      type="button"
                      onClick={() => item.type === "tag" ? addTagMention(item.tag) : addMention(item.paper)}
                    >
                      <span className="mention-menu-title">
                        {item.type === "tag" ? `# ${item.tag}` : item.paper.title || item.paper.id}
                      </span>
                      <span className="mention-menu-authors">
                        {item.type === "tag" ? `${item.count} 篇论文，多个 tag 自动取交集` : (item.paper.authors ?? []).join(", ") || "Unknown authors"}
                      </span>
                    </button>
                  )) : <p>没有匹配的论文或 tag</p>}
                </div>
              )}
              {isStreaming ? (
                <button type="button" className="chat-send-button" onClick={props.stopChat} aria-label="停止生成" title="停止生成">
                  <Square size={15} />
                </button>
              ) : (
                <button type="button" className="chat-send-button" onClick={send} disabled={!input.trim()} aria-label="发送" title="发送">
                  <SendHorizontal size={16} />
                </button>
              )}
            </div>
          </div>
        </section>
      </section>
    </div>
  );
}

function appendTextSegment(message: ChatMessage, delta: string): ChatMessage {
  if (!delta) return message;
  const segments = [...(message.segments ?? [])];
  const last = segments[segments.length - 1];
  if (last?.type === "text") {
    segments[segments.length - 1] = { ...last, content: last.content + delta };
  } else {
    segments.push({ id: `text-${Date.now()}-${segments.length}`, type: "text", content: delta });
  }
  return { ...message, content: message.content + delta, segments };
}

function completeToolCall(tool: ChatToolCall, payload: Record<string, any>): ChatToolCall {
  return {
    ...tool,
    result: payload.result,
    resultDetail: payload.detail,
    isError: Boolean(payload.is_error),
    state: "done",
  };
}

function ChatMessageView({ message, paperById, kbRoot }: {
  message: ChatMessage; paperById: Map<string, Paper>; kbRoot: string;
}) {
  const segments = message.role === "assistant" && message.segments?.length
    ? message.segments
    : null;
  const showThinking = Boolean(message.pending && !message.content && !(message.segments?.length));
  const mentionedPapers = (message.paperIds ?? [])
    .map((id) => paperById.get(id))
    .filter(Boolean) as Paper[];

  return (
    <article className={`chat-message ${message.role}`}>
      <div className="chat-avatar" aria-hidden="true">
        {message.role === "assistant" ? <Bot size={17} /> : <UserRound size={17} />}
      </div>
      <div className="chat-bubble">
        {message.role === "user" && mentionedPapers.length ? (
          <div className="message-mentions">
            {mentionedPapers.map((paper) => (
              <span key={paper.id}>{paper.title || paper.id}</span>
            ))}
          </div>
        ) : null}
        {segments ? (
          segments.map((segment) => (
            segment.type === "tool" ? (
              <ToolCallView key={segment.id} tool={segment.tool} kbRoot={kbRoot} />
            ) : (
              <div className="markdown-body chat-markdown chat-segment" key={segment.id}>
                <MarkdownView>{segment.content}</MarkdownView>
              </div>
            )
          ))
        ) : (
          <>
            {message.role === "assistant" && (message.tools ?? []).map((tool) => (
              <ToolCallView key={tool.id} tool={tool} kbRoot={kbRoot} />
            ))}
            {message.content ? (
              <div className="markdown-body chat-markdown">
                <MarkdownView>{message.content}</MarkdownView>
              </div>
            ) : null}
          </>
        )}
        {showThinking ? (
          <div className="chat-thinking"><Loader2 className="spin" size={14} /> 思考中</div>
        ) : null}
      </div>
    </article>
  );
}

type PdfArchive = {
  kind: "pdf_archive";
  archive_id: string;
  filename: string;
  paper_count: number;
  size_bytes: number;
  unavailable?: { paper_id: string; reason: string }[];
};

function findPdfArchive(value: unknown, depth = 0): PdfArchive | null {
  if (depth > 5 || value == null) return null;
  if (typeof value === "string") {
    try { return findPdfArchive(JSON.parse(value), depth + 1); } catch { return null; }
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const archive = findPdfArchive(item, depth + 1);
      if (archive) return archive;
    }
    return null;
  }
  if (typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  if (item.kind === "pdf_archive" && typeof item.archive_id === "string" && typeof item.filename === "string") {
    return {
      kind: "pdf_archive",
      archive_id: item.archive_id,
      filename: item.filename,
      paper_count: Number(item.paper_count) || 0,
      size_bytes: Number(item.size_bytes) || 0,
      unavailable: Array.isArray(item.unavailable) ? item.unavailable as PdfArchive["unavailable"] : [],
    };
  }
  return findPdfArchive(item.text ?? item.content ?? item.result, depth + 1);
}

function archiveDownloadUrl(archiveId: string, kbRoot: string): string {
  const params = new URLSearchParams();
  if (kbRoot) params.set("root", kbRoot);
  const suffix = params.toString();
  return `${API}/api/librarian/archives/${encodeURIComponent(archiveId)}/download${suffix ? `?${suffix}` : ""}`;
}

function readableBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(bytes >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
}

function PdfArchiveCard({ archive, kbRoot }: { archive: PdfArchive; kbRoot: string }) {
  const unavailable = archive.unavailable?.length ?? 0;
  return (
    <section className="chat-file-card">
      <div className="chat-file-card-icon"><FileText size={19} /></div>
      <div className="chat-file-card-copy">
        <strong>{archive.filename}</strong>
        <small>{archive.paper_count} 篇 PDF · {readableBytes(archive.size_bytes)}{unavailable ? ` · ${unavailable} 篇未打包` : ""}</small>
      </div>
      <a className="chat-file-download" href={archiveDownloadUrl(archive.archive_id, kbRoot)} download={archive.filename} aria-label={`下载 ${archive.filename}`} title="下载 ZIP 文件">
        <Download size={18} />
      </a>
    </section>
  );
}

function ToolCallView({ tool, kbRoot }: { tool: ChatToolCall; kbRoot: string }) {
  const [open, setOpen] = useState(false);
  const archive = tool.isError ? null : (findPdfArchive(tool.result) ?? findPdfArchive(tool.resultDetail));
  if (archive) return <PdfArchiveCard archive={archive} kbRoot={kbRoot} />;
  const inputText = stringifyToolPayload(tool.input ?? tool.detail);
  const resultText = stringifyToolPayload(tool.result ?? tool.resultDetail);
  const label = toolIntentLabel(tool);
  const status = tool.state === "running" ? "运行中" : tool.isError ? "失败" : "完成";

  return (
    <div className={`tool-call ${tool.isError ? "failed" : ""}`}>
      <button className="tool-call-head" type="button" onClick={() => setOpen(!open)}>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <Wrench size={14} />
        <span>{label}</span>
        <small>{status} · {friendlyToolName(tool.name)}</small>
      </button>
      {open && (
        <div className="tool-call-body">
          <section>
            <strong>参数</strong>
            <pre>{inputText || "-"}</pre>
          </section>
          <section>
            <strong>返回</strong>
            <pre>{resultText || (tool.state === "running" ? "等待工具返回…" : "-")}</pre>
          </section>
        </div>
      )}
    </div>
  );
}

function toolIntentLabel(tool: ChatToolCall): string {
  const input = tool.input;
  if (input && typeof input === "object" && "intend" in input) {
    const intend = String((input as { intend?: unknown }).intend ?? "").trim();
    if (intend) return intend;
  }
  return fallbackToolIntent(tool);
}

function fallbackToolIntent(tool: ChatToolCall): string {
  const input = tool.input && typeof tool.input === "object" ? tool.input as Record<string, unknown> : {};
  const path = typeof input.path === "string" ? input.path : "";
  const pages = typeof input.pages === "string" ? input.pages : "";
  if (tool.name.includes("kb_read_pdf_pages")) return pages ? `正在读取 PDF 第 ${pages} 页` : "正在读取 PDF";
  if (tool.name.includes("kb_render_pdf_pages")) return pages ? `正在查看 PDF 第 ${pages} 页` : "正在查看 PDF 页面";
  if (tool.name.includes("kb_pdf_info")) return "正在检查 PDF 信息";
  if (tool.name.includes("kb_read")) return path ? `正在读取 ${compactToolPath(path)}` : "正在读取资料";
  if (tool.name.includes("kb_list")) return path ? `正在浏览 ${compactToolPath(path)}` : "正在浏览资料";
  if (tool.name.includes("kb_write")) return path ? `正在保存 ${compactToolPath(path)}` : "正在保存修正";
  if (tool.name.includes("librarian_package_paper_pdfs")) return "正在打包所选论文 PDF";
  return "正在处理资料";
}

function friendlyToolName(name: string): string {
  const normalized = name.replace(/^mcp__neunote__/, "");
  const labels: Record<string, string> = {
    kb_list: "浏览",
    kb_read: "读取",
    kb_write: "保存",
    kb_pdf_info: "PDF 信息",
    kb_read_pdf_pages: "PDF 文本",
    kb_render_pdf_pages: "PDF 视觉",
    librarian_package_paper_pdfs: "打包 PDF",
  };
  return labels[normalized] ?? normalized;
}

function compactToolPath(path: string): string {
  const filename = path.split("/").filter(Boolean).pop() || path;
  return filename.length > 28 ? `${filename.slice(0, 25)}...` : filename;
}

function stringifyToolPayload(value: unknown): string {
  if (value === undefined || value === null || value === "") return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

// ── Jobs ─────────────────────────────────────────────────────────────

function JobsPage({ jobs, queueStatus, refresh, cancelJob, cancelAllJobs, pauseJob, resumeJob, retryJob, setQueuePaused, batchJobAction, deleteJob, cleanupJobs, busy }: {
  jobs: Job[];
  queueStatus: QueueStatus;
  refresh: () => void;
  cancelJob: (id: string) => void;
  cancelAllJobs: () => void;
  pauseJob: (id: string) => void;
  resumeJob: (id: string) => void;
  retryJob: (id: string) => void;
  setQueuePaused: (paused: boolean) => void;
  batchJobAction: (ids: string[], action: "pause" | "resume" | "retry" | "cancel") => void;
  deleteJob: (id: string) => void;
  cleanupJobs: () => void;
  busy: string;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectedJobIds, setSelectedJobIds] = useState<Set<string>>(new Set());
  const finishedCount = jobs.filter((j) => ["completed", "failed", "cancelled"].includes(j.status)).length;
  const activeCount = jobs.filter((j) => ["queued", "running", "paused"].includes(j.status)).length;
  const selectedIds = Array.from(selectedJobIds);
  const counts = {
    queued: jobs.filter((j) => j.status === "queued").length,
    running: jobs.filter((j) => j.status === "running").length,
    paused: jobs.filter((j) => j.status === "paused").length,
    completed: jobs.filter((j) => j.status === "completed").length,
    failed: jobs.filter((j) => j.status === "failed").length,
    cancelled: jobs.filter((j) => j.status === "cancelled").length,
  };
  const total = Math.max(jobs.length, 1);

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function toggleJobSelection(id: string) {
    setSelectedJobIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function toggleAllJobs() {
    setSelectedJobIds((prev) => {
      const next = new Set(prev);
      const allSelected = jobs.length > 0 && jobs.every((job) => next.has(job.id));
      if (allSelected) jobs.forEach((job) => next.delete(job.id));
      else jobs.forEach((job) => next.add(job.id));
      return next;
    });
  }

  function runBatch(action: "pause" | "resume" | "retry" | "cancel") {
    batchJobAction(selectedIds, action);
    setSelectedJobIds(new Set());
  }

  return (
    <div className="jobs-page">
      <section className="page-heading inline">
        <div>
          <p className="kicker">整理队列</p>
          <h1>整理队列</h1>
          <p>后台文献整理任务，并发数量可在设置中调整。</p>
        </div>
        <div className="toolbar">
          <button onClick={() => setQueuePaused(!queueStatus.paused)} disabled={busy === "pause-queue" || busy === "resume-queue"}>
            {busy === "pause-queue" || busy === "resume-queue" ? <Loader2 className="spin" size={16} /> : queueStatus.paused ? <Play size={16} /> : <Square size={16} />}
            {queueStatus.paused ? "恢复队列" : "暂停队列"}
          </button>
          {activeCount > 0 && (
            <button onClick={cancelAllJobs} disabled={busy === "cancel-all"}>
              {busy === "cancel-all" ? <Loader2 className="spin" size={16} /> : <XCircle size={16} />}
              停止全部 {activeCount} 项
            </button>
          )}
          {finishedCount > 0 && (
            <button onClick={cleanupJobs} disabled={busy === "cleanup"}>
              {busy === "cleanup" ? <Loader2 className="spin" size={16} /> : <Trash2 size={16} />}
              清理 {finishedCount} 项
            </button>
          )}
          <button onClick={refresh}><RefreshCw size={16} /> 刷新</button>
        </div>
      </section>

      <section className="queue-overview">
        <div className="queue-card queue-card-primary">
          <span>{queueStatus.paused ? "已暂停" : counts.running ? "运行中" : counts.queued ? "待执行" : "空闲"}</span>
          <strong>{activeCount}</strong>
          <small>活跃任务</small>
        </div>
        <div className="queue-card">
          <span>运行</span>
          <strong>{counts.running}</strong>
          <small>当前执行</small>
        </div>
        <div className="queue-card">
          <span>等待</span>
          <strong>{counts.queued}</strong>
          <small>排队任务</small>
        </div>
        <div className="queue-card">
          <span>失败</span>
          <strong>{counts.failed}</strong>
          <small>可重试</small>
        </div>
        <div className="queue-state-chart" aria-label="任务状态分布">
          <span className="chart-segment running" style={{ width: `${counts.running / total * 100}%` }} />
          <span className="chart-segment queued" style={{ width: `${counts.queued / total * 100}%` }} />
          <span className="chart-segment paused" style={{ width: `${counts.paused / total * 100}%` }} />
          <span className="chart-segment completed" style={{ width: `${counts.completed / total * 100}%` }} />
          <span className="chart-segment failed" style={{ width: `${counts.failed / total * 100}%` }} />
          <span className="chart-segment cancelled" style={{ width: `${counts.cancelled / total * 100}%` }} />
        </div>
      </section>

      <section className="job-bulk-panel">
        <label className="bulk-select-toggle">
          <input
            type="checkbox"
            checked={jobs.length > 0 && selectedIds.length === jobs.length}
            onChange={toggleAllJobs}
          />
          <span>{selectedIds.length ? `已选择 ${selectedIds.length} 项任务` : "多选任务"}</span>
        </label>
        {selectedIds.length > 0 && (
          <div className="bulk-actions">
            <button onClick={() => runBatch("pause")} disabled={busy === "batch-pause"}><Square size={15} /> 暂停</button>
            <button onClick={() => runBatch("resume")} disabled={busy === "batch-resume"}><Play size={15} /> 恢复</button>
            <button onClick={() => runBatch("retry")} disabled={busy === "batch-retry"}><RefreshCw size={15} /> 重试</button>
            <button className="danger-button" onClick={() => runBatch("cancel")} disabled={busy === "batch-cancel"}><XCircle size={15} /> 停止</button>
          </div>
        )}
      </section>

      <section className="jobs-list">
        {jobs.length === 0 && <EmptyState title="排字台暂时空闲" body="归档 PDF 或批量整理后，任务进度会在这里显示。" />}
        {jobs.map((job) => {
          const isExpanded = expanded.has(job.id);
          const hasEvents = (job.events ?? []).length > 0;
          const selected = selectedJobIds.has(job.id);
          const canPause = ["queued", "running"].includes(job.status);
          const canResume = job.status === "paused";
          const canRetry = ["failed", "cancelled"].includes(job.status);
          return (
            <article className={`job-card ${job.status} ${selected ? "selected" : ""}`} key={job.id}>
              <div className="job-card-header">
                <label className="job-select-check" title="选择任务">
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => toggleJobSelection(job.id)}
                  />
                </label>
                <div>
                  <h2>{job.title}</h2>
                  <p>{jobKindLabel(job.kind)}{job.paper_id ? ` · ${job.paper_id}` : ""} · {job.stage} · 第 {job.attempts ?? 0} 次</p>
                </div>
                <span className={`job-status ${job.status}`}>{jobStatusLabel(job.status)}</span>
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
                  {canPause && <button onClick={() => pauseJob(job.id)} disabled={busy === `pause-${job.id}`}><Square size={15} /> 暂停</button>}
                  {canResume && <button onClick={() => resumeJob(job.id)} disabled={busy === `resume-${job.id}`}><Play size={15} /> 恢复</button>}
                  {canRetry && <button onClick={() => retryJob(job.id)} disabled={busy === `retry-${job.id}`}><RefreshCw size={15} /> 重试</button>}
                  <button onClick={() => cancelJob(job.id)} disabled={["completed", "failed", "cancelled"].includes(job.status) || busy === `cancel-${job.id}`}>
                    {busy === `cancel-${job.id}` ? <Loader2 className="spin" size={15} /> : <XCircle size={15} />} 停止
                  </button>
                  <button className="danger-button" onClick={() => deleteJob(job.id)} disabled={busy === `delete-${job.id}`}>
                    {busy === `delete-${job.id}` ? <Loader2 className="spin" size={15} /> : <Trash2 size={15} />} 删除
                  </button>
                </div>
              </div>
              {job.last_error && <p className="job-error-text">{job.last_error}</p>}
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

function jobStatusLabel(status: string): string {
  if (status === "queued") return "等待";
  if (status === "running") return "运行";
  if (status === "paused") return "暂停";
  if (status === "completed") return "完成";
  if (status === "failed") return "失败";
  if (status === "cancelled") return "停止";
  return status;
}

// ── Settings ─────────────────────────────────────────────────────────

function SettingsPage(props: {
  root: string; setRoot: (v: string) => void;
  claudeEndpoint: string; setClaudeEndpoint: (v: string) => void;
  claudeApiKey: string; setClaudeApiKey: (v: string) => void;
  claudeModel: string; setClaudeModel: (v: string) => void;
  maxConcurrency: number; setMaxConcurrency: (v: number) => void;
  translationEngine: "local" | "llm";
  setTranslationEngine: (v: "local" | "llm") => void;
  defaultSummaryLanguage: SummaryLanguage;
  setDefaultSummaryLanguage: (v: SummaryLanguage) => void;
  mineruApiToken: string; setMineruApiToken: (v: string) => void;
  mineruExtractionMode: MinerUExtractionMode;
  setMineruExtractionMode: (v: MinerUExtractionMode) => void;
  mineruModel: "vlm" | "pipeline"; setMineruModel: (v: "vlm" | "pipeline") => void;
  mineruAllowRemote: boolean; setMineruAllowRemote: (v: boolean) => void;
  syncMode: "local" | "git"; setSyncMode: (v: "local" | "git") => void;
  gitRemote: string; setGitRemote: (v: string) => void;
  gitRemoteUrl: string; setGitRemoteUrl: (v: string) => void;
  gitBranch: string; setGitBranch: (v: string) => void;
  gitSyncPdfs: boolean; setGitSyncPdfs: (v: boolean) => void;
  gitSyncChats: boolean; setGitSyncChats: (v: boolean) => void;
  gitAutoSync: boolean; setGitAutoSync: (v: boolean) => void;
  gitSyncIntervalMinutes: number; setGitSyncIntervalMinutes: (v: number) => void;
  syncStatus: SyncStatus | null; syncNow: () => void;
  busy: string; saveRoot: () => void;
}) {
  const decConcurrency = () => props.setMaxConcurrency(Math.max(1, props.maxConcurrency - 1));
  const incConcurrency = () => props.setMaxConcurrency(Math.min(20, props.maxConcurrency + 1));
  return (
    <div className="settings-page">
      <section className="page-heading">
        <p className="kicker">系统设置</p>
        <h1>设置</h1>
        <p>配置文献库根目录与自动整理服务。</p>
      </section>
      <section className="settings-grid">
        <div className="panel settings-panel settings-panel-wide">
          <label className="label"><FolderCog size={15} /> 文献库根目录</label>
          <div className="root-row">
            <input
              value={props.root}
              onChange={(e) => props.setRoot(e.target.value)}
              placeholder="/path/to/kb"
            />
          </div>
          <p className="hint">包含 papers/ 与 originals/papers/ 的独立数据目录；不要选择 NeuNote 代码仓库。</p>
        </div>

        <div className="panel settings-panel settings-panel-wide sync-settings-panel">
          <label className="label"><CloudUpload size={15} /> 用户数据同步</label>
          <div className="ios-segmented" role="radiogroup" aria-label="用户数据同步方式">
            <button
              type="button" role="radio" aria-checked={props.syncMode === "local"}
              className={props.syncMode === "local" ? "active" : ""}
              onClick={() => props.setSyncMode("local")}
            >
              <HardDrive size={14} /> 仅本地
            </button>
            <button
              type="button" role="radio" aria-checked={props.syncMode === "git"}
              className={props.syncMode === "git" ? "active" : ""}
              onClick={() => props.setSyncMode("git")}
            >
              <GitBranch size={14} /> Git 同步
            </button>
          </div>
          <p className="hint">论文 YAML 始终是同步内容；API 密钥、本机路径、任务和调试日志永远仅保存在本地。远端默认直连失败时，会自动改用本机 127.0.0.1:7890 代理重试。</p>

          {props.syncMode === "git" && (
            <div className="git-sync-options">
              <div className="git-fields">
                <label>
                  <span>远端名称</span>
                  <input value={props.gitRemote} onChange={(e) => props.setGitRemote(e.target.value)} placeholder="origin" />
                </label>
                <label>
                  <span>分支</span>
                  <input value={props.gitBranch} onChange={(e) => props.setGitBranch(e.target.value)} placeholder="main" />
                </label>
              </div>
              <label>
                <span>远端仓库 URL</span>
                <input
                  value={props.gitRemoteUrl}
                  onChange={(e) => props.setGitRemoteUrl(e.target.value)}
                  placeholder="已有 origin 时可留空；请使用系统 Git 凭据"
                />
              </label>
              <label className="sync-check-row">
                <input type="checkbox" checked={props.gitSyncChats} onChange={(e) => props.setGitSyncChats(e.target.checked)} />
                <span><strong>同步聊天记录</strong><small>包含私人研究信息；关闭后，下次同步会从远端撤回并保留本地副本。</small></span>
              </label>
              <label className="sync-check-row">
                <input type="checkbox" checked={props.gitSyncPdfs} onChange={(e) => props.setGitSyncPdfs(e.target.checked)} />
                <span><strong>同步原始 PDF</strong><small>仅建议用于私有仓库；关闭后，下次同步会从远端撤回并保留本地文件。</small></span>
              </label>
              <label className="sync-check-row">
                <input type="checkbox" checked={props.gitAutoSync} onChange={(e) => props.setGitAutoSync(e.target.checked)} />
                <span><strong>定时同步</strong><small>后端持续运行时，按设定间隔检查、提交、拉取并推送用户数据。</small></span>
              </label>
              {props.gitAutoSync && (
                <label className="sync-interval-row">
                  <span>同步间隔（分钟）</span>
                  <input
                    type="number" min={1} max={1440}
                    value={props.gitSyncIntervalMinutes}
                    onChange={(e) => props.setGitSyncIntervalMinutes(Math.max(1, Math.min(1440, Number(e.target.value) || 10)))}
                  />
                </label>
              )}
              <div className="sync-status-card">
                <div>
                  <strong>{props.syncStatus?.detail ?? "保存设置后可查看 Git 状态。"}</strong>
                  {props.syncStatus?.last_commit && <small>最近提交：{props.syncStatus.last_commit}</small>}
                  {typeof props.syncStatus?.pending_files === "number" && <small>待同步项：{props.syncStatus.pending_files}</small>}
                  {props.syncStatus?.inventory && (
                    <small className={props.syncStatus.inventory.complete ? "" : "sync-error"}>
                      完整性：{props.syncStatus.inventory.paper_records} 份档案 · {props.syncStatus.inventory.pdf_files} 份 PDF · {props.syncStatus.inventory.figure_files} 张配图 · {props.syncStatus.inventory.chat_sessions} 个对话
                      {!props.syncStatus.inventory.complete && ` · 发现 ${props.syncStatus.inventory.invalid_papers.length + props.syncStatus.inventory.missing_pdf_references.length + props.syncStatus.inventory.missing_figure_references.length} 项异常`}
                    </small>
                  )}
                  {props.syncStatus?.auto_sync?.running && <small>定时同步正在运行…</small>}
                  {props.syncStatus?.auto_sync?.next_sync_at && (
                    <small>下次检查：{new Date(props.syncStatus.auto_sync.next_sync_at).toLocaleString("zh-CN")}</small>
                  )}
                  {props.syncStatus?.auto_sync?.last_error && <small className="sync-error">上次定时同步失败：{props.syncStatus.auto_sync.last_error}</small>}
                </div>
                <button type="button" onClick={props.syncNow} disabled={props.busy === "git-sync"} className="sync-now-btn">
                  {props.busy === "git-sync" ? <Loader2 className="spin" size={15} /> : <RefreshCw size={15} />}
                  立即同步
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="panel settings-panel">
          <label className="label"><KeyRound size={15} /> 智能代理接口</label>
          <input
            value={props.claudeEndpoint}
            onChange={(e) => props.setClaudeEndpoint(e.target.value)}
            placeholder="Endpoint / base URL (optional)"
          />
          <input
            value={props.claudeApiKey}
            onChange={(e) => props.setClaudeApiKey(e.target.value)}
            type="password"
            placeholder="API key"
          />
          <input
            value={props.claudeModel}
            onChange={(e) => props.setClaudeModel(e.target.value)}
            placeholder="Model, e.g. sonnet"
          />
        </div>

        <div className="panel settings-panel">
          <label className="label"><Languages size={15} /> 翻译引擎</label>
          <div
            className="ios-segmented"
            role="radiogroup"
            aria-label="翻译引擎"
          >
            <button
              type="button"
              className={props.translationEngine === "local" ? "active" : ""}
              role="radio"
              aria-checked={props.translationEngine === "local"}
              onClick={() => props.setTranslationEngine("local")}
            >
              本地模型
            </button>
            <button
              type="button"
              className={props.translationEngine === "llm" ? "active" : ""}
              role="radio"
              aria-checked={props.translationEngine === "llm"}
              onClick={() => props.setTranslationEngine("llm")}
            >
              LLM 服务
            </button>
          </div>
          <p className="hint">
            {props.translationEngine === "llm"
              ? "使用上方配置的 Claude 兼容接口生成翻译，质量更好但需要联网和 API 配额。"
              : "使用本地 Argos Translate 离线模型，无需联网，但译文偏直译、术语一致性较弱。"}
          </p>
        </div>

        <div className="panel settings-panel">
          <label className="label"><BookOpen size={15} /> 文献详情默认语言</label>
          <div
            className="ios-segmented"
            role="radiogroup"
            aria-label="文献详情默认语言"
          >
            <button
              type="button"
              className={props.defaultSummaryLanguage === "en" ? "active" : ""}
              role="radio"
              aria-checked={props.defaultSummaryLanguage === "en"}
              onClick={() => props.setDefaultSummaryLanguage("en")}
            >
              English
            </button>
            <button
              type="button"
              className={props.defaultSummaryLanguage === "zh" ? "active" : ""}
              role="radio"
              aria-checked={props.defaultSummaryLanguage === "zh"}
              onClick={() => props.setDefaultSummaryLanguage("zh")}
            >
              中文
            </button>
          </div>
          <p className="hint">进入论文详情页时的摘要展示语言；选择中文时，已有译文会优先显示，未生成译文的论文仍显示英文。</p>
        </div>

        <div className="panel settings-panel">
          <label className="label"><Sparkles size={15} /> MinerU 文档解析</label>
          <div
            className="ios-segmented"
            role="radiogroup"
            aria-label="MinerU 解析方式"
          >
            <button
              type="button"
              className={props.mineruExtractionMode === "auto" ? "active" : ""}
              role="radio"
              aria-checked={props.mineruExtractionMode === "auto"}
              onClick={() => props.setMineruExtractionMode("auto")}
            >
              自动
            </button>
            <button
              type="button"
              className={props.mineruExtractionMode === "precision" ? "active" : ""}
              role="radio"
              aria-checked={props.mineruExtractionMode === "precision"}
              onClick={() => props.setMineruExtractionMode("precision")}
            >
              精确
            </button>
            <button
              type="button"
              className={props.mineruExtractionMode === "flash" ? "active" : ""}
              role="radio"
              aria-checked={props.mineruExtractionMode === "flash"}
              onClick={() => props.setMineruExtractionMode("flash")}
            >
              快速
            </button>
          </div>
          <input
            type="password"
            value={props.mineruApiToken}
            onChange={(e) => props.setMineruApiToken(e.target.value)}
            placeholder="MinerU API Token（精确模式需要）"
            autoComplete="off"
          />
          <label className="sync-check-row">
            <input
              type="checkbox"
              checked={props.mineruAllowRemote}
              onChange={(e) => props.setMineruAllowRemote(e.target.checked)}
            />
            <span><strong>允许发送文档到 MinerU 服务</strong><small>默认开启。MinerU 会解析 PDF 的正文、版面、表格、公式与图片；关闭后无法执行 AI 整理。</small></span>
          </label>
          <p className="hint">
            {props.mineruExtractionMode === "precision"
              ? "精确模式使用 VLM 解析复杂学术版式，并保留结构化 Markdown、图片、表格和公式。"
              : "自动模式有 Token 时使用精确解析；未配置 Token 时使用 MinerU 免登录解析。快速模式始终使用免登录解析。"}
          </p>
        </div>

        <div className="panel settings-panel">
          <label className="label"><Zap size={15} /> 并行整理</label>
          <div className="concurrency-row">
            <span className="concurrency-label">最大并发任务</span>
            <div className="ios-stepper" role="group" aria-label="最大并发任务">
              <button
                type="button"
                className="ios-stepper-btn"
                onClick={decConcurrency}
                disabled={props.maxConcurrency <= 1}
                aria-label="减少"
              >
                <Minus size={15} strokeWidth={2.5} />
              </button>
              <span className="ios-stepper-value" aria-live="polite">{props.maxConcurrency}</span>
              <button
                type="button"
                className="ios-stepper-btn"
                onClick={incConcurrency}
                disabled={props.maxConcurrency >= 20}
                aria-label="增加"
              >
                <Plus size={15} strokeWidth={2.5} />
              </button>
            </div>
          </div>
          <p className="hint">同时整理的文献数量，通常建议 4–8。</p>
        </div>
      </section>
      <button
        onClick={props.saveRoot}
        disabled={props.busy === "root"}
        className="save-settings-btn ios-save-button"
      >
        {props.busy === "root" ? <Loader2 className="spin" size={16} /> : null}
        保存设置
      </button>
    </div>
  );
}

// ── mount ────────────────────────────────────────────────────────────

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error('NeuNote: <div id="root"> missing from index.html — cannot mount.');
}
createRoot(rootEl).render(<App />);
