from __future__ import annotations


def compiled_core_paths(_project_spec=None) -> list[str]:
    return [
        "package.json",
        "vite.config.ts",
        "tsconfig.json",
        "tsconfig.node.json",
        "index.html",
        ".env",
        ".gitignore",
        "src/main.tsx",
        "src/App.tsx",
        "src/styles/variables.css",
        "src/styles/global.css",
        "src/services/api.ts",
        "src/types/index.ts",
        "server/index.ts",
        "server/db/database.ts",
    ]
