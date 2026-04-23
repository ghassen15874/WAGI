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
      const [keysRes, pipeRes] = await Promise.all([
        axios.get("/api/users/api-keys", { headers: { Authorization: `Bearer ${token}` } }),
        axios.get("/api/users/pipeline", { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      setKeys(keysRes.data.keys);
      setPipeline(pipeRes.data);
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
            <Rocket size={16} />
          </div>
          WAGI <span style={{ fontWeight: 400, color: "var(--color-text-muted)" }}>| Dashboard</span>
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

      <main style={{ padding: 40, maxWidth: 1100, margin: "0 auto", display: "grid", gap: 24, gridTemplateColumns: "1fr 1fr" }}>
        {/* GitHub Deployment Card */}
        <div
          className="glass"
          style={{
            padding: 24,
            borderRadius: "var(--radius-xl)",
            gridColumn: "1 / -1",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ fontSize: 18, fontWeight: 700 }}>GitHub Deployment</div>
            {repoUrl ? (
              <>
                <div style={{ fontSize: 13, color: "var(--color-success)" }}>✅ Project deployed to GitHub</div>
                <a
                  href={repoUrl}
                  target="_blank"
                  rel="noreferrer"
                  style={{ fontSize: 13, color: "var(--color-accent)", textDecoration: "none" }}
                >
                  {repoUrl}
                </a>
              </>
            ) : githubError ? (
              <div style={{ fontSize: 13, color: "var(--color-error)" }}>{githubError}</div>
            ) : user?.githubConnected ? (
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                Connected as {user.githubUsername || "GitHub user"}.
              </div>
            ) : (
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                Connect GitHub to create a repository and deploy your latest project.
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={handleConnectGithubDeploy}
            disabled={githubDeploying}
            className="btn-primary"
            style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 20px" }}
          >
            {githubDeploying ? <Loader2 size={16} className="animate-spin" /> : <Github size={16} />}
            Connect GitHub & Deploy
          </button>
        </div>

        {/* API Keys Card */}
        <div className="glass" style={{ padding: 24, borderRadius: "var(--radius-xl)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
            <div
              style={{
                width: 40,
                height: 40,
                borderRadius: "var(--radius-md)",
                background: "var(--color-accent-muted)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Key size={18} color="var(--color-accent)" />
            </div>
            <h2 style={{ fontSize: 18, fontWeight: 700 }}>API Keys (BYOK)</h2>
          </div>

          <form onSubmit={handleAddKey} style={{ display: "flex", gap: 8, marginBottom: 20 }}>
            <select
              value={newKeyProvider}
              onChange={(e) => setNewKeyProvider(e.target.value)}
              style={{
                padding: "10px 12px",
                borderRadius: "var(--radius-md)",
                background: "var(--color-surface2)",
                border: "1px solid var(--color-border)",
                color: "var(--color-text)",
                outline: "none",
                minWidth: 100,
              }}
            >
              {availableProviders.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name}
                </option>
              ))}
            </select>
            <input
              required
              type="text"
              placeholder="api_key..."
              value={newKeyValue}
              onChange={(e) => setNewKeyValue(e.target.value)}
              style={{
                flex: 1,
                padding: "10px 12px",
                borderRadius: "var(--radius-md)",
                background: "var(--color-surface2)",
                border: "1px solid var(--color-border)",
                color: "var(--color-text)",
                outline: "none",
              }}
            />
            <button
              type="submit"
              style={{
                padding: "10px 14px",
                borderRadius: "var(--radius-md)",
                background: "var(--gradient-accent)",
                color: "#fff",
                border: "none",
                cursor: "pointer",
              }}
            >
              <Plus size={16} />
            </button>
          </form>

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {keys.length === 0 && (
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>No keys added yet. Add one above.</div>
            )}
            {keys.map((k, index) => (
              <div
                key={k.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "14px 16px",
                  background: "var(--color-surface2)",
                  borderRadius: "var(--radius-md)",
                  border: "1px solid var(--color-border)",
                }}
              >
                <div>
                  <div style={{ fontWeight: 600, fontSize: 13, textTransform: "capitalize" }}>
                    {k.provider}
                    <span style={{ marginLeft: 8, fontSize: 11, color: "var(--color-text-muted2)" }}>#{index + 1}</span>
                  </div>
                  {k.label ? <div style={{ fontSize: 12, color: "var(--color-text)" }}>{k.label}</div> : null}
                  <div style={{ fontSize: 11, color: "var(--color-text-muted2)" }}>
                    Added {new Date(k.created_at).toLocaleDateString()}
                  </div>
                </div>
                <button
                  onClick={() => handleDeleteKey(k.id)}
                  style={{ background: "transparent", border: "none", color: "var(--color-error)", cursor: "pointer" }}
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Pipeline Config Card */}
        <div className="glass" style={{ padding: 24, borderRadius: "var(--radius-xl)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
            <div
              style={{
                width: 40,
                height: 40,
                borderRadius: "var(--radius-md)",
                background: "var(--color-accent-muted)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Settings size={18} color="var(--color-accent)" />
            </div>
            <h2 style={{ fontSize: 18, fontWeight: 700 }}>Pipeline Configuration</h2>
          </div>
          {pipeline && (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <Toggle label="Clear Sandbox Before Build" checked={pipeline.clearSandboxEnabled} onChange={() => togglePipeline("clearSandboxEnabled")} />
              <Toggle label="Generate Design System" checked={pipeline.designSystemEnabled} onChange={() => togglePipeline("designSystemEnabled")} />
              <Toggle label="Write .lovable/spec.md" checked={pipeline.specEnabled} onChange={() => togglePipeline("specEnabled")} />
              <Toggle label="Build System Prompt" checked={pipeline.systemPromptEnabled} onChange={() => togglePipeline("systemPromptEnabled")} />
              <div style={{ height: 1, background: "var(--color-border)", margin: "8px 0" }} />
              <Toggle label="Generate Work Plan (Planner Phase)" checked={pipeline.plannerEnabled} onChange={() => togglePipeline("plannerEnabled")} />
              <Toggle label="Generate Code (Builder Phase)" checked={pipeline.builderEnabled} onChange={() => togglePipeline("builderEnabled")} />
              <div style={{ height: 1, background: "var(--color-border)", margin: "8px 0" }} />
              <Toggle label="Auto Install NPM Dependencies" checked={pipeline.autoInstallEnabled} onChange={() => togglePipeline("autoInstallEnabled")} />
              <Toggle label="Project Build Check (Vite)" checked={pipeline.projectBuildEnabled} onChange={() => togglePipeline("projectBuildEnabled")} />
              <Toggle label="Integration Tests (npm test)" checked={pipeline.integrationTestEnabled} onChange={() => togglePipeline("integrationTestEnabled")} />
              <div style={{ height: 1, background: "var(--color-border)", margin: "8px 0" }} />
              <Toggle label="Code Linter Validation" checked={pipeline.linterEnabled} onChange={() => togglePipeline("linterEnabled")} />
              <Toggle label="Backend Runtime Service (Port 3001)" checked={pipeline.runtimeEnabled} onChange={() => togglePipeline("runtimeEnabled")} />
              <Toggle label="Feature & UI Validator (Playwright)" checked={pipeline.featureValidatorEnabled} onChange={() => togglePipeline("featureValidatorEnabled")} />
              <div style={{ height: 1, background: "var(--color-border)", margin: "8px 0" }} />
              <Toggle label="Self-Healing Correction Loop" checked={pipeline.selfHealingEnabled} onChange={() => togglePipeline("selfHealingEnabled")} />
              <Toggle label="Save Project Summary (.lovable/summary.md)" checked={pipeline.summaryEnabled} onChange={() => togglePipeline("summaryEnabled")} />
              <Toggle label="Active Memory (Context)" checked={pipeline.activeMemoryEnabled} onChange={() => togglePipeline("activeMemoryEnabled")} />
              <div style={{ height: 1, background: "var(--color-border)", margin: "8px 0" }} />
              <Toggle label="Use Same Model Sequence For All Stages" checked={pipeline.useSharedModels} onChange={() => updatePipeline({ useSharedModels: !pipeline.useSharedModels })} />

              {pipeline.useSharedModels ? (
                <MultiModelPicker
                  label="Shared model sequence"
                  hint="The builder will try these provider/model pairs in order until one succeeds."
                  value={pipeline.sharedModels || []}
                  options={modelOptions}
                  onChange={(models) => updatePipeline({ sharedModels: models })}
                />
              ) : (
                <div style={{ display: "grid", gap: 12 }}>
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

              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12 }}>
                <span style={{ fontSize: 13, fontWeight: 500 }}>Max AI Iterations</span>
                <input
                  type="number"
                  min="1"
                  max="150"
                  value={pipeline.maxIter}
                  onChange={(e) => updatePipeline({ maxIter: parseInt(e.target.value) || 1 })}
                  style={{
                    width: 70,
                    padding: "6px 10px",
                    borderRadius: "var(--radius-sm)",
                    background: "var(--color-surface2)",
                    border: "1px solid var(--color-border)",
                    color: "var(--color-text)",
                    outline: "none",
                    textAlign: "center",
                  }}
                />
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 13, fontWeight: 500 }}>Max Healing Attempts</span>
                <input
                  type="number"
                  min="1"
                  max="50"
                  value={pipeline.maxHealingAttempts}
                  onChange={(e) => updatePipeline({ maxHealingAttempts: parseInt(e.target.value) || 1 })}
                  style={{
                    width: 70,
                    padding: "6px 10px",
                    borderRadius: "var(--radius-sm)",
                    background: "var(--color-surface2)",
                    border: "1px solid var(--color-border)",
                    color: "var(--color-text)",
                    outline: "none",
                    textAlign: "center",
                  }}
                />
              </div>
            </div>
          )}
        </div>

        {/* Profile Settings Card */}
        <div className="glass" style={{ padding: 24, borderRadius: "var(--radius-xl)", gridColumn: "1 / -1" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
            <div
              style={{
                width: 40,
                height: 40,
                borderRadius: "var(--radius-md)",
                background: "var(--color-accent-muted)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <User size={18} color="var(--color-accent)" />
            </div>
            <h2 style={{ fontSize: 18, fontWeight: 700 }}>Profile Settings</h2>
          </div>
          <form onSubmit={handleUpdateProfile} style={{ display: "flex", gap: 16, maxWidth: 400 }}>
            <div style={{ flex: 1 }}>
              <label
                style={{
                  display: "block",
                  fontSize: 12,
                  fontWeight: 600,
                  color: "var(--color-text-muted)",
                  marginBottom: 8,
                }}
              >
                New Password
              </label>
              <input
                required
                type="password"
                placeholder="Min 6 characters..."
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="input-field"
                style={{ background: "var(--color-surface2)" }}
              />
            </div>
            <div style={{ display: "flex", alignItems: "flex-end" }}>
              <button type="submit" className="btn-primary" style={{ padding: "12px 20px" }}>
                Update
              </button>
            </div>
          </form>
        </div>
      </main>
    </div>
  );
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
