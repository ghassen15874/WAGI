import React from "react";

type AppErrorBoundaryState = {
  hasError: boolean;
  message: string;
};

export class AppErrorBoundary extends React.Component<React.PropsWithChildren, AppErrorBoundaryState> {
  constructor(props: React.PropsWithChildren) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { hasError: true, message: error?.message || "Unexpected application error" };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("App crashed:", error, errorInfo);
  }

  private handleReload = () => {
    window.location.reload();
  };

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--color-bg)",
          color: "var(--color-text)",
          padding: 24,
        }}
      >
        <div
          style={{
            width: "100%",
            maxWidth: 760,
            border: "1px solid var(--color-border)",
            background: "var(--color-surface)",
            borderRadius: "var(--radius-lg)",
            boxShadow: "var(--shadow-lg)",
            padding: 20,
          }}
        >
          <h2 style={{ marginBottom: 10, fontSize: 22, fontWeight: 800 }}>App Error Detected</h2>
          <p style={{ color: "var(--color-text-muted)", marginBottom: 12 }}>
            A runtime error occurred after page load.
          </p>
          <pre
            style={{
              margin: 0,
              padding: 12,
              borderRadius: "var(--radius-md)",
              background: "var(--color-surface2)",
              border: "1px solid var(--color-border)",
              color: "var(--color-error)",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontSize: 12,
            }}
          >
            {this.state.message}
          </pre>
          <button
            onClick={this.handleReload}
            className="btn btn-primary"
            style={{ marginTop: 14, padding: "10px 16px", fontSize: 13 }}
          >
            Reload App
          </button>
        </div>
      </div>
    );
  }
}

