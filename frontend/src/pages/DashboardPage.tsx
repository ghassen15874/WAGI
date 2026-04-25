import { useState, useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Rocket,
  Key,
  Settings,
  Trash2,
  Plus,
  Loader2,
  LogOut,
  User,
  Github,
  Sun,
  Moon,
  LayoutDashboard,
  CheckCircle2,
  Clock,
  AlertCircle,
} from "lucide-react";
import axios from "axios";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../hooks/useTheme";

const backendPublicUrl = (import.meta.env.VITE_BACKEND_PUBLIC_URL as string | undefined)?.trim() || "http://localhost:8080";
const frontendOrigin = typeof window !== "undefined" ? window.location.origin : "";
const githubAuthUrl = `${backendPublicUrl.replace(/\/+$/, "")}/auth/github?frontend=${encodeURIComponent(frontendOrigin)}`;

type ProviderOption = { id: string; name: string; models: string[] };
type ModelOption = { value: string; label: string };

const STAGE_FIELDS = [
  { key: "planningModels", label: "Planning stage" },
  { key: "architectureModels", label: "Architecture / mixed generation" },
  { key: "frontendModels", label: "Frontend generation" },
  { key: "backendModels", label: "Backend generation" },
  { key: "validationModels", label: "Validation / self-healing" },
] as const;

function flattenModelOptions(providers: ProviderOption[]): ModelOption[] {
  return providers.flatMap((provider) =>
    (provider.models || []).map((model) => ({
      value: `${provider.id}:${model}`,
      label: `${provider.name} / ${model}`,
    }))
  );
}

export default function DashboardPage() {
  const { user, token, logout } = useAuth();
  const [searchParams] = useSearchParams();
  const [keys, setKeys] = useState<any[]>([]);
  const [pipeline, setPipeline] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [availableProviders, setAvailableProviders] = useState<ProviderOption[]>([]);
  const [githubDeploying, setGithubDeploying] = useState(false);
  const [newKeyProvider, setNewKeyProvider] = useState("groq");
  const [newKeyValue, setNewKeyValue] = useState("");
  const [newKeyLabel, setNewKeyLabel] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [projects, setProjects] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<"statistics" | "profile" | "pipeline" | "provider">("statistics");
  const repoUrl = searchParams.get("repo") || "";
  const githubError = searchParams.get("github_error") || "";
  const { theme, toggleTheme } = useTheme();

  useEffect(() => {
    fetchData();
  }, []);

  useEffect(() => {
    axios
      .get("/api/providers")
      .then((res) => {
        const providers = Array.isArray(res.data.providers)
          ? res.data.providers.filter((provider: any) => provider.id !== "auto")
          : [];
        setAvailableProviders(providers);
        if (providers.length && !providers.some((provider: any) => provider.id === newKeyProvider)) {
          setNewKeyProvider(providers[0].id);
        }
      })
      .catch(console.error);
  }, [newKeyProvider]);

  const fetchData = async () => {
    try {
      const [keysRes, pipeRes, projectsRes] = await Promise.all([
        axios.get("/api/users/api-keys", { headers: { Authorization: `Bearer ${token}` } }),
        axios.get("/api/users/pipeline", { headers: { Authorization: `Bearer ${token}` } }),
        axios.get("/api/projects", { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      setKeys(keysRes.data.keys);
      setPipeline(pipeRes.data);
      setProjects(projectsRes.data.projects);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleAddKey = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await axios.post(
        "/api/users/api-keys",
        { provider: newKeyProvider, api_key: newKeyValue, label: newKeyLabel },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setNewKeyValue("");
      setNewKeyLabel("");
      fetchData();
    } catch (err) {
      alert("Failed to add key");
    }
  };

  const handleDeleteKey = async (id: string) => {
    try {
      await axios.delete(`/api/users/api-keys/${id}`, { headers: { Authorization: `Bearer ${token}` } });
      fetchData();
    } catch (err) {
      alert("Failed to delete key");
    }
  };

  const togglePipeline = async (field: string) => {
    const updated = { ...pipeline, [field]: !pipeline[field] };
    setPipeline(updated);
    try {
      await axios.put("/api/users/pipeline", updated, { headers: { Authorization: `Bearer ${token}` } });
    } catch (err) {
      alert("Failed to update pipeline");
      setPipeline(pipeline);
    }
  };

  const updatePipeline = async (patch: Record<string, any>) => {
    const updated = { ...pipeline, ...patch };
    setPipeline(updated);
    try {
      await axios.put("/api/users/pipeline", updated, { headers: { Authorization: `Bearer ${token}` } });
    } catch (err) {
      alert("Failed to update pipeline");
      setPipeline(pipeline);
    }
  };

  const modelOptions = flattenModelOptions(availableProviders);

  const handleUpdateProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await axios.put("/api/users/profile", { password: newPassword }, { headers: { Authorization: `Bearer ${token}` } });
      alert("Password updated successfully");
      setNewPassword("");
    } catch (err) {
      alert("Failed to update password");
    }
  };

  const handleConnectGithubDeploy = async () => {
    setGithubDeploying(true);
    try {
      const res = await axios.post(
        "/api/github/prepare",
        { frontendUrl: frontendOrigin },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      window.location.href = res.data.redirect_url || githubAuthUrl;
    } catch (err: any) {
      alert(err?.response?.data?.detail || "Failed to start GitHub deployment");
      setGithubDeploying(false);
    }
  };

  if (loading)
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--color-bg)",
        }}
      >
        <Loader2 className="animate-spin" size={32} />
      </div>
    );

  return (
    <div style={{ minHeight: "100vh", background: "var(--color-bg)" }}>
      {/* Navbar */}
      <nav
        style={{
          padding: "16px 32px",
          background: "var(--color-surface)",
          borderBottom: "1px solid var(--color-border)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <Link
          to="/app"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            textDecoration: "none",
            color: "var(--color-text)",
            fontWeight: 800,
            fontSize: 18,
          }}
        >
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 8,
              background: "var(--gradient-accent)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#fff",
            }}
          >
            <Settings size={16} />
          </div>
          WAGI <span style={{ fontWeight: 400, color: "var(--color-text-muted)" }}>| Settings</span>
        </Link>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <button
            onClick={toggleTheme}
            className="btn-icon"
            aria-label="Toggle theme"
          >
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <span style={{ fontSize: 13, color: "var(--color-text-muted)" }}>{user?.email}</span>
          {user?.role === "ADMIN" && (
            <Link to="/admin" style={{ fontSize: 13, color: "var(--color-accent)", textDecoration: "none" }}>
              Admin Panel
            </Link>
          )}
          <button
            onClick={logout}
            className="btn btn-text"
            style={{ color: "var(--color-error)", gap: 6, fontSize: 13 }}
          >
            <LogOut size={14} /> Logout
          </button>
        </div>
      </nav>

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Sidebar */}
        <aside
          style={{
            width: 240,
            background: "var(--color-surface)",
            borderRight: "1px solid var(--color-border)",
            display: "flex",
            flexDirection: "column",
            padding: "20px 0",
          }}
        >
          <div style={{ padding: "0 24px", marginBottom: 20 }}>
            <h2 style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Settings
            </h2>
          </div>
          <nav style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {[
              { id: "statistics", label: "Statistics", icon: <LayoutDashboard size={18} /> },
              { id: "profile", label: "Profile", icon: <User size={18} /> },
              { id: "pipeline", label: "Pipeline Config", icon: <Settings size={18} /> },
              { id: "provider", label: "Provider", icon: <Key size={18} /> },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "10px 24px",
                  border: "none",
                  background: activeTab === tab.id ? "var(--color-accent-muted)" : "transparent",
                  color: activeTab === tab.id ? "var(--color-accent)" : "var(--color-text)",
                  textAlign: "left",
                  cursor: "pointer",
                  fontSize: 14,
                  fontWeight: 500,
                  transition: "all var(--transition)",
                  borderLeft: activeTab === tab.id ? "3px solid var(--color-accent)" : "3px solid transparent",
                }}
              >
                {tab.icon} {tab.label}
              </button>
            ))}
          </nav>
        </aside>

        {/* Content */}
        <main style={{ flex: 1, overflowY: "auto", padding: "40px", background: "var(--color-bg)" }}>
          <div style={{ maxWidth: 1000, margin: "0 auto" }}>
            {activeTab === "statistics" && renderStatistics()}
            {activeTab === "profile" && renderProfile()}
            {activeTab === "pipeline" && renderPipeline()}
            {activeTab === "provider" && renderProvider()}
          </div>
        </main>
      </div>
    </div>
  );

  function renderStatistics() {
    const doneCount = projects.filter((p) => p.status === "COMPLETED" || p.status === "SUCCESS").length;
    const progressCount = projects.filter((p) => p.status === "GENERATING" || p.status === "BUILDING" || (!p.status && p.updated_at)).length;
    const failedCount = projects.filter((p) => p.status === "FAILED" || p.status === "ERROR").length;
    const total = doneCount + progressCount + failedCount || 1;

    // SVG Donut Chart Calculation
    const size = 180;
    const center = size / 2;
    const radius = 70;
    const circumference = 2 * Math.PI * radius;

    const doneOffset = 0;
    const doneStroke = (doneCount / total) * circumference;
    const progressStroke = (progressCount / total) * circumference;
    const failedStroke = (failedCount / total) * circumference;

    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
        <header style={{ marginBottom: 8 }}>
          <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Statistics</h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 14 }}>Overview of your project building performance.</p>
        </header>

        <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 32 }}>
          {/* Chart Card */}
          <div className="glass" style={{ padding: 32, borderRadius: "var(--radius-xl)", background: "var(--color-surface)", border: "1px solid var(--color-border)", display: "flex", flexDirection: "column", alignItems: "center", gap: 24 }}>
            <div style={{ position: "relative", width: size, height: size }}>
              <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ transform: "rotate(-90deg)" }}>
                {/* Background circle */}
                <circle cx={center} cy={center} r={radius} fill="none" stroke="var(--color-border)" strokeWidth="15" />
                {/* Done segment */}
                <circle
                  cx={center} cy={center} r={radius} fill="none" stroke="var(--color-success)" strokeWidth="15"
                  strokeDasharray={`${doneStroke} ${circumference - doneStroke}`}
                  strokeDashoffset={0}
                  strokeLinecap="round"
                  style={{ transition: "stroke-dasharray 0.5s ease" }}
                />
                {/* Progress segment */}
                <circle
                  cx={center} cy={center} r={radius} fill="none" stroke="var(--color-accent)" strokeWidth="15"
                  strokeDasharray={`${progressStroke} ${circumference - progressStroke}`}
                  strokeDashoffset={-doneStroke}
                  strokeLinecap="round"
                  style={{ transition: "stroke-dasharray 0.5s ease" }}
                />
                {/* Failed segment */}
                <circle
                  cx={center} cy={center} r={radius} fill="none" stroke="var(--color-error)" strokeWidth="15"
                  strokeDasharray={`${failedStroke} ${circumference - failedStroke}`}
                  strokeDashoffset={-(doneStroke + progressStroke)}
                  strokeLinecap="round"
                  style={{ transition: "stroke-dasharray 0.5s ease" }}
                />
              </svg>
              <div style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
                <span style={{ fontSize: 32, fontWeight: 800 }}>{projects.length}</span>
                <span style={{ fontSize: 11, color: "var(--color-text-muted)", textTransform: "uppercase", fontWeight: 700 }}>Projects</span>
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 24, width: "100%" }}>
              {[
                { label: "Done", count: doneCount, color: "var(--color-success)", icon: <CheckCircle2 size={14} /> },
                { label: "Progress", count: progressCount, color: "var(--color-accent)", icon: <Clock size={14} /> },
                { label: "Failed", count: failedCount, color: "var(--color-error)", icon: <AlertCircle size={14} /> },
              ].map((stat) => (
                <div key={stat.label} style={{ textAlign: "center" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6, color: stat.color, marginBottom: 4 }}>
                    {stat.icon}
                    <span style={{ fontSize: 11, fontWeight: 800, textTransform: "uppercase" }}>{stat.label}</span>
                  </div>
                  <div style={{ fontSize: 20, fontWeight: 700 }}>{stat.count}</div>
                  <div style={{ fontSize: 10, color: "var(--color-text-muted)" }}>{Math.round((stat.count / total) * 100)}%</div>
                </div>
              ))}
            </div>
          </div>

          {/* GitHub Card */}
          <div className="glass" style={{ padding: 32, borderRadius: "var(--radius-xl)", background: "var(--color-surface)", border: "1px solid var(--color-border)", display: "flex", flexDirection: "column", gap: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ width: 40, height: 40, borderRadius: "var(--radius-md)", background: "var(--color-surface2)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Github size={20} />
              </div>
              <h3 style={{ fontSize: 18, fontWeight: 700 }}>Deployment</h3>
            </div>

            <div style={{ flex: 1 }}>
              {repoUrl ? (
                <div style={{ padding: "16px", borderRadius: 12, background: "rgba(16,185,129,0.05)", border: "1px solid rgba(16,185,129,0.15)" }}>
                  <div style={{ fontSize: 13, color: "var(--color-success)", fontWeight: 600, marginBottom: 8 }}>✅ Project deployed to GitHub</div>
                  <a href={repoUrl} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: "var(--color-accent)", textDecoration: "none", wordBreak: "break-all" }}>{repoUrl}</a>
                </div>
              ) : githubError ? (
                <div style={{ color: "var(--color-error)", fontSize: 13 }}>{githubError}</div>
              ) : user?.githubConnected ? (
                <div style={{ color: "var(--color-text-muted)", fontSize: 13 }}>Connected as <strong>{user.githubUsername}</strong></div>
              ) : (
                <p style={{ color: "var(--color-text-muted)", fontSize: 13, lineHeight: 1.5 }}>Connect GitHub to enable automated repository creation and cloud deployment for your building projects.</p>
              )}
            </div>

            <button
              onClick={handleConnectGithubDeploy}
              disabled={githubDeploying}
              className="btn btn-primary"
              style={{ width: "100%", padding: "12px", gap: 8 }}
            >
              {githubDeploying ? <Loader2 size={16} className="animate-spin" /> : <Github size={16} />}
              Connect GitHub
            </button>
          </div>
        </div>
      </div>
    );
  }

  function renderProfile() {
    return (
      <div style={{ maxWidth: 600 }}>
        <header style={{ marginBottom: 32 }}>
          <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Profile</h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 14 }}>Manage your account settings and security.</p>
        </header>

        <div className="glass" style={{ padding: 32, borderRadius: "var(--radius-xl)", background: "var(--color-surface)", border: "1px solid var(--color-border)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 24 }}>
            <div style={{ width: 40, height: 40, borderRadius: "var(--radius-md)", background: "var(--color-accent-muted)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <User size={18} color="var(--color-accent)" />
            </div>
            <h2 style={{ fontSize: 18, fontWeight: 700 }}>Security</h2>
          </div>

          <form onSubmit={handleUpdateProfile} style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            <div>
              <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "var(--color-text-muted)", marginBottom: 8 }}>Email Address</label>
              <input disabled value={user?.email || ""} className="input-field" style={{ background: "var(--color-surface2)", cursor: "not-allowed", opacity: 0.7 }} />
            </div>
            <div>
              <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "var(--color-text-muted)", marginBottom: 8 }}>New Password</label>
              <input required type="password" placeholder="Min 6 characters..." value={newPassword} onChange={(e) => setNewPassword(e.target.value)} className="input-field" style={{ background: "var(--color-surface2)" }} />
            </div>
            <button type="submit" className="btn btn-primary" style={{ padding: "12px 20px", alignSelf: "flex-start" }}>Update Password</button>
          </form>
        </div>
      </div>
    );
  }

  function renderProvider() {
    return (
      <div style={{ maxWidth: 800 }}>
        <header style={{ marginBottom: 32 }}>
          <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Provider</h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 14 }}>Configure LLM providers and BYOK (Bring Your Own Keys).</p>
        </header>

        <div className="glass" style={{ padding: 32, borderRadius: "var(--radius-xl)", background: "var(--color-surface)", border: "1px solid var(--color-border)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 24 }}>
            <div style={{ width: 40, height: 40, borderRadius: "var(--radius-md)", background: "var(--color-accent-muted)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Key size={18} color="var(--color-accent)" />
            </div>
            <h2 style={{ fontSize: 18, fontWeight: 700 }}>API Keys</h2>
          </div>

          <form onSubmit={handleAddKey} style={{ display: "flex", gap: 12, marginBottom: 24 }}>
            <select
              value={newKeyProvider}
              onChange={(e) => setNewKeyProvider(e.target.value)}
              style={{ padding: "10px 12px", borderRadius: "8px", background: "var(--color-surface2)", border: "1px solid var(--color-border)", color: "var(--color-text)", outline: "none", minWidth: 120 }}
            >
              {availableProviders.map((provider) => (
                <option key={provider.id} value={provider.id}>{provider.name}</option>
              ))}
            </select>
            <input
              required
              placeholder="api_key..."
              value={newKeyValue}
              onChange={(e) => setNewKeyValue(e.target.value)}
              style={{ flex: 1, padding: "10px 12px", borderRadius: "8px", background: "var(--color-surface2)", border: "1px solid var(--color-border)", color: "var(--color-text)", outline: "none" }}
            />
            <button type="submit" className="btn btn-primary" style={{ padding: "10px 16px" }}>
              <Plus size={18} />
            </button>
          </form>

          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {keys.length === 0 && (
              <div style={{ padding: "20px", textAlign: "center", border: "1px dashed var(--color-border)", borderRadius: 12 }}>
                <span style={{ fontSize: 13, color: "var(--color-text-muted)" }}>No keys added yet. Add one above.</span>
              </div>
            )}
            {keys.map((k, index) => (
              <div key={k.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 20px", background: "var(--color-surface2)", borderRadius: "12px", border: "1px solid var(--color-border)" }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 14, textTransform: "capitalize", display: "flex", alignItems: "center", gap: 8 }}>
                    {k.provider}
                    <span style={{ fontSize: 10, padding: "2px 6px", background: "var(--color-border)", borderRadius: 4 }}>KEY #{index + 1}</span>
                  </div>
                  <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 4 }}>Added on {new Date(k.created_at).toLocaleDateString()}</div>
                </div>
                <button onClick={() => handleDeleteKey(k.id)} style={{ background: "transparent", border: "none", color: "var(--color-error)", cursor: "pointer", padding: 8 }}>
                  <Trash2 size={18} />
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  function renderPipeline() {
    return (
      <div style={{ maxWidth: 800 }}>
        <header style={{ marginBottom: 32 }}>
          <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Pipeline Configuration</h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 14 }}>Fine-tune the AI building engine and self-healing loops.</p>
        </header>

        <div className="glass" style={{ padding: 32, borderRadius: "var(--radius-xl)", background: "var(--color-surface)", border: "1px solid var(--color-border)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 24 }}>
            <div style={{ width: 40, height: 40, borderRadius: "var(--radius-md)", background: "var(--color-accent-muted)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Settings size={18} color="var(--color-accent)" />
            </div>
            <h2 style={{ fontSize: 18, fontWeight: 700 }}>Engine Toggles</h2>
          </div>

          {pipeline && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  <Toggle label="Clear Sandbox" checked={pipeline.clearSandboxEnabled} onChange={() => togglePipeline("clearSandboxEnabled")} />
                  <Toggle label="Design System" checked={pipeline.designSystemEnabled} onChange={() => togglePipeline("designSystemEnabled")} />
                  <Toggle label="Generate Spec" checked={pipeline.specEnabled} onChange={() => togglePipeline("specEnabled")} />
                  <Toggle label="System Prompt" checked={pipeline.systemPromptEnabled} onChange={() => togglePipeline("systemPromptEnabled")} />
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  <Toggle label="Planner Phase" checked={pipeline.plannerEnabled} onChange={() => togglePipeline("plannerEnabled")} />
                  <Toggle label="Builder Phase" checked={pipeline.builderEnabled} onChange={() => togglePipeline("builderEnabled")} />
                  <Toggle label="Auto NPM Install" checked={pipeline.autoInstallEnabled} onChange={() => togglePipeline("autoInstallEnabled")} />
                  <Toggle label="Build Check" checked={pipeline.projectBuildEnabled} onChange={() => togglePipeline("projectBuildEnabled")} />
                </div>
              </div>

              <div style={{ height: 1, background: "var(--color-border)", margin: "10px 0" }} />

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  <Toggle label="Linter Validation" checked={pipeline.linterEnabled} onChange={() => togglePipeline("linterEnabled")} />
                  <Toggle label="Runtime Sync" checked={pipeline.runtimeEnabled} onChange={() => togglePipeline("runtimeEnabled")} />
                  <Toggle label="Feature Validator" checked={pipeline.featureValidatorEnabled} onChange={() => togglePipeline("featureValidatorEnabled")} />
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  <Toggle label="Self-Healing" checked={pipeline.selfHealingEnabled} onChange={() => togglePipeline("selfHealingEnabled")} />
                  <Toggle label="Project Summary" checked={pipeline.summaryEnabled} onChange={() => togglePipeline("summaryEnabled")} />
                  <Toggle label="Active Memory" checked={pipeline.activeMemoryEnabled} onChange={() => togglePipeline("activeMemoryEnabled")} />
                </div>
              </div>

              <div style={{ height: 1, background: "var(--color-border)", margin: "10px 0" }} />

              <Toggle label="Shared Model Sequence" checked={pipeline.useSharedModels} onChange={() => updatePipeline({ useSharedModels: !pipeline.useSharedModels })} />

              {pipeline.useSharedModels ? (
                <MultiModelPicker
                  label="Shared model sequence"
                  hint="The builder will try these in order."
                  value={pipeline.sharedModels || []}
                  options={modelOptions}
                  onChange={(models) => updatePipeline({ sharedModels: models })}
                />
              ) : (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
                  {STAGE_FIELDS.map((field) => (
                    <MultiModelPicker
                      key={field.key}
                      label={field.label}
                      value={pipeline[field.key] || []}
                      options={modelOptions}
                      onChange={(models) => updatePipeline({ [field.key]: models })}
                    />
                  ))}
                </div>
              )}

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginTop: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px", borderRadius: 8, background: "var(--color-surface2)" }}>
                  <span style={{ fontSize: 13, fontWeight: 500 }}>Max Iterations</span>
                  <input type="number" min="1" max="150" value={pipeline.maxIter} onChange={(e) => updatePipeline({ maxIter: parseInt(e.target.value) || 1 })} style={{ width: 60, padding: "5px", background: "transparent", border: "1px solid var(--color-border)", color: "var(--color-text)", textAlign: "center" }} />
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px", borderRadius: 8, background: "var(--color-surface2)" }}>
                  <span style={{ fontSize: 13, fontWeight: 500 }}>Max Healing</span>
                  <input type="number" min="1" max="50" value={pipeline.maxHealingAttempts} onChange={(e) => updatePipeline({ maxHealingAttempts: parseInt(e.target.value) || 1 })} style={{ width: 60, padding: "5px", background: "transparent", border: "1px solid var(--color-border)", color: "var(--color-text)", textAlign: "center" }} />
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: () => void }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ fontSize: 13, fontWeight: 500 }}>{label}</span>
      <div
        onClick={onChange}
        style={{
          width: 44,
          height: 24,
          borderRadius: 12,
          cursor: "pointer",
          background: checked ? "var(--color-accent)" : "var(--color-border)",
          position: "relative",
          transition: "all var(--transition)",
        }}
      >
        <div
          style={{
            width: 18,
            height: 18,
            borderRadius: "50%",
            background: "#fff",
            position: "absolute",
            top: 3,
            left: checked ? 23 : 3,
            transition: "all var(--transition)",
          }}
        />
      </div>
    </div>
  );
}

function MultiModelPicker({
  label,
  value,
  options,
  onChange,
  hint,
}: {
  label: string;
  value: string[];
  options: ModelOption[];
  onChange: (models: string[]) => void;
  hint?: string;
}) {
  const [pendingModel, setPendingModel] = useState(options[0]?.value || "");

  useEffect(() => {
    if (!pendingModel && options[0]?.value) {
      setPendingModel(options[0].value);
    }
  }, [options, pendingModel]);

  const appendModel = () => {
    if (!pendingModel || value.includes(pendingModel)) return;
    onChange([...value, pendingModel]);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <label style={{ fontSize: 13, fontWeight: 500 }}>{label}</label>
      {hint ? <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{hint}</div> : null}
      <div style={{ display: "flex", gap: 8 }}>
        <select
          value={pendingModel}
          onChange={(e) => setPendingModel(e.target.value)}
          style={{
            flex: 1,
            padding: "10px 12px",
            borderRadius: "var(--radius-md)",
            background: "var(--color-surface2)",
            border: "1px solid var(--color-border)",
            color: "var(--color-text)",
            outline: "none",
          }}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={appendModel}
          style={{
            padding: "10px 14px",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--color-border)",
            background: "var(--color-surface2)",
            color: "var(--color-text)",
            cursor: "pointer",
            fontWeight: 500,
          }}
        >
          Add
        </button>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
        {value.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--color-text-muted2)" }}>No models selected yet.</div>
        ) : value.map((selectedValue, index) => {
          const option = options.find((item) => item.value === selectedValue);
          return (
            <div
              key={`${selectedValue}-${index}`}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "10px 12px",
                borderRadius: "var(--radius-md)",
                background: "var(--color-surface2)",
                border: "1px solid var(--color-border)",
              }}
            >
              <span style={{ fontSize: 12, color: "var(--color-text-muted2)", minWidth: 20 }}>{index + 1}.</span>
              <span style={{ flex: 1, fontSize: 13 }}>{option?.label || selectedValue}</span>
              <button
                type="button"
                disabled={index === 0}
                onClick={() => {
                  const next = [...value];
                  [next[index - 1], next[index]] = [next[index], next[index - 1]];
                  onChange(next);
                }}
                style={{
                  background: "none",
                  border: "none",
                  color: "var(--color-text-muted)",
                  cursor: index === 0 ? "default" : "pointer",
                  opacity: index === 0 ? 0.4 : 1,
                  fontSize: 12,
                }}
              >
                Up
              </button>
              <button
                type="button"
                disabled={index === value.length - 1}
                onClick={() => {
                  const next = [...value];
                  [next[index], next[index + 1]] = [next[index + 1], next[index]];
                  onChange(next);
                }}
                style={{
                  background: "none",
                  border: "none",
                  color: "var(--color-text-muted)",
                  cursor: index === value.length - 1 ? "default" : "pointer",
                  opacity: index === value.length - 1 ? 0.4 : 1,
                  fontSize: 12,
                }}
              >
                Down
              </button>
              <button
                type="button"
                onClick={() => onChange(value.filter((item) => item !== selectedValue || value.indexOf(item) !== index))}
                style={{ background: "none", border: "none", color: "var(--color-error)", cursor: "pointer", fontSize: 12 }}
              >
                Remove
              </button>
            </div>
          );
        })}
      </div>
      <div style={{ fontSize: 11, color: "var(--color-text-muted2)" }}>Selected order is preserved and used as fallback priority.</div>
    </div>
  );
}
