import { Link } from "react-router-dom";
import {
  Code2,
  Shield,
  Settings2,
  Database,
  Layout,
  Rocket,
  Zap,
  Cloud,
  Users,
  Lock,
  Terminal,
  Play,
} from "lucide-react";
import Navbar from "./Navbar";

const features = [
  {
    icon: <Code2 size={28} />,
    title: "Full-Stack Engineering",
    description:
      "From database schema to React components, WAGI handles the entire stack. Generate REST APIs, GraphQL endpoints, authentication systems, and frontend code all from natural language prompts.",
    benefits: [
      "Auto-generated database schemas",
      "REST & GraphQL API generation",
      "Built-in authentication flows",
      "TypeScript full-stack output",
    ],
  },
  {
    icon: <Shield size={28} />,
    title: "Privacy First (BYOK)",
    description:
      "Your data stays yours. We support Bring Your Own Keys (BYOK) for Groq, Anthropic, OpenAI, and other providers. All API keys are encrypted at rest with AES-256.",
    benefits: [
      "Bring your own API keys",
      "Encrypted key storage",
      "No data training on your inputs",
      "SOC 2 compliant infrastructure",
    ],
  },
  {
    icon: <Settings2 size={28} />,
    title: "Pipeline Granularity",
    description:
      "Control every step of your AI generation pipeline. Toggle specific build steps like Linter, Integration Tests, Architecture Planning, or Security Scanning.",
    benefits: [
      "Modular pipeline stages",
      "Custom pipeline templates",
      "Test & lint integration",
      "Security vulnerability scanning",
    ],
  },
  {
    icon: <Database size={28} />,
    title: "Persistent Workspace",
    description:
      "Every project gets its own sandbox environment. Your code, files, and state persist across sessions. Multi-tenant architecture keeps data completely isolated.",
    benefits: [
      "Dedicated sandbox per project",
      "Persistent file storage",
      "Complete isolation between tenants",
      "Unlimited project history",
    ],
  },
  {
    icon: <Layout size={28} />,
    title: "Admin Oversight",
    description:
      "Built-in admin console for user management, team controls, and real-time system monitoring. Track usage, manage seats, and monitor system health.",
    benefits: [
      "Team management dashboard",
      "Usage analytics & reporting",
      "Role-based access control",
      "Real-time system monitoring",
    ],
  },
  {
    icon: <Rocket size={28} />,
    title: "WebContainer VM",
    description:
      "Instant interactive previews powered by StackBlitz WebContainers. Run Node.js directly in the browser with full npm support, live reloading, and terminal access.",
    benefits: [
      "Browser-based Node.js runtime",
      "Instant preview deployment",
      "Live reload & hot module replacement",
      "Full terminal access",
    ],
  },
];

const techStack = [
  { icon: <Zap size={20} />, name: "Lightning Fast" },
  { icon: <Cloud size={20} />, name: "Cloud Native" },
  { icon: <Lock size={20} />, name: "Secure by Default" },
  { icon: <Users size={20} />, name: "Team Collaboration" },
];

export default function FeaturesPage() {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--color-bg)",
        color: "var(--color-text)",
        fontFamily: "var(--font-sans)",
      }}
    >
      <Navbar />

      <main>
        {/* Hero Section */}
        <section
          style={{
            padding: "120px 8% 80px",
            textAlign: "center",
          }}
        >
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 16px",
              borderRadius: 20,
              background: "var(--color-surface2)",
              fontSize: 12,
              fontWeight: 600,
              color: "var(--color-accent)",
              marginBottom: 32,
              border: "1px solid var(--color-border)",
            }}
          >
            <Zap size={14} /> Platform Features
          </div>

          <h1
            style={{
              fontSize: "clamp(36px, 6vw, 64px)",
              fontWeight: 800,
              lineHeight: 1.1,
              marginBottom: 24,
              letterSpacing: "-0.03em",
              maxWidth: 800,
              margin: "0 auto 24px",
            }}
          >
            Everything you need to{" "}
            <span style={{ color: "var(--color-text-muted)" }}>
              build faster
            </span>
          </h1>

          <p
            style={{
              fontSize: 18,
              color: "var(--color-text-muted)",
              maxWidth: 600,
              margin: "0 auto 48px",
              lineHeight: 1.6,
            }}
          >
            A complete AI-powered development platform with enterprise-grade
            security, infinite scalability, and seamless integrations.
          </p>

          <div
            style={{
              display: "flex",
              gap: 16,
              justifyContent: "center",
              flexWrap: "wrap",
            }}
          >
            <Link
              to="/register"
              style={{
                background: "var(--color-text)",
                color: "#000",
                textDecoration: "none",
                fontWeight: 600,
                padding: "14px 32px",
                borderRadius: 30,
                fontSize: 16,
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              Get Started Free
            </Link>
            <Link
              to="/how-it-works"
              style={{
                background: "transparent",
                color: "var(--color-text)",
                textDecoration: "none",
                fontWeight: 600,
                padding: "14px 32px",
                borderRadius: 30,
                fontSize: 16,
                border: "1px solid var(--color-border)",
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              See How It Works <Play size={16} />
            </Link>
          </div>
        </section>

        {/* Tech Stack Badges */}
        <section
          style={{
            padding: "0 8% 80px",
            display: "flex",
            justifyContent: "center",
            flexWrap: "wrap",
            gap: 24,
          }}
        >
          {techStack.map((tech) => (
            <div
              key={tech.name}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "12px 20px",
                borderRadius: 12,
                background: "var(--color-surface)",
                border: "1px solid var(--color-border)",
                fontSize: 14,
                fontWeight: 500,
              }}
            >
              {tech.icon}
              {tech.name}
            </div>
          ))}
        </section>

        {/* Features Grid */}
        <section
          style={{ padding: "40px 8% 120px", maxWidth: 1400, margin: "0 auto" }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))",
              gap: 32,
            }}
          >
            {features.map((feature, index) => (
              <FeatureCard key={index} feature={feature} />
            ))}
          </div>
        </section>

        {/* CTA Section */}
        <section
          style={{
            padding: "100px 8%",
            background: "var(--color-surface)",
            borderTop: "1px solid var(--color-border)",
            textAlign: "center",
          }}
        >
          <h2
            style={{
              fontSize: "clamp(28px, 4vw, 42px)",
              fontWeight: 800,
              marginBottom: 16,
              letterSpacing: "-0.02em",
            }}
          >
            Ready to transform your workflow?
          </h2>
          <p
            style={{
              fontSize: 18,
              color: "var(--color-text-muted)",
              maxWidth: 500,
              margin: "0 auto 32px",
            }}
          >
            Join thousands of developers building faster with WAGI.
          </p>
          <Link
            to="/register"
            style={{
              background: "var(--color-text)",
              color: "#000",
              textDecoration: "none",
              fontWeight: 600,
              padding: "16px 40px",
              borderRadius: 30,
              fontSize: 16,
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            Start Building Free <Zap size={18} />
          </Link>
        </section>

        {/* Footer */}
        <footer
          style={{
            padding: "40px 8%",
            borderTop: "1px solid var(--color-border)",
            textAlign: "center",
            fontSize: 13,
            color: "var(--color-text-muted)",
          }}
        >
          <div
            style={{
              marginBottom: 16,
              display: "flex",
              justifyContent: "center",
              gap: 24,
            }}
          >
            <span>Twitter</span>
            <span>Discord</span>
            <span>Documentation</span>
            <span>Changelog</span>
          </div>
          <div>© 2026 WAGI Platform. All rights reserved.</div>
        </footer>
      </main>
    </div>
  );
}

function FeatureCard({ feature }: { feature: (typeof features)[0] }) {
  return (
    <div
      style={{
        padding: 40,
        borderRadius: 24,
        background: "var(--color-surface)",
        border: "1px solid var(--color-border)",
        transition: "var(--transition)",
      }}
      onMouseEnter={(e) =>
        (e.currentTarget.style.borderColor = "var(--color-text-muted)")
      }
      onMouseLeave={(e) =>
        (e.currentTarget.style.borderColor = "var(--color-border)")
      }
    >
      <div
        style={{
          width: 56,
          height: 56,
          borderRadius: 14,
          background: "var(--color-surface2)",
          color: "var(--color-text)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          marginBottom: 24,
        }}
      >
        {feature.icon}
      </div>
      <h3 style={{ fontSize: 22, fontWeight: 700, marginBottom: 12 }}>
        {feature.title}
      </h3>
      <p
        style={{
          color: "var(--color-text-muted)",
          lineHeight: 1.6,
          marginBottom: 20,
        }}
      >
        {feature.description}
      </p>
      <ul
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {feature.benefits.map((benefit, i) => (
          <li
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 14,
              color: "var(--color-text-muted)",
            }}
          >
            <div
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: "var(--color-accent)",
              }}
            />
            {benefit}
          </li>
        ))}
      </ul>
    </div>
  );
}
