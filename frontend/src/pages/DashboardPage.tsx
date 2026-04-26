import { useState, useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Rocket, Key, Settings, Trash2, Plus, Loader2, LogOut, User,
  Github, Sun, Moon, LayoutDashboard, CheckCircle2, Clock,
  AlertCircle, Settings2, Server, Zap, ShieldCheck, Palette,
  Cpu, Globe, Info, BarChart3, Fingerprint, ChevronRight,
  Eye, EyeOff, Save, RefreshCw
} from "lucide-react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'
import axios from "axios";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../hooks/useTheme";
import AppLayout from "../components/AppLayout";

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
  const [showPassword, setShowPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [isSidebarVisible, setIsSidebarVisible] = useState(true);

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
    setSaving(true);
    try {
      await axios.put("/api/users/profile", { password: newPassword }, { headers: { Authorization: `Bearer ${token}` } });
      alert("Password updated successfully");
      setNewPassword("");
    } catch (err) {
      alert("Failed to update password");
    } finally {
      setSaving(false);
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
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--color-bg)" }}>
        <Loader2 className="animate-spin" size={32} />
      </div>
    );

  const sidebarContent = (
    <div style={{ padding: isSidebarVisible ? "12px" : "12px 0", width: "100%", display: "flex", flexDirection: "column", gap: 4, alignItems: "center" }}>
      <div style={{ fontSize: 11, color: "var(--color-sidebar-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", padding: "12px 8px 8px", width: "100%", textAlign: isSidebarVisible ? "left" : "center" }}>
        {isSidebarVisible ? "Settings" : "•"}
      </div>
      {[
        { id: "statistics", label: "Statistics", icon: <BarChart3 size={18} /> },
        { id: "profile", label: "Profile", icon: <User size={18} /> },
        { id: "pipeline", label: "Pipeline Config", icon: <Settings2 size={18} /> },
        { id: "provider", label: "Provider", icon: <Key size={18} /> },
      ].map((item) => (
        <button
          key={item.id}
          onClick={() => setActiveTab(item.id as any)}
          style={{
            padding: isSidebarVisible ? "10px 12px" : "10px",
            borderRadius: isSidebarVisible ? "var(--radius-md)" : "var(--radius-full)",
            background: activeTab === item.id ? "var(--color-sidebar-item-active)" : "transparent",
            display: "flex",
            alignItems: "center",
            justifyContent: isSidebarVisible ? "flex-start" : "center",
            gap: 8,
            fontSize: 13,
            cursor: "pointer",
            color: activeTab === item.id ? "var(--color-sidebar-text)" : "var(--color-sidebar-text)",
            opacity: activeTab === item.id ? 1 : 0.7,
            transition: "all var(--transition)",
            border: activeTab === item.id ? "1px solid var(--color-sidebar-border)" : "1px solid transparent",
            width: isSidebarVisible ? "calc(100% - 16px)" : "auto",
            margin: isSidebarVisible ? "0 8px" : "0",
            textAlign: "left"
          }}
          title={!isSidebarVisible ? item.label : ""}
          onMouseEnter={(e) => { if (activeTab !== item.id) e.currentTarget.style.background = "var(--color-sidebar-item-hover)"; }}
          onMouseLeave={(e) => { if (activeTab !== item.id) e.currentTarget.style.background = "transparent"; }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", color: activeTab === item.id ? "var(--color-accent)" : "inherit" }}>
            {item.icon}
          </div>
          {isSidebarVisible && item.label}
        </button>
      ))}
    </div>
  );

  return (
    <AppLayout
      isSidebarVisible={isSidebarVisible}
      setIsSidebarVisible={setIsSidebarVisible}
      sidebarContent={sidebarContent}
    >
      <div style={{ padding: "40px", maxWidth: "1200px", margin: "0 auto", animation: "fadeIn 0.4s ease-out" }}>
        <div style={{ marginBottom: 40 }}>
          <h1 style={{ fontSize: 32, fontWeight: 800, color: "var(--color-text)", marginBottom: 8 }}>
            {activeTab === 'statistics' && "Platform Usage"}
            {activeTab === 'profile' && "Account Settings"}
            {activeTab === 'pipeline' && "Generation Pipeline"}
            {activeTab === 'provider' && "AI Providers"}
          </h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 15 }}>
            Configure your workspace and monitor platform resources.
          </p>
        </div>

        <div style={{ minHeight: '600px' }}>
          {activeTab === 'statistics' && renderStatistics()}
          {activeTab === 'profile' && renderProfile()}
          {activeTab === 'pipeline' && renderPipeline()}
          {activeTab === 'provider' && renderProvider()}
        </div>
      </div>
    </AppLayout>
  );

  function renderStatistics() {
    const doneCount = projects.filter((p) => p.status === "COMPLETED" || p.status === "SUCCESS").length;
    const progressCount = projects.filter((p) => p.status === "GENERATING" || p.status === "BUILDING" || (!p.status && p.updated_at)).length;
    const failedCount = projects.filter((p) => p.status === "FAILED" || p.status === "ERROR").length;
    const total = doneCount + progressCount + failedCount || 1;

    const data = [
      { name: 'Completed', value: doneCount, color: 'var(--color-success)' },
      { name: 'In Progress', value: progressCount, color: 'var(--color-accent)' },
      { name: 'Failed', value: failedCount, color: 'var(--color-error)' }
    ].filter(d => d.value > 0);

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 40 }}>
        <header>
          <h1 style={{ fontSize: 32, fontWeight: 800, marginBottom: 8, letterSpacing: '-0.02em' }}>Statistics</h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 15 }}>Performance metrics and project activity.</p>
        </header>

        <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 32 }}>
          <div className="glass" style={{ padding: 40, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 32 }}>
            <div style={{ width: '100%', height: 260, position: 'relative' }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={data.length ? data : [{ name: 'Empty', value: 1, color: 'var(--color-border)' }]}
                    cx="50%" cy="50%"
                    innerRadius={80} outerRadius={110}
                    paddingAngle={5} dataKey="value"
                    stroke="none"
                  >
                    {data.length ? data.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    )) : <Cell fill="var(--color-border)" />}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
              <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', textAlign: 'center' }}>
                <div style={{ fontSize: 40, fontWeight: 900, lineHeight: 1 }}>{projects.length}</div>
                <div style={{ fontSize: 12, color: 'var(--color-text-muted)', fontWeight: 700, textTransform: 'uppercase', marginTop: 4 }}>Total</div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 40, width: '100%', justifyContent: 'center' }}>
              {data.map((stat) => (
                <div key={stat.name} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{ width: 8, height: 8, borderRadius: '50%', background: stat.color }} />
                    <span style={{ fontSize: 13, fontWeight: 600 }}>{stat.name}</span>
                  </div>
                  <div style={{ fontSize: 24, fontWeight: 800 }}>{stat.value}</div>
                </div>
              ))}
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
            <div className="glass" style={{ padding: 32, display: 'flex', flexDirection: 'column', gap: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ width: 44, height: 44, borderRadius: 12, background: 'var(--color-surface2)', display: 'flex', alignItems: 'center', justifyContent: "center" }}>
                  <Github size={22} />
                </div>
                <h2 style={{ fontSize: 20, fontWeight: 700 }}>Deployment</h2>
              </div>
              <p style={{ fontSize: 14, color: 'var(--color-text-muted)', lineHeight: 1.6 }}>
                Connect your GitHub account to enable automated continuous deployment and remote repository management.
              </p>
              <div style={{ padding: '16px', borderRadius: 12, background: 'var(--color-surface2)', border: '1px solid var(--color-border)' }}>
                {repoUrl ? <div style={{ color: 'var(--color-success)', fontSize: 13, fontWeight: 600 }}>✅ Project synced to GitHub</div> : <div style={{ fontSize: 13 }}>GitHub status: <span style={{ color: 'var(--color-text-muted)' }}>Not connected</span></div>}
              </div>
              <button onClick={handleConnectGithubDeploy} disabled={githubDeploying} className="btn-primary" style={{ height: 48, gap: 10 }}>
                <Github size={18} /> {githubDeploying ? 'Connecting...' : 'Connect GitHub'}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  function renderProfile() {
    return (
      <div style={{ maxWidth: 700 }}>
        <header style={{ marginBottom: 40 }}>
          <h1 style={{ fontSize: 32, fontWeight: 800, marginBottom: 8 }}>Profile</h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 15 }}>Manage your account security and preferences.</p>
        </header>

        <div className="glass" style={{ padding: 40 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 32 }}>
            <div style={{ width: 44, height: 44, borderRadius: 12, background: 'var(--color-accent-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <ShieldCheck size={22} color="var(--color-accent)" />
            </div>
            <h3 style={{ fontSize: 20, fontWeight: 700 }}>Security Settings</h3>
          </div>

          <form onSubmit={handleUpdateProfile} style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <label style={labelStyle}>Email Address</label>
              <input disabled value={user?.email || ""} className="btn-secondary" style={{ width: '100%', textAlign: 'left', cursor: 'not-allowed', opacity: 0.6 }} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <label style={labelStyle}>New Password</label>
              <div style={{ position: 'relative' }}>
                <input required type={showPassword ? 'text' : 'password'} placeholder="••••••••" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} style={inputStyle} />
                <button type="button" onClick={() => setShowPassword(!showPassword)} style={{ position: 'absolute', right: 16, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: 'var(--color-text-muted)', cursor: 'pointer' }}>
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>
            <button type="submit" disabled={saving || !newPassword} className="btn-primary" style={{ padding: '14px 24px', alignSelf: 'flex-start', minWidth: 160 }}>
              {saving ? <RefreshCw size={18} className="animate-spin" /> : <Save size={18} />}
              Update Password
            </button>
          </form>
        </div>
      </div>
    );
  }

  function renderPipeline() {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 40 }}>
        <header>
          <h1 style={{ fontSize: 32, fontWeight: 800, marginBottom: 8 }}>Pipeline Config</h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 15 }}>Configure the project building and self-healing behaviors.</p>
        </header>

        <div className="glass" style={{ padding: 40 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 32 }}>
            <div style={{ width: 44, height: 44, borderRadius: 12, background: 'var(--color-surface2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Zap size={22} color="var(--color-warning)" />
            </div>
            <h2 style={{ fontSize: 20, fontWeight: 700 }}>Engine Control Center</h2>
          </div>

          {pipeline && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 24 }}>
                {[
                  { label: 'Clear Sandbox', field: 'clearSandboxEnabled' },
                  { label: 'Design System', field: 'designSystemEnabled' },
                  { label: 'Generate Spec', field: 'specEnabled' },
                  { label: 'System Prompt', field: 'systemPromptEnabled' },
                  { label: 'Planner Phase', field: 'plannerEnabled' },
                  { label: 'Builder Phase', field: 'builderEnabled' },
                  { label: 'Auto Install', field: 'autoInstallEnabled' },
                  { label: 'Build Check', field: 'projectBuildEnabled' },
                  { label: 'Linter Validation', field: 'linterEnabled' },
                  { label: 'Self-Healing', field: 'selfHealingEnabled' },
                ].map((item) => (
                  <div key={item.field} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 20px', background: 'var(--color-surface2)', borderRadius: 16, border: '1px solid var(--color-border)' }}>
                    <span style={{ fontWeight: 600, fontSize: 14 }}>{item.label}</span>
                    <div onClick={() => togglePipeline(item.field)} style={{ width: 48, height: 26, borderRadius: 13, background: pipeline[item.field] ? 'var(--color-accent)' : 'var(--color-border)', position: 'relative', cursor: 'pointer', transition: 'var(--transition)' }}>
                      <div style={{ width: 20, height: 20, borderRadius: '50%', background: 'white', position: 'absolute', top: 3, left: pipeline[item.field] ? 25 : 3, transition: 'var(--transition)' }} />
                    </div>
                  </div>
                ))}
              </div>

              <div style={{ height: 1, background: 'var(--color-border)' }} />

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <label style={labelStyle}>Max AI Iterations</label>
                  <input type="number" value={pipeline.maxIter} onChange={(e) => updatePipeline({ maxIter: parseInt(e.target.value) || 1 })} style={inputStyle} />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <label style={labelStyle}>Self-Healing Limit</label>
                  <input type="number" value={pipeline.maxHealingAttempts} onChange={(e) => updatePipeline({ maxHealingAttempts: parseInt(e.target.value) || 1 })} style={inputStyle} />
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  function renderProvider() {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 40 }}>
        <header>
          <h1 style={{ fontSize: 32, fontWeight: 800, marginBottom: 8 }}>Provider</h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 15 }}>Manage your AI model providers and API keys (BYOK).</p>
        </header>

        <div className="glass" style={{ padding: 40 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 32 }}>
            <div style={{ width: 44, height: 44, borderRadius: 12, background: 'var(--color-surface2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Fingerprint size={22} color="var(--color-accent)" />
            </div>
            <h2 style={{ fontSize: 20, fontWeight: 700 }}>API Key Management</h2>
          </div>

          <form onSubmit={handleAddKey} style={{ display: 'grid', gridTemplateColumns: '1fr 2fr auto', gap: 12, marginBottom: 40 }}>
            <select value={newKeyProvider} onChange={(e) => setNewKeyProvider(e.target.value)} style={inputStyle}>
              {availableProviders.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <input required placeholder="Paste your API key here..." value={newKeyValue} onChange={(e) => setNewKeyValue(e.target.value)} type="password" style={inputStyle} />
            <button type="submit" className="btn-primary" style={{ padding: '0 24px' }}><Plus size={20} /></button>
          </form>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {keys.map((k, idx) => (
              <div key={k.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '20px 24px', background: 'var(--color-surface)', borderRadius: 16, border: '1px solid var(--color-border)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                  <div style={{ width: 40, height: 40, borderRadius: 12, background: 'var(--color-surface2)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 800 }}>{idx + 1}</div>
                  <div>
                    <div style={{ fontWeight: 800, textTransform: 'uppercase', fontSize: 13, letterSpacing: '0.02em' }}>{k.provider}</div>
                    <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 2 }}>Added on {new Date(k.created_at).toLocaleDateString()}</div>
                  </div>
                </div>
                <button onClick={() => handleDeleteKey(k.id)} className="btn-icon" style={{ color: 'var(--color-error)' }}>
                  <Trash2 size={18} />
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }
}

const labelStyle: React.CSSProperties = {
  fontSize: 11, fontWeight: 800, color: 'var(--color-text-muted2)',
  textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4, display: 'block'
}

const inputStyle: React.CSSProperties = {
  width: '100%', padding: '12px 16px', borderRadius: 12,
  background: 'var(--color-surface2)', border: '1px solid var(--color-border)',
  color: 'var(--color-text)', fontSize: 13, outline: 'none', transition: 'var(--transition)'
}
