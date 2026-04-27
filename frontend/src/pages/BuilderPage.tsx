import { useState, useEffect, useRef, useMemo } from "react";
import axios from "axios";
import { useAgent } from "../hooks/useAgent";
import ChatPanel from "../components/ChatPanel";
import WebContainerPreview from "../components/WebContainerPreview";
import LivePreviewWorkbench from "../components/LivePreviewWorkbench";
import AppLayout from "../components/AppLayout";
import { Settings, Plus, MessageSquare, LogOut, LayoutDashboard, Trash2, Download, Sun, Moon, Play, Pencil, Github, Loader2, X, PanelLeft, Search, Square, RotateCcw, Check } from "lucide-react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../hooks/useTheme";

type Tab = "preview" | "files";
type PreviewPaneView = "preview" | "code" | "manual";
const BUILDER_PREFS_KEY = "builder_page_preferences";
const BUILDER_PLAN_PREFS_KEY = "builder_page_plan";

type BillingPlanOption = {
  id: string;
  name: string;
  provider: string;
  model: string;
  canUse: boolean;
  isCurrent: boolean;
};

export default function BuilderPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { state, generate, stop, reset, loadProject, reconnect, resumeGeneration } = useAgent();
  const { token, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();

  const [isSidebarVisible, setIsSidebarVisible] = useState(true);
  const searchInputRef = useRef<HTMLInputElement>(null);
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
  const [planOptions, setPlanOptions] = useState<BillingPlanOption[]>([]);
  const [selectedPlanId, setSelectedPlanId] = useState(() => {
    try {
      return localStorage.getItem(BUILDER_PLAN_PREFS_KEY) || "";
    } catch {
      return "";
    }
  });
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
  const [githubDeploying, setGithubDeploying] = useState(false);
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
    const fetchBuilderContext = async () => {
      try {
        const providersReq = axios.get("/api/providers");
        const billingReq = token
          ? axios.get("/api/billing/me", { headers: { Authorization: `Bearer ${token}` } })
          : Promise.resolve(null);

        const [providersRes, billingRes]: any[] = await Promise.all([providersReq, billingReq]);
        const providers = Array.isArray(providersRes?.data?.providers)
          ? providersRes.data.providers.filter((item: any) => item.id !== "auto")
          : [];
        setAvailableProviders(providers);

        const rawPlans = Array.isArray(billingRes?.data?.plans) ? billingRes.data.plans : [];
        const plans: BillingPlanOption[] = rawPlans.map((plan: any) => ({
          id: plan.id,
          name: plan.name,
          provider: plan.provider,
          model: plan.model,
          canUse: Boolean(plan.canUse),
          isCurrent: Boolean(plan.isCurrent),
        }));
        setPlanOptions(plans);

        if (plans.length) {
          const currentPlanId = String(billingRes?.data?.currentPlan?.id || "");
          setSelectedPlanId((prev) => {
            if (prev && plans.some((plan) => plan.id === prev && plan.canUse)) {
              return prev;
            }
            if (currentPlanId && plans.some((plan) => plan.id === currentPlanId)) {
              return currentPlanId;
            }
            const firstAllowed = plans.find((plan) => plan.canUse) || plans[0];
            return firstAllowed?.id || prev;
          });
        }
      } catch (error) {
        console.error(error);
      }
    };

    fetchBuilderContext();
    window.addEventListener("focus", fetchBuilderContext);
    return () => window.removeEventListener("focus", fetchBuilderContext);
  }, [token]);

  useEffect(() => {
    if (selectedPlanId !== "byok") {
      return;
    }
    if (!availableProviders.length) {
      return;
    }
    const selectedProvider = availableProviders.find((item) => item.id === provider);
    if (!selectedProvider) {
      const fallbackProvider = availableProviders[0];
      setProvider(fallbackProvider.id);
      if (!model.trim()) {
        setModel(fallbackProvider.models?.[0] || "");
      }
      return;
    }
    if (!model.trim()) {
      setModel(selectedProvider.models?.[0] || "");
    }
  }, [selectedPlanId, availableProviders, provider, model]);

  useEffect(() => {
    if (!planOptions.length || selectedPlanId === "byok") {
      return;
    }

    const selectedPlan =
      planOptions.find((plan) => plan.id === selectedPlanId && plan.canUse)
      || planOptions.find((plan) => plan.isCurrent)
      || planOptions.find((plan) => plan.canUse);

    if (selectedPlan) {
      setProvider(selectedPlan.provider);
      setModel(selectedPlan.model);
      return;
    }

    if (!availableProviders.length) {
      return;
    }

    const selectedProvider = availableProviders.find((item) => item.id === provider);
    if (!selectedProvider) {
      setProvider(availableProviders[0].id);
      setModel(availableProviders[0].models?.[0] || "");
      return;
    }
    if (!selectedProvider.models?.includes(model)) {
      setModel(selectedProvider.models?.[0] || "");
    }
  }, [selectedPlanId, planOptions, availableProviders, provider, model]);

  useEffect(() => {
    localStorage.setItem(BUILDER_PREFS_KEY, JSON.stringify({ provider, model }));
  }, [provider, model]);

  useEffect(() => {
    if (!selectedPlanId) {
      return;
    }
    localStorage.setItem(BUILDER_PLAN_PREFS_KEY, selectedPlanId);
  }, [selectedPlanId]);

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

  const handleGithubDeploy = async () => {
    setGithubDeploying(true);
    const targetProjectId = state.sessionId || id;
    if (!targetProjectId) {
      alert("No project selected.");
      setGithubDeploying(false);
      return;
    }
    try {
      const frontendOrigin = typeof window !== "undefined" ? window.location.origin : "";
      const backendPublicUrl = (import.meta.env.VITE_BACKEND_PUBLIC_URL as string | undefined)?.trim() || "http://localhost:8080";
      const githubAuthUrl = `${backendPublicUrl.replace(/\/+$/, "")}/auth/github?frontend=${encodeURIComponent(frontendOrigin)}`;

      const res = await axios.post(
        "/api/github/prepare",
        { frontendUrl: frontendOrigin, projectId: targetProjectId },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      window.location.href = res.data.redirect_url || githubAuthUrl;
    } catch (err: any) {
      alert(err?.response?.data?.detail || "Failed to start GitHub deployment");
      setGithubDeploying(false);
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
  const deleteTargetProjects = projects.filter((project) => deleteTargetIds.includes(project.id));
  const selectedPlan =
    planOptions.find((plan) => plan.id === selectedPlanId)
    || planOptions.find((plan) => plan.isCurrent)
    || planOptions[0];

  const sidebarContent = (
    <>
      <div style={{ padding: "16px", display: "flex", flexDirection: "column", gap: 16, width: "100%" }}>
        <div style={{ display: "flex", justifyContent: "center", alignItems: "center" }}>
          {isSidebarVisible ? (
            <button
              onClick={handleNewProject}
              className="btn btn-primary"
              style={{ padding: "10px 16px", fontSize: 13, flex: 1, display: "flex", alignItems: "center", gap: 8, justifyContent: "center" }}
            >
              <Plus size={16} /> New Project
            </button>
          ) : (
            <button
              onClick={handleNewProject}
              style={{
                background: "var(--color-accent)",
                border: "none",
                color: "white",
                cursor: "pointer",
                width: 36,
                height: 36,
                borderRadius: "50%",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                boxShadow: "var(--shadow-md)",
                transition: "all var(--transition)",
                flexShrink: 0,
              }}
              onMouseEnter={(e) => e.currentTarget.style.transform = "scale(1.05)"}
              onMouseLeave={(e) => e.currentTarget.style.transform = "scale(1)"}
              title="New Project"
            >
              <Plus size={20} />
            </button>
          )}
        </div>
      </div>

      <div style={{ flex: 1, overflowY: "auto", overflowX: "clip", padding: isSidebarVisible ? "12px" : "12px 0", width: "100%", display: "flex", flexDirection: "column", alignItems: "center" }}>
        {isSidebarVisible ? (
          <>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, padding: "0 4px", width: "100%" }}>
              <div
                style={{
                  fontSize: 11,
                  color: "var(--color-sidebar-muted)",
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
              ref={searchInputRef}
              value={projectSearchTerm}
              onChange={(e) => setProjectSearchTerm(e.target.value)}
              placeholder="Search projects..."
              style={{
                width: "100%",
                marginBottom: 8,
                padding: "8px 10px",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--color-sidebar-input-border)",
                background: "var(--color-sidebar-input-bg)",
                color: "var(--color-sidebar-text)",
                fontSize: 12,
                outline: "none",
              }}
            />
          </>
        ) : (
          <div
            onClick={() => {
              setIsSidebarVisible(true);
              setTimeout(() => searchInputRef.current?.focus(), 100);
            }}
            style={{ marginBottom: 12, color: "var(--color-sidebar-muted)", padding: 4, cursor: "pointer" }}
            title="Search projects (Expand)"
          >
            <Search size={18} />
          </div>
        )}

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

        <div style={{ display: "flex", flexDirection: "column", gap: 4, width: "100%" }}>
          {filteredProjects.length === 0 && (
            <div style={{ padding: "10px 12px", fontSize: 12, color: "var(--color-text-muted)", textAlign: "center" }}>
              No projects found.
            </div>
          )}

          {filteredProjects.map((p) => (
            <div
              key={p.id}
              onClick={() => handleProjectRowClick(p.id)}
              style={{
                padding: isSidebarVisible ? "10px 12px" : "10px",
                borderRadius: isSidebarVisible ? "var(--radius-md)" : "var(--radius-full)",
                background: selectedProjectIds.includes(p.id) || state.sessionId === p.id || id === p.id ? "var(--color-sidebar-item-active)" : "transparent",
                display: "flex",
                alignItems: "center",
                justifyContent: isSidebarVisible ? "flex-start" : "center",
                gap: 8,
                fontSize: 13,
                cursor: "pointer",
                color: "var(--color-sidebar-text)",
                transition: "all var(--transition)",
                border: selectedProjectIds.includes(p.id) ? "1px solid var(--color-primary)" : "1px solid transparent",
                width: isSidebarVisible ? "100%" : "auto",
              }}
              title={!isSidebarVisible ? p.name : ""}
            >
              {isSidebarVisible ? (
                <>
                  {isProjectSelectionMode && (
                    <input
                      type="checkbox"
                      checked={selectedProjectIds.includes(p.id)}
                      onChange={() => toggleProjectSelection(p.id)}
                      onClick={(e) => e.stopPropagation()}
                      style={{ accentColor: "var(--color-primary)", width: 14, height: 14, cursor: "pointer" }}
                    />
                  )}
                  {renamingProjectId === p.id ? (
                    <input
                      value={renameDraft} autoFocus
                      onChange={(e) => setRenameDraft(e.target.value)}
                      onKeyDown={(e) => { e.key === "Enter" && submitRenameProject(p.id); e.key === "Escape" && cancelRenameProject(); }}
                      style={{ width: "100%", padding: "6px 8px", borderRadius: "var(--radius-sm)", border: "1px solid var(--color-border-hover)", background: "var(--color-surface)", color: "var(--color-text)", fontSize: 12, outline: "none" }}
                    />
                  ) : (
                    <span style={{ flex: "1 1 0%", minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontWeight: 500 }}>{p.name}</span>
                  )}
                  {!isProjectSelectionMode && renamingProjectId !== p.id && (state.sessionId === p.id || id === p.id) && (
                    <div style={{ display: "flex", alignItems: "center", gap: 2, flexShrink: 0 }}>
                      <button onClick={(e) => handleRunProject(p.id, e)} style={{ background: "transparent", border: "none", cursor: "pointer", padding: 4, display: "flex", color: runningProjectId === p.id ? "var(--color-primary)" : "var(--color-text-muted)" }}><Play size={14} /></button>
                      <button onClick={(e) => handleExportProject(p.id, e)} style={{ background: "transparent", border: "none", cursor: "pointer", padding: 4, display: "flex", color: "var(--color-text-muted)" }}><Download size={14} /></button>
                      <button onClick={(e) => startRenameProject(p.id, p.name, e)} style={{ background: "transparent", border: "none", cursor: "pointer", padding: 4, display: "flex", color: "var(--color-text-muted)" }}><Pencil size={14} /></button>
                      <button onClick={(e) => handleDeleteProject(p.id, e)} style={{ background: "transparent", border: "none", cursor: "pointer", padding: 4, display: "flex", color: "var(--color-error)" }}><Trash2 size={14} /></button>
                    </div>
                  )}
                </>
              ) : (
                <div style={{ width: 18, height: 18, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, fontWeight: 700, fontSize: 14, color: (state.sessionId === p.id || id === p.id) ? "var(--color-accent)" : "var(--color-text-muted)", textTransform: "uppercase" }}>
                  {p.name.charAt(0)}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </>
  );

  const navbarRightContent = (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <div style={{ display: "flex", gap: 6, opacity: 0.8 }}>
        <button
          onClick={() => {
            const next = !showPreview;
            setShowPreview(next);
            setIsPreviewOpen(next);
            if (next) setPreviewPaneView("preview");
          }}
          className="btn btn-ghost"
          style={{
            padding: "6px 12px",
            fontSize: 11,
            borderRadius: 12,
            color: showPreview ? "var(--color-primary)" : "var(--color-text-muted)",
            background: showPreview ? "var(--color-surface2)" : "transparent"
          }}
        >
          Preview
        </button>
        <button
          onClick={() => setShowLogs(!showLogs)}
          className="btn btn-ghost"
          style={{
            padding: "6px 12px",
            fontSize: 11,
            borderRadius: 12,
            color: showLogs ? "var(--color-primary)" : "var(--color-text-muted)",
            background: showLogs ? "var(--color-surface2)" : "transparent"
          }}
        >
          Logs
        </button>
      </div>

      {planOptions.length > 0 ? (
        <div style={{ display: "flex", alignItems: "center", gap: 6, background: "var(--color-surface2)", padding: "2px 8px", borderRadius: 12, border: "1px solid var(--color-border)" }}>
          <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--color-text-muted)" }}>Model Plan</span>
          <select
            value={selectedPlanId || selectedPlan?.id || ""}
            onChange={(e) => setSelectedPlanId(e.target.value)}
            style={{ padding: "6px 4px", background: "transparent", border: "none", color: "var(--color-text)", fontSize: 11, fontWeight: 600, outline: "none", cursor: "pointer", minWidth: 120 }}
          >
            {planOptions.map((plan) => (
              <option key={plan.id} value={plan.id} disabled={!plan.canUse}>
                {plan.name}{plan.canUse ? "" : " (Upgrade)"}
              </option>
            ))}
            <option value="byok">Bring Your Own Key (BYOK)</option>
          </select>
          {(selectedPlan && selectedPlanId !== "byok") ? (
            <span style={{ fontSize: 10, color: "var(--color-text-muted)" }}>
              {selectedPlan.provider}:{selectedPlan.model}
            </span>
          ) : (
            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <div style={{ width: 1, height: 12, background: "var(--color-border)", margin: "0 4px" }} />
              <select
                value={provider}
                onChange={(e) => {
                  const opt = availableProviders.find((p) => p.id === e.target.value) || availableProviders[0];
                  setProvider(opt.id);
                  setModel(opt.models?.[0] || "");
                }}
                style={{ padding: "6px 4px", background: "transparent", border: "none", color: "var(--color-text)", fontSize: 11, fontWeight: 600, outline: "none", cursor: "pointer", maxWidth: 100 }}
              >
                {availableProviders.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
              <div style={{ width: 1, height: 12, background: "var(--color-border)" }} />
              <input
                value={model}
                onChange={(e) => setModel(e.target.value)}
                list="builder-byok-model-options"
                placeholder="Model ID (e.g. deepseek-chat)"
                style={{
                  padding: "6px 8px",
                  background: "transparent",
                  border: "none",
                  color: "var(--color-text-muted)",
                  fontSize: 11,
                  outline: "none",
                  maxWidth: 180,
                }}
              />
              <datalist id="builder-byok-model-options">
                {(availableProviders.find((p) => p.id === provider)?.models || []).map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </div>
          )}
        </div>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 4, background: "var(--color-surface2)", padding: "2px 8px", borderRadius: 12, border: "1px solid var(--color-border)" }}>
          <select
            value={provider}
            onChange={(e) => {
              const opt = availableProviders.find((p) => p.id === e.target.value) || availableProviders[0];
              setProvider(opt.id);
              setModel(opt.models?.[0] || "");
            }}
            style={{ padding: "6px 4px", background: "transparent", border: "none", color: "var(--color-text)", fontSize: 11, fontWeight: 600, outline: "none", cursor: "pointer", maxWidth: 100 }}
          >
            {availableProviders.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <div style={{ width: 1, height: 12, background: "var(--color-border)" }} />
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            style={{ padding: "6px 4px", background: "transparent", border: "none", color: "var(--color-text-muted)", fontSize: 11, outline: "none", cursor: "pointer", maxWidth: 140 }}
            disabled={!provider || (availableProviders.find((p) => p.id === provider)?.models.length || 0) === 0}
          >
            {(availableProviders.find((p) => p.id === provider)?.models || []).map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
      )}

      {state.status !== 'idle' && (
        <button
          onClick={() => {
            if (state.status === 'generating') {
              stop();
            } else {
              reset();
              setInitialPrompt("");
              setIsInitialState(true);
            }
          }}
          className="btn btn-icon btn-icon-sm"
          style={{ borderRadius: 10, background: "var(--color-surface2)" }}
          title={state.status === 'generating' ? "Stop Generation" : "Reset Session"}
        >
          {state.status === 'generating' ? <Square size={14} fill="currentColor" /> : <RotateCcw size={14} />}
        </button>
      )}
    </div>
  );


  return (
    <AppLayout
      isSidebarVisible={isSidebarVisible}
      setIsSidebarVisible={setIsSidebarVisible}
      sidebarContent={sidebarContent}
      navbarRightContent={navbarRightContent}
    >
      {showInitialWorkspace ? (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: "24px", position: "relative", overflow: "auto" }}>
          <div style={{ width: "100%", maxWidth: 700, display: "flex", flexDirection: "column", gap: 32, animation: "fadeIn 0.5s ease-out" }}>
            <div style={{ textAlign: "center", marginBottom: 8 }}>
              <h1 style={{ fontSize: 36, fontWeight: 700, color: "var(--color-text)", marginBottom: 12, letterSpacing: "-0.02em", lineHeight: 1.2 }}>What would you like to build?</h1>
              <p style={{ fontSize: 16, color: "var(--color-text-muted)", lineHeight: 1.6, maxWidth: 480, margin: "0 auto" }}>Describe your idea in detail and I'll create a fully functional web application for you.</p>
            </div>
            <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: 24, padding: "16px 20px", boxShadow: "var(--shadow-lg)", transition: "all 0.3s ease", borderColor: "var(--color-border-hover)" }}>
              <textarea
                value={initialPrompt} onChange={(e) => setInitialPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                    e.preventDefault();
                    if (initialPrompt.trim()) {
                      shouldAutoOpenGeneratedSessionRef.current = true;
                      generate({ prompt: initialPrompt.trim(), provider, model, apiKey, planId: selectedPlanId, projectId: state.sessionId || "" });
                      setIsInitialState(false);
                    }
                  }
                }}
                placeholder="e.g., Build a modern SaaS dashboard with analytics charts, user management, and dark mode..."
                rows={4} autoFocus
                style={{ width: "100%", background: "transparent", border: "none", color: "var(--color-text)", fontFamily: "var(--font-sans)", fontSize: 15, resize: "none", outline: "none", lineHeight: 1.6, minHeight: 100 }}
              />
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12, gap: 12 }}>
                <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Press Cmd+Enter to generate</span>
                <button
                  onClick={() => {
                    if (initialPrompt.trim()) {
                      shouldAutoOpenGeneratedSessionRef.current = true;
                      generate({ prompt: initialPrompt.trim(), provider, model, apiKey, planId: selectedPlanId, projectId: state.sessionId || "" });
                      setIsInitialState(false);
                    }
                  }}
                  disabled={!initialPrompt.trim()} className="btn btn-primary" style={{ padding: "10px 24px", fontSize: 14, opacity: !initialPrompt.trim() ? 0.5 : 1, cursor: !initialPrompt.trim() ? "not-allowed" : "pointer" }}
                >
                  Generate App
                </button>
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ textAlign: "center" }}><span style={{ fontSize: 12, color: "var(--color-text-muted)", fontWeight: 500 }}>Try an example</span></div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
                {["Build a SaaS dashboard with charts", "Create an e-commerce store", "Build a portfolio website", "Create a blog platform"].map((ex, i) => (
                  <button key={i} onClick={() => setInitialPrompt(ex)} className="btn btn-ghost" style={{ padding: "10px 18px", fontSize: 13, borderRadius: 20, border: "1px solid var(--color-border)", background: "var(--color-surface2)" }}>{ex}</button>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="split-layout" style={{ display: "flex", flex: 1, minHeight: 0, flexDirection: "column", position: "relative", overflow: "hidden" }}>
          <style>{`
            @media (min-width: 1024px) {
              .split-layout { flex-direction: row !important; height: 100%; min-height: 0; }
              .preview-panel { width: ${isPreviewOpen ? '55%' : '0%'}; height: 100%; transition: width 0.35s cubic-bezier(0.4, 0, 0.2, 1); flex-shrink: 0; overflow: hidden; }
              .chat-panel { width: ${isPreviewOpen ? '45%' : '100%'}; height: 100%; transition: width 0.35s cubic-bezier(0.4, 0, 0.2, 1); flex: 1; min-width: 0; }
            }
            @media (max-width: 1023px) {
              .preview-panel { width: 100% !important; height: ${isPreviewOpen ? '45%' : '0%'}; transition: height 0.35s cubic-bezier(0.4, 0, 0.2, 1); }
              .chat-panel { width: 100% !important; height: ${isPreviewOpen ? '55%' : '100%'}; transition: height 0.35s cubic-bezier(0.4, 0, 0.2, 1); }
            }
            @keyframes slideInLeft { from { transform: translateX(-20px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
            .preview-content { animation: slideInLeft 0.4s cubic-bezier(0.4, 0, 0.2, 1); }
          `}</style>
          <div className="preview-panel" style={{ display: isPreviewOpen ? "flex" : "none", flexDirection: "column", overflow: "hidden", background: "var(--color-bg)", borderRight: "1px solid var(--color-border)" }}>
            <div style={{ padding: "8px 16px", borderBottom: "1px solid var(--color-border)", display: "flex", alignItems: "center", justifyContent: "space-between", background: "var(--color-surface)", zIndex: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 4, background: "var(--color-surface2)", padding: "4px", borderRadius: "var(--radius-lg)", border: "1px solid var(--color-border)" }}>
                {[{ id: "preview", label: "Live Preview" }, { id: "code", label: "Code" }, { id: "manual", label: "Manual Edit" }].map((tab) => (
                  <button key={tab.id} onClick={() => setPreviewPaneView(tab.id as any)} style={{ padding: "6px 16px", fontSize: 12, fontWeight: 600, borderRadius: "var(--radius-md)", border: "none", background: previewPaneView === tab.id ? "var(--color-surface)" : "transparent", color: previewPaneView === tab.id ? "var(--color-text)" : "var(--color-text-muted)", boxShadow: previewPaneView === tab.id ? "var(--shadow-sm)" : "none", cursor: "pointer", transition: "all 0.2s cubic-bezier(0.4, 0, 0.2, 1)" }}>{tab.label}</button>
                ))}
                <div style={{ width: 1, height: 16, background: "var(--color-border)", margin: "0 4px" }} />
                <button onClick={handleGithubDeploy} disabled={githubDeploying} className="btn btn-ghost" style={{ padding: "6px 16px", fontSize: 12, display: "flex", alignItems: "center", gap: 8 }}>
                  {githubDeploying ? <Loader2 size={14} className="animate-spin" /> : <Github size={14} />} Deploy to GitHub
                </button>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                {state.status === "generating" && <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><span className="animate-pulse" style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--color-accent)' }} /><span style={{ fontSize: 11, color: "var(--color-text-muted)", fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Generating...</span></div>}
                {state.status !== "generating" && <button onClick={() => { setIsPreviewOpen(false); setShowPreview(false); }} style={{ background: "var(--color-surface2)", border: "1px solid var(--color-border)", color: "var(--color-text-muted)", cursor: "pointer", width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: 8, transition: "all 0.2s" }} title="Close Preview"><X size={14} /></button>}
              </div>
            </div>
            <div className="preview-content" style={{ flex: 1, position: "relative", overflow: "hidden", display: "flex", flexDirection: "column", minHeight: 0 }}>
              {previewPaneView === "preview" ? (
                <WebContainerPreview files={editableFiles} sessionId={state.sessionId} generationStatus={state.status} allowHostPreview={state.status === "generating" || (Boolean(state.sessionId) && runtimeProjectId === state.sessionId)} />
              ) : (
                <LivePreviewWorkbench files={editableFiles} output={state.output} mode={previewPaneView === "code" ? "code" : "manual"} generationStatus={state.status} onChangeFile={handleChangeGeneratedFile} onSaveFile={handleSaveGeneratedFile} />
              )}
            </div>
          </div>
          <div className="chat-panel" style={{ display: "flex", flexDirection: "column", background: "var(--color-bg)", minWidth: 0, flex: 1, height: "100%" }}>
            <ChatPanel
              output={state.output} status={state.status} compactLogs={true}
              onGenerate={(prompt) => {
                const projectId = state.sessionId;
                if (!projectId) {
                  generate({ prompt: prompt.trim(), provider, model, apiKey, planId: selectedPlanId });
                } else {
                  generate({ prompt: prompt.trim(), provider, model, apiKey, planId: selectedPlanId, projectId: projectId });
                }
                setIsInitialState(false);
              }}
              onResume={() => resumeGeneration({ prompt: "", provider, model, apiKey, planId: selectedPlanId, projectId: state.sessionId || id || "" })}
              onStop={stop} onReset={() => {
                reset();
                setInitialPrompt("");
                setIsInitialState(true);
              }}
              provider={provider} model={model} apiKey={apiKey} availableProviders={availableProviders}
              onProviderChange={(p, m, k) => { setProvider(p); setModel(m); setApiKey(k); }}
              showPreview={showPreview} setShowPreview={(v) => { setShowPreview(v); setIsPreviewOpen(v); if (v) setPreviewPaneView("preview"); }}
              showLogs={showLogs} setShowLogs={setShowLogs}
            />
          </div>
          {showLogs && (
            <div style={{ position: "absolute", bottom: 16, left: 16, right: 16, maxHeight: 280, background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-lg)", zIndex: 50, display: "flex", flexDirection: "column", overflow: "hidden", animation: "slideUp 0.25s cubic-bezier(0.4, 0, 0.2, 1)" }}>
              <div style={{ padding: "10px 14px", background: "var(--color-surface2)", borderBottom: "1px solid var(--color-border)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-muted)" }}>Generation Logs</span>
                <button onClick={() => setShowLogs(false)} style={{ background: "transparent", border: "none", color: "var(--color-text-muted)", cursor: "pointer", padding: 4 }}>✕</button>
              </div>
              <div style={{ flex: 1, overflowY: "auto", padding: 14, fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--color-text-muted)" }}>
                {state.output.split("\n").filter(l => l.trim() && (l.startsWith("📦") || l.startsWith("✨") || l.startsWith("📝") || l.startsWith("🚀") || l.startsWith("") || l.startsWith("🛠️") || l.startsWith("✅") || l.startsWith("❌") || l.includes("Analyzing") || l.includes("Generating") || l.includes("Writing") || l.includes("Installing") || l.includes("Starting") || l.includes("Successfully"))).map((line, i) => (
                  <div key={i} style={{ marginBottom: 4, display: "flex", gap: 8 }}><span style={{ color: "var(--color-text-muted2)" }}>[{i + 1}]</span><span>{line}</span></div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {deleteTargetIds.length > 0 && (
        <div style={{ position: "fixed", inset: 0, zIndex: 110, display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
          <div onClick={closeDeleteDialog} style={{ position: "absolute", inset: 0, background: "var(--color-bg-overlay)", backdropFilter: "blur(4px)" }} />
          <div style={{ width: "100%", maxWidth: 520, background: "var(--color-surface)", borderRadius: "var(--radius-xl)", border: "1px solid var(--color-border)", boxShadow: "var(--shadow-xl)", position: "relative", padding: 22, display: "flex", flexDirection: "column", gap: 14 }}>
            <h3 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "var(--color-text)" }}>Delete {deleteTargetIds.length > 1 ? "projects" : "project"}?</h3>
            <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5, color: "var(--color-text-muted)" }}>This action cannot be undone. You are about to permanently remove <strong>{deleteTargetIds.length}</strong> {deleteTargetIds.length > 1 ? "projects" : "project"}.</p>
            {deleteTargetProjects.length > 0 && (
              <div style={{ border: "1px solid var(--color-border)", borderRadius: "var(--radius-md)", background: "var(--color-surface2)", maxHeight: 140, overflowY: "auto", padding: "8px 10px" }}>
                {deleteTargetProjects.slice(0, 5).map(project => (<div key={project.id} style={{ fontSize: 12, color: "var(--color-text)", padding: "3px 0" }}>{project.name || "Untitled Project"}</div>))}
                {deleteTargetProjects.length > 5 && (<div style={{ fontSize: 12, color: "var(--color-text-muted)", paddingTop: 4 }}>+{deleteTargetProjects.length - 5} more</div>)}
              </div>
            )}
            {deleteError && (<div role="alert" style={{ fontSize: 12, color: "var(--color-error)", background: "rgba(239, 68, 68, 0.12)", border: "1px solid rgba(239, 68, 68, 0.28)", borderRadius: "var(--radius-md)", padding: "8px 10px" }}>{deleteError}</div>)}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <button onClick={closeDeleteDialog} className="btn btn-ghost" style={{ padding: "8px 14px" }} disabled={isDeletingProjects}>Cancel</button>
              <button onClick={confirmDeleteProjects} className="btn btn-ghost" style={{ padding: "8px 14px", color: "var(--color-error)" }} disabled={isDeletingProjects}>{isDeletingProjects ? "Deleting..." : `Delete ${deleteTargetIds.length > 1 ? "Projects" : "Project"}`}</button>
            </div>
          </div>
        </div>
      )}
    </AppLayout>
  );
}
