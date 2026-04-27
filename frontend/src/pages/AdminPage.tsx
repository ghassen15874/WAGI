import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Rocket, Users, Activity, Database, Loader2, Zap, Settings, Plus, ShieldCheck, UserCog } from "lucide-react";
import axios from "axios";
import { useAuth } from "../hooks/useAuth";
import AppLayout from "../components/AppLayout";

export default function AdminPage() {
  const { token } = useAuth();
  const [tab, setTab] = useState<"users" | "metrics" | "logs" | "models" | "providers" | "plans">("metrics");
  const [metrics, setMetrics] = useState<any>(null);
  const [users, setUsers] = useState<any[]>([]);
  const [logs, setLogs] = useState<any[]>([]);
  const [models, setModels] = useState<any[]>([]);
  const [providers, setProviders] = useState<any[]>([]);
  const [plans, setPlans] = useState<any[]>([]);
  const [planApiKeys, setPlanApiKeys] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [newModelId, setNewModelId] = useState("");
  const [newModelProvider, setNewModelProvider] = useState("groq");
  const [isSidebarVisible, setIsSidebarVisible] = useState(true);

  // User Creation State
  const [showCreateUser, setShowCreateUser] = useState(false);
  const [newUserEmail, setNewUserEmail] = useState("");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [newUserRole, setNewUserRole] = useState("USER");

  useEffect(() => {
    fetchData();
  }, [tab, token]);

  useEffect(() => {
    const firstProvider = providers.find((p) => p.id !== "auto");
    if (firstProvider && !providers.some((p) => p.id === newModelProvider)) {
      setNewModelProvider(firstProvider.id);
    }
  }, [providers, newModelProvider]);

  const fetchData = async () => {
    setLoading(true);
    setError("");
    try {
      const config = { headers: { Authorization: `Bearer ${token}` } };
      if (tab === "metrics") {
        const res = await axios.get("/api/admin/metrics", config);
        setMetrics(res.data);
      } else if (tab === "users") {
        const res = await axios.get("/api/admin/users", config);
        setUsers(res.data.users);
      } else if (tab === "logs") {
        const res = await axios.get("/api/admin/logs", config);
        setLogs(res.data.logs);
      } else if (tab === "models" || tab === "plans") {
        const [modelsRes, providersRes, plansRes] = await Promise.all([
          axios.get("/api/admin/models", config),
          axios.get("/api/admin/providers", config),
          axios.get("/api/admin/plans", config),
        ]);
        setModels(modelsRes.data.models);
        setProviders(providersRes.data.providers);
        setPlans(plansRes.data.plans || []);
      } else if (tab === "providers") {
        const res = await axios.get("/api/admin/providers", config);
        setProviders(res.data.providers);
      }
    } catch (err: any) {
      console.error(err);
      setError(err.response?.data?.detail || "Failed to load admin data");
    } finally {
      setLoading(false);
    }
  };

  const toggleUserActive = async (id: string, current: boolean) => {
    try {
      await axios.patch(`/api/admin/users/${id}`, { isActive: !current }, { headers: { Authorization: `Bearer ${token}` } });
      fetchData();
    } catch (err) {
      alert("Failed to update user");
    }
  };

  const updateUserRole = async (id: string, role: string) => {
    try {
      await axios.patch(`/api/admin/users/${id}`, { role }, { headers: { Authorization: `Bearer ${token}` } });
      fetchData();
    } catch (err) {
      alert("Failed to update role");
    }
  };

  const updateUserPlan = async (id: string, planId: string) => {
    try {
      await axios.patch(`/api/admin/users/${id}`, { planId }, { headers: { Authorization: `Bearer ${token}` } });
      fetchData();
    } catch (err) {
      alert("Failed to update plan");
    }
  };

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await axios.post(
        "/api/admin/users",
        { email: newUserEmail, password: newUserPassword, role: newUserRole },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setShowCreateUser(false);
      setNewUserEmail("");
      setNewUserPassword("");
      fetchData();
    } catch (err: any) {
      alert(err.response?.data?.detail || "Failed to create user");
    }
  };

  const toggleModel = async (id: string, current: boolean) => {
    try {
      await axios.patch(`/api/admin/models/${encodeURIComponent(id)}`, { enabled: !current }, { headers: { Authorization: `Bearer ${token}` } });
      fetchData();
    } catch (err) {
      alert("Failed to update model");
    }
  };

  const toggleProvider = async (id: string, current: boolean) => {
    try {
      await axios.patch(`/api/admin/providers/${id}`, { enabled: !current }, { headers: { Authorization: `Bearer ${token}` } });
      fetchData();
    } catch (err) {
      alert("Failed to update provider");
    }
  };

  const handleCreateModel = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newModelId.trim()) return;
    try {
      await axios.post(
        "/api/admin/models",
        { id: newModelId.trim(), provider: newModelProvider, enabled: true },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setNewModelId("");
      fetchData();
    } catch (err: any) {
      alert(err.response?.data?.detail || "Failed to add model");
    }
  };

  const updatePlanField = (planId: string, field: string, value: any) => {
    setPlans((prev) =>
      prev.map((plan) => (plan.id === planId ? { ...plan, [field]: value } : plan))
    );
  };

  const savePlan = async (plan: any) => {
    try {
      await axios.patch(
        `/api/admin/plans/${plan.id}`,
        {
          name: plan.name,
          description: plan.description,
          provider: plan.provider,
          model: plan.model,
          limitStrategy: String(plan.limitStrategy || "monthly"),
          dailyTokenLimit: Number(plan.dailyTokenLimit || 0),
          totalTokenLimit: Number(plan.totalTokenLimit || 0),
          monthlyPriceCents: Number(plan.monthlyPriceCents || 0),
          monthlyRequestLimit: Number(plan.monthlyRequestLimit || 0),
          inputTokenPricePerMillion: Number(plan.inputTokenPricePerMillion || 0),
          outputTokenPricePerMillion: Number(plan.outputTokenPricePerMillion || 0),
          stripePriceId: plan.stripePriceId || "",
          active: Boolean(plan.active),
          sortOrder: Number(plan.sortOrder || 0),
          apiKey: (planApiKeys[plan.id] || "").trim() || undefined,
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setPlanApiKeys((prev) => ({ ...prev, [plan.id]: "" }));
      fetchData();
    } catch (err: any) {
      alert(err.response?.data?.detail || "Failed to save plan");
    }
  };

  const sidebarContent = (
    <div style={{ padding: "24px 16px", display: "flex", flexDirection: "column", gap: 4 }}>
      {isSidebarVisible && (
        <div style={{ fontSize: 11, fontWeight: 700, color: "var(--color-sidebar-muted)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 12, paddingLeft: 12 }}>
          System Control
        </div>
      )}
      <TabBtn active={tab === "metrics"} onClick={() => setTab("metrics")} icon={<Activity size={18} />} label={isSidebarVisible ? "Overview & Stats" : ""} />
      <TabBtn active={tab === "users"} onClick={() => setTab("users")} icon={<Users size={18} />} label={isSidebarVisible ? "User Management" : ""} />
      <TabBtn active={tab === "providers"} onClick={() => setTab("providers")} icon={<Zap size={18} />} label={isSidebarVisible ? "LLM Providers" : ""} />
      <TabBtn active={tab === "models"} onClick={() => setTab("models")} icon={<Settings size={18} />} label={isSidebarVisible ? "Model Registry" : ""} />
      <TabBtn active={tab === "plans"} onClick={() => setTab("plans")} icon={<Rocket size={18} />} label={isSidebarVisible ? "Plans & Billing" : ""} />
      <TabBtn active={tab === "logs"} onClick={() => setTab("logs")} icon={<Database size={18} />} label={isSidebarVisible ? "Audit Logs" : ""} />
    </div>
  );

  return (
    <AppLayout
      isSidebarVisible={isSidebarVisible}
      setIsSidebarVisible={setIsSidebarVisible}
      sidebarContent={sidebarContent}
    >
      <main style={{ flex: 1, padding: "40px clamp(20px, 5%, 80px)", overflowY: "auto" }}>
        {loading ? (
          <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100%" }}>
            <Loader2 className="animate-spin" size={32} color="var(--color-accent)" />
          </div>
        ) : error ? (
          <div className="glass" style={{ padding: 24, borderRadius: "var(--radius-lg)", color: "var(--color-error)" }}>
            {error}
          </div>
        ) : (
          <div key={tab} className="animate-fadeIn">
            {tab === "metrics" && metrics && (
              <div>
                <h2 style={{ fontSize: 24, fontWeight: 800, marginBottom: 32, letterSpacing: "-0.02em" }}>
                  Platform Metrics
                </h2>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                    gap: 20,
                  }}
                >
                  <StatCard title="Total Users" value={metrics.users.total} />
                  <StatCard title="Active Adms" value={metrics.users.admins} color="var(--color-accent)" />
                  {Object.entries(metrics.subscriptions || {}).map(([plan, count]) => (
                    <StatCard key={plan} title={`${plan.toUpperCase()} Plan`} value={count} color="var(--color-success)" />
                  ))}
                  <StatCard title="Global API Keys" value={metrics.api_keys.total} />
                  <StatCard title="Error Rate" value={metrics.logs.errors} color="var(--color-error)" />
                </div>
                <div style={{ marginTop: 32 }} className="glass">
                  <div
                    style={{
                      padding: 20,
                      borderBottom: "1px solid var(--color-border)",
                      fontWeight: 700,
                    }}
                  >
                    System Health
                  </div>
                  <div style={{ padding: 20, color: "var(--color-text-muted)", fontSize: 14 }}>
                    All systems operational. Backend heartbeat: 100%. User Listing:{" "}
                    {metrics.users.total > 0 ? "Verified" : "No users yet"}.
                  </div>
                </div>
              </div>
            )}

            {tab === "users" && (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 32 }}>
                  <h2 style={{ fontSize: 24, fontWeight: 800, margin: 0, letterSpacing: "-0.02em" }}>
                    User Management
                  </h2>
                  <button
                    onClick={() => setShowCreateUser(true)}
                    className="btn btn-primary"
                    style={{ gap: 8, padding: "10px 20px" }}
                  >
                    <Plus size={18} /> New Account
                  </button>
                </div>

                {showCreateUser && (
                  <div className="glass shadow-xl animate-scaleIn" style={{ padding: 24, borderRadius: 24, marginBottom: 32, border: "1px solid var(--color-accent-muted)" }}>
                    <form onSubmit={handleCreateUser} style={{ display: "grid", gridTemplateColumns: "1fr 1fr 120px 140px", gap: 16, alignItems: "end" }}>
                      <div>
                        <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", display: "block", marginBottom: 8 }}>Email</label>
                        <input className="input-field" value={newUserEmail} onChange={e => setNewUserEmail(e.target.value)} placeholder="email@wagi.ai" required />
                      </div>
                      <div>
                        <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", display: "block", marginBottom: 8 }}>Password</label>
                        <input className="input-field" type="password" value={newUserPassword} onChange={e => setNewUserPassword(e.target.value)} required />
                      </div>
                      <div>
                        <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", display: "block", marginBottom: 8 }}>Role</label>
                        <select className="input-field" value={newUserRole} onChange={e => setNewUserRole(e.target.value)}>
                          <option value="USER">USER</option>
                          <option value="ADMIN">ADMIN</option>
                        </select>
                      </div>
                      <div style={{ display: "flex", gap: 8 }}>
                        <button type="submit" className="btn btn-primary" style={{ flex: 1 }}>Create</button>
                        <button type="button" onClick={() => setShowCreateUser(false)} className="btn btn-ghost" style={{ padding: 10 }}>Cancel</button>
                      </div>
                    </form>
                  </div>
                )}

                <div className="glass" style={{ borderRadius: "var(--radius-xl)", overflow: "hidden" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ background: "var(--color-surface2)", borderBottom: "1px solid var(--color-border)" }}>
                        <th style={{ padding: "16px 24px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase" }}>User Identity</th>
                        <th style={{ padding: "16px 24px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase" }}>Role</th>
                        <th style={{ padding: "16px 24px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase" }}>Active Plan</th>
                        <th style={{ padding: "16px 24px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase" }}>Status</th>
                        <th style={{ padding: "16px 24px", textAlign: "right", fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase" }}>Management</th>
                      </tr>
                    </thead>
                    <tbody>
                      {users.map((u) => (
                        <tr key={u.id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                          <td style={{ padding: "16px 24px" }}>
                            <div style={{ fontWeight: 600 }}>{u.email}</div>
                            <div style={{ fontSize: 11, color: "var(--color-text-muted2)" }}>{u.id}</div>
                          </td>
                          <td style={{ padding: "16px 24px" }}>
                            <select
                              value={u.role}
                              onChange={(e) => updateUserRole(u.id, e.target.value)}
                              style={{
                                background: u.role === 'ADMIN' ? 'var(--color-accent-muted)' : 'var(--color-surface2)',
                                border: '1px solid var(--color-border)',
                                borderRadius: 8,
                                fontSize: 11,
                                fontWeight: 700,
                                padding: '4px 8px',
                                color: u.role === 'ADMIN' ? 'var(--color-accent)' : 'inherit',
                                cursor: 'pointer'
                              }}
                            >
                              <option value="USER">USER</option>
                              <option value="ADMIN">ADMIN</option>
                            </select>
                          </td>
                          <td style={{ padding: "16px 24px" }}>
                            <select
                              value={u.planId || "free"}
                              onChange={(e) => updateUserPlan(u.id, e.target.value)}
                              style={{
                                background: 'var(--color-surface2)',
                                border: '1px solid var(--color-border)',
                                borderRadius: 8,
                                fontSize: 11,
                                fontWeight: 600,
                                padding: '4px 8px',
                                cursor: 'pointer'
                              }}
                            >
                              <option value="free">Free</option>
                              <option value="plus">Plus (15$)</option>
                              <option value="pro">Pro (30$)</option>
                            </select>
                          </td>
                          <td style={{ padding: "16px 24px" }}>
                            <span style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 6,
                              color: u.isActive ? "var(--color-success)" : "var(--color-error)",
                              fontSize: 12,
                              fontWeight: 600
                            }}>
                              <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor' }} />
                              {u.isActive ? "Active" : "Suspended"}
                            </span>
                          </td>
                          <td style={{ padding: "16px 24px", textAlign: "right" }}>
                            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                              <button
                                onClick={() => toggleUserActive(u.id, u.isActive)}
                                className="btn btn-ghost"
                                style={{
                                  padding: "6px 12px",
                                  fontSize: 12,
                                  borderRadius: 10,
                                  color: u.isActive ? "var(--color-error)" : "var(--color-success)"
                                }}
                              >
                                {u.isActive ? "Suspend" : "Activate"}
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {tab === "providers" && (
              <div>
                <h2 style={{ fontSize: 24, fontWeight: 800, marginBottom: 32 }}>LLM Providers</h2>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                    gap: 16,
                  }}
                >
                  {providers.map((p) => (
                    <div
                      key={p.id}
                      className="glass"
                      style={{
                        padding: 24,
                        borderRadius: "var(--radius-xl)",
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 700, textTransform: "uppercase", fontSize: 14 }}>{p.id}</div>
                        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Global API Integration</div>
                      </div>
                      <button
                        onClick={() => toggleProvider(p.id, p.enabled)}
                        style={{
                          background: p.enabled ? "var(--color-success)" : "var(--color-surface2)",
                          border: "none",
                          color: p.enabled ? "#fff" : "var(--color-text)",
                          padding: "8px 16px",
                          borderRadius: "var(--radius-full)",
                          fontSize: 11,
                          fontWeight: 700,
                          cursor: "pointer",
                        }}
                      >
                        {p.enabled ? "ENABLED" : "DISABLED"}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {tab === "models" && (
              <div>
                <h2 style={{ fontSize: 24, fontWeight: 800, marginBottom: 32 }}>Model Registry</h2>
                <form
                  onSubmit={handleCreateModel}
                  className="glass"
                  style={{
                    padding: 20,
                    borderRadius: "var(--radius-xl)",
                    display: "flex",
                    gap: 12,
                    alignItems: "end",
                    marginBottom: 20,
                  }}
                >
                  <div style={{ flex: 1 }}>
                    <div
                      style={{
                        fontSize: 11,
                        fontWeight: 700,
                        textTransform: "uppercase",
                        color: "var(--color-text-muted)",
                        marginBottom: 8,
                      }}
                    >
                      New Model ID
                    </div>
                    <input
                      value={newModelId}
                      onChange={(e) => setNewModelId(e.target.value)}
                      placeholder="e.g. llama-4-scout"
                      className="input-field"
                    />
                  </div>
                  <div style={{ minWidth: 160 }}>
                    <div
                      style={{
                        fontSize: 11,
                        fontWeight: 700,
                        textTransform: "uppercase",
                        color: "var(--color-text-muted)",
                        marginBottom: 8,
                      }}
                    >
                      Provider
                    </div>
                    <select
                      value={newModelProvider}
                      onChange={(e) => setNewModelProvider(e.target.value)}
                      className="input-field"
                      style={{ minWidth: 140 }}
                    >
                      {providers
                        .filter((p) => p.id !== "auto")
                        .map((provider) => (
                          <option key={provider.id} value={provider.id}>
                            {provider.name || provider.id}
                          </option>
                        ))}
                    </select>
                  </div>
                  <button type="submit" className="btn-primary" style={{ padding: "12px 20px" }}>
                    Add Model
                  </button>
                </form>
                <div className="glass" style={{ borderRadius: "var(--radius-xl)", overflow: "hidden" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ background: "var(--color-surface2)", borderBottom: "1px solid var(--color-border)" }}>
                        <th
                          style={{
                            padding: "16px 24px",
                            textAlign: "left",
                            fontSize: 11,
                            fontWeight: 700,
                            textTransform: "uppercase",
                          }}
                        >
                          Model ID
                        </th>
                        <th
                          style={{
                            padding: "16px 24px",
                            textAlign: "left",
                            fontSize: 11,
                            fontWeight: 700,
                            textTransform: "uppercase",
                          }}
                        >
                          Provider
                        </th>
                        <th
                          style={{
                            padding: "16px 24px",
                            textAlign: "right",
                            fontSize: 11,
                            fontWeight: 700,
                            textTransform: "uppercase",
                          }}
                        >
                          Visibility
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {models.map((m) => (
                        <tr key={m.id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                          <td style={{ padding: "16px 24px", fontWeight: 600, fontSize: 14 }}>{m.modelId || m.id}</td>
                          <td style={{ padding: "16px 24px", fontSize: 13, color: "var(--color-text-muted)" }}>{m.provider}</td>
                          <td style={{ padding: "16px 24px", textAlign: "right" }}>
                            <button
                              onClick={() => toggleModel(m.id, m.enabled)}
                              style={{
                                background: m.enabled ? "var(--color-success)" : "var(--color-error)",
                                border: "none",
                                color: "#fff",
                                padding: "6px 12px",
                                borderRadius: "var(--radius-md)",
                                fontSize: 12,
                                fontWeight: 600,
                                cursor: "pointer",
                              }}
                            >
                              {m.enabled ? "Public" : "Hidden"}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {tab === "plans" && (
              <div>
                <h2 style={{ fontSize: 24, fontWeight: 800, marginBottom: 20 }}>Subscription Plans</h2>
                <p style={{ color: "var(--color-text-muted)", marginBottom: 24, fontSize: 14 }}>
                  Configure plan model mapping, usage strategy/limits, Stripe price ID, and plan-level API keys.
                </p>

                <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                  {plans.map((plan) => {
                    const providerModels = models.filter((model) => model.provider === plan.provider);
                    const apiKeyConfigured = Boolean(plan.apiKeyConfigured);
                    return (
                      <div key={plan.id} className="glass" style={{ padding: 20, borderRadius: "var(--radius-xl)" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                          <div style={{ fontWeight: 800, fontSize: 18, textTransform: "uppercase" }}>{plan.id}</div>
                          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--color-text-muted)" }}>
                            <input
                              type="checkbox"
                              checked={Boolean(plan.active)}
                              onChange={(e) => updatePlanField(plan.id, "active", e.target.checked)}
                            />
                            Active
                          </label>
                        </div>

                        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 12 }}>
                          <input
                            className="input-field"
                            value={plan.name || ""}
                            onChange={(e) => updatePlanField(plan.id, "name", e.target.value)}
                            placeholder="Plan name"
                          />
                          <input
                            className="input-field"
                            value={plan.description || ""}
                            onChange={(e) => updatePlanField(plan.id, "description", e.target.value)}
                            placeholder="Description"
                          />
                          <select
                            className="input-field"
                            value={plan.provider}
                            onChange={(e) => {
                              const providerId = e.target.value;
                              const nextModel = models.find((model) => model.provider === providerId)?.modelId || "";
                              updatePlanField(plan.id, "provider", providerId);
                              if (nextModel) {
                                updatePlanField(plan.id, "model", nextModel);
                              }
                            }}
                          >
                            {providers.filter((provider) => provider.id !== "auto").map((provider) => (
                              <option key={provider.id} value={provider.id}>{provider.id}</option>
                            ))}
                          </select>
                          <select
                            className="input-field"
                            value={plan.model}
                            onChange={(e) => updatePlanField(plan.id, "model", e.target.value)}
                          >
                            {providerModels.map((model) => (
                              <option key={model.id} value={model.modelId}>{model.modelId}</option>
                            ))}
                          </select>
                          <select
                            className="input-field"
                            value={plan.limitStrategy || "monthly"}
                            onChange={(e) => updatePlanField(plan.id, "limitStrategy", e.target.value)}
                          >
                            <option value="daily">Daily token limit (resets each day)</option>
                            <option value="total">Total token bucket (no time reset)</option>
                            <option value="monthly">Monthly request limit</option>
                          </select>
                          {(plan.limitStrategy || "monthly") === "daily" ? (
                            <input
                              className="input-field"
                              type="number"
                              value={plan.dailyTokenLimit || 0}
                              onChange={(e) => updatePlanField(plan.id, "dailyTokenLimit", Number(e.target.value || 0))}
                              placeholder="Daily token limit"
                            />
                          ) : (
                            <input
                              className="input-field"
                              type="number"
                              value={plan.totalTokenLimit || 0}
                              onChange={(e) => updatePlanField(plan.id, "totalTokenLimit", Number(e.target.value || 0))}
                              placeholder="Total token limit"
                            />
                          )}
                          <input
                            className="input-field"
                            type="number"
                            value={plan.monthlyPriceCents}
                            onChange={(e) => updatePlanField(plan.id, "monthlyPriceCents", Number(e.target.value || 0))}
                            placeholder="Monthly price (cents)"
                          />
                          <input
                            className="input-field"
                            type="number"
                            value={plan.monthlyRequestLimit}
                            onChange={(e) => updatePlanField(plan.id, "monthlyRequestLimit", Number(e.target.value || 0))}
                            placeholder="Monthly request limit"
                          />
                          <input
                            className="input-field"
                            type="number"
                            step="0.0001"
                            value={plan.inputTokenPricePerMillion}
                            onChange={(e) => updatePlanField(plan.id, "inputTokenPricePerMillion", Number(e.target.value || 0))}
                            placeholder="Input token price / 1M"
                          />
                          <input
                            className="input-field"
                            type="number"
                            step="0.0001"
                            value={plan.outputTokenPricePerMillion}
                            onChange={(e) => updatePlanField(plan.id, "outputTokenPricePerMillion", Number(e.target.value || 0))}
                            placeholder="Output token price / 1M"
                          />
                          <input
                            className="input-field"
                            value={plan.stripePriceId || ""}
                            onChange={(e) => updatePlanField(plan.id, "stripePriceId", e.target.value)}
                            placeholder="Stripe price ID (price_...)"
                          />
                          <input
                            className="input-field"
                            type="password"
                            value={planApiKeys[plan.id] || ""}
                            onChange={(e) => setPlanApiKeys((prev) => ({ ...prev, [plan.id]: e.target.value }))}
                            placeholder={apiKeyConfigured ? "API key configured (enter to replace)" : "Plan API key"}
                          />
                        </div>

                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 14 }}>
                          <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                            Provider model for this plan will be enforced in Builder.
                          </span>
                          <button className="btn-primary" style={{ padding: "10px 16px" }} onClick={() => savePlan(plan)}>
                            Save Plan
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {tab === "logs" && (
              <div>
                <h2 style={{ fontSize: 24, fontWeight: 800, marginBottom: 32 }}>Audit Logs</h2>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {logs.map((log) => (
                    <div
                      key={log.id}
                      className="glass"
                      style={{
                        padding: 16,
                        borderRadius: "var(--radius-lg)",
                        display: "flex",
                        gap: 20,
                        alignItems: "center",
                      }}
                    >
                      <div style={{ fontSize: 12, color: "var(--color-text-muted2)", width: 160 }}>
                        {new Date(log.created_at).toLocaleString()}
                      </div>
                      <div style={{ fontSize: 13, fontWeight: 700, minWidth: 140 }}>{log.event}</div>
                      <div style={{ fontSize: 13, color: "var(--color-text-muted)", flex: 1 }}>{log.detail}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </main>
    </AppLayout>
  );
}

function TabBtn({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  const isCollapsed = !label;
  return (
    <button
      onClick={onClick}
      style={{
        width: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: isCollapsed ? "center" : "flex-start",
        gap: isCollapsed ? 0 : 12,
        padding: isCollapsed ? "10px 0" : "10px 14px",
        background: active ? "var(--color-accent-muted)" : "transparent",
        color: active ? "var(--color-accent)" : "var(--color-sidebar-text)",
        border: "none",
        borderRadius: "var(--radius-md)",
        cursor: "pointer",
        fontWeight: active ? 700 : 500,
        fontSize: 13,
        transition: "all var(--transition)",
        textAlign: isCollapsed ? "center" : "left",
      }}
    >
      <div style={{ opacity: active ? 1 : 0.6, display: "flex", alignItems: "center", justifyContent: "center" }}>{icon}</div>
      {label}
    </button>
  );
}

function StatCard({ title, value, color }: { title: string; value: any; color?: string }) {
  return (
    <div
      className="glass"
      style={{
        padding: 28,
        borderRadius: "var(--radius-xl)",
        borderBottom: `3px solid ${color || "var(--color-border)"}`,
      }}
    >
      <div
        style={{
          fontSize: 11,
          color: "var(--color-text-muted2)",
          fontWeight: 700,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          marginBottom: 12,
        }}
      >
        {title}
      </div>
      <div style={{ fontSize: 36, fontWeight: 800, color: color || "var(--color-text)", letterSpacing: "-0.04em" }}>
        {value}
      </div>
    </div>
  );
}
