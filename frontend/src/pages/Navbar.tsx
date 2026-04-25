import React, { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Zap, Menu, X, Sun, Moon, LogOut } from "lucide-react";
import { useTheme } from "../hooks/useTheme";
import { useAuth } from "../hooks/useAuth";

const navItems = [
  { label: "Home", section: "home" },
  { label: "Features", section: "features" },
  { label: "How it works", section: "how-it-works" },
  { label: "Pricing", section: "pricing" },
];

const NAVBAR_HEIGHT = 72;

const Navbar: React.FC = () => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [activeSection, setActiveSection] = useState("home");
  const { theme, toggleTheme } = useTheme();
  const { user, logout } = useAuth();

  useEffect(() => {
    const handleScroll = () => {
      const sections = navItems.map((item) => item.section);
      const scrollPosition = window.scrollY + NAVBAR_HEIGHT + 50;

      for (let i = sections.length - 1; i >= 0; i--) {
        const section = document.getElementById(sections[i]);
        if (section && section.offsetTop <= scrollPosition) {
          setActiveSection(sections[i]);
          break;
        }
      }
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const isActive = (section: string) => activeSection === section;

  const scrollToSection = (sectionId: string) => {
    const element = document.getElementById(sectionId);
    if (element) {
      element.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }
  };

  return (
    <nav
      style={{
        display: "flex",
        justifyContent: "space-between",
        padding: "0 8%",
        alignItems: "center",
        background: "var(--color-bg)",
        backdropFilter: "blur(20px)",
        position: "sticky",
        top: 0,
        zIndex: 1000,
        borderBottom: "1px solid var(--color-border)",
        height: NAVBAR_HEIGHT,
      }}
    >
      <div
        onClick={() => scrollToSection("home")}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          fontWeight: 700,
          fontSize: 20,
          letterSpacing: "-0.03em",
          cursor: "pointer",
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
      </div>

      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "center",
        }}
        className="desktop-nav"
      >
        {navItems.map((item) => (
          <div
            key={item.section}
            onClick={() => scrollToSection(item.section)}
            style={{
              color: isActive(item.section)
                ? "var(--color-text)"
                : "var(--color-text-muted)",
              textDecoration: "none",
              fontWeight: 500,
              fontSize: 14,
              cursor: "pointer",
              padding: "8px 16px",
              borderRadius: "var(--radius-full)",
              background: isActive(item.section)
                ? "var(--color-surface2)"
                : "transparent",
              transition: "all var(--transition)",
            }}
            onMouseEnter={(e) => {
              if (!isActive(item.section)) {
                e.currentTarget.style.background = "var(--color-surface2)";
                e.currentTarget.style.color = "var(--color-text)";
              }
            }}
            onMouseLeave={(e) => {
              if (!isActive(item.section)) {
                e.currentTarget.style.background = "transparent";
                e.currentTarget.style.color = "var(--color-text-muted)";
              }
            }}
          >
            {item.label}
          </div>
        ))}
      </div>

      <div
        style={{
          display: "flex",
          gap: 12,
          alignItems: "center",
        }}
        className="desktop-actions"
      >
        <button
          onClick={toggleTheme}
          className="btn btn-icon"
          aria-label="Toggle theme"
        >
          {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
        </button>

        {!user ? (
          <>
            <Link
              to="/login"
              style={{
                color: "var(--color-text-muted)",
                textDecoration: "none",
                fontWeight: 500,
                fontSize: 14,
                padding: "8px 16px",
                borderRadius: "var(--radius-full)",
                transition: "all var(--transition)",
                border: "1px solid transparent",
                cursor: "pointer",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = "var(--color-text)";
                e.currentTarget.style.borderColor = "var(--color-border)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = "var(--color-text-muted)";
                e.currentTarget.style.borderColor = "transparent";
              }}
            >
              Log in
            </Link>
            <Link
              to="/register"
              className="btn btn-primary"
              style={{
                padding: "10px 24px",
                fontSize: 14,
                textDecoration: "none",
              }}
            >
              Sign up
            </Link>
          </>
        ) : (
          <>
            <Link
              to="/dashboard"
              className="btn"
              style={{
                color: "var(--color-text)",
                textDecoration: "none",
                fontWeight: 500,
                fontSize: 14,
                padding: "8px 16px",
                borderRadius: "var(--radius-full)",
                border: "1px solid var(--color-border)",
                background: "var(--color-surface2)",
              }}
            >
              Dashboard
            </Link>
            <button
              onClick={logout}
              className="btn btn-icon"
              title="Log out"
              style={{ color: "var(--color-text-muted)" }}
            >
              <LogOut size={18} />
            </button>
          </>
        )}
      </div>

      <button
        type="button"
        onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
        className="btn btn-icon mobile-toggle"
        aria-label="Toggle menu"
      >
        {mobileMenuOpen ? <X size={22} /> : <Menu size={22} />}
      </button>

      {mobileMenuOpen && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            background: "var(--color-bg)",
            backdropFilter: "blur(20px)",
            borderBottom: "1px solid var(--color-border)",
            padding: "16px 8%",
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
          className="mobile-menu"
        >
          <button
            type="button"
            onClick={toggleTheme}
            className="btn"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              width: "100%",
              justifyContent: "flex-start",
              background: "transparent",
              color: "var(--color-text-muted)",
              border: "none",
              padding: "12px 16px",
              borderRadius: "var(--radius-md)",
              fontWeight: 500,
              fontSize: 15,
              cursor: "pointer",
            }}
          >
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            <span>{theme === "dark" ? "Light Mode" : "Dark Mode"}</span>
          </button>
          {navItems.map((item) => (
            <div
              key={item.section}
              onClick={() => {
                scrollToSection(item.section);
                setMobileMenuOpen(false);
              }}
              style={{
                color: isActive(item.section)
                  ? "var(--color-text)"
                  : "var(--color-text-muted)",
                textDecoration: "none",
                fontWeight: 500,
                fontSize: 15,
                cursor: "pointer",
                padding: "12px 16px",
                borderRadius: "var(--radius-md)",
                background: isActive(item.section)
                  ? "var(--color-surface2)"
                  : "transparent",
              }}
            >
              {item.label}
            </div>
          ))}
          <div
            style={{
              borderTop: "1px solid var(--color-border)",
              paddingTop: 16,
              marginTop: 8,
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            {!user ? (
              <>
                <Link
                  to="/login"
                  onClick={() => setMobileMenuOpen(false)}
                  style={{
                    color: "var(--color-text-muted)",
                    textDecoration: "none",
                    fontWeight: 500,
                    fontSize: 15,
                    padding: "12px 16px",
                    borderRadius: "var(--radius-md)",
                    border: "1px solid transparent",
                    transition: "all var(--transition)",
                    cursor: "pointer",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.color = "var(--color-text)";
                    e.currentTarget.style.borderColor = "var(--color-border)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.color = "var(--color-text-muted)";
                    e.currentTarget.style.borderColor = "transparent";
                  }}
                >
                  Log in
                </Link>
                <Link
                  to="/register"
                  onClick={() => setMobileMenuOpen(false)}
                  className="btn btn-primary"
                  style={{
                    fontSize: 15,
                    textAlign: "center",
                    textDecoration: "none",
                  }}
                >
                  Sign up
                </Link>
              </>
            ) : (
              <>
                <Link
                  to="/dashboard"
                  onClick={() => setMobileMenuOpen(false)}
                  style={{
                    color: "var(--color-text)",
                    textDecoration: "none",
                    fontWeight: 500,
                    fontSize: 15,
                    padding: "12px 16px",
                    borderRadius: "var(--radius-md)",
                    background: "var(--color-surface2)",
                    textAlign: "center",
                  }}
                >
                  Go to Dashboard
                </Link>
                <button
                  onClick={() => {
                    logout();
                    setMobileMenuOpen(false);
                  }}
                  className="btn"
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "12px 16px",
                    color: "var(--color-text-muted)",
                    justifyContent: "center",
                  }}
                >
                  <LogOut size={18} />
                  <span>Log out</span>
                </button>
              </>
            )}
          </div>
        </div>
      )}

      <style>{`
  .mobile-toggle {
    display: none !important;
  }

  @media (max-width: 1100px) {
    .desktop-nav, .desktop-actions {
      display: none !important;
    }

    .mobile-toggle {
      display: flex !important;
      align-items: center;
      justify-content: center;
    }
  }
`}</style>
    </nav>
  );
};

export default Navbar;