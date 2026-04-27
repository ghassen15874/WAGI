import React, { useState, useRef, ReactNode } from "react";
import { Link } from "react-router-dom";
import {
    Plus, Settings, LogOut, PanelLeft, Search, Sun, Moon, LayoutDashboard, Rocket
} from "lucide-react";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../hooks/useTheme";

interface AppLayoutProps {
    sidebarContent: ReactNode;
    navbarCenterContent?: ReactNode;
    navbarRightContent?: ReactNode;
    children: ReactNode;
    isSidebarVisible: boolean;
    setIsSidebarVisible: (visible: boolean) => void;
}

export default function AppLayout({
    sidebarContent,
    navbarCenterContent,
    navbarRightContent,
    children,
    isSidebarVisible,
    setIsSidebarVisible
}: AppLayoutProps) {
    const { user, logout } = useAuth();
    const { theme, toggleTheme } = useTheme();

    return (
        <div
            style={{
                display: "flex",
                height: "100vh",
                fontFamily: "var(--font-sans)",
                background: "var(--color-bg)",
                overflow: "hidden",
            }}
        >
            {/* Shared Sidebar */}
            <div
                style={{
                    width: isSidebarVisible ? 240 : 48,
                    minWidth: isSidebarVisible ? 240 : 48,
                    background: "var(--color-sidebar-bg)",
                    borderRight: "1px solid var(--color-sidebar-border)",
                    display: "flex",
                    flexDirection: "column",
                    flex: "0 0 auto",
                    overflowX: "clip",
                    transition: "width 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
                    alignItems: isSidebarVisible ? "stretch" : "center",
                }}
            >
                <div style={{ flex: 1, display: "flex", flexDirection: "column", overflowY: "auto", overflowX: "clip", width: "100%" }}>
                    {sidebarContent}
                </div>

                {/* Shared Sidebar Footer */}
                <div
                    style={{
                        padding: isSidebarVisible ? "12px 16px" : "12px 0",
                        display: "flex",
                        flexDirection: "column",
                        gap: 4,
                        width: "100%",
                        alignItems: isSidebarVisible ? "stretch" : "center",
                        borderTop: "1px solid var(--color-sidebar-border)",
                    }}
                >
                    {isSidebarVisible ? (
                        <Link
                            to="/dashboard"
                            style={{
                                padding: "10px 12px",
                                borderRadius: "var(--radius-md)",
                                display: "flex",
                                alignItems: "center",
                                gap: 8,
                                fontSize: 13,
                                color: "var(--color-sidebar-text)",
                                textDecoration: "none",
                                transition: "all var(--transition)",
                            }}
                            onMouseEnter={(e) => e.currentTarget.style.background = "var(--color-sidebar-item-hover)"}
                            onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                        >
                            <Settings size={16} color="var(--color-sidebar-muted)" /> Settings
                        </Link>
                    ) : (
                        <Link
                            to="/dashboard"
                            style={{
                                padding: "10px",
                                borderRadius: "var(--radius-full)",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                color: "var(--color-sidebar-text)",
                                textDecoration: "none",
                                transition: "all var(--transition)",
                            }}
                            onMouseEnter={(e) => e.currentTarget.style.background = "var(--color-sidebar-item-hover)"}
                            onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                            title="Settings"
                        >
                            <Settings size={18} color="var(--color-sidebar-muted)" />
                        </Link>
                    )}

                    {isSidebarVisible ? (
                        <Link
                            to="/dashboard?tab=billing"
                            style={{
                                padding: "10px 12px",
                                borderRadius: "var(--radius-md)",
                                display: "flex",
                                alignItems: "center",
                                gap: 8,
                                fontSize: 13,
                                color: "var(--color-sidebar-text)",
                                textDecoration: "none",
                                transition: "all var(--transition)",
                            }}
                            onMouseEnter={(e) => e.currentTarget.style.background = "var(--color-sidebar-item-hover)"}
                            onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                        >
                            <Plus size={16} color="var(--color-sidebar-muted)" /> Upgrade
                        </Link>
                    ) : (
                        <Link
                            to="/dashboard?tab=billing"
                            style={{
                                padding: "10px",
                                borderRadius: "var(--radius-full)",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                color: "var(--color-sidebar-text)",
                                textDecoration: "none",
                                transition: "all var(--transition)",
                            }}
                            onMouseEnter={(e) => e.currentTarget.style.background = "var(--color-sidebar-item-hover)"}
                            onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                            title="Upgrade"
                        >
                            <Plus size={18} color="var(--color-sidebar-muted)" />
                        </Link>
                    )}

                    <button
                        onClick={logout}
                        style={{
                            padding: isSidebarVisible ? "10px 12px" : "10px",
                            borderRadius: isSidebarVisible ? "var(--radius-md)" : "var(--radius-full)",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: isSidebarVisible ? "flex-start" : "center",
                            gap: 8,
                            fontSize: 13,
                            color: "var(--color-sidebar-text)",
                            background: "transparent",
                            border: "none",
                            cursor: "pointer",
                            textAlign: "left",
                            width: isSidebarVisible ? "100%" : "auto",
                            transition: "all var(--transition)",
                        }}
                        onMouseEnter={(e) => e.currentTarget.style.background = "var(--color-sidebar-item-hover)"}
                        onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                        title={!isSidebarVisible ? "Log out" : ""}
                    >
                        <LogOut size={isSidebarVisible ? 16 : 18} color="var(--color-sidebar-muted)" />
                        {isSidebarVisible && "Log out"}
                    </button>
                </div>
            </div>

            {/* Main Container */}
            <div
                style={{
                    flex: 1,
                    display: "flex",
                    flexDirection: "column",
                    background: "var(--color-bg)",
                    overflow: "hidden",
                    position: "relative",
                }}
            >
                {/* Shared Top Navbar */}
                <div
                    style={{
                        padding: "12px 16px",
                        display: "flex",
                        alignItems: "center",
                        gap: 12,
                        borderBottom: "1px solid var(--color-border)",
                        background: "var(--color-bg)",
                        height: 56,
                        flexShrink: 0,
                    }}
                >
                    <button
                        onClick={() => setIsSidebarVisible(!isSidebarVisible)}
                        style={{
                            background: "transparent",
                            border: "none",
                            color: "var(--color-text-muted)",
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            padding: 6,
                            borderRadius: 8,
                            transition: "all 0.2s",
                        }}
                        title={isSidebarVisible ? "Hide Sidebar" : "Show Sidebar"}
                        onMouseEnter={(e) => e.currentTarget.style.background = "var(--color-surface2)"}
                        onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                    >
                        <PanelLeft size={20} style={{ opacity: isSidebarVisible ? 1 : 0.6 }} />
                    </button>

                    <Link
                        to="/app"
                        style={{
                            fontWeight: 600,
                            fontSize: 18,
                            color: "var(--color-text)",
                            display: "flex",
                            alignItems: "center",
                            textDecoration: "none",
                            gap: 8
                        }}
                    >
                        <div style={{
                            width: 32,
                            height: 32,
                            background: "var(--gradient-accent)",
                            borderRadius: 8,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            color: "white"
                        }}>
                            <Rocket size={18} />
                        </div>
                        WAGI <span style={{ fontSize: 13, color: "var(--color-text-muted)", opacity: 0.5, marginLeft: 4 }}>platform</span>
                    </Link>

                    {navbarCenterContent}

                    <div style={{ display: "flex", gap: 8, flex: 1, justifyContent: "flex-end", alignItems: "center" }}>
                        {navbarRightContent}

                        <button
                            onClick={toggleTheme}
                            className="btn btn-ghost"
                            style={{ width: 36, height: 36, padding: 0, borderRadius: 10, display: "flex", alignItems: "center", justifyContent: "center" }}
                            title="Toggle Theme"
                        >
                            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
                        </button>

                        {user && (
                            <div
                                style={{
                                    padding: "6px 12px",
                                    background: "var(--color-surface2)",
                                    borderRadius: "var(--radius-full)",
                                    fontSize: 12,
                                    fontWeight: 500,
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 8,
                                    color: "var(--color-text-muted)"
                                }}
                            >
                                <div style={{ width: 8, height: 8, background: "var(--color-success)", borderRadius: "50%" }} />
                                {user.githubUsername || user.email.split('@')[0]}
                            </div>
                        )}
                    </div>
                </div>

                {/* Page Content Area */}
                <div style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column" }}>
                    {children}
                </div>
            </div>
        </div>
    );
}
