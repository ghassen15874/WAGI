import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Zap, Loader2, ArrowRight, Github, Sun, Moon } from "lucide-react";
import axios from "axios";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../hooks/useTheme";

const backendPublicUrl = (import.meta.env.VITE_BACKEND_PUBLIC_URL as string | undefined)?.trim() || "http://localhost:8080";
const frontendOrigin = typeof window !== "undefined" ? window.location.origin : "";
const githubAuthUrl = `${backendPublicUrl.replace(/\/+$/, "")}/auth/github?frontend=${encodeURIComponent(frontendOrigin)}`;

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [githubLoading, setGithubLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { theme, toggleTheme } = useTheme();

  useEffect(() => {
    const token = searchParams.get("token");
    const githubError = searchParams.get("github_error");

    if (githubError) {
      setError(githubError);
      setGithubLoading(false);
      setSearchParams({}, { replace: true });
      return;
    }

    if (!token) return;

    const finishGithubLogin = async () => {
      setLoading(true);
      try {
        const res = await axios.get("/api/auth/me", {
          headers: { Authorization: `Bearer ${token}` },
        });
        login(token, res.data);
        setSearchParams({}, { replace: true });
        navigate(res.data.role === "ADMIN" ? "/admin" : "/app", { replace: true });
      } catch (err: any) {
        setError(err.response?.data?.detail || "GitHub login failed");
        setSearchParams({}, { replace: true });
      } finally {
        setLoading(false);
        setGithubLoading(false);
      }
    };

    void finishGithubLogin();
  }, [login, navigate, searchParams, setSearchParams]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await axios.post("/api/auth/login", { email, password });
      login(res.data.token, res.data.user);
      navigate(res.data.user.role === "ADMIN" ? "/admin" : "/app");
    } catch (err: any) {
      setError(err.response?.data?.detail || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  const handleGithubLogin = () => {
    setGithubLoading(true);
    window.location.href = githubAuthUrl;
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        background: "var(--color-bg)",
        padding: 24,
        position: "relative",
      }}
    >
      {/* Background Effects */}
      <div
        style={{
          position: "absolute",
          top: "10%",
          left: "50%",
          transform: "translateX(-50%)",
          width: "60%",
          height: "40%",
          background: "radial-gradient(ellipse, var(--color-accent-muted) 0%, transparent 70%)",
          pointerEvents: "none",
        }}
      />

      {/* Theme Toggle */}
      <button
        onClick={toggleTheme}
        className="btn btn-icon"
        style={{ position: "absolute", top: 24, right: 24 }}
        aria-label="Toggle theme"
      >
        {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
      </button>

      {/* Logo */}
      <Link
        to="/"
        style={{
          position: "absolute",
          top: 24,
          left: 24,
          display: "flex",
          alignItems: "center",
          gap: 10,
          textDecoration: "none",
          color: "inherit",
          fontWeight: 700,
          fontSize: 20,
          letterSpacing: "-0.03em",
        }}
      >
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 10,
            background: "var(--gradient-accent)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#fff",
            boxShadow: "var(--shadow-accent)",
          }}
        >
          <Zap size={18} />
        </div>
        WAGI<span style={{ opacity: 0.5 }}>.</span>
      </Link>

      {/* Login Card */}
      <div
        className="glass"
        style={{
          width: "100%",
          maxWidth: 420,
          padding: 40,
          borderRadius: "var(--radius-xl)",
          position: "relative",
        }}
      >
        <h2
          style={{
            fontSize: 28,
            fontWeight: 800,
            marginBottom: 8,
            textAlign: "center",
            letterSpacing: "-0.02em",
          }}
        >
          Welcome back
        </h2>
        <p
          style={{
            color: "var(--color-text-muted)",
            textAlign: "center",
            marginBottom: 32,
            fontSize: 15,
          }}
        >
          Sign in to your account
        </p>

        {error && (
          <div
            style={{
              padding: 14,
              borderRadius: "var(--radius-md)",
              background: "rgba(239, 68, 68, 0.1)",
              color: "var(--color-error)",
              fontSize: 13,
              marginBottom: 20,
              textAlign: "center",
              border: "1px solid rgba(239, 68, 68, 0.2)",
            }}
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div>
            <label
              style={{
                display: "block",
                fontSize: 12,
                fontWeight: 600,
                color: "var(--color-text-muted)",
                marginBottom: 8,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
              }}
            >
              Email Address
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input-field"
              style={{ background: "var(--color-surface2)" }}
            />
          </div>
          <div>
            <label
              style={{
                display: "block",
                fontSize: 12,
                fontWeight: 600,
                color: "var(--color-text-muted)",
                marginBottom: 8,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
              }}
            >
              Password
            </label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input-field"
              style={{ background: "var(--color-surface2)" }}
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="btn-primary"
            style={{
              marginTop: 8,
              display: "flex",
              justifyContent: "center",
              alignItems: "center",
              gap: 10,
              width: "100%",
              padding: "14px",
              fontSize: 15,
            }}
          >
            {loading ? (
              <Loader2 size={18} className="animate-spin" />
            ) : (
              <>
                Sign In <ArrowRight size={18} />
              </>
            )}
          </button>
        </form>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 16,
            margin: "24px 0",
          }}
        >
          <div
            style={{ height: 1, background: "var(--color-border)", flex: 1 }}
          />
          <span
            style={{
              fontSize: 11,
              color: "var(--color-text-muted2)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
            }}
          >
            or
          </span>
          <div
            style={{ height: 1, background: "var(--color-border)", flex: 1 }}
          />
        </div>

        <button
          type="button"
          disabled={loading || githubLoading}
          onClick={handleGithubLogin}
          className="btn-secondary"
          style={{
            width: "100%",
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            gap: 10,
            padding: "14px",
            fontSize: 15,
          }}
        >
          {githubLoading ? (
            <Loader2 size={18} className="animate-spin" />
          ) : (
            <Github size={18} />
          )}
          Continue with GitHub
        </button>

        <div
          style={{
            marginTop: 28,
            textAlign: "center",
            fontSize: 14,
            color: "var(--color-text-muted)",
          }}
        >
          Don't have an account?{" "}
          <Link
            to="/register"
            style={{
              color: "var(--color-accent)",
              textDecoration: "none",
              fontWeight: 600,
            }}
          >
            Create one
          </Link>
        </div>
      </div>
    </div>
  );
}
