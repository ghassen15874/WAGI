import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { useAgent } from "../hooks/useAgent";
import ChatPanel from "../components/ChatPanel";
import WebContainerPreview from "../components/WebContainerPreview";
import FileTree from "../components/FileTree";
import SettingsPage from "./SettingsPage";
import { Settings, Plus, MessageSquare, LogOut, LayoutDashboard, Trash2, Download, Sun, Moon, Play } from "lucide-react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../hooks/useTheme";

type Tab = "preview" | "files";
const BUILDER_PREFS_KEY = "builder_page_preferences";

export default function BuilderPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { state, generate, stop, reset, loadProject, reconnect, resumeGeneration } = useAgent();
  const { token, logout } = useAuth();
  const [tab, setTab] = useState<Tab>("preview");
  const [showSettings, setShowSettings] = useState(false);
  const [provider, setProvider] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(BUILDER_PREFS_KEY) || "{}");
      return saved.provider || "groq";
    } catch {
      return "groq";
    }
  });
  const [model, setModel] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(BUILDER_PREFS_KEY) || "{}");
      return saved.model || "llama-3.3-70b-versatile";
    } catch {
      return "llama-3.3-70b-versatile";
    }
  });
  const [apiKey, setApiKey] = useState("");
  const [projects, setProjects] = useState<any[]>([]);
  const [showPreview, setShowPreview] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [availableProviders, setAvailableProviders] = useState<Array<{ id: string; name: string; models: string[] }>>([]);
  const [runningProjectId, setRunningProjectId] = useState<string | null>(null);
  const [runtimeProjectId, setRuntimeProjectId] = useState<string | null>(null);
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);
  const [initialPrompt, setInitialPrompt] = useState("");
  const [isInitialState, setIsInitialState] = useState(true);
  const { theme, toggleTheme } = useTheme();
  const shouldAutoOpenGeneratedSessionRef = useRef(false);
  const skipProjectHydrationRef = useRef(false);

  const fileCount = state.files ? Object.keys(state.files).length : 0;

  useEffect(() => {
    if (state.status === 'generating' || fileCount > 0 || state.sessionId) {
      setIsInitialState(false);
    }
  }, [state.status, fileCount, state.sessionId]);

  useEffect(() => {
    if (state.status === 'generating') {
      setShowPreview(true);
      setIsPreviewOpen(true);
      if (state.sessionId) {
        setRuntimeProjectId(state.sessionId);
      }
    }
  }, [state.status, state.sessionId]);

  useEffect(() => {
    if (token) {
      axios
        .get("/api/projects", { headers: { Authorization: `Bearer ${token}` } })
        .then((res) => setProjects(res.data.projects))
        .catch(console.error);
    }
  }, [token, state.sessionId]);

  useEffect(() => {
    const fetchProviders = () => {
      axios
        .get("/api/providers")
        .then((res) => {
          const providers = Array.isArray(res.data.providers)
            ? res.data.providers.filter((item: any) => item.id !== "auto")
            : [];
          setAvailableProviders(providers);

          if (!providers.length) {
            return;
          }

          const selectedProvider = providers.find((item: any) => item.id === provider);
          if (!selectedProvider) {
            setProvider(providers[0].id);
            setModel(providers[0].models?.[0] || "");
            return;
          }

          if (!selectedProvider.models?.includes(model)) {
            setModel(selectedProvider.models?.[0] || "");
          }
        })
        .catch(console.error);
    };

    fetchProviders();
    window.addEventListener("focus", fetchProviders);
    return () => window.removeEventListener("focus", fetchProviders);
  }, [provider, model]);

  useEffect(() => {
    localStorage.setItem(BUILDER_PREFS_KEY, JSON.stringify({ provider, model }));
  }, [provider, model]);

  const handleDeleteProject = async (projId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("Are you sure you want to delete this project?")) return;
    try {
      await axios.delete(`/api/projects/${projId}`, { headers: { Authorization: `Bearer ${token}` } });
      setProjects((prev) => prev.filter((p) => p.id !== projId));
      if (state.sessionId === projId || id === projId) {
        reset();
        navigate("/app");
      }
    } catch (e) {
      console.error("Failed to delete project", e);
    }
  };

  const handleExportProject = async (projId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const response = await axios.get(`/api/projects/${projId}/export`, {
        headers: { Authorization: `Bearer ${token}` },
        responseType: "blob",
      });
      const blobUrl = window.URL.createObjectURL(new Blob([response.data], { type: "application/zip" }));
      const link = document.createElement("a");
      link.href = blobUrl;
      const projectName = `${projects.find((p) => p.id === projId)?.name || "project"}`
        .replace(/[^a-z0-9-_]+/gi, "-")
        .replace(/-+/g, "-")
        .replace(/^-|-$/g, "") || "project";
      link.download = `${projectName}.zip`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(blobUrl);
    } catch (e: any) {
      console.error("Failed to export project", e);
      alert(e?.response?.data?.detail || "Failed to export project as ZIP");
    }
  };

  const handleRunProject = async (projId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!token) return;
    setRunningProjectId(projId);
    try {
      await axios.post(
        `/api/projects/${projId}/run`,
        {},
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      setRuntimeProjectId(projId);
      navigate(`/app/${projId}`);
      setShowPreview(true);
      setIsPreviewOpen(true);
    } catch (err: any) {
      console.error("Failed to run project runtime", err);
      alert(err?.response?.data?.detail || "Failed to run this project");
    } finally {
      setRunningProjectId(null);
    }
  };

  useEffect(() => {
    if (skipProjectHydrationRef.current) {
      return;
    }

    if (!id || !token || state.sessionId === id) {
      return;
    }

    const proj = projects.find((p) => p.id === id);
    const projectUpdatedAt = proj?.updated_at ? new Date(proj.updated_at).getTime() : 0;
    const isFreshGenerating = proj?.status === "GENERATING" && projectUpdatedAt > 0 && (Date.now() - projectUpdatedAt) < 5 * 60 * 1000;

    if (isFreshGenerating) {
      reconnect(id);
      return;
    }

    loadProject(id, token);
  }, [id, token, projects, state.sessionId, reconnect, loadProject]);

  useEffect(() => {
    if (!id) {
      skipProjectHydrationRef.current = false;
    }
  }, [id]);

  useEffect(() => {
    // Only auto-route after generation creates/selects a session from the root /app page.
    // Do not override explicit user navigation between /app/:id routes.
    if (!id && state.sessionId && shouldAutoOpenGeneratedSessionRef.current) {
      shouldAutoOpenGeneratedSessionRef.current = false;
      navigate(`/app/${state.sessionId}`, { replace: true });
    }
  }, [state.sessionId, id, navigate]);

  useEffect(() => {
    if (state.status === "generating") {
      setShowLogs(true);
    }
  }, [state.status]);

  useEffect(() => {
    if (!id || !runtimeProjectId || state.status === "generating") {
      return;
    }
    if (id !== runtimeProjectId) {
      setShowPreview(false);
      setIsPreviewOpen(false);
    }
  }, [id, runtimeProjectId, state.status]);

  const handleNewProject = () => {
    skipProjectHydrationRef.current = true;
    reset();
    shouldAutoOpenGeneratedSessionRef.current = false;
    setInitialPrompt("");
    setIsInitialState(true);
    setShowPreview(false);
    setIsPreviewOpen(false);
    setShowLogs(false);
    setRuntimeProjectId(null);
    navigate("/app");
  };

  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        fontFamily: "var(--font-sans)",
        background: "var(--color-bg)",
        overflow: "hidden",
      }}
    >
      {/* Global Sidebar */}
      <div
        style={{
          width: 260,
          background: "var(--color-surface)",
          borderRight: "1px solid var(--color-border)",
          display: "flex",
          flexDirection: "column",
          flexShrink: 0,
        }}
      >
        {/* Sidebar Header */}
        <div style={{ padding: "16px", borderBottom: "1px solid var(--color-border)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <button
              onClick={handleNewProject}
              className="btn btn-primary"
              style={{ padding: "10px 16px", fontSize: 13 }}
            >
              <Plus size={16} /> New Project
            </button>
          </div>
        </div>

        {/* Projects List */}
        <div style={{ flex: 1, overflowY: "auto", padding: "12px" }}>
          <div
            style={{
              fontSize: 11,
              color: "var(--color-text-muted2)",
              fontWeight: 700,
              marginBottom: 8,
              padding: "0 8px",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}
          >
            Your Projects
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {projects.map((p) => (
              <div
                key={p.id}
                onClick={() => navigate(`/app/${p.id}`)}
                style={{
                  padding: "10px 12px",
                  borderRadius: "var(--radius-md)",
                  background: state.sessionId === p.id || id === p.id ? "var(--color-surface2)" : "transparent",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 13,
                  cursor: "pointer",
                  color: "var(--color-text)",
                  transition: "all var(--transition)",
                  border: "1px solid transparent",
                }}
              >
                <span
                  style={{
                    flex: 1,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    fontWeight: 500,
                  }}
                >
                  {p.name}
                </span>
                {(state.sessionId === p.id || id === p.id) && (
                  <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <button
                      onClick={(e) => handleRunProject(p.id, e)}
                      style={{
                        background: "transparent",
                        border: "none",
                        cursor: "pointer",
                        padding: 4,
                        display: "flex",
                        color: runningProjectId === p.id ? "var(--color-primary)" : "var(--color-text-muted)",
                        borderRadius: 4,
                      }}
                      title="Run Project Runtime"
                      disabled={runningProjectId === p.id}
                    >
                      <Play size={14} />
                    </button>
                    <button
                      onClick={(e) => handleExportProject(p.id, e)}
                      style={{
                        background: "transparent",
                        border: "none",
                        cursor: "pointer",
                        padding: 4,
                        display: "flex",
                        color: "var(--color-text-muted)",
                        borderRadius: 4,
                      }}
                      title="Export Project as ZIP"
                    >
                      <Download size={14} />
                    </button>
                    <button
                      onClick={(e) => handleDeleteProject(p.id, e)}
                      style={{
                        background: "transparent",
                        border: "none",
                        cursor: "pointer",
                        padding: 4,
                        display: "flex",
                        color: "var(--color-error)",
                        borderRadius: 4,
                      }}
                      title="Delete Project"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Sidebar Footer */}
        <div
          style={{
            padding: "12px 16px",
            borderTop: "1px solid var(--color-border)",
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          <Link
            to="/dashboard"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "10px 12px",
              borderRadius: "var(--radius-md)",
              textDecoration: "none",
              color: "var(--color-text)",
              fontSize: 13,
              fontWeight: 500,
              transition: "all var(--transition)",
            }}
          >
            <LayoutDashboard size={16} /> Dashboard
          </Link>
          <button
            onClick={toggleTheme}
            className="btn btn-text"
            style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: "var(--radius-md)", fontSize: 13, textAlign: "left" }}
          >
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />} {theme === "dark" ? "Light Mode" : "Dark Mode"}
          </button>
          <button
            onClick={logout}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "10px 12px",
              borderRadius: "var(--radius-md)",
              background: "transparent",
              border: "none",
              color: "var(--color-error)",
              fontSize: 13,
              cursor: "pointer",
              textAlign: "left",
              transition: "all var(--transition)",
            }}
          >
            <LogOut size={16} /> Log out
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          position: "relative",
          overflow: "hidden",
        }}
      >
        {isInitialState ? (
          /* Centered Initial State */
          <div
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "var(--color-bg)",
              padding: "24px",
              position: "relative",
            }}
          >
            <div
              style={{
                width: "100%",
                maxWidth: 700,
                display: "flex",
                flexDirection: "column",
                gap: 32,
                animation: "fadeIn 0.5s ease-out",
              }}
            >
              {/* Header */}
              <div style={{ textAlign: "center", marginBottom: 8 }}>
                <h1
                  style={{
                    fontSize: 36,
                    fontWeight: 700,
                    color: "var(--color-text)",
                    marginBottom: 12,
                    letterSpacing: "-0.02em",
                    lineHeight: 1.2,
                  }}
                >
                  What would you like to build?
                </h1>
                <p
                  style={{
                    fontSize: 16,
                    color: "var(--color-text-muted)",
                    lineHeight: 1.6,
                    maxWidth: 480,
                    margin: "0 auto",
                  }}
                >
                  Describe your idea in detail and I'll create a fully functional web application for you.
                </p>
              </div>

              {/* Input Area */}
              <div
                style={{
                  background: "var(--color-surface)",
                  border: "1px solid var(--color-border)",
                  borderRadius: 24,
                  padding: "16px 20px",
                  boxShadow: "var(--shadow-lg)",
                  transition: "all 0.3s ease",
                  borderColor: "var(--color-border-hover)",
                }}
              >
                <textarea
                  value={initialPrompt}
                  onChange={(e) => setInitialPrompt(e.target.value)}
                  onKeyDown={(e) => {
                    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                      e.preventDefault();
                      if (initialPrompt.trim()) {
                        shouldAutoOpenGeneratedSessionRef.current = true;
                        generate({
                          prompt: initialPrompt.trim(),
                          provider,
                          model,
                          apiKey,
                          projectId: state.sessionId || "",
                        });
                        setIsInitialState(false);
                      }
                    }
                  }}
                  placeholder="e.g., Build a modern SaaS dashboard with analytics charts, user management, and dark mode..."
                  rows={4}
                  autoFocus
                  style={{
                    width: "100%",
                    background: "transparent",
                    border: "none",
                    color: "var(--color-text)",
                    fontFamily: "var(--font-sans)",
                    fontSize: 15,
                    resize: "none",
                    outline: "none",
                    lineHeight: 1.6,
                    minHeight: 100,
                  }}
                />
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginTop: 12,
                    gap: 12,
                  }}
                >
                  <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                    Press Cmd+Enter to generate
                  </span>
                  <button
                    onClick={() => {
                      if (initialPrompt.trim()) {
                        shouldAutoOpenGeneratedSessionRef.current = true;
                        generate({
                          prompt: initialPrompt.trim(),
                          provider,
                          model,
                          apiKey,
                          projectId: state.sessionId || "",
                        });
                        setIsInitialState(false);
                      }
                    }}
                    disabled={!initialPrompt.trim()}
                    className="btn btn-primary"
                    style={{
                      padding: "10px 24px",
                      fontSize: 14,
                      opacity: !initialPrompt.trim() ? 0.5 : 1,
                      cursor: !initialPrompt.trim() ? "not-allowed" : "pointer",
                    }}
                  >
                    Generate App
                  </button>
                </div>
              </div>

              {/* Example Prompts */}
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ textAlign: "center" }}>
                  <span style={{ fontSize: 12, color: "var(--color-text-muted)", fontWeight: 500 }}>
                    Try an example
                  </span>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
                  {[
                    "Build a SaaS dashboard with charts",
                    "Create an e-commerce store",
                    "Build a portfolio website",
                    "Create a blog platform",
                  ].map((ex, i) => (
                    <button
                      key={i}
                      onClick={() => setInitialPrompt(ex)}
                      className="btn btn-ghost"
                      style={{
                        padding: "10px 18px",
                        fontSize: 13,
                        borderRadius: 20,
                        border: "1px solid var(--color-border)",
                        background: "var(--color-surface2)",
                      }}
                    >
                      {ex}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        ) : (
          /* Split Layout for Active Session */
          <>
            <style>{`
              @media (min-width: 1024px) {
                .split-layout {
                  flex-direction: row !important;
                }
                .preview-panel {
                  width: ${isPreviewOpen ? '55%' : '0%'};
                  transition: width 0.35s cubic-bezier(0.4, 0, 0.2, 1);
                }
                .chat-panel {
                  width: ${isPreviewOpen ? '45%' : '100%'};
                  transition: width 0.35s cubic-bezier(0.4, 0, 0.2, 1);
                }
              }
              @media (max-width: 1023px) {
                .preview-panel {
                  width: 100% !important;
                  height: ${isPreviewOpen ? '45%' : '0%'};
                  transition: height 0.35s cubic-bezier(0.4, 0, 0.2, 1);
                }
                .chat-panel {
                  width: 100% !important;
                  height: ${isPreviewOpen ? '55%' : '100%'};
                  transition: height 0.35s cubic-bezier(0.4, 0, 0.2, 1);
                }
              }
              @keyframes slideInLeft {
                from { transform: translateX(-20px); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
              }
              .preview-content {
                animation: slideInLeft 0.4s cubic-bezier(0.4, 0, 0.2, 1);
              }
              @keyframes slideUp {
                from { transform: translateY(20px); opacity: 0; }
                to { transform: translateY(0); opacity: 1; }
              }
              @keyframes dotPulse {
                0%, 100% { opacity: 0.4; transform: scale(0.8); }
                50% { opacity: 1; transform: scale(1.2); }
              }
              .dot-pulse {
                animation: dotPulse 1.4s ease-in-out infinite;
              }
            `}</style>

            <div
              className="split-layout"
              style={{
                display: "flex",
                flex: 1,
                minHeight: 0,
                flexDirection: "column",
                position: "relative",
                overflow: "hidden",
              }}
            >
            {/* Live Preview Panel - Right Side */}
            <div
              className="preview-panel"
              style={{
                display: isPreviewOpen ? "flex" : "none",
                flexDirection: "column",
                overflow: "hidden",
                background: "var(--color-bg)",
                borderRight: "1px solid var(--color-border)",
              }}
            >
              <div
                style={{
                  padding: "10px 14px",
                  background: "var(--color-surface)",
                  borderBottom: "1px solid var(--color-border)",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexShrink: 0,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text)" }}>Live Preview</span>
                  {state.status === "generating" && (
                    <span
                      style={{
                        fontSize: 10,
                        padding: "2px 8px",
                        borderRadius: 999,
                        background: "rgba(99,102,241,0.15)",
                        color: "var(--color-primary)",
                        fontWeight: 500,
                      }}
                    >
                      Generating...
                    </span>
                  )}
                </div>
                {state.status !== "generating" && (
                  <button
                    onClick={() => {
                      setIsPreviewOpen(false);
                      setShowPreview(false);
                    }}
                    style={{
                      background: "transparent",
                      border: "none",
                      color: "var(--color-text-muted)",
                      cursor: "pointer",
                      padding: 4,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      borderRadius: 4,
                      transition: "all 0.2s",
                    }}
                    title="Close Preview"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M18 6L6 18M6 6l12 12" />
                    </svg>
                  </button>
                )}
              </div>
              <div className="preview-content" style={{ flex: 1, position: "relative", overflow: "hidden" }}>
                <WebContainerPreview
                  files={state.files}
                  sessionId={state.sessionId}
                  generationStatus={state.status}
                  allowHostPreview={state.status === "generating" || (Boolean(state.sessionId) && runtimeProjectId === state.sessionId)}
                />
              </div>
            </div>

            {/* Chat Panel - Left Side */}
            <div className="chat-panel" style={{ display: "flex", flexDirection: "column", overflow: "hidden", position: "relative", flex: 1, minHeight: 0 }}>
              <ChatPanel
                output={state.output}
                status={state.status}
                onGenerate={(prompt) => {
                  generate({ prompt, provider, model, apiKey, projectId: state.sessionId || "" });
                  setIsInitialState(false);
                }}
                onResume={() =>
                  resumeGeneration({
                    prompt: "",
                    provider,
                    model,
                    apiKey,
                    projectId: state.sessionId || "",
                  })
                }
                onStop={stop}
                onReset={() => {
                  reset();
                  setInitialPrompt("");
                  setIsInitialState(true);
                }}
                provider={provider}
                model={model}
                apiKey={apiKey}
                availableProviders={availableProviders}
                onProviderChange={(p, m, k) => {
                  setProvider(p);
                  setModel(m);
                  setApiKey(k);
                }}
                showPreview={showPreview}
                setShowPreview={(v) => {
                  setShowPreview(v);
                  setIsPreviewOpen(v);
                }}
                showLogs={showLogs}
                setShowLogs={setShowLogs}
              />
            </div>

            {/* Narration/Logs Panel */}
            {showLogs && (
              <div
                style={{
                  position: "absolute",
                  bottom: 16,
                  left: 16,
                  right: 16,
                  maxHeight: 280,
                  background: "var(--color-surface)",
                  border: "1px solid var(--color-border)",
                  borderRadius: "var(--radius-lg)",
                  boxShadow: "var(--shadow-lg)",
                  zIndex: 50,
                  display: "flex",
                  flexDirection: "column",
                  overflow: "hidden",
                  animation: "slideUp 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
                }}
              >
                <div
                  style={{
                    padding: "10px 14px",
                    background: "var(--color-surface2)",
                    borderBottom: "1px solid var(--color-border)",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-muted)" }}>Generation Logs</span>
                  <button
                    onClick={() => setShowLogs(false)}
                    style={{
                      background: "transparent",
                      border: "none",
                      color: "var(--color-text-muted)",
                      cursor: "pointer",
                      padding: 4,
                    }}
                  >
                    ✕
                  </button>
                </div>
                <div
                  style={{
                    flex: 1,
                    overflowY: "auto",
                    padding: 14,
                    fontSize: 12,
                    fontFamily: "var(--font-mono)",
                    color: "var(--color-text-muted)",
                  }}
                >
                  {state.output
                    .split("\n")
                    .filter(
                      (l) =>
                        l.trim() &&
                        (l.startsWith("📦") ||
                          l.startsWith("✨") ||
                          l.startsWith("📝") ||
                          l.startsWith("🚀") ||
                          l.startsWith("�") ||
                          l.startsWith("🛠️") ||
                          l.startsWith("✅") ||
                          l.startsWith("❌") ||
                          l.includes("Analyzing") ||
                          l.includes("Generating") ||
                          l.includes("Writing") ||
                          l.includes("Installing") ||
                          l.includes("Starting") ||
                          l.includes("Successfully"))
                    )
                    .map((line, i) => (
                      <div key={i} style={{ marginBottom: 4, display: "flex", gap: 8 }}>
                        <span style={{ color: "var(--color-text-muted2)" }}>[{i + 1}]</span>
                        <span>{line}</span>
                      </div>
                    ))}
                </div>
              </div>
            )}
            </div>
          </>
        )}
      </div>

      {/* Settings Modal */}
      {showSettings && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 100,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 24,
          }}
        >
          <div
            onClick={() => setShowSettings(false)}
            style={{
              position: "absolute",
              inset: 0,
              background: "var(--color-bg-overlay)",
              backdropFilter: "blur(4px)",
            }}
          />
          <div
            style={{
              width: "100%",
              maxWidth: 600,
              maxHeight: "90vh",
              background: "var(--color-surface)",
              borderRadius: "var(--radius-xl)",
              border: "1px solid var(--color-border)",
              boxShadow: "var(--shadow-xl)",
              position: "relative",
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                padding: "20px 24px",
                borderBottom: "1px solid var(--color-border)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <h2 style={{ fontSize: 18, fontWeight: 700 }}>Settings</h2>
              <button onClick={() => setShowSettings(false)} className="btn btn-ghost" style={{ padding: 8 }}>
                ✕
              </button>
            </div>
            <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
              <SettingsPage />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
