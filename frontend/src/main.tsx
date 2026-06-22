import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
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
  Clock3,
  Copy,
  Bot,
  ExternalLink,
  FileText,
  FolderCog,
  Gauge,
  Globe,
  KeyRound,
  Languages,
  Library,
  Loader2,
  MessageCircle,
  Minus,
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

type Page = "dashboard" | "library" | "profile" | "chat" | "jobs" | "settings";

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

type ChatSessionSummary = {
  id: string;
  title: string;
  created_at?: string;
  updated_at?: string;
  message_count: number;
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
  const [root, setRoot] = useState("");
  const [savedRoot, setSavedRoot] = useState("");
  const [claudeApiKey, setClaudeApiKey] = useState("");
  const [claudeEndpoint, setClaudeEndpoint] = useState("");
  const [claudeModel, setClaudeModel] = useState("sonnet");
  const [translationEngine, setTranslationEngine] = useState<"local" | "llm">("llm");
  const [maxConcurrency, setMaxConcurrency] = useState(4);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [stats, setStats] = useState<Stats>({ papers: 0, needs_review: 0, profiled: 0, tags: 0, duplicate_groups: 0, duplicate_papers: 0 });
  const [jobs, setJobs] = useState<Job[]>([]);
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
    const data = await request<{
      root: string;
      claude_api_key?: string;
      claude_endpoint?: string;
      claude_model?: string;
      max_concurrency?: number;
      translation_engine?: "local" | "llm";
    }>("/api/config");
    setRoot(data.root);
    setSavedRoot(data.root);
    setClaudeApiKey(data.claude_api_key ?? "");
    setClaudeEndpoint(data.claude_endpoint ?? "");
    setClaudeModel(data.claude_model ?? "sonnet");
    setMaxConcurrency(data.max_concurrency ?? 4);
    setTranslationEngine(data.translation_engine ?? "local");
    await loadPapers(data.root);
    await loadJobs(data.root);
    await loadDuplicates(data.root);
    await loadSessions(data.root);
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
      const data = await request<{ root: string; translation_engine?: "local" | "llm" }>("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          root,
          claude_api_key: claudeApiKey,
          claude_endpoint: claudeEndpoint,
          claude_model: claudeModel,
          max_concurrency: maxConcurrency,
          translation_engine: translationEngine,
        }),
      });
      setSavedRoot(data.root);
      setRoot(data.root);
      if (data.translation_engine) setTranslationEngine(data.translation_engine);
      await loadPapers(data.root);
      await loadJobs(data.root);
      await loadSessions(data.root);
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
    // Bump the sequence; any earlier in-flight call will see the mismatch
    // when its fetch resolves and bail out instead of clobbering state.
    const seq = ++openProfileSeq.current;
    setBusy("profile");
    setError("");
    setSelectedPaperId(paperId);
    setPage("profile");
    try {
      const params = savedRoot ? `?root=${encodeURIComponent(savedRoot)}` : "";
      const data = await request<{ paper: Paper }>(`/api/papers/${encodeURIComponent(paperId)}${params}`);
      if (seq !== openProfileSeq.current) return; // stale, newer click won
      setSelectedPaper(data.paper);
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

  async function translatePaper(paperId: string) {
    setBusy("translate");
    setError("");
    try {
      const data = await request<{ translations: Record<string, string | string[]> }>(
        `/api/papers/${encodeURIComponent(paperId)}/translate`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ root: savedRoot }) }
      );
      // Spread from selectedPaperRef (live) so concurrent fields updated by
      // loadPapers during the await aren't clobbered. Guard on id to avoid
      // clobbering a different paper the user has navigated to.
      if (selectedPaperIdRef.current === paperId && selectedPaperRef.current) {
        setSelectedPaper({ ...selectedPaperRef.current, translations: data.translations });
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
            paperJobs={paperJobs} enrichAll={enrichAll}
          />
        )}
        {page === "profile" && (
          <ProfilePage
            paper={selectedPaper} busy={busy}
            goBack={() => setPage("library")}
            openChat={openPaperChat}
            enrichPaper={enrichPaper} translatePaper={translatePaper}
            updatePaper={updatePaper}
            deletePaper={deletePaper} openPdf={openPdf}
            paperJob={selectedPaperId ? paperJobs.get(selectedPaperId) : undefined}
            tagCounts={tagCounts}
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
            busy={busy}
            newChat={openGeneralChat}
            openSession={loadChatSession}
            openPdf={openPdf}
            sendMessage={sendChatMessage}
            stopChat={stopChat}
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
            translationEngine={translationEngine} setTranslationEngine={setTranslationEngine}
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
        <span><strong>NeuNote</strong><small>{paperCount} entries archived</small></span>
      </button>
      <nav>
        <button className={page === "dashboard" ? "active" : ""} onClick={() => setPage("dashboard")}><Gauge size={16} /> 档案总览</button>
        <button className={page === "library" || page === "profile" ? "active" : ""} onClick={() => setPage("library")}><Library size={16} /> 文献档案</button>
        <button className={page === "chat" ? "active" : ""} onClick={openChat}><MessageCircle size={16} /> 对话</button>
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

function computeNoteStats(text: string): { words: number; minutes: number } {
  const stripped = text.replace(/```[\s\S]*?```/g, "").replace(/[#>*_`~\-]/g, " ");
  const cjk = (text.match(/[\u4e00-\u9fff\u3400-\u4dbf]/g) || []).length;
  const asciiWords = stripped.split(/\s+/).filter(Boolean).length;
  const words = cjk + asciiWords;
  const minutes = Math.max(1, Math.round(cjk / 300 + asciiWords / 200));
  return { words, minutes };
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

// ── NotesEditor (边注: debounced auto-save + markdown preview) ────

type NotesStatus = "clean" | "dirty" | "saving" | "saved" | "error";
type ViewMode = "edit" | "preview" | "split";

function NotesEditor(props: {
  notes: string;
  busy: boolean;
  onCommit: (next: string) => Promise<void> | void;
}) {
  const [local, setLocal] = useState<string>(props.notes);
  const [status, setStatus] = useState<NotesStatus>("clean");
  const [mode, setMode] = useState<ViewMode>("edit");
  const lastSentRef = useRef<string>(props.notes);
  const debounceRef = useRef<number | null>(null);
  const fadeTimerRef = useRef<number | null>(null);

  async function flush() {
    if (debounceRef.current !== null) {
      window.clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    if (local === lastSentRef.current) return;
    setStatus("saving");
    try {
      await props.onCommit(local);
      lastSentRef.current = local;
      setStatus("saved");
      if (fadeTimerRef.current) window.clearTimeout(fadeTimerRef.current);
      fadeTimerRef.current = window.setTimeout(() => setStatus("clean"), 2000);
    } catch {
      setStatus("error");
    }
  }

  useEffect(() => {
    if (local === lastSentRef.current) return;
    setStatus("dirty");
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      debounceRef.current = null;
      void flush();
    }, 1200);
  }, [local]);

  useEffect(() => () => {
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    if (fadeTimerRef.current !== null) window.clearTimeout(fadeTimerRef.current);
  }, []);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "s" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void flush();
    } else if (e.key === "Escape") {
      (e.target as HTMLTextAreaElement).blur();
    }
  };

  const stats = useMemo(() => computeNoteStats(local), [local]);

  return (
    <div className="notes-editor">
      <div className="notes-toolbar">
        <div className="notes-mode">
          <button type="button" className={mode === "edit" ? "active" : ""} onClick={() => setMode("edit")}>
            <FileText size={13} /> 编辑
          </button>
          <button type="button" className={mode === "preview" ? "active" : ""} onClick={() => setMode("preview")}>
            <ExternalLink size={13} /> 预览
          </button>
          <button type="button" className={mode === "split" ? "active" : ""} onClick={() => setMode("split")}>
            <Copy size={13} /> 分栏
          </button>
        </div>
        <div className="notes-stats">
          <span>{stats.words} 字 · ≈{stats.minutes} 分钟阅读</span>
        </div>
        <div className={`notes-status notes-status-${status}`}>
          {status === "clean" && <span>·</span>}
          {status === "dirty" && <span>● 未保存</span>}
          {status === "saving" && <span><Loader2 className="spin" size={12} /> 保存中</span>}
          {status === "saved" && <span><CheckCircle2 size={12} /> 已保存</span>}
          {status === "error" && <span>✗ 失败</span>}
        </div>
      </div>
      <div className={`notes-body notes-body-${mode}`}>
        {(mode === "edit" || mode === "split") && (
          <textarea
            className="notes-textarea"
            value={local}
            onChange={(e) => setLocal(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="写下你的边注… 支持 Markdown（# 标题, - 列表, > 引用, **加粗**, `代码`）。Cmd/Ctrl+S 强制保存。"
            rows={16}
            spellCheck={false}
          />
        )}
        {(mode === "preview" || mode === "split") && (
          <div className="notes-preview markdown-body">
            {local.trim()
              ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{local}</ReactMarkdown>
              : <p className="muted small">暂无内容</p>}
          </div>
        )}
      </div>
      <div className="notes-footer">
        <span className="muted small">Cmd/Ctrl + S 立即保存 · Esc 收起</span>
        <button type="button" onClick={() => void flush()} disabled={status === "saving" || local === lastSentRef.current}>
          {status === "saving" ? <Loader2 className="spin" size={14} /> : <RefreshCw size={14} />}
          立即保存
        </button>
      </div>
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
  paperJob?: Job;
  tagCounts: [string, number][];
}) {
  const paper = props.paper;
  const [showChinese, setShowChinese] = useState(false);

  useEffect(() => {
    if (paper) setShowChinese(false);
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
            <button className="chat-launch-button" onClick={() => props.openChat(paper)}>
              <MessageCircle size={15} /> 论文 Chat
            </button>
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
            <h2>校阅札记</h2>
            <ReviewNotesEditor
              key={paper.id}
              notes={normalizeReviewNotes(paper.review_notes)}
              busy={props.busy === "save"}
              onCommit={(next) => props.updatePaper(paper.id, { review_notes: next })}
            />
          </section>
          <section className="panel">
            <h2>边注</h2>
            <NotesEditor
              key={paper.id}
              notes={paper.notes ?? ""}
              busy={props.busy === "save"}
              onCommit={(next) => props.updatePaper(paper.id, { notes: next })}
            />
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
  busy: string;
  newChat: () => void;
  openSession: (sessionId: string) => void;
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
    "帮我找出库里和 agent harness 相关的论文。",
  ];

  return (
    <div className="chat-page chat-module-page">
      <aside className="chat-history-panel">
        <div className="chat-history-head">
          <div>
            <p className="kicker">Chat Logs</p>
            <h2>历史对话</h2>
          </div>
          <button type="button" className="icon-button" onClick={props.newChat} aria-label="新对话" title="新对话">
            <Plus size={16} />
          </button>
        </div>
        <div className="chat-session-list">
          {props.sessions.length ? props.sessions.map((session) => (
            <button
              key={session.id}
              type="button"
              className={session.id === props.activeSessionId ? "active" : ""}
              onClick={() => props.openSession(session.id)}
            >
              <strong>{session.title}</strong>
              <span>{session.message_count} 条消息 · {formatDateShort(session.updated_at)}</span>
            </button>
          )) : (
            <p className="empty-note">暂无历史对话</p>
          )}
        </div>
      </aside>

      <section className="chat-main-panel">
        <section className="chat-topbar">
          <div className="chat-title">
            <p className="kicker">NeuNote Chat</p>
            <h1>和文献库对话</h1>
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
              props.messages.map((message) => <ChatMessageView key={message.id} message={message} paperById={paperById} />)
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

function ChatMessageView({ message, paperById }: { message: ChatMessage; paperById: Map<string, Paper> }) {
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
              <ToolCallView key={segment.id} tool={segment.tool} />
            ) : (
              <div className="markdown-body chat-markdown chat-segment" key={segment.id}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{segment.content}</ReactMarkdown>
              </div>
            )
          ))
        ) : (
          <>
            {message.role === "assistant" && (message.tools ?? []).map((tool) => (
              <ToolCallView key={tool.id} tool={tool} />
            ))}
            {message.content ? (
              <div className="markdown-body chat-markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
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

function ToolCallView({ tool }: { tool: ChatToolCall }) {
  const [open, setOpen] = useState(false);
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
  translationEngine: "local" | "llm";
  setTranslationEngine: (v: "local" | "llm") => void;
  busy: string; saveRoot: () => void;
}) {
  const decConcurrency = () => props.setMaxConcurrency(Math.max(1, props.maxConcurrency - 1));
  const incConcurrency = () => props.setMaxConcurrency(Math.min(20, props.maxConcurrency + 1));
  return (
    <div className="settings-page">
      <section className="page-heading">
        <p className="kicker">Press Settings</p>
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
          <p className="hint">包含 papers/ 与 originals/papers/ 的目录。</p>
        </div>

        <div className="panel settings-panel">
          <label className="label"><KeyRound size={15} /> Agent API</label>
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
