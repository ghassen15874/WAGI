import { useState, useEffect, useRef, useMemo } from "react";
import axios from "axios";
import { useAgent } from "../hooks/useAgent";
import ChatPanel from "../components/ChatPanel";
import WebContainerPreview from "../components/WebContainerPreview";
import LivePreviewWorkbench from "../components/LivePreviewWorkbench";
import SettingsPage from "./SettingsPage";
import { Settings, Plus, MessageSquare, LogOut, LayoutDashboard, Trash2, Download, Sun, Moon, Play, Pencil } from "lucide-react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../hooks/useTheme";

type Tab = "preview" | "files";
type PreviewPaneView = "preview" | "code" | "manual";
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
  const [previewPaneView, setPreviewPaneView] = useState<PreviewPaneView>("preview");
  const [availableProviders, setAvailableProviders] = useState<Array<{ id: string; name: string; models: string[] }>>([]);
  const [runningProjectId, setRunningProjectId] = useState<string | null>(null);
  const [runtimeProjectId, setRuntimeProjectId] = useState<string | null>(null);
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);
  const [initialPrompt, setInitialPrompt] = useState("");
  const [isInitialState, setIsInitialState] = useState(true);
  const [projectSearchTerm, setProjectSearchTerm] = useState("");
  const [isProjectSelectionMode, setIsProjectSelectionMode] = useState(false);
  const [selectedProjectIds, setSelectedProjectIds] = useState<string[]>([]);
  const [renamingProjectId, setRenamingProjectId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [renameError, setRenameError] = useState("");
  const [renameSavingProjectId, setRenameSavingProjectId] = useState<string | null>(null);
  const [deleteTargetIds, setDeleteTargetIds] = useState<string[]>([]);
  const [deleteError, setDeleteError] = useState("");
  const [isDeletingProjects, setIsDeletingProjects] = useState(false);
  const [editableFiles, setEditableFiles] = useState<Record<string, string>>({});
  const { theme, toggleTheme } = useTheme();
  const shouldAutoOpenGeneratedSessionRef = useRef(false);
  const skipProjectHydrationRef = useRef(false);

  const fileCount = state.files ? Object.keys(state.files).length : 0;
  const normalizedProjectSearch = projectSearchTerm.trim().toLowerCase();
  const filteredProjects = useMemo(
    () =>
      projects.filter((project) =>
        String(project?.name || "")
          .toLowerCase()
          .includes(normalizedProjectSearch)
      ),
    [projects, normalizedProjectSearch]
  );
  const allVisibleProjectsSelected =
    filteredProjects.length > 0 && filteredProjects.every((project) => selectedProjectIds.includes(project.id));

  useEffect(() => {
    if (state.status === 'generating' || fileCount > 0 || state.sessionId) {
      setIsInitialState(false);
    }
  }, [state.status, fileCount, state.sessionId]);

  useEffect(() => {
    setEditableFiles(state.files || {});
  }, [state.files, state.sessionId]);

  useEffect(() => {
    if (state.status === 'generating') {
      setShowPreview(true);
      setIsPreviewOpen(true);
      setPreviewPaneView("preview");
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
    const projectIdSet = new Set(projects.map((project) => project.id));
    setSelectedProjectIds((prev) => prev.filter((projectId) => projectIdSet.has(projectId)));
    if (renamingProjectId && !projectIdSet.has(renamingProjectId)) {
      setRenamingProjectId(null);
      setRenameDraft("");
      setRenameError("");
    }
  }, [projects, renamingProjectId]);

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

  const openDeleteDialog = (projectIds: string[]) => {
    const dedupedIds = Array.from(new Set(projectIds.filter(Boolean)));
    if (!dedupedIds.length) return;
    setDeleteError("");
    setDeleteTargetIds(dedupedIds);
  };

  const closeDeleteDialog = () => {
    if (isDeletingProjects) return;
    setDeleteTargetIds([]);
    setDeleteError("");
  };

  const handleDeleteProject = (projId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    openDeleteDialog([projId]);
  };

  const confirmDeleteProjects = async () => {
    if (!token || deleteTargetIds.length === 0) return;
    setIsDeletingProjects(true);
    setDeleteError("");
    const idsToDelete = [...deleteTargetIds];

    try {
      const results = await Promise.allSettled(
        idsToDelete.map((projId) =>
          axios.delete(`/api/projects/${projId}`, { headers: { Authorization: `Bearer ${token}` } })
        )
      );

      const deletedIds = idsToDelete.filter((_, index) => results[index].status === "fulfilled");
      const failedIds = idsToDelete.filter((_, index) => results[index].status === "rejected");

      if (deletedIds.length > 0) {
        const deletedSet = new Set(deletedIds);
        setProjects((prev) => prev.filter((project) => !deletedSet.has(project.id)));
        const remainingSelected = selectedProjectIds.filter((projectId) => !deletedSet.has(projectId));
        setSelectedProjectIds(remainingSelected);
        if (!remainingSelected.length) {
          setIsProjectSelectionMode(false);
        }

        if (deletedIds.some((projId) => state.sessionId === projId || id === projId)) {
          reset();
          navigate("/app");
        }
      }

      if (failedIds.length > 0) {
        setDeleteTargetIds(failedIds);
        setDeleteError(
          deletedIds.length > 0
            ? `Deleted ${deletedIds.length} project(s). Failed to delete ${failedIds.length} project(s).`
            : "Failed to delete selected project(s)."
        );
      } else {
        setDeleteTargetIds([]);
      }
    } catch (error) {
      console.error("Failed to delete project(s)", error);
      setDeleteError("Failed to delete selected project(s).");
    } finally {
      setIsDeletingProjects(false);
    }
  };

  const toggleProjectSelection = (projId: string) => {
    setSelectedProjectIds((prev) =>
      prev.includes(projId) ? prev.filter((id) => id !== projId) : [...prev, projId]
    );
  };

  const handleProjectRowClick = (projId: string) => {
    if (isProjectSelectionMode) {
      toggleProjectSelection(projId);
      return;
    }
    if (renamingProjectId) {
      return;
    }
    navigate(`/app/${projId}`);
  };

  const toggleProjectSelectionMode = () => {
    setIsProjectSelectionMode((prev) => {
      const next = !prev;
      if (!next) {
        setSelectedProjectIds([]);
      }
      return next;
    });
    setRenamingProjectId(null);
    setRenameDraft("");
    setRenameError("");
  };

  const startRenameProject = (projectId: string, currentName: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setIsProjectSelectionMode(false);
    setSelectedProjectIds([]);
    setRenamingProjectId(projectId);
    setRenameDraft(currentName || "");
    setRenameError("");
  };

  const cancelRenameProject = (e?: React.MouseEvent) => {
    if (e) {
      e.stopPropagation();
    }
    setRenamingProjectId(null);
    setRenameDraft("");
    setRenameError("");
    setRenameSavingProjectId(null);
  };

  const submitRenameProject = async (projectId: string) => {
    if (!token || renameSavingProjectId === projectId) return;
    const nextName = renameDraft.trim();
    if (!nextName) {
      setRenameError("Project name cannot be empty.");
      return;
    }
    if (nextName.length > 255) {
      setRenameError("Project name must be 255 characters or fewer.");
      return;
    }

    setRenameSavingProjectId(projectId);
    setRenameError("");
    try {
      await axios.patch(
        `/api/projects/${projectId}`,
        { name: nextName },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setProjects((prev) =>
        prev.map((project) => (project.id === projectId ? { ...project, name: nextName } : project))
      );
      setRenamingProjectId(null);
      setRenameDraft("");
    } catch (error: any) {
      console.error("Failed to rename project", error);
      setRenameError(error?.response?.data?.detail || "Failed to rename project.");
    } finally {
      setRenameSavingProjectId(null);
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
      setPreviewPaneView("preview");
    } catch (err: any) {
      console.error("Failed to run project runtime", err);
      alert(err?.response?.data?.detail || "Failed to run this project");
    } finally {
      setRunningProjectId(null);
    }
  };

  const handleChangeGeneratedFile = (path: string, content: string) => {
    setEditableFiles((prev) => ({ ...prev, [path]: content }));
  };

  const handleSaveGeneratedFile = async (path: string, content: string): Promise<boolean> => {
    const targetProjectId = state.sessionId || id;
    if (!token || !targetProjectId) {
      return false;
    }
    try {
      await axios.patch(
        `/api/projects/${targetProjectId}/files`,
        { path, content },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      return true;
    } catch (error) {
      console.error("Failed to save generated file", error);
      return false;
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
    // Keep /app (no selected project) on the initial new-chat screen unless
    // we are actively generating and planning to auto-route to a new session.
    if (!id && !shouldAutoOpenGeneratedSessionRef.current) {
      setIsInitialState(true);
      if (state.status !== "generating") {
        setShowPreview(false);
        setIsPreviewOpen(false);
      }
    }
  }, [id, state.status]);

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
    setPreviewPaneView("preview");
    setShowLogs(false);
    setRuntimeProjectId(null);
    setIsProjectSelectionMode(false);
    setSelectedProjectIds([]);
    setRenamingProjectId(null);
    setRenameDraft("");
    setRenameError("");
    setDeleteTargetIds([]);
    setDeleteError("");
    navigate("/app");
  };

  const showInitialWorkspace = !id && isInitialState;
  const initialProviderOptions =
    availableProviders.length
      ? availableProviders
      : [{ id: provider, name: provider, models: model ? [model] : [] }];
  const initialSelectedProvider =
    initialProviderOptions.find((p) => p.id === provider) || initialProviderOptions[0];
  const deleteTargetProjects = projects.filter((project) => deleteTargetIds.includes(project.id));

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
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, padding: "0 4px" }}>
            <div
              style={{
                fontSize: 11,
                color: "var(--color-text-muted2)",
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
              }}
            >
              Your Projects
            </div>
            <button
              onClick={toggleProjectSelectionMode}
              className="btn btn-ghost"
              style={{ padding: "4px 8px", fontSize: 11 }}
            >
              {isProjectSelectionMode ? "Done" : "Select"}
            </button>
          </div>

          <input
            value={projectSearchTerm}
            onChange={(e) => setProjectSearchTerm(e.target.value)}
            placeholder="Search projects..."
            style={{
              width: "100%",
              marginBottom: 8,
              padding: "8px 10px",
              borderRadius: "var(--radius-md)",
              border: "1px solid var(--color-border)",
              background: "var(--color-surface2)",
              color: "var(--color-text)",
              fontSize: 12,
              outline: "none",
            }}
          />

          {isProjectSelectionMode && (
            <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
              <button
                onClick={() => setSelectedProjectIds(filteredProjects.map((project) => project.id))}
                className="btn btn-ghost"
                style={{ padding: "5px 8px", fontSize: 11 }}
                disabled={filteredProjects.length === 0 || allVisibleProjectsSelected}
              >
                Select All
              </button>
              <button
                onClick={() => setSelectedProjectIds([])}
                className="btn btn-ghost"
                style={{ padding: "5px 8px", fontSize: 11 }}
                disabled={selectedProjectIds.length === 0}
              >
                Clear
              </button>
              <button
                onClick={() => openDeleteDialog(selectedProjectIds)}
                className="btn btn-ghost"
                style={{ padding: "5px 8px", fontSize: 11, color: "var(--color-error)" }}
                disabled={selectedProjectIds.length === 0}
              >
                Delete ({selectedProjectIds.length})
              </button>
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {filteredProjects.length === 0 && (
              <div style={{ padding: "10px 12px", fontSize: 12, color: "var(--color-text-muted)", textAlign: "center" }}>
                No projects found.
              </div>
            )}

            {filteredProjects.map((p) => {
              const isActiveProject = state.sessionId === p.id || id === p.id;
              const isSelectedProject = selectedProjectIds.includes(p.id);
              const isRenaming = renamingProjectId === p.id;

              return (
                <div
                  key={p.id}
                  onClick={() => handleProjectRowClick(p.id)}
                  style={{
                    padding: "10px 12px",
                    borderRadius: "var(--radius-md)",
                    background: isSelectedProject || isActiveProject ? "var(--color-surface2)" : "transparent",
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    fontSize: 13,
                    cursor: "pointer",
                    color: "var(--color-text)",
                    transition: "all var(--transition)",
                    border: isSelectedProject ? "1px solid var(--color-primary)" : "1px solid transparent",
                  }}
                >
                  {isProjectSelectionMode && (
                    <input
                      type="checkbox"
                      checked={isSelectedProject}
                      onChange={() => toggleProjectSelection(p.id)}
                      onClick={(e) => e.stopPropagation()}
                      style={{
                        accentColor: "var(--color-primary)",
                        width: 14,
                        height: 14,
                        cursor: "pointer",
                      }}
                    />
                  )}

                  {isRenaming ? (
                    <div
                      style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <input
                        value={renameDraft}
                        autoFocus
                        onChange={(e) => setRenameDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            submitRenameProject(p.id);
                          }
                          if (e.key === "Escape") {
                            e.preventDefault();
                            cancelRenameProject();
                          }
                        }}
                        style={{
                          width: "100%",
                          padding: "6px 8px",
                          borderRadius: "var(--radius-sm)",
                          border: "1px solid var(--color-border-hover)",
                          background: "var(--color-surface)",
                          color: "var(--color-text)",
                          fontSize: 12,
                          outline: "none",
                        }}
                      />
                      {renameError && (
                        <span style={{ color: "var(--color-error)", fontSize: 11 }}>
                          {renameError}
                        </span>
                      )}
                    </div>
                  ) : (
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
                  )}

                  {!isProjectSelectionMode && isRenaming && (
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          submitRenameProject(p.id);
                        }}
                        className="btn btn-ghost"
                        style={{ padding: "4px 6px", fontSize: 11 }}
                        disabled={renameSavingProjectId === p.id}
                      >
                        {renameSavingProjectId === p.id ? "Saving..." : "Save"}
                      </button>
                      <button
                        onClick={(e) => cancelRenameProject(e)}
                        className="btn btn-ghost"
                        style={{ padding: "4px 6px", fontSize: 11 }}
                        disabled={renameSavingProjectId === p.id}
                      >
                        Cancel
                      </button>
                    </div>
                  )}

                  {!isProjectSelectionMode && !isRenaming && isActiveProject && (
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
                        onClick={(e) => startRenameProject(p.id, p.name, e)}
                        style={{
                          background: "transparent",
                          border: "none",
                          cursor: "pointer",
                          padding: 4,
                          display: "flex",
                          color: "var(--color-text-muted)",
                          borderRadius: 4,
                        }}
                        title="Rename Project"
                      >
                        <Pencil size={14} />
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
              );
            })}
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
            <Settings size={16} /> Settings
          </Link>
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
        {showInitialWorkspace ? (
          /* Centered Initial State */
          <div
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              background: "var(--color-bg)",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                padding: "12px 16px",
                display: "flex",
                alignItems: "center",
                gap: 12,
                borderBottom: "1px solid var(--color-border)",
                background: "var(--color-surface)",
              }}
            >
              <div style={{ fontWeight: 600, fontSize: 18, color: "var(--color-text-muted)", display: "flex", alignItems: "center" }}>
                WAGI <span style={{ fontSize: 13, color: "var(--color-text-muted)", opacity: 0.5, marginLeft: 4 }}>platform</span>
              </div>
              <div style={{ display: "flex", gap: 6, flex: 1, justifyContent: "flex-end", opacity: 0.6 }}>
                <button
                  onClick={() => setShowPreview((v) => !v)}
                  className="btn btn-ghost"
                  style={{ padding: "4px 10px", fontSize: 11, borderRadius: 12 }}
                  title="Toggle Preview"
                >
                  Preview
                </button>
                <button
                  onClick={() => setShowLogs((v) => !v)}
                  className="btn btn-ghost"
                  style={{ padding: "4px 10px", fontSize: 11, borderRadius: 12 }}
                  title="Toggle Logs"
                >
                  Logs
                </button>
                <button
                  onClick={toggleTheme}
                  className="btn btn-ghost"
                  style={{ padding: "4px 8px", fontSize: 11, borderRadius: 12 }}
                  title="Toggle Theme"
                >
                  {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
                </button>
                <select
                  value={provider}
                  onChange={(e) => {
                    const selected = initialProviderOptions.find((p) => p.id === e.target.value) || initialProviderOptions[0];
                    setProvider(selected.id);
                    setModel(selected.models?.[0] || "");
                  }}
                  style={{
                    padding: "6px 10px",
                    background: "transparent",
                    border: "none",
                    color: "var(--color-text-muted)",
                    fontSize: 12,
                    outline: "none",
                    cursor: "pointer",
                    maxWidth: 140,
                  }}
                >
                  {initialProviderOptions.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
                <select
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  style={{
                    padding: "6px 10px",
                    background: "transparent",
                    border: "none",
                    color: "var(--color-text-muted)",
                    fontSize: 12,
                    outline: "none",
                    cursor: "pointer",
                    maxWidth: 170,
                  }}
                  disabled={!initialSelectedProvider || initialSelectedProvider.models.length === 0}
                >
                  {(initialSelectedProvider?.models || []).map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>
            </div>

            <div
              style={{
                flex: 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                padding: "24px",
                position: "relative",
                overflow: "auto",
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
                    gap: 8,
                    flexShrink: 0,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <button
                      onClick={() => setPreviewPaneView("preview")}
                      className="btn"
                      style={{
                        padding: "6px 12px",
                        fontSize: 12,
                        fontWeight: 600,
                        background: previewPaneView === "preview" ? "var(--color-primary)" : "var(--color-surface2)",
                        color: previewPaneView === "preview" ? "white" : "var(--color-text)",
                        border: "1px solid var(--color-border)",
                      }}
                    >
                      Live Preview
                    </button>
                    <button
                      onClick={() => setPreviewPaneView("code")}
                      className="btn"
                      style={{
                        padding: "6px 12px",
                        fontSize: 12,
                        fontWeight: 600,
                        background: previewPaneView === "code" ? "var(--color-primary)" : "var(--color-surface2)",
                        color: previewPaneView === "code" ? "white" : "var(--color-text)",
                        border: "1px solid var(--color-border)",
                      }}
                    >
                      Code
                    </button>
                    <button
                      onClick={() => setPreviewPaneView("manual")}
                      className="btn"
                      style={{
                        padding: "6px 12px",
                        fontSize: 12,
                        fontWeight: 600,
                        background: previewPaneView === "manual" ? "var(--color-primary)" : "var(--color-surface2)",
                        color: previewPaneView === "manual" ? "white" : "var(--color-text)",
                        border: "1px solid var(--color-border)",
                      }}
                    >
                      Manual Edit
                    </button>
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
                <div
                  className="preview-content"
                  style={{
                    flex: 1,
                    position: "relative",
                    overflow: "hidden",
                    display: "flex",
                    flexDirection: "column",
                    minHeight: 0,
                  }}
                >
                  {previewPaneView === "preview" ? (
                    <WebContainerPreview
                      files={editableFiles}
                      sessionId={state.sessionId}
                      generationStatus={state.status}
                      allowHostPreview={state.status === "generating" || (Boolean(state.sessionId) && runtimeProjectId === state.sessionId)}
                    />
                  ) : (
                    <LivePreviewWorkbench
                      files={editableFiles}
                      output={state.output}
                      mode={previewPaneView === "code" ? "code" : "manual"}
                      generationStatus={state.status}
                      onChangeFile={handleChangeGeneratedFile}
                      onSaveFile={handleSaveGeneratedFile}
                    />
                  )}
                </div>
              </div>

              {/* Chat Panel - Left Side */}
              <div className="chat-panel" style={{ display: "flex", flexDirection: "column", overflow: "hidden", position: "relative", flex: 1, minHeight: 0 }}>
                <ChatPanel
                  output={state.output}
                  status={state.status}
                  compactLogs={true}
                  onGenerate={(prompt) => {
                    generate({
                      prompt,
                      provider,
                      model,
                      apiKey,
                      projectId: state.sessionId || id || "",
                      resume: Boolean(state.sessionId || id)
                    });
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
                    if (v) {
                      setPreviewPaneView("preview");
                    }
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

      {/* Delete Projects Confirmation Modal */}
      {deleteTargetIds.length > 0 && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 110,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 24,
          }}
        >
          <div
            onClick={closeDeleteDialog}
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
              maxWidth: 520,
              background: "var(--color-surface)",
              borderRadius: "var(--radius-xl)",
              border: "1px solid var(--color-border)",
              boxShadow: "var(--shadow-xl)",
              position: "relative",
              padding: 22,
              display: "flex",
              flexDirection: "column",
              gap: 14,
            }}
          >
            <h3 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "var(--color-text)" }}>
              Delete {deleteTargetIds.length > 1 ? "projects" : "project"}?
            </h3>
            <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5, color: "var(--color-text-muted)" }}>
              This action cannot be undone. You are about to permanently remove{" "}
              <strong>{deleteTargetIds.length}</strong> {deleteTargetIds.length > 1 ? "projects" : "project"}.
            </p>

            {deleteTargetProjects.length > 0 && (
              <div
                style={{
                  border: "1px solid var(--color-border)",
                  borderRadius: "var(--radius-md)",
                  background: "var(--color-surface2)",
                  maxHeight: 140,
                  overflowY: "auto",
                  padding: "8px 10px",
                }}
              >
                {deleteTargetProjects.slice(0, 5).map((project) => (
                  <div key={project.id} style={{ fontSize: 12, color: "var(--color-text)", padding: "3px 0" }}>
                    {project.name || "Untitled Project"}
                  </div>
                ))}
                {deleteTargetProjects.length > 5 && (
                  <div style={{ fontSize: 12, color: "var(--color-text-muted)", paddingTop: 4 }}>
                    +{deleteTargetProjects.length - 5} more
                  </div>
                )}
              </div>
            )}

            {deleteError && (
              <div
                role="alert"
                style={{
                  fontSize: 12,
                  color: "var(--color-error)",
                  background: "rgba(239, 68, 68, 0.12)",
                  border: "1px solid rgba(239, 68, 68, 0.28)",
                  borderRadius: "var(--radius-md)",
                  padding: "8px 10px",
                }}
              >
                {deleteError}
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <button
                onClick={closeDeleteDialog}
                className="btn btn-ghost"
                style={{ padding: "8px 14px" }}
                disabled={isDeletingProjects}
              >
                Cancel
              </button>
              <button
                onClick={confirmDeleteProjects}
                className="btn btn-ghost"
                style={{ padding: "8px 14px", color: "var(--color-error)" }}
                disabled={isDeletingProjects}
              >
                {isDeletingProjects ? "Deleting..." : `Delete ${deleteTargetIds.length > 1 ? "Projects" : "Project"}`}
              </button>
            </div>
          </div>
        </div>
      )}

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
