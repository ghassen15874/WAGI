import React from "react";
import { Link } from "react-router-dom";
import { Zap, Github, Twitter, Linkedin, Youtube } from "lucide-react";

interface FooterLink {
  label: string;
  href: string;
  isExternal?: boolean;
}

interface FooterColumn {
  title: string;
  links: FooterLink[];
}

const footerColumns: FooterColumn[] = [
  {
    title: "Product",
    links: [
      { label: "Features", href: "#features" },
      { label: "Pricing", href: "#pricing" },
      { label: "How it works", href: "#how-it-works" },
    ],
  },
  {
    title: "Account",
    links: [
      { label: "Log in", href: "/login" },
      { label: "Sign up", href: "/register" },
    ],
  },
  {
    title: "Resources",
    links: [
      { label: "Documentation", href: "#" },
      { label: "API Reference", href: "#" },
      { label: "Changelog", href: "#" },
    ],
  },
];

const socialLinks = [
  { icon: <Github size={18} />, label: "GitHub", href: "https://github.com" },
  { icon: <Twitter size={18} />, label: "Twitter", href: "https://twitter.com" },
  { icon: <Linkedin size={18} />, label: "LinkedIn", href: "https://linkedin.com" },
  { icon: <Youtube size={18} />, label: "YouTube", href: "https://youtube.com" },
];

const Footer: React.FC = () => {
  const currentYear = new Date().getFullYear();

  const scrollToSection = (href: string) => {
    if (href.startsWith("#") && href.length > 1) {
      const element = document.getElementById(href.slice(1));
      if (element) {
        element.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
  };

  return (
    <footer
      style={{
        background: "var(--color-surface)",
        borderTop: "1px solid var(--color-border)",
        padding: "80px 8% 32px",
      }}
    >
      <div style={{ maxWidth: 1200, margin: "0 auto" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "2fr repeat(3, 1fr)",
            gap: 48,
            marginBottom: 64,
          }}
          className="footer-grid"
        >
          {/* Brand Column */}
          <div>
            <Link
              to="/"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                fontWeight: 700,
                fontSize: 20,
                letterSpacing: "-0.03em",
                marginBottom: 16,
                textDecoration: "none",
                color: "inherit",
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
            <p
              style={{
                color: "var(--color-text-muted)",
                fontSize: 14,
                lineHeight: 1.7,
                maxWidth: 280,
                marginBottom: 24,
              }}
            >
              The future of automated development. Think. Prompt. Build.
              Deploy. All in one place.
            </p>
            <div style={{ display: "flex", gap: 8 }}>
              {socialLinks.map((social) => (
                <a
                  key={social.label}
                  href={social.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={social.label}
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: "var(--radius-md)",
                    background: "var(--color-surface2)",
                    border: "1px solid var(--color-border)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "var(--color-text-muted)",
                    textDecoration: "none",
                    transition: "all var(--transition)",
                  }}
                >
                  {social.icon}
                </a>
              ))}
            </div>
          </div>

          {/* Link Columns */}
          {footerColumns.map((column) => (
            <div key={column.title}>
              <h4
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  color: "var(--color-text)",
                  marginBottom: 16,
                  textTransform: "uppercase",
                  letterSpacing: "0.08em",
                }}
              >
                {column.title}
              </h4>
              <ul
                style={{
                  listStyle: "none",
                  padding: 0,
                  margin: 0,
                  display: "flex",
                  flexDirection: "column",
                  gap: 10,
                }}
              >
                {column.links.map((link) => (
                  <li key={link.label}>
                    {link.href.startsWith("#") && link.href.length > 1 ? (
                      <span
                        onClick={() => scrollToSection(link.href)}
                        style={{
                          color: "var(--color-text-muted)",
                          textDecoration: "none",
                          fontSize: 14,
                          cursor: "pointer",
                          transition: "color var(--transition)",
                        }}
                      >
                        {link.label}
                      </span>
                    ) : (
                      <Link
                        to={link.href}
                        style={{
                          color: "var(--color-text-muted)",
                          textDecoration: "none",
                          fontSize: 14,
                          transition: "color var(--transition)",
                        }}
                      >
                        {link.label}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {/* Bottom Copyright */}
        <div
          style={{
            borderTop: "1px solid var(--color-border)",
            paddingTop: 24,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: 16,
          }}
          className="footer-bottom"
        >
          <p
            style={{
              color: "var(--color-text-muted2)",
              fontSize: 13,
              margin: 0,
            }}
          >
            © {currentYear} WAGI. All rights reserved.
          </p>
          <div style={{ display: "flex", gap: 24 }}>
            <a
              href="#"
              style={{
                color: "var(--color-text-muted)",
                textDecoration: "none",
                fontSize: 13,
              }}
            >
              Privacy Policy
            </a>
            <a
              href="#"
              style={{
                color: "var(--color-text-muted)",
                textDecoration: "none",
                fontSize: 13,
              }}
            >
              Terms of Service
            </a>
          </div>
        </div>
      </div>

      <style>{`
        @media (max-width: 900px) {
          .footer-grid {
            grid-template-columns: repeat(2, 1fr) !important;
          }
        }
        @media (max-width: 600px) {
          .footer-grid {
            grid-template-columns: 1fr !important;
            gap: 32px !important;
          }
          .footer-bottom {
            flex-direction: column;
            text-align: center;
          }
        }
      `}</style>
    </footer>
  );
};

export default Footer;