import { Link } from "react-router-dom";
import { Check, Zap, Rocket, Building2, ArrowRight } from "lucide-react";
import Navbar from "./Navbar";

const plans = [
  {
    name: "Free",
    price: "$0",
    period: "forever",
    description: "Perfect for exploring WAGI and small projects",
    icon: <Zap size={24} />,
    features: [
      "3 projects",
      "500MB storage per project",
      "Basic AI generation",
      "Community support",
      "Public deployments",
    ],
    cta: "Get Started",
    popular: false,
  },
  {
    name: "Pro",
    price: "$29",
    period: "/month",
    description: "For developers building production apps",
    icon: <Rocket size={24} />,
    features: [
      "Unlimited projects",
      "10GB storage per project",
      "Advanced AI generation",
      "Priority support",
      "Private deployments",
      "Custom domains",
      "API access",
    ],
    cta: "Start Free Trial",
    popular: true,
  },
  {
    name: "Enterprise",
    price: "Custom",
    period: "",
    description: "For teams requiring advanced security & support",
    icon: <Building2 size={24} />,
    features: [
      "Unlimited everything",
      "Dedicated infrastructure",
      "SSO & SAML",
      "24/7 phone support",
      "Custom SLA",
      "On-premise option",
      "Dedicated account manager",
    ],
    cta: "Contact Sales",
    popular: false,
  },
];

const faqs = [
  {
    question: "Can I change plans later?",
    answer:
      "Yes! You can upgrade or downgrade your plan at any time. When upgrading, you'll get immediate access to new features. When downgrading, changes take effect at the end of your billing cycle.",
  },
  {
    question: "What payment methods do you accept?",
    answer:
      "We accept all major credit cards (Visa, Mastercard, American Express), PayPal, and bank transfers for Enterprise plans.",
  },
  {
    question: "Is there a free trial?",
    answer:
      "Yes! The Pro plan comes with a 14-day free trial. No credit card required to start. You can explore all features before committing.",
  },
  {
    question: "What happens to my projects if I cancel?",
    answer:
      "Your projects will remain accessible for 30 days after cancellation. You can export your code anytime during this period. After 30 days, projects on the free tier will be deleted.",
  },
  {
    question: "Do you offer refunds?",
    answer:
      "We offer a 30-day money-back guarantee for annual plans. Monthly plans can be cancelled anytime with no further charges.",
  },
  {
    question: "Can I use my own API keys?",
    answer:
      "Absolutely! All plans support Bring Your Own Keys (BYOK). Use your own OpenAI, Anthropic, or Groq API keys to avoid per-request charges.",
  },
];

export default function PricingPage() {
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
            <Zap size={14} /> Pricing
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
            Simple,{" "}
            <span style={{ color: "var(--color-text-muted)" }}>transparent</span>{" "}
            pricing
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
            Start free, scale as you grow. No hidden fees, no surprises.
          </p>
        </section>

        {/* Pricing Cards */}
        <section
          style={{
            padding: "40px 8% 120px",
            maxWidth: 1200,
            margin: "0 auto",
          }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
              gap: 24,
            }}
          >
            {plans.map((plan, index) => (
              <PricingCard key={index} plan={plan} />
            ))}
          </div>
        </section>

        {/* FAQ Section */}
        <section
          style={{
            padding: "80px 8%",
            background: "var(--color-surface)",
            borderTop: "1px solid var(--color-border)",
            borderBottom: "1px solid var(--color-border)",
          }}
        >
          <div style={{ maxWidth: 800, margin: "0 auto" }}>
            <h2
              style={{
                fontSize: "clamp(28px, 4vw, 36px)",
                fontWeight: 800,
                textAlign: "center",
                marginBottom: 48,
                letterSpacing: "-0.02em",
              }}
            >
              Frequently asked questions
            </h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {faqs.map((faq, index) => (
                <details
                  key={index}
                  style={{
                    padding: 24,
                    borderRadius: 16,
                    background: "var(--color-bg)",
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
          </div>
        </section>

        {/* CTA Section */}
        <section
          style={{
            padding: "100px 8%",
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
            Still have questions?
          </h2>
          <p
            style={{
              fontSize: 18,
              color: "var(--color-text-muted)",
              maxWidth: 500,
              margin: "0 auto 32px",
            }}
          >
            Can't find the answer you're looking for? Chat with our team.
          </p>
          <Link
            to="/register"
            className="btn btn-light"
            style={{ textDecoration: "none", padding: "16px 40px", fontSize: 16 }}
          >
            Get Started <Zap size={18} />
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

function PricingCard({ plan }: { plan: typeof plans[0] }) {
  return (
    <div
      style={{
        padding: 40,
        borderRadius: 24,
        background: "var(--color-surface)",
        border: plan.popular
          ? "2px solid var(--color-accent)"
          : "1px solid var(--color-border)",
        position: "relative",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {plan.popular && (
        <div
          style={{
            position: "absolute",
            top: -12,
            left: "50%",
            transform: "translateX(-50%)",
            background: "var(--color-accent)",
            color: "#000",
            padding: "6px 16px",
            borderRadius: 20,
            fontSize: 12,
            fontWeight: 700,
          }}
        >
          MOST POPULAR
        </div>
      )}

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 24,
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
            color: "var(--color-accent)",
          }}
        >
          {plan.icon}
        </div>
        <div>
          <h3 style={{ fontSize: 20, fontWeight: 700 }}>{plan.name}</h3>
          <p style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
            {plan.description}
          </p>
        </div>
      </div>

      <div style={{ marginBottom: 24 }}>
        <span
          style={{
            fontSize: 48,
            fontWeight: 800,
            letterSpacing: "-0.02em",
          }}
        >
          {plan.price}
        </span>
        {plan.period && (
          <span style={{ fontSize: 16, color: "var(--color-text-muted)" }}>
            {plan.period}
          </span>
        )}
      </div>

      <Link
        to="/register"
        className={`btn ${plan.popular ? "btn-primary" : "btn-dark"}`}
        style={{ textDecoration: "none", marginBottom: 32, display: "block" }}
      >
        {plan.cta}
      </Link>

      <ul
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "flex",
          flexDirection: "column",
          gap: 12,
          flex: 1,
        }}
      >
        {plan.features.map((feature, index) => (
          <li
            key={index}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              fontSize: 14,
            }}
          >
            <Check
              size={18}
              style={{ color: "var(--color-accent)", flexShrink: 0 }}
            />
            {feature}
          </li>
        ))}
      </ul>
    </div>
  );
}