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
  const [billing, setBilling] = useState<any>(null);
  const [activeTab, setActiveTab] = useState<"statistics" | "profile" | "pipeline" | "provider" | "billing">("statistics");
  const [showPassword, setShowPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [billingBusyPlanId, setBillingBusyPlanId] = useState("");
  const [isSidebarVisible, setIsSidebarVisible] = useState(true);

  const repoUrl = searchParams.get("repo") || "";
  const githubError = searchParams.get("github_error") || "";
  const billingStatus = searchParams.get("billing") || "";
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

  useEffect(() => {
    const requestedTab = (searchParams.get("tab") || "").toLowerCase();
    if (requestedTab === "statistics" || requestedTab === "profile" || requestedTab === "pipeline" || requestedTab === "provider" || requestedTab === "billing") {
      setActiveTab(requestedTab as any);
    }
  }, [searchParams]);

  const fetchData = async () => {
    try {
      const [keysRes, pipeRes, projectsRes, billingRes] = await Promise.all([
        axios.get("/api/users/api-keys", { headers: { Authorization: `Bearer ${token}` } }),
        axios.get("/api/users/pipeline", { headers: { Authorization: `Bearer ${token}` } }),
        axios.get("/api/projects", { headers: { Authorization: `Bearer ${token}` } }),
        axios.get("/api/billing/me", { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      setKeys(keysRes.data.keys);
      setPipeline(pipeRes.data);
      setProjects(projectsRes.data.projects);
      setBilling(billingRes.data);
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

  const handlePlanChange = async (planId: string) => {
    if (!token || billingBusyPlanId) {
      return;
    }

    setBillingBusyPlanId(planId);
    try {
      const res = await axios.post(
        "/api/billing/checkout",
        { planId },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      const payload = res.data || {};
      if (payload.checkoutUrl) {
        window.location.href = payload.checkoutUrl;
        return;
      }

      await fetchData();
    } catch (error: any) {
      alert(error?.response?.data?.detail || "Failed to change plan");
    } finally {
      setBillingBusyPlanId("");
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
        { id: "billing", label: "Billing", icon: <Zap size={18} /> },
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
      <div style={{ padding: "40px 60px", width: "100%", animation: "fadeIn 0.4s ease-out" }}>
        <div style={{ marginBottom: 40 }}>
          <h1 style={{ fontSize: 32, fontWeight: 800, color: "var(--color-text)", marginBottom: 8 }}>
            {activeTab === 'statistics' && "Statistics"}
            {activeTab === 'billing' && "Billing"}
            {activeTab === 'profile' && "Account Settings"}
            {activeTab === 'pipeline' && "Generation Pipeline"}
            {activeTab === 'provider' && "AI Providers"}
          </h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 15 }}>
            {activeTab === 'statistics' && "Performance metrics and project activity."}
            {activeTab === 'billing' && "Track monthly request usage and manage your active plan."}
            {activeTab === 'profile' && "Configure your workspace and monitor platform resources."}
            {activeTab === 'pipeline' && "Configure your workspace and monitor platform resources."}
            {activeTab === 'provider' && "Configure your workspace and monitor platform resources."}
          </p>
        </div>

        <div style={{ minHeight: '600px' }}>
          {activeTab === 'statistics' && renderStatistics()}
          {activeTab === 'billing' && renderBilling()}
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

  function renderBilling() {
    const usage = billing?.usage || {};
    const plans = Array.isArray(billing?.plans) ? billing.plans : [];
    const currentPlan = billing?.currentPlan || null;
    const requestsLimit = Number(usage.requestsLimit || 0);
    const requestsUsed = Number(usage.requestsUsed || 0);
    const requestsLeft = Number(usage.requestsLeft || Math.max(0, requestsLimit - requestsUsed));

    const formatUSD = (cents: number) => {
      const safe = Number(cents || 0);
      return safe <= 0 ? "Free" : `$${(safe / 100).toFixed(2)}/mo`;
    };

    const formatCount = (num: number) => {
      const n = Number(num || 0);
      if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
      if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
      return n.toString();
    };

    const strategy = usage.strategy || "monthly";
    const dailyLimit = Number(usage.dailyTokensLimit || 0);
    const totalLimit = Number(usage.totalTokensLimit || 0);
    const inputUsed = Number(usage.inputTokens || 0);
    const outputUsed = Number(usage.outputTokens || 0);
    const totalTokenUsed = strategy === "total" ? Number(usage.totalTokensUsed || 0) : Number(usage.dailyTokensUsed || 0);
    const activeLimit = strategy === "total" ? totalLimit : (strategy === "daily" ? dailyLimit : 0);

    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>

        {billingStatus === "success" && (
          <div style={{ padding: "12px 14px", borderRadius: 12, background: "rgba(16,185,129,0.12)", border: "1px solid rgba(16,185,129,0.3)", color: "var(--color-success)", fontSize: 13 }}>
            Stripe checkout completed. Your subscription will update automatically in a few seconds.
          </div>
        )}

        {billingStatus === "cancel" && (
          <div style={{ padding: "12px 14px", borderRadius: 12, background: "rgba(245,158,11,0.12)", border: "1px solid rgba(245,158,11,0.3)", color: "var(--color-warning)", fontSize: 13 }}>
            Checkout was canceled. Your current plan remains unchanged.
          </div>
        )}

        {/* Global Overview Section */}
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 16, color: "var(--color-text)", display: "flex", alignItems: "center", gap: 8 }}>
            <BarChart3 size={18} /> Account Usage Overview
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 24, marginBottom: 28 }}>
            <div className="glass" style={{ padding: 28, position: "relative", overflow: "hidden", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <div style={{ position: "absolute", top: -20, right: -20, opacity: 0.1, transform: "rotate(15deg)" }}><Rocket size={100} /></div>
              <div>
                <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-muted2)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 12 }}>Current Plan</div>
                <div style={{ fontSize: 32, fontWeight: 900, marginBottom: 6, color: "var(--color-accent)" }}>{currentPlan?.name || "Free"}</div>
                <div style={{ color: "var(--color-text-muted)", fontSize: 14 }}>{formatUSD(Number(currentPlan?.monthlyPriceCents || 0))}</div>
              </div>
            </div>

            <div className="glass" style={{ padding: 28, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-muted2)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 12 }}>Requests Used</div>
                <div style={{ fontSize: 32, fontWeight: 900, marginBottom: 6 }}>{requestsUsed}</div>
                <div style={{ color: "var(--color-text-muted)", fontSize: 14 }}>of {requestsLimit} this month</div>
              </div>
              <div style={{ height: 6, background: "var(--color-surface2)", borderRadius: 3, marginTop: 16, overflow: "hidden" }}>
                <div style={{ height: "100%", background: "var(--color-accent)", width: `${Math.min(100, (requestsUsed / (requestsLimit || 1)) * 100)}%`, transition: "width 1s ease-out" }} />
              </div>
            </div>

            <div className="glass" style={{ padding: 28, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-muted2)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 12 }}>Requests Left</div>
                <div style={{ fontSize: 32, fontWeight: 900, marginBottom: 6, color: "var(--color-success)" }}>{requestsLeft}</div>
                <div style={{ color: "var(--color-text-muted)", fontSize: 14 }}>period: {usage.periodKey || "-"}</div>
              </div>
            </div>
          </div>
        </div>

        {/* Token Specific Section */}
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 16, color: "var(--color-text)", display: "flex", alignItems: "center", gap: 8 }}>
            <Zap size={18} color="var(--color-warning)" /> Generation Intelligence (Tokens)
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 20 }}>
            <div className="glass" style={{ padding: 20, background: "var(--color-surface2)" }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted2)", textTransform: "uppercase", marginBottom: 8 }}>Limit Strategy</div>
              <div style={{ fontSize: 18, fontWeight: 800, textTransform: "capitalize" }}>{strategy}</div>
            </div>
            <div className="glass" style={{ padding: 20 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted2)", textTransform: "uppercase", marginBottom: 8 }}>Input Tokens</div>
              <div style={{ fontSize: 22, fontWeight: 800 }}>{formatCount(inputUsed)}</div>
            </div>
            <div className="glass" style={{ padding: 20 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted2)", textTransform: "uppercase", marginBottom: 8 }}>Output Tokens</div>
              <div style={{ fontSize: 22, fontWeight: 800 }}>{formatCount(outputUsed)}</div>
            </div>
            <div className="glass" style={{ padding: 20, border: "1px solid var(--color-accent-muted)" }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted2)", textTransform: "uppercase", marginBottom: 8 }}>{strategy === "total" ? "Total Consumed" : "Daily Usage"}</div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
                <span style={{ fontSize: 22, fontWeight: 800 }}>{formatCount(totalTokenUsed)}</span>
                {activeLimit > 0 && <span style={{ fontSize: 14, color: "var(--color-text-muted)" }}>/ {formatCount(activeLimit)}</span>}
              </div>
              {activeLimit > 0 && (
                <div style={{ height: 4, background: "var(--color-surface2)", borderRadius: 2, marginTop: 12, overflow: "hidden" }}>
                  <div style={{ height: "100%", background: "var(--color-success)", width: `${Math.min(100, (totalTokenUsed / activeLimit) * 100)}%` }} />
                </div>
              )}
            </div>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 14 }}>
          {plans.map((plan: any) => {
            const isCurrent = Boolean(plan.isCurrent);
            const canUse = Boolean(plan.canUse);
            const actionLabel = isCurrent ? "Current Plan" : (canUse ? "Included in your tier" : "Upgrade");
            const busy = billingBusyPlanId === plan.id;

            return (
              <div key={plan.id} className="glass" style={{ padding: 20, border: isCurrent ? "1px solid var(--color-accent)" : "1px solid var(--color-border)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <div style={{ fontSize: 18, fontWeight: 800 }}>{plan.name}</div>
                  {isCurrent && (
                    <span style={{ fontSize: 11, fontWeight: 700, color: "var(--color-success)", background: "rgba(16,185,129,0.12)", border: "1px solid rgba(16,185,129,0.25)", borderRadius: 999, padding: "3px 8px" }}>
                      Active
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 14, color: "var(--color-text-muted)", marginBottom: 14 }}>{formatUSD(Number(plan.monthlyPriceCents || 0))}</div>
                <div style={{ fontSize: 13, color: "var(--color-text-muted)", display: "flex", flexDirection: "column", gap: 4, marginBottom: 16 }}>
                  <span>Model: {plan.provider}:{plan.model}</span>
                  <span>Request limit: {plan.monthlyRequestLimit} / month</span>
                  <span>Input token price: ${Number(plan.inputTokenPricePerMillion || 0).toFixed(4)} / 1M</span>
                  <span>Output token price: ${Number(plan.outputTokenPricePerMillion || 0).toFixed(4)} / 1M</span>
                </div>
                <button
                  onClick={() => !canUse && handlePlanChange(plan.id)}
                  disabled={isCurrent || canUse || busy}
                  className="btn btn-primary"
                  style={{ width: "100%", opacity: isCurrent || canUse ? 0.65 : 1 }}
                >
                  {busy ? "Processing..." : actionLabel}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  function renderProfile() {
    return (
      <div style={{ width: "100%" }}>

        <div className="glass" style={{ padding: 48, background: "var(--gradient-surface)", boxShadow: "var(--shadow-lg)" }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 40 }}>
            <div style={{ width: 56, height: 56, borderRadius: 16, background: 'var(--color-accent-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', border: "1px solid var(--color-accent-muted)" }}>
              <ShieldCheck size={28} color="var(--color-accent)" />
            </div>
            <div>
              <h3 style={{ fontSize: 22, fontWeight: 800 }}>Security Settings</h3>
              <p style={{ fontSize: 14, color: "var(--color-text-muted)" }}>Update your master password and email preferences.</p>
            </div>
          </div>

          <form onSubmit={handleUpdateProfile} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 32 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <label style={labelStyle}>Email Address</label>
              <div style={{ padding: '14px 18px', borderRadius: 12, background: 'var(--color-surface2)', border: '1px solid var(--color-border)', color: 'var(--color-text-muted)', fontSize: 14 }}>
                {user?.email || "No email connected"}
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <label style={labelStyle}>New Password</label>
              <div style={{ position: 'relative' }}>
                <input required type={showPassword ? 'text' : 'password'} placeholder="••••••••" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} style={{ ...inputStyle, paddingRight: 48 }} />
                <button type="button" onClick={() => setShowPassword(!showPassword)} style={{ position: 'absolute', right: 16, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: 'var(--color-text-muted)', cursor: 'pointer' }}>
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>
            <div style={{ gridColumn: 'span 2', display: 'flex', justifyContent: 'flex-start', marginTop: 8 }}>
              <button type="submit" disabled={saving || !newPassword} className="btn-primary" style={{ padding: '14px 32px', height: 52 }}>
                {saving ? <RefreshCw size={18} className="animate-spin" /> : <Save size={18} />}
                <span>Save Changes</span>
              </button>
            </div>
          </form>
        </div>
      </div>
    );
  }

  function renderPipeline() {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 40 }}>

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

        <div className="glass" style={{ padding: 48, background: "var(--gradient-surface)", boxShadow: "var(--shadow-lg)" }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 40 }}>
            <div style={{ width: 56, height: 56, borderRadius: 16, background: 'var(--color-surface2)', display: 'flex', alignItems: 'center', justifyContent: 'center', border: "1px solid var(--color-border)" }}>
              <Fingerprint size={28} color="var(--color-accent)" />
            </div>
            <div>
              <h2 style={{ fontSize: 22, fontWeight: 800 }}>API Key Management</h2>
              <p style={{ fontSize: 14, color: "var(--color-text-muted)" }}>Control your external AI model access and personal keys.</p>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 40 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 16, color: "var(--color-text)" }}>Add New Connection</div>
              <form onSubmit={handleAddKey} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <label style={labelStyle}>Provider</label>
                  <select value={newKeyProvider} onChange={(e) => setNewKeyProvider(e.target.value)} style={inputStyle}>
                    {availableProviders.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <label style={labelStyle}>API Key</label>
                  <input required placeholder="Paste your API key here..." value={newKeyValue} onChange={(e) => setNewKeyValue(e.target.value)} type="password" style={inputStyle} />
                </div>
                <button type="submit" className="btn-primary" style={{ height: 48, marginTop: 12 }}>
                  <Plus size={18} />
                  <span>Register Provider</span>
                </button>
              </form>
            </div>

            <div>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 16, color: "var(--color-text)" }}>Existing Keys</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxHeight: 400, overflowY: "auto", paddingRight: 4 }}>
                {keys.length === 0 && (
                  <div style={{ padding: 24, textAlign: "center", color: "var(--color-text-muted)", border: "1px dashed var(--color-border)", borderRadius: 16 }}>
                    No keys added yet.
                  </div>
                )}
                {keys.map((k, idx) => (
                  <div key={k.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 20px', background: 'var(--color-surface2)', borderRadius: 16, border: '1px solid var(--color-border)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                      <div style={{ fontWeight: 800, textTransform: 'uppercase', fontSize: 12, letterSpacing: '0.05em', color: "var(--color-accent)" }}>{k.provider}</div>
                      <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{new Date(k.created_at).toLocaleDateString()}</div>
                    </div>
                    <button onClick={() => handleDeleteKey(k.id)} className="btn-icon btn-icon-sm" style={{ color: 'var(--color-error)', border: "none", background: "transparent" }}>
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
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
