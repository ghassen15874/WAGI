import React, { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import {
  Rocket,
  Shield,
  Settings2,
  Code2,
  Database,
  Layout,
  Zap,
  ArrowRight,
  Github,
  Play,
  Check,
  MessageSquare,
  Wand2,
  Rocket as DeployIcon,
  Sparkles,
  Layers,
  Globe,
  Lock,
} from "lucide-react";
import Navbar from "./Navbar";
import Footer from "./Footer";
import { useAuth } from "../hooks/useAuth";

interface AnimatedSectionProps {
  children: React.ReactNode;
  className?: string;
  delay?: number;
}

const AnimatedSection: React.FC<AnimatedSectionProps> = ({
  children,
  delay = 0,
}) => {
  const [isVisible, setIsVisible] = useState(true); // Default to true for reliability
  const [ref, setRef] = useState<HTMLElement | null>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setTimeout(() => setIsVisible(true), delay);
        }
      },
      { threshold: 0.1, rootMargin: "-50px" },
    );

    if (ref) observer.observe(ref);
    return () => observer.disconnect();
  }, [ref, delay]);

  return (
    <section
      ref={setRef as any}
      style={{
        opacity: isVisible ? 1 : 0,
        transform: isVisible ? "translateY(0)" : "translateY(40px)",
        transition:
          "opacity 0.8s cubic-bezier(0.16, 1, 0.3, 1), transform 0.8s cubic-bezier(0.16, 1, 0.3, 1)",
      }}
    >
      {children}
    </section>
  );
};

interface FeatureCardProps {
  icon: React.ReactElement<{ size?: number }>;
  title: string;
  description: string;
  delay?: number;
}

const FeatureCard: React.FC<FeatureCardProps> = ({
  icon,
  title,
  description,
  delay = 0,
}) => {
  const [isVisible, setIsVisible] = useState(true); // Default to true for reliability
  const [ref, setRef] = useState<HTMLElement | null>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setTimeout(() => setIsVisible(true), delay);
        }
      },
      { threshold: 0.2 },
    );

    if (ref) observer.observe(ref);
    return () => observer.disconnect();
  }, [ref, delay]);
  const howItWorksSteps = [
    {
      number: "01",
      title: "Describe Your Idea",
      description:
        "Tell WAGI what you want to build in plain English. Our AI understands complex requirements.",
      delay: 100,
    },
    {
      number: "02",
      title: "AI Generates Your Code",
      description:
        "Our AI creates a complete full-stack application automatically with best practices built-in.",
      delay: 200,
    },
    {
      number: "03",
      title: "Review & Customize",
      description:
        "Preview instantly and edit with natural language instructions. Full control over your code.",
      delay: 300,
    },
    {
      number: "04",
      title: "Deploy to Production",
      description:
        "One-click deployment to our global edge network. Your app is live in seconds.",
      delay: 400,
      isLast: true,
    },
  ];

  return (
    <div
      ref={setRef as any}
      style={{
        padding: "32px",
        borderRadius: "24px",
        background: "var(--color-surface)",
        border: "1px solid var(--color-border)",
        transition: "all 0.4s cubic-bezier(0.16, 1, 0.3, 1)",
        cursor: "default",
        opacity: isVisible ? 1 : 0,
        transform: isVisible ? "translateY(0)" : "translateY(30px)",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = "translateY(-8px)";
        e.currentTarget.style.boxShadow = "0 20px 40px rgba(0,0,0,0.3)";
        e.currentTarget.style.borderColor = "var(--color-accent)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = "translateY(0)";
        e.currentTarget.style.boxShadow = "none";
        e.currentTarget.style.borderColor = "var(--color-border)";
      }}
    >
      <div
        style={{
          width: "64px",
          height: "64px",
          borderRadius: "16px",
          background:
            "linear-gradient(135deg, var(--color-accent) 0%, #a78bfa 100%)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          marginBottom: "24px",
          boxShadow: "0 8px 24px rgba(139, 92, 246, 0.25)",
          color: "#000",
        }}
      >
        {React.isValidElement(icon)
          ? React.cloneElement(icon as React.ReactElement<{ size?: number }>, {
              size: 28,
            })
          : icon}
      </div>
      <h3
        style={{
          fontSize: "22px",
          fontWeight: 700,
          marginBottom: "12px",
          letterSpacing: "-0.02em",
        }}
      >
        {title}
      </h3>
      <p
        style={{
          color: "var(--color-text-muted)",
          lineHeight: 1.7,
          fontSize: "15px",
        }}
      >
        {description}
      </p>
    </div>
  );
};

interface PricingCardProps {
  id: string;
  name: string;
  price: string;
  period: string;
  features: string[];
  cta: string;
  popular: boolean;
  delay?: number;
  onCta: (id: string) => void;
}

const PricingCard: React.FC<PricingCardProps> = ({
  id,
  name,
  price,
  period,
  features,
  cta,
  popular,
  delay = 0,
  onCta,
}) => {
  const [isVisible, setIsVisible] = useState(true); // Default to true for reliability
  const [ref, setRef] = useState<HTMLElement | null>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setTimeout(() => setIsVisible(true), delay);
        }
      },
      { threshold: 0.2 },
    );

    if (ref) observer.observe(ref);
    return () => observer.disconnect();
  }, [ref, delay]);

  return (
    <div
      ref={setRef as any}
      style={{
        padding: "40px 32px",
        borderRadius: "24px",
        background: popular
          ? "linear-gradient(135deg, rgba(139, 92, 246, 0.1) 0%, rgba(59, 130, 246, 0.05) 100%)"
          : "var(--color-surface)",
        border: popular
          ? "2px solid var(--color-accent)"
          : "1px solid var(--color-border)",
        position: "relative",
        transition: "all 0.4s cubic-bezier(0.16, 1, 0.3, 1)",
        opacity: isVisible ? 1 : 0,
        transform: isVisible ? "translateY(0)" : "translateY(30px)",
      }}
      onMouseEnter={(e) => {
        if (!popular) {
          e.currentTarget.style.borderColor = "var(--color-text-muted)";
          e.currentTarget.style.transform = "translateY(-8px)";
        }
      }}
      onMouseLeave={(e) => {
        if (!popular) {
          e.currentTarget.style.borderColor = "var(--color-border)";
          e.currentTarget.style.transform = "translateY(0)";
        }
      }}
    >
      {popular && (
        <div
          style={{
            position: "absolute",
            top: "-14px",
            left: "50%",
            transform: "translateX(-50%)",
            background:
              "linear-gradient(135deg, var(--color-accent) 0%, #a78bfa 100%)",
            color: "#000",
            padding: "6px 16px",
            borderRadius: "20px",
            fontSize: "12px",
            fontWeight: 700,
            letterSpacing: "0.05em",
            boxShadow: "0 4px 16px rgba(139, 92, 246, 0.4)",
          }}
        >
          MOST POPULAR
        </div>
      )}
      <h3
        style={{
          fontSize: "20px",
          fontWeight: 700,
          marginBottom: "8px",
          letterSpacing: "-0.02em",
        }}
      >
        {name}
      </h3>
      <div
        style={{
          marginBottom: "24px",
          display: "flex",
          alignItems: "baseline",
          gap: "4px",
        }}
      >
        <span
          style={{
            fontSize: "48px",
            fontWeight: 800,
            letterSpacing: "-0.03em",
          }}
        >
          {price}
        </span>
        <span style={{ fontSize: "14px", color: "var(--color-text-muted)" }}>
          {period}
        </span>
      </div>
      <button
        onClick={() => onCta(id)}
        style={{
          width: "100%",
          border: "none",
          cursor: "pointer",
          background: popular
            ? "linear-gradient(135deg, var(--color-accent) 0%, #a78bfa 100%)"
            : "var(--color-text)",
          color: popular ? "#000" : "var(--color-bg)",
          textDecoration: "none",
          fontWeight: 600,
          padding: "14px 24px",
          borderRadius: "16px",
          fontSize: "15px",
          display: "block",
          textAlign: "center",
          marginBottom: "24px",
          transition: "all 0.3s ease",
          boxShadow: popular ? "0 8px 24px rgba(139, 92, 246, 0.3)" : "none",
        }}
      >
        {cta}
      </button>
      <ul
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "flex",
          flexDirection: "column",
          gap: "14px",
        }}
      >
        {features.map((f, i) => (
          <li
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "12px",
              fontSize: "14px",
            }}
          >
            <div
              style={{
                width: "20px",
                height: "20px",
                borderRadius: "50%",
                background: "rgba(139, 92, 246, 0.15)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <Check size={12} style={{ color: "var(--color-accent)" }} />
            </div>
            {f}
          </li>
        ))}
      </ul>
    </div>
  );
};

interface StepCardProps {
  number: string;
  title: string;
  description: string;
  delay?: number;
  isLast?: boolean;
}

const StepCard: React.FC<StepCardProps> = ({
  number,
  title,
  description,
  delay = 0,
  isLast = false,
}) => {
  const [isVisible, setIsVisible] = useState(true); // Default to true for reliability
  const [ref, setRef] = useState<HTMLElement | null>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setTimeout(() => setIsVisible(true), delay);
        }
      },
      { threshold: 0.25 },
    );

    if (ref) observer.observe(ref);
    return () => observer.disconnect();
  }, [ref, delay]);

  return (
    <div
      ref={setRef as any}
      style={{
        display: "grid",
        gridTemplateColumns: "72px 1fr",
        gap: "24px",
        alignItems: "center",
        position: "relative",
        opacity: isVisible ? 1 : 0,
        transform: isVisible ? "translateY(0)" : "translateY(24px)",
        transition: "all 0.8s cubic-bezier(0.16, 1, 0.3, 1)",
        padding: "24px 28px",
        borderRadius: "24px",
        background: "transparent",
      }}
    >
      {!isLast && (
        <div
          style={{
            position: "absolute",
            left: "35px",
            top: "88px",
            bottom: "-28px",
            width: "2px",
            background:
              "linear-gradient(180deg, var(--color-accent) 0%, transparent 100%)",
            opacity: 0.25,
          }}
        />
      )}

      <div
        style={{
          width: "56px",
          height: "56px",
          borderRadius: "18px",
          background:
            "linear-gradient(135deg, var(--color-accent) 0%, #a78bfa 100%)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: "18px",
          fontWeight: 800,
          color: "#000",
          boxShadow: "0 10px 28px rgba(139, 92, 246, 0.28)",
          position: "relative",
          zIndex: 1,
          flexShrink: 0,
        }}
      >
        {number}
      </div>

      <div>
        <h3
          style={{
            fontSize: "22px",
            fontWeight: 700,
            marginBottom: "8px",
            letterSpacing: "-0.02em",
          }}
        >
          {title}
        </h3>
        <p
          style={{
            color: "var(--color-text-muted)",
            lineHeight: 1.7,
            fontSize: "15px",
            margin: 0,
          }}
        >
          {description}
        </p>
      </div>
    </div>
  );
};

export default function LandingPage() {
  const [heroVisible, setHeroVisible] = useState(true); // Default to true for reliability
  const { user } = useAuth();
  const howItWorksSteps = [
    {
      number: "01",
      title: "Describe Your Idea",
      description:
        "Tell WAGI what you want to build in plain English. Our AI understands complex requirements.",
      delay: 100,
    },
    {
      number: "02",
      title: "AI Generates Your Code",
      description:
        "Our AI creates a complete full-stack application automatically with best practices built-in.",
      delay: 200,
    },
    {
      number: "03",
      title: "Review & Customize",
      description:
        "Preview instantly and edit with natural language instructions. Full control over your code.",
      delay: 300,
    },
    {
      number: "04",
      title: "Deploy to Production",
      description:
        "One-click deployment to our global edge network. Your app is live in seconds.",
      delay: 400,
      isLast: true,
    },
  ];

  useEffect(() => {
    window.scrollTo(0, 0);
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => setHeroVisible(true), 100);
    return () => clearTimeout(timer);
  }, []);

  const handleCta = async (planId: string) => {
    if (!user) {
      window.location.href = "/register";
      return;
    }
    if (planId === "free") {
      window.location.href = "/dashboard";
      return;
    }
    try {
      // Create a checkout session and redirect
      const res = await axios.post(
        "/api/billing/checkout",
        { plan_id: planId },
        {
          headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
        },
      );
      if (res.data.checkoutUrl) {
        window.location.href = res.data.checkoutUrl;
      }
    } catch (err) {
      window.location.href = "/dashboard?tab=billing";
    }
  };

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

      {/* Hero Section */}
      <header
        id="home"
        style={{
          padding: "180px 8% 140px",
          textAlign: "center",
          position: "relative",
          overflow: "hidden",
        }}
      >
        {/* Background Effects */}
        <div
          style={{
            position: "absolute",
            top: "0",
            left: "50%",
            transform: "translateX(-50%)",
            width: "100%",
            height: "100%",
            background:
              "radial-gradient(ellipse 80% 60% at 50% 0%, rgba(139, 92, 246, 0.12) 0%, transparent 60%)",
            zIndex: 0,
            pointerEvents: "none",
          }}
        />
        <div
          style={{
            position: "absolute",
            top: "20%",
            left: "50%",
            transform: "translateX(-50%)",
            width: "60%",
            height: "40%",
            background:
              "radial-gradient(circle, rgba(59, 130, 246, 0.08) 0%, transparent 70%)",
            zIndex: 0,
            pointerEvents: "none",
          }}
        />

        {/* Badge */}

        {/* Hero Title */}
        <h1
          style={{
            fontSize: "clamp(52px, 7vw, 80px)",
            fontWeight: 800,
            lineHeight: 1.05,
            letterSpacing: "-0.04em",
            maxWidth: 900,
            margin: "0 auto 32px",
            position: "relative",
            zIndex: 1,
            opacity: heroVisible ? 1 : 0,
            transform: heroVisible ? "translateY(0)" : "translateY(30px)",
            transition: "all 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.3s",
          }}
        >
          The future of{" "}
          <span
            style={{
              background:
                "linear-gradient(135deg, var(--color-accent) 0%, #a78bfa 50%, #3b82f6 100%)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            automated dev
          </span>
        </h1>

        {/* Hero Subtitle */}
        <p
          style={{
            fontSize: "clamp(18px, 2vw, 22px)",
            color: "var(--color-text-muted)",
            maxWidth: 640,
            margin: "0 auto 48px",
            lineHeight: 1.6,
            fontWeight: 400,
            position: "relative",
            zIndex: 1,
            opacity: heroVisible ? 1 : 0,
            transform: heroVisible ? "translateY(0)" : "translateY(30px)",
            transition: "all 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.4s",
          }}
        >
          WAGI is a world-class AI platform for building websites. Think.
          Prompt. Build. Deploy. All in one place.
        </p>

        {/* CTA Buttons */}
        <div
          style={{
            display: "flex",
            gap: "16px",
            justifyContent: "center",
            flexWrap: "wrap",
            position: "relative",
            zIndex: 1,
            opacity: heroVisible ? 1 : 0,
            transform: heroVisible ? "translateY(0)" : "translateY(30px)",
            transition: "all 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.5s",
          }}
        >
          <Link
            to={user ? "/dashboard" : "/register"}
            style={{
              background:
                "linear-gradient(135deg, var(--color-accent) 0%, #a78bfa 100%)",
              color: "#000",
              textDecoration: "none",
              fontWeight: 600,
              padding: "18px 44px",
              borderRadius: "50px",
              fontSize: "17px",
              display: "flex",
              alignItems: "center",
              gap: "10px",
              transition: "all 0.4s cubic-bezier(0.23, 1, 0.32, 1)",
              boxShadow: "0 8px 32px rgba(139, 92, 246, 0.35)",
              transform: "translateY(0) scale(1)",
              filter: "brightness(1)",
              willChange: "transform, box-shadow, filter",
            }}
            onMouseEnter={(e) => {
              const el = e.currentTarget;
              el.style.transform = "translateY(-4px) scale(1.03)";
              el.style.boxShadow = "0 20px 50px rgba(139, 92, 246, 0.5)";
              el.style.filter = "brightness(1.1)";
              const text = el.querySelector(".sb-text") as HTMLElement;
              const icon = el.querySelector(".sb-icon") as HTMLElement;
              if (text) text.style.transform = "translateX(-3px)";
              if (icon) icon.style.transform = "translateX(3px)";
            }}
            onMouseLeave={(e) => {
              const el = e.currentTarget;
              el.style.transform = "translateY(0) scale(1)";
              el.style.boxShadow = "0 8px 32px rgba(139, 92, 246, 0.35)";
              el.style.filter = "brightness(1)";
              const text = el.querySelector(".sb-text") as HTMLElement;
              const icon = el.querySelector(".sb-icon") as HTMLElement;
              if (text) text.style.transform = "translateX(0)";
              if (icon) icon.style.transform = "translateX(0)";
            }}
          >
            <span
              className="sb-text"
              style={{
                display: "inline-flex",
                alignItems: "center",
                transition: "transform 0.4s cubic-bezier(0.23, 1, 0.32, 1)",
              }}
            >
              {user ? "Go to Dashboard" : "Start building"}
            </span>
            <ArrowRight
              className="sb-icon"
              size={18}
              style={{
                transition: "transform 0.4s cubic-bezier(0.23, 1, 0.32, 1)",
                transform: "translateX(0)",
              }}
            />
          </Link>
          <a
            href="https://github.com"
            style={{
              background: "rgba(255,255,255,0.03)",
              color: "var(--color-text)",
              textDecoration: "none",
              fontWeight: 600,
              padding: "18px 44px",
              borderRadius: "50px",
              fontSize: "17px",
              border: "1px solid var(--color-border)",
              display: "flex",
              alignItems: "center",
              gap: "10px",
              transition: "all 0.4s cubic-bezier(0.23, 1, 0.32, 1)",
              transform: "translateY(0) scale(1)",
              filter: "brightness(1)",
              willChange: "transform, box-shadow, filter, border-color",
            }}
            onMouseEnter={(e) => {
              const el = e.currentTarget;
              el.style.transform = "translateY(-4px) scale(1.03)";
              el.style.boxShadow = "0 16px 40px rgba(0,0,0,0.3)";
              el.style.borderColor = "var(--color-accent)";
              el.style.filter = "brightness(1.05)";
              const icon = el.querySelector(".vs-icon") as HTMLElement;
              const text = el.querySelector(".vs-text") as HTMLElement;
              if (icon) icon.style.transform = "translateX(3px) rotate(-8deg)";
              if (text) text.style.transform = "translateX(3px)";
            }}
            onMouseLeave={(e) => {
              const el = e.currentTarget;
              el.style.transform = "translateY(0) scale(1)";
              el.style.boxShadow = "none";
              el.style.borderColor = "var(--color-border)";
              el.style.filter = "brightness(1)";
              const icon = el.querySelector(".vs-icon") as HTMLElement;
              const text = el.querySelector(".vs-text") as HTMLElement;
              if (icon) icon.style.transform = "translateX(0) rotate(0deg)";
              if (text) text.style.transform = "translateX(0)";
            }}
          >
            <Github
              className="vs-icon"
              size={18}
              style={{
                transition: "all 0.4s cubic-bezier(0.23, 1, 0.32, 1)",
                transform: "translateX(0) rotate(0deg)",
              }}
            />
            <span
              className="vs-text"
              style={{
                display: "inline-flex",
                alignItems: "center",
                transition: "transform 0.4s cubic-bezier(0.23, 1, 0.32, 1)",
              }}
            >
              View Source
            </span>
          </a>
        </div>
      </header>

      {/* Features Section */}
      <section
        id="features"
        style={{
          padding: "120px 8%",
          scrollMarginTop: "100px",
          position: "relative",
        }}
      >
        <AnimatedSection>
          <div
            style={{
              textAlign: "center",
              marginBottom: "80px",
              maxWidth: 700,
              margin: "0 auto 80px",
            }}
          >
            <h2
              style={{
                fontSize: "clamp(36px, 5vw, 52px)",
                fontWeight: 800,
                letterSpacing: "-0.03em",
                marginBottom: "20px",
                lineHeight: 1.1,
              }}
            >
              Everything you need to{" "}
              <span
                style={{
                  background:
                    "linear-gradient(135deg, var(--color-accent) 0%, #a78bfa 100%)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  backgroundClip: "text",
                }}
              >
                build faster
              </span>
            </h2>
            <p
              style={{
                fontSize: "18px",
                color: "var(--color-text-muted)",
                maxWidth: 560,
                margin: "0 auto",
                lineHeight: 1.7,
              }}
            >
              A complete AI-powered development platform with enterprise-grade
              security and seamless integrations.
            </p>
          </div>
        </AnimatedSection>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
            gap: "28px",
            maxWidth: 1200,
            margin: "0 auto",
          }}
        >
          <FeatureCard
            icon={<Code2 size={28} />}
            title="Full-Stack Engineering"
            description="From database schema to React components, WAGI handles the entire stack with intelligent code generation."
            delay={100}
          />
          <FeatureCard
            icon={<Shield size={28} />}
            title="Privacy First (BYOK)"
            description="Encrypted API key storage. Bring your own keys for Groq, Anthropic, or OpenAI."
            delay={200}
          />
          <FeatureCard
            icon={<Settings2 size={28} />}
            title="Pipeline Granularity"
            description="Toggle specific build steps like Linter, Integration Tests, or Architecture planning."
            delay={300}
          />
          <FeatureCard
            icon={<Database size={28} />}
            title="Persistent Workspace"
            description="Every project gets its own sandbox. No data loss, multi-tenant by design."
            delay={400}
          />
          <FeatureCard
            icon={<Layout size={28} />}
            title="Admin Oversight"
            description="Built-in console for user management and real-time system monitoring."
            delay={500}
          />
          <FeatureCard
            icon={<Rocket size={28} />}
            title="WebContainer VM"
            description="Instant interactive previews powered by StackBlitz WebContainers."
            delay={600}
          />
        </div>
      </section>

      {/* How It Works Section */}
      <section
        id="how-it-works"
        style={{
          padding: "140px 8%",
          background: "var(--color-surface)",
          scrollMarginTop: "100px",
          position: "relative",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: "0",
            left: "50%",
            transform: "translateX(-50%)",
            width: "80%",
            height: "60%",
            background:
              "radial-gradient(ellipse 60% 40% at 50% 0%, rgba(139, 92, 246, 0.08) 0%, transparent 60%)",
            pointerEvents: "none",
          }}
        />

        <AnimatedSection>
          <div
            style={{
              textAlign: "center",
              marginBottom: "80px",
              maxWidth: 700,
              margin: "0 auto 80px",
            }}
          >
            <h2
              style={{
                fontSize: "clamp(36px, 5vw, 52px)",
                fontWeight: 800,
                letterSpacing: "-0.03em",
                marginBottom: "20px",
                lineHeight: 1.1,
              }}
            >
              From idea to{" "}
              <span
                style={{
                  background:
                    "linear-gradient(135deg, var(--color-accent) 0%, #a78bfa 100%)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  backgroundClip: "text",
                }}
              >
                production
              </span>{" "}
              in 4 steps
            </h2>
          </div>
        </AnimatedSection>

        <div
          style={{
            maxWidth: 920,
            margin: "0 auto",
            display: "flex",
            flexDirection: "column",
            gap: "28px",
            position: "relative",
          }}
        >
          {howItWorksSteps.map((step) => (
            <StepCard
              key={step.number}
              number={step.number}
              title={step.title}
              description={step.description}
              delay={step.delay}
              isLast={step.isLast}
            />
          ))}
        </div>
      </section>

      {/* Pricing Section */}
      <section
        id="pricing"
        style={{
          padding: "140px 8%",
          scrollMarginTop: "100px",
          position: "relative",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: "0",
            left: "50%",
            transform: "translateX(-50%)",
            width: "80%",
            height: "50%",
            background:
              "radial-gradient(ellipse 60% 40% at 50% 0%, rgba(59, 130, 246, 0.06) 0%, transparent 60%)",
            pointerEvents: "none",
          }}
        />

        <AnimatedSection>
          <div
            style={{
              textAlign: "center",
              marginBottom: "80px",
              maxWidth: 700,
              margin: "0 auto 80px",
            }}
          >
            <h2
              style={{
                fontSize: "clamp(36px, 5vw, 52px)",
                fontWeight: 800,
                letterSpacing: "-0.03em",
                marginBottom: "20px",
                lineHeight: 1.1,
              }}
            >
              Simple,{" "}
              <span
                style={{
                  background:
                    "linear-gradient(135deg, var(--color-accent) 0%, #a78bfa 100%)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  backgroundClip: "text",
                }}
              >
                transparent
              </span>{" "}
              pricing
            </h2>
            <p
              style={{
                fontSize: "18px",
                color: "var(--color-text-muted)",
                maxWidth: 520,
                margin: "0 auto",
                lineHeight: 1.7,
              }}
            >
              Start free, scale as you grow. No hidden fees, no surprises.
            </p>
          </div>
        </AnimatedSection>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
            gap: "28px",
            maxWidth: 1100,
            margin: "0 auto",
            alignItems: "start",
          }}
        >
          <PricingCard
            id="free"
            name="Free"
            price="$0"
            period="forever"
            features={[
              "3 projects",
              "100k daily tokens",
              "Basic AI generation",
              "Community support",
              "Public deployments",
            ]}
            cta="Get Started"
            popular={false}
            delay={100}
            onCta={handleCta}
          />
          <PricingCard
            id="plus"
            name="Plus"
            price="$15"
            period="one-time"
            features={[
              "Unlimited projects",
              "1M token bucket",
              "Priority AI generation",
              "Private deployments",
              "BYOK Support",
              "Dashboard tokens tracking",
            ]}
            cta="Buy Token Pack"
            popular={true}
            delay={200}
            onCta={handleCta}
          />
          <PricingCard
            id="pro"
            name="Pro"
            price="$30"
            period="one-time"
            features={[
              "Enterprise speed",
              "5M token bucket",
              "Priority support",
              "Team collaboration",
              "Persistent Workspaces",
              "Custom Domain support",
            ]}
            cta="Scale Credits"
            popular={false}
            delay={300}
            onCta={handleCta}
          />
        </div>
      </section>

      {/* CTA Section */}
      <section
        style={{
          padding: "120px 8%",
          textAlign: "center",
          position: "relative",
        }}
      >
        <AnimatedSection>
          <div
            style={{
              maxWidth: 800,
              margin: "0 auto",
              padding: "80px 40px",
              borderRadius: "32px",
              background:
                "linear-gradient(135deg, rgba(139, 92, 246, 0.1) 0%, rgba(59, 130, 246, 0.05) 100%)",
              border: "1px solid rgba(139, 92, 246, 0.2)",
              position: "relative",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                position: "absolute",
                top: "-50%",
                left: "-20%",
                width: "60%",
                height: "200%",
                background:
                  "radial-gradient(circle, rgba(139, 92, 246, 0.1) 0%, transparent 70%)",
                pointerEvents: "none",
              }}
            />
            <h2
              style={{
                fontSize: "clamp(28px, 4vw, 40px)",
                fontWeight: 800,
                letterSpacing: "-0.03em",
                marginBottom: "16px",
                position: "relative",
              }}
            >
              Ready to build something amazing?
            </h2>
            <p
              style={{
                fontSize: "18px",
                color: "var(--color-text-muted)",
                maxWidth: 480,
                margin: "0 auto 32px",
                lineHeight: 1.6,
                position: "relative",
              }}
            >
              Join thousands of developers already building with WAGI.
            </p>
            <Link
              to={user ? "/dashboard" : "/register"}
              style={{
                background:
                  "linear-gradient(135deg, var(--color-accent) 0%, #a78bfa 100%)",
                color: "#000",
                textDecoration: "none",
                fontWeight: 600,
                padding: "18px 48px",
                borderRadius: "50px",
                fontSize: "17px",
                display: "inline-flex",
                alignItems: "center",
                gap: "10px",
                transition: "all 0.4s cubic-bezier(0.23, 1, 0.32, 1)",
                boxShadow: "0 8px 32px rgba(139, 92, 246, 0.35)",
                transform: "translateY(0) scale(1)",
                filter: "brightness(1)",
                willChange: "transform, box-shadow, filter",
              }}
              onMouseEnter={(e) => {
                const el = e.currentTarget;
                el.style.transform = "translateY(-4px) scale(1.03)";
                el.style.boxShadow = "0 20px 50px rgba(139, 92, 246, 0.5)";
                el.style.filter = "brightness(1.1)";
                const icon = el.querySelector(".gsf-icon") as HTMLElement;
                const text = el.querySelector(".gsf-text") as HTMLElement;
                if (text) text.style.transform = "translateX(-3px)";
                if (icon) icon.style.transform = "translateX(3px)";
              }}
              onMouseLeave={(e) => {
                const el = e.currentTarget;
                el.style.transform = "translateY(0) scale(1)";
                el.style.boxShadow = "0 8px 32px rgba(139, 92, 246, 0.35)";
                el.style.filter = "brightness(1)";
                const icon = el.querySelector(".gsf-icon") as HTMLElement;
                const text = el.querySelector(".gsf-text") as HTMLElement;
                if (text) text.style.transform = "translateX(0)";
                if (icon) icon.style.transform = "translateX(0)";
              }}
            >
              <span
                className="gsf-text"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  transition: "transform 0.4s cubic-bezier(0.23, 1, 0.32, 1)",
                }}
              >
                {user ? "Go to Dashboard" : "Get Started Free"}
              </span>
              <ArrowRight
                className="gsf-icon"
                size={18}
                style={{
                  transition: "transform 0.4s cubic-bezier(0.23, 1, 0.32, 1)",
                  transform: "translateX(0)",
                }}
              />
            </Link>
          </div>
        </AnimatedSection>
      </section>

      <Footer />

      <style>{`
        @media (max-width: 768px) {
          header {
            padding: 140px 6% 100px !important;
          }
          section {
            padding: 80px 6% !important;
          }
        }
      `}</style>
    </div>
  );
}
