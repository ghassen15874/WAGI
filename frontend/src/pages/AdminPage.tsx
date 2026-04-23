import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Rocket, Users, Activity, Database, Loader2, LogOut, Zap, Sun, Moon, Settings } from "lucide-react";
import axios from "axios";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../hooks/useTheme";

export default function AdminPage() {
  const { user, token, logout } = useAuth();
  const [tab, setTab] = useState<"users" | "metrics" | "logs" | "models" | "providers">("metrics");
  const [metrics, setMetrics] = useState<any>(null);
  const [users, setUsers] = useState<any[]>([]);
  const [logs, setLogs] = useState<any[]>([]);
  const [models, setModels] = useState<any[]>([]);
  const [providers, setProviders] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [newModelId, setNewModelId] = useState("");
  const [newModelProvider, setNewModelProvider] = useState("groq");
  const { theme, toggleTheme } = useTheme();

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
      } else if (tab === "models") {
        const [modelsRes, providersRes] = await Promise.all([axios.get("/api/admin/models", config), axios.get("/api/admin/providers", config)]);
        setModels(modelsRes.data.models);
        setProviders(providersRes.data.providers);
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
            <Rocket size={16} />
          </div>
          WAGI <span style={{ fontWeight: 400, color: "var(--color-accent)" }}>| Admin Console</span>
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
          <Link to="/dashboard" style={{ fontSize: 13, color: "var(--color-accent)", textDecoration: "none" }}>
            User Dashboard
          </Link>
          <button
            onClick={logout}
            className="btn btn-text"
            style={{ color: "var(--color-error)", gap: 6, fontSize: 13 }}
          >
            <LogOut size={14} /> Logout
          </button>
        </div>
      </nav>

      <div style={{ display: "flex", minHeight: "calc(100vh - 65px)" }}>
        {/* Sidebar */}
        <div
          style={{
            width: 260,
            background: "var(--color-surface)",
            borderRight: "1px solid var(--color-border)",
            padding: "24px 16px",
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: "var(--color-text-muted2)",
              textTransform: "uppercase",
              letterSpacing: "0.1em",
              marginBottom: 16,
              paddingLeft: 12,
            }}
          >
            System Control
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <TabBtn active={tab === "metrics"} onClick={() => setTab("metrics")} icon={<Activity size={18} />} label="Overview & Stats" />
            <TabBtn active={tab === "users"} onClick={() => setTab("users")} icon={<Users size={18} />} label="User Accounts" />
            <TabBtn active={tab === "providers"} onClick={() => setTab("providers")} icon={<Zap size={18} />} label="Providers" />
            <TabBtn active={tab === "models"} onClick={() => setTab("models")} icon={<Settings size={18} />} label="Model Registry" />
            <TabBtn active={tab === "logs"} onClick={() => setTab("logs")} icon={<Database size={18} />} label="Audit Logs" />
          </div>
        </div>

        {/* Content Area */}
        <main style={{ flex: 1, padding: 40, overflowY: "auto" }}>
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
                      gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                      gap: 20,
                    }}
                  >
                    <StatCard title="Total Users" value={metrics.users.total} />
                    <StatCard title="Active Seats" value={metrics.users.active} color="var(--color-success)" />
                    <StatCard title="Global API Keys" value={metrics.api_keys.total} />
                    <StatCard title="Error Rate (Logs)" value={metrics.logs.errors} color="var(--color-error)" />
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
                <div>
                  <h2 style={{ fontSize: 24, fontWeight: 800, marginBottom: 32, letterSpacing: "-0.02em" }}>
                    User Management
                  </h2>
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
                              color: "var(--color-text-muted)",
                              textTransform: "uppercase",
                            }}
                          >
                            User Identity
                          </th>
                          <th
                            style={{
                              padding: "16px 24px",
                              textAlign: "left",
                              fontSize: 11,
                              fontWeight: 700,
                              color: "var(--color-text-muted)",
                              textTransform: "uppercase",
                            }}
                          >
                            Permissions
                          </th>
                          <th
                            style={{
                              padding: "16px 24px",
                              textAlign: "left",
                              fontSize: 11,
                              fontWeight: 700,
                              color: "var(--color-text-muted)",
                              textTransform: "uppercase",
                            }}
                          >
                            Lifecycle
                          </th>
                          <th
                            style={{
                              padding: "16px 24px",
                              textAlign: "right",
                              fontSize: 11,
                              fontWeight: 700,
                              color: "var(--color-text-muted)",
                              textTransform: "uppercase",
                            }}
                          >
                            Management
                          </th>
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
                              <span
                                style={{
                                  fontSize: 11,
                                  fontWeight: 700,
                                  padding: "4px 10px",
                                  borderRadius: "var(--radius-full)",
                                  background: "var(--color-surface2)",
                                }}
                              >
                                {u.role}
                              </span>
                            </td>
                            <td style={{ padding: "16px 24px" }}>
                              <span style={{ color: u.isActive ? "var(--color-success)" : "var(--color-error)", fontSize: 13 }}>
                                {u.isActive ? "Active" : "Suspended"}
                              </span>
                            </td>
                            <td style={{ padding: "16px 24px", textAlign: "right" }}>
                              <button
                                onClick={() => toggleUserActive(u.id, u.isActive)}
                                style={{
                                  background: "var(--color-surface2)",
                                  border: "none",
                                  color: "var(--color-text)",
                                  padding: "8px 14px",
                                  borderRadius: "var(--radius-md)",
                                  cursor: "pointer",
                                  fontSize: 12,
                                  fontWeight: 500,
                                }}
                              >
                                {u.isActive ? "Suspend" : "Activate"}
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
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
      </div>
    </div>
  );
}

function TabBtn({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button
      onClick={onClick}
      style={{
        width: "100%",
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "12px 16px",
        background: active ? "var(--color-surface2)" : "transparent",
        color: active ? "var(--color-text)" : "var(--color-text-muted)",
        border: "none",
        borderRadius: "var(--radius-md)",
        cursor: "pointer",
        fontWeight: active ? 600 : 500,
        fontSize: 14,
        transition: "all var(--transition)",
        textAlign: "left",
      }}
    >
      {icon} {label}
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