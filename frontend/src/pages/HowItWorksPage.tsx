import { Link } from "react-router-dom";
import {
  MessageSquare,
  Wand2,
  Code,
  Rocket,
  ArrowRight,
  Play,
  CheckCircle,
  Zap,
  Shield,
  Clock,
  Users,
} from "lucide-react";
import Navbar from "./Navbar";

const steps = [
  {
    number: "01",
    icon: <MessageSquare size={32} />,
    title: "Describe Your Idea",
    description:
      "Tell WAGI what you want to build in plain English. Describe your app's functionality, UI requirements, and any specific features you need.",
    example: '"Build a task management app with drag-and-drop boards, user auth, and real-time notifications"',
  },
  {
    number: "02",
    icon: <Wand2 size={32} />,
    title: "AI Generates Your Code",
    description:
      "Our AI analyzes your requirements and generates a complete full-stack application. Database schemas, API endpoints, React components, and styling all created automatically.",
    example: null,
  },
  {
    number: "03",
    icon: <Code size={32} />,
    title: "Review & Customize",
    description:
      "Preview your generated app instantly in the browser. Edit prompts, tweak components, or add new features with simple natural language instructions.",
    example: null,
  },
  {
    number: "04",
    icon: <Rocket size={32} />,
    title: "Deploy to Production",
    description:
      "One-click deployment to our global edge network. Your app is live with SSL, CDN, and automatic scaling from day one.",
    example: null,
  },
];

const benefits = [
  {
    icon: <Zap size={24} />,
    title: "Lightning Fast",
    description: "Generate complete apps in minutes, not hours or days.",
  },
  {
    icon: <Shield size={24} />,
    title: "Enterprise Security",
    description: "Your data is encrypted and isolated with SOC 2 compliance.",
  },
  {
    icon: <Clock size={24} />,
    title: "Save 10x Time",
    description: "Focus on ideas, not implementation details.",
  },
  {
    icon: <Users size={24} />,
    title: "Team Collaboration",
    description: "Work together with shared workspaces and real-time editing.",
  },
];

const faqs = [
  {
    question: "How does WAGI understand what I want to build?",
    answer:
      "WAGI uses advanced AI models trained on millions of open-source projects. It understands software architecture, best practices, and can translate natural language descriptions into working code.",
  },
  {
    question: "What technologies does WAGI generate?",
    answer:
      "WAGI generates modern full-stack applications using React, TypeScript, Node.js, PostgreSQL, and more. All code follows industry best practices and is production-ready.",
  },
  {
    question: "Can I edit the generated code?",
    answer:
      "Absolutely! The generated code is fully editable. You can modify any part of your application, add new features, or integrate with external services.",
  },
  {
    question: "Is my code secure?",
    answer:
      "Security is our top priority. We encrypt all data at rest and in transit. Your code is isolated in your own sandbox environment and never shared with other users.",
  },
  {
    question: "How much does it cost?",
    answer:
      "We offer a free tier to get started. Paid plans start at $29/month with more projects, longer retention, and priority support. Visit our pricing page for details.",
  },
];

export default function HowItWorksPage() {
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
            <Play size={14} /> How It Works
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
            From idea to{" "}
            <span style={{ color: "var(--color-text-muted)" }}>production</span> in
            4 steps
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
            WAGI turns your ideas into working applications. No coding required.
            Just describe what you want and watch it get built.
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
            Try It Now <ArrowRight size={18} />
          </Link>
        </section>

        {/* Steps */}
        <section
          style={{
            padding: "40px 8% 120px",
            maxWidth: 1000,
            margin: "0 auto",
          }}
        >
          <div
            style={{ display: "flex", flexDirection: "column", gap: 80 }}
          >
            {steps.map((step, index) => (
              <StepCard key={index} step={step} index={index} />
            ))}
          </div>
        </section>

        {/* Benefits */}
        <section
          style={{
            padding: "80px 8%",
            background: "var(--color-surface)",
            borderTop: "1px solid var(--color-border)",
            borderBottom: "1px solid var(--color-border)",
          }}
        >
          <div style={{ maxWidth: 1200, margin: "0 auto" }}>
            <h2
              style={{
                fontSize: "clamp(28px, 4vw, 42px)",
                fontWeight: 800,
                textAlign: "center",
                marginBottom: 60,
                letterSpacing: "-0.02em",
              }}
            >
              Why developers love WAGI
            </h2>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))",
                gap: 32,
              }}
            >
              {benefits.map((benefit, index) => (
                <div
                  key={index}
                  style={{
                    padding: 32,
                    borderRadius: 20,
                    background: "var(--color-bg)",
                    border: "1px solid var(--color-border)",
                  }}
                >
                  <div
                    style={{
                      width: 48,
                      height: 48,
                      borderRadius: 12,
                      background: "var(--color-surface2)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      marginBottom: 16,
                      color: "var(--color-accent)",
                    }}
                  >
                    {benefit.icon}
                  </div>
                  <h3
                    style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}
                  >
                    {benefit.title}
                  </h3>
                  <p
                    style={{
                      color: "var(--color-text-muted)",
                      lineHeight: 1.5,
                      fontSize: 14,
                    }}
                  >
                    {benefit.description}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* FAQ */}
        <section style={{ padding: "80px 8% 120px", maxWidth: 800, margin: "0 auto" }}>
          <h2
            style={{
              fontSize: "clamp(28px, 4vw, 42px)",
              fontWeight: 800,
              textAlign: "center",
              marginBottom: 48,
              letterSpacing: "-0.02em",
            }}
          >
            Frequently asked questions
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
            {faqs.map((faq, index) => (
              <details
                key={index}
                style={{
                  padding: 24,
                  borderRadius: 16,
                  background: "var(--color-surface)",
                  border: "1px solid var(--color-border)",
                  cursor: "pointer",
                }}
              >
                <summary
                  style={{
                    fontWeight: 600,
                    fontSize: 16,
                    listStyle: "none",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  {faq.question}
                  <ArrowRight
                    size={18}
                    style={{
                      transform: "rotate(90deg)",
                      transition: "transform 0.2s",
                    }}
                  />
                </summary>
                <p
                  style={{
                    marginTop: 16,
                    color: "var(--color-text-muted)",
                    lineHeight: 1.6,
                  }}
                >
                  {faq.answer}
                </p>
              </details>
            ))}
          </div>
        </section>

        {/* CTA */}
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
            Ready to get started?
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
            style={{ marginBottom: 16, display: "flex", justifyContent: "center", gap: 24 }}
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

function StepCard({ step, index }: { step: typeof steps[0]; index: number }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
        gap: 48,
        alignItems: "center",
      }}
    >
      <div>
        <div
          style={{
            fontSize: 72,
            fontWeight: 800,
            color: "var(--color-border)",
            lineHeight: 1,
            marginBottom: 16,
          }}
        >
          {step.number}
        </div>
        <h3
          style={{
            fontSize: 28,
            fontWeight: 700,
            marginBottom: 12,
          }}
        >
          {step.title}
        </h3>
        <p
          style={{
            color: "var(--color-text-muted)",
            lineHeight: 1.6,
            marginBottom: 16,
          }}
        >
          {step.description}
        </p>
        {step.example && (
          <div
            style={{
              padding: 16,
              borderRadius: 12,
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              fontSize: 13,
              color: "var(--color-text-muted)",
              fontStyle: "italic",
            }}
          >
            "{step.example}"
          </div>
        )}
      </div>
      <div
        style={{
          padding: 40,
          borderRadius: 24,
          background: "var(--color-surface)",
          border: "1px solid var(--color-border)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          minHeight: 200,
        }}
      >
        <div
          style={{
            width: 80,
            height: 80,
            borderRadius: 20,
            background: "var(--color-surface2)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--color-accent)",
          }}
        >
          {step.icon}
        </div>
      </div>
    </div>
  );
}