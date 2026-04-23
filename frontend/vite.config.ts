import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backendTarget = process.env.VITE_API_TARGET || "http://localhost:8080";
const enableCrossOriginIsolation = process.env.VITE_ENABLE_CROSS_ORIGIN_ISOLATION === "true";
const isolationHeaders = enableCrossOriginIsolation
  ? {
      "Cross-Origin-Embedder-Policy": "require-corp",
      "Cross-Origin-Opener-Policy": "same-origin",
    }
  : undefined;

function malformedUriGuard() {
  return {
    name: "malformed-uri-guard",
    configureServer(server: any) {
      server.middlewares.use((req: any, _res: any, next: any) => {
        const rawUrl = String(req.url || "");
        if (!rawUrl) {
          next();
          return;
        }

        try {
          decodeURI(rawUrl);
        } catch {
          const repairedUrl = rawUrl.replace(/%(?![0-9A-Fa-f]{2})/g, "%25");
          console.warn(`[vite] repaired malformed URL: ${rawUrl} -> ${repairedUrl}`);
          req.url = repairedUrl;
        }

        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [malformedUriGuard(), react()],
  server: {
    headers: isolationHeaders,
    proxy: {
      "/api": {
        target: backendTarget,
        changeOrigin: true,
      },
      "/auth": {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
  preview: {
    headers: isolationHeaders,
  },
});
