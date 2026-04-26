import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Zap, Loader2, UserPlus, Github, Sun, Moon } from "lucide-react";
import axios from "axios";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../hooks/useTheme";

const backendPublicUrl =
  (import.meta.env.VITE_BACKEND_PUBLIC_URL as string | undefined)?.trim() ||
  "http://localhost:8080";
const frontendOrigin =
  typeof window !== "undefined" ? window.location.origin : "";
const githubAuthUrl = `${backendPublicUrl.replace(/\/+$/, "")}/auth/github?frontend=${encodeURIComponent(frontendOrigin)}`;

export default function RegisterPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [githubLoading, setGithubLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirm) {
      return setError("Passwords do not match");
    }
    if (password.length < 6) {
      return setError("Password must be at least 6 characters");
    }

    setError("");
    setLoading(true);
    try {
      const res = await axios.post("/api/auth/register", { email, password });
      login(res.data.token, res.data.user);
      navigate("/app");
    } catch (err: any) {
      setError(err.response?.data?.detail || "Registration failed");
    } finally {
      setLoading(false);
    }
  };

  const handleGithubSignup = () => {
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
          background:
            "radial-gradient(ellipse, var(--color-accent-muted) 0%, transparent 70%)",
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
            fontWeight: 800,
            fontSize: 20,
            lineHeight: 1,
            letterSpacing: "-0.03em",
            transition:
              "transform 0.25s ease, box-shadow 0.25s ease, filter 0.25s ease",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.transform = "translateY(-4px) scale(1.05)";
            e.currentTarget.style.boxShadow = "0 10px 20px rgba(0,0,0,0.2)";
            e.currentTarget.style.filter = "brightness(1.05)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.transform = "translateY(0) scale(1)";
            e.currentTarget.style.boxShadow = "var(--shadow-accent)";
            e.currentTarget.style.filter = "brightness(1)";
          }}
        >
          W
        </div>
        WAGI<span style={{ opacity: 0.5 }}></span>
      </Link>

      {/* Register Card */}
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
          Create Account
        </h2>
        <p
          style={{
            color: "var(--color-text-muted)",
            textAlign: "center",
            marginBottom: 32,
            fontSize: 15,
          }}
        >
          Start building with WAGI AI
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

        <form
          onSubmit={handleSubmit}
          style={{ display: "flex", flexDirection: "column", gap: 20 }}
        >
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
              Confirm Password
            </label>
            <input
              type="password"
              required
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
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
                Sign Up <UserPlus size={18} />
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
          onClick={handleGithubSignup}
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
          Already have an account?{" "}
          <Link
            to="/login"
            style={{
              color: "var(--color-accent)",
              textDecoration: "none",
              fontWeight: 600,
            }}
          >
            Log in
          </Link>
        </div>
      </div>
    </div>
  );
}
