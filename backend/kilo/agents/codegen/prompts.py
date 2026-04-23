"""
System prompt builder — INSPIRED BY refs/cline/src/core/prompts/system.ts
Cline uses XML-formatted tool definitions and strict rules for the AI.
"""
import json
import re
from typing import Any

from ...shared.design.models import DesignSystem

# 1. Define ticks at the top to prevent truncation
ticks = "`" * 3

# 2. Keep static templates at the top
MANDATORY_FILES_TEMPLATE = """
## MANDATORY FILES — Write ALL 14 before finishing

This is a FULL-STACK React + Vite + Express project.
The frontend calls the Express API. Express stores data in SQLite.

### vite.config.ts (CRITICAL: MUST INCLUDE PROXY)
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  build: {
    minify: false
  },
  server: {
    port: 3000,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:3001',
        changeOrigin: true
      }
    }
  },
  preview: {
    port: 3000,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:3001',
        changeOrigin: true
      }
    }
  }
})

### package.json (CRITICAL SCRIPT FIX)
- The scripts section MUST use tsx to run the server:
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "server": "node --import tsx server/index.ts"
  }
- CRITICAL: The `server` script must be EXACTLY `node --import tsx server/index.ts`. Do NOT use `tsx server/index.ts`, `npm run dev`, `server/app.ts`, or `server/server.ts`.
- CRITICAL: You MUST add "type": "module" to package.json.
- CRITICAL: For SQLite, use "better-sqlite3": "^12.2.0" in dependencies.
- CRITICAL: If using `better-sqlite3`, package.json MUST include `"postinstall": "npm rebuild better-sqlite3"` in scripts.
- CRITICAL: For UI/Design, include "lucide-react", "recharts", "framer-motion", "clsx", "tailwind-merge" in dependencies.
- CRITICAL: Add `"esbuild": "0.25.0"` to `devDependencies` for Node 22 compatibility.
- CRITICAL: This pipeline standardizes on `better-sqlite3` ONLY. NEVER use `sqlite3`.
- CRITICAL: NEVER add competing database stacks such as `prisma`, `sequelize`, `mongoose`, `knex`, or `pg`.
- CRITICAL: Do NOT use old better-sqlite3 9.x versions because they break on Node 22 in this environment.
- CRITICAL: Keep `axios` in dependencies because this pipeline standardizes on a shared axios client.
- RULE — SQLITE SEED DATA:
  - `better-sqlite3` does NOT accept JavaScript booleans as bind values.
  - ALWAYS use integers for boolean columns in seed data and prepared statements.
  - ✅ CORRECT: `featured: 1`, `active: 0`
  - ❌ WRONG: `featured: true`, `active: false`
  - This applies to all `insert/run()` calls, transactions, and seed arrays.

### index.html — must have <div id="root"> and <script type="module" src="/src/main.tsx">
### src/main.tsx — import React from 'react'; import { createRoot } from 'react-dom/client'
### src/App.tsx — main app component
### src/styles/variables.css — CSS custom properties from the design system
### src/styles/global.css — shared global styles and resets
### tsconfig.json — MUST use Vite-friendly frontend settings and MUST include ONLY ["src"]
### tsconfig.node.json — MUST include ONLY ["vite.config.ts"]. NEVER set "noEmit": true in this file if it is referenced by a composite project.
- CRITICAL TS RULE: Prefer a standalone `tsconfig.node.json` (no `extends`) so it does not inherit frontend-only flags.
- CRITICAL TS RULE: In `tsconfig.node.json`, use `"composite": true` and `"noEmit": false` (or omit noEmit), and NEVER set `"allowImportingTsExtensions": true`.
### server/index.ts — Express on port 3001, /api routes (100% ESM ONLY)
### server/db/database.ts — SQLite with better-sqlite3@^12.2.0 (100% ESM ONLY, 30 seed rows)

### FRONTEND SAFETY (CRITICAL)
- NEVER assume data (e.g. posts, items) is defined. Use default values: const { posts = [] } = usePosts();
- ALWAYS handle loading states: if (loading) return <div>Loading...</div>
- COMPONENT PROP SAFETY: If a component (like PostList) requires a prop, the parent MUST fetch and pass it.

COMPONENT QUALITY RULES:
- NEVER write empty components or placeholders.
- ALL React files containing JSX MUST use the .tsx extension.
- REAL PHOTO RULE:
  - Use real HTTPS photo URLs relevant to the actual site/domain content (dynamic per project).
  - NEVER use fake placeholders such as `/placeholder.jpg`, `/images/example.jpg`, or `via.placeholder.com` unless the file is actually created in `public/`.
  - For seed data image fields (`image`, `image_url`, `imageUrl`, `coverImage`), provide real photo URLs that match each record/topic.
- RULE — IMPORT EXTENSIONS:
  - This system generates ONLY `.tsx` and `.ts` files. Never `.jsx` or `.js` for React components.
  - ALL imports of local components, hooks, and pages MUST use `.tsx` extension.
  - ✅ CORRECT: `import Hero from '../components/Hero.tsx'`
  - ✅ CORRECT: `import { useProducts } from '../hooks/useProducts.tsx'`
  - ❌ WRONG: `import Hero from '../components/Hero.jsx'`
  - ❌ WRONG: `import { useProducts } from '../hooks/useProducts.jsx'`
- Use the axios 'api' wrapper from src/services/api.ts for all requests. Do not use fetch().
- `src/services/api.ts` is the ONLY frontend file allowed to import `axios` directly. Other frontend files must import the shared `api` client or service modules built on top of it.
- AUTH SERVICE SAFETY: login() and register() from authService.ts MUST take a single object (LoginCredentials/RegisterCredentials). Component calls MUST wrap arguments in {}.
- AUTH CONTEXT CONTRACT: `AuthContext` login() MUST accept a credentials object (`LoginCredentials`) and call the authService internally. It MUST NOT accept separate `(token: string, user: User)` arguments. After a successful login it should internally call `authService.login(credentials)` and then update context state.
- AUTH TYPES: `src/types/index.ts` MUST export `LoginCredentials` and (if registration is enabled) `RegisterCredentials` interfaces so that `Login.tsx`, `Signup.tsx`, and auth services can all import from one source.

BACKEND RULES (CRITICAL):
- server/ files MUST use 100% ESM (import and export). NEVER use require() or module.exports.
- ABSOLUTE RULE — SERVER FILES ESM PURITY:
  - All files under server/ MUST use 100% ESM syntax.
  - NEVER use require() anywhere, including inside functions.
  - ALWAYS declare imports at the top of the file.
  - NEVER use module.exports; use export / export default.
  - Violation will cause immediate build failure.
- RULE — ROUTE FILE IMPORTS:
  - Route files in `server/routes/` MUST import controllers using `../controllers/`, never `./`.
  - ✅ CORRECT: `import { list } from '../controllers/productController.js'`
  - ❌ WRONG: `import { list } from './productController.js'`
  - `routes/` and `controllers/` are sibling directories under `server/`.
- `server/routes/*.ts` files MUST import controllers from `../controllers/...`, never `./SomeController`.
- `server/controllers/*.ts` files MUST import the database from `../db/database.js`. Note the explicit execution extension in imports.
- EVERY method referenced in routes/*.ts MUST be exported from its controller using:
  export const methodName = async (req, res) => { ... };
- Port MUST be 3001. vite.config.ts MUST keep both server.proxy and preview.proxy targeting http://localhost:3001.
- CRITICAL RULE — VITE PROXY PORT:
  - When writing or fixing vite.config.ts, ALWAYS use port 3001 for proxy targets.
  - server.proxy['/api'].target MUST be 'http://localhost:3001'.
  - preview.proxy['/api'].target MUST be 'http://localhost:3001'.
  - NEVER use port 3000 as the backend proxy target. Port 3000 is reserved for frontend dev/preview.
- CRITICAL: tsconfig.json MUST NOT include "server" because the frontend build command is `tsc && vite build`.

BUILD / RUNTIME DISCIPLINE (CRITICAL):
- NO IMAGINARY FILES: NEVER require() or import files that do not exist in the project.
- DATABASE INITIALIZATION: `server/db/database.ts` MUST execute all CREATE TABLE statements at module load time before the app serves requests.
- FULL-STACK CONNECTIVITY: If you implement backend Auth or CRUD routes, you MUST also create the corresponding frontend pages/forms/components now. Do not leave features half-wired.
- REAL AUTH IMPLEMENTATION (CRITICAL): If auth is enabled, login/register must be backed by real persistence and verification.
  - Login must query a real user record (DB/ORM), not return hardcoded success.
  - Registration must persist a new user record when registration is enabled.
  - For token auth modes, generate token server-side (JWT/signing utility) and return it.
  - Never return demo/mock tokens such as `"demo-token"` / `"fake-token"` or fake static users.
  - If password-based auth is used, verify hashed passwords (bcrypt/argon2); never compare plain password literals.
- FRONTEND ROUTE TARGETS (CRITICAL): Do not generate links/navigation to routes that are not declared in `src/App.tsx`.
  - If you link to `/profile`, `/feed`, `/dashboard`, `/create`, or `/posts/new`, you MUST register the route and provide the page in the same run.
- AUTH UI STATE (CRITICAL): For auth-enabled projects, Login/Register CTAs in shared surfaces (Navbar/Home/Hero) must be conditional on auth state (`user`/`isAuthenticated`) so they do not appear after login.
- ROOT PROVIDERS: If you create `AuthProvider` or another app-wide provider, wrap `<App />` in `src/main.tsx`. Keep `App.tsx` focused on layout and routes.
- SPA ROUTING: Express should serve the frontend app for non-API routes and keep `/api/*` for JSON endpoints only.
- MIDDLEWARE NAMING: The name imported from middleware MUST match the actual export style of that middleware file.
- BACKEND STARTUP: In this environment, prefer `node --import tsx server/index.ts` for the package.json `server` script.
"""

STRICT_GENERATION_RULES_TEMPLATE = """
## STRICT GENERATION RULES — FOLLOW THESE BEFORE WRITING ANY FILE

### 0. PHASED EXECUTION PLANNING (CRITICAL)
Before making ANY change, you MUST mentally map out a structured phase plan:
- **Phase 1: Detect Scope**: Identify the source file, importing files, controllers, services, hooks, pages, schemas, and types sharing the same entity representation. Build a full dependency map.
- **Phase 2: Classify the Issue**: Is it a VALIDATOR_FALSE_POSITIVE, IMPORT_SITE_ERROR, MODULE_EXPORT_MISSING, CONVENTION_MISMATCH, API_CONTRACT_DRIFT, GENERATION_ERROR, or TRIAGE_STRATEGY_ERROR?
- **Phase 3: Define Repair Set**: Define ALL files that must be updated together. Never fix only one file if the issue spans multiple files.
- **Phase 4: Apply Coordinated Changes**: Apply edits in order (Types → Controllers → Services → Hooks → Pages).
- **Phase 5: Cross-File Validation**: Ensure imports match exports, hooks come from `react`, and DTOs match the contract.
- **Phase 6: Final Consistency Pass**: Ensure project-wide naming, export patterns, and mapper usage are completely uniform.

### 1. BLUEPRINT-DRIVEN ANTI-FRAGMENTATION RULE (CRITICAL)
Before any generation or fix, you MUST prioritize the MASTER BLUEPRINT CONTRACT as your primary planning source, treating any local utils/spec fragments as strictly transitional. You MUST ask yourself: 👉 "Which contract node does this belong to? Which files share the same blueprint batch? Which files consume the public contract?" Do not generate isolated fixes. You must regenerate the full coordinated blueprint contract cluster.

### 2. CONTRACT LOCK (MOST IMPORTANT)
- Before writing frontend hooks/components/pages, decide the EXACT field names for each resource and keep them identical everywhere.
- The SAME resource MUST NOT use mixed naming styles across files.
- Example of FORBIDDEN mixing:
  - `createdAt` in one file and `created_at` in another
  - `categoryName` in one file and `category_name` in another
  - `coverImage` in one file and `image_url` in another
- Do NOT add diagnostic comments that restate both naming styles, such as `createdAt vs created_at`.
- Comments should describe implementation intent, not validator strategy or alternate contract variants.
- If the backend uses snake_case database columns, either:
  - expose snake_case consistently to the frontend, OR
  - alias the SQL response to a camelCase contract consistently.
- Pick ONE PUBLIC contract and use it in:
  - controllers (use `toPublicModelName(row)` functions to map DB results)
  - route responses
  - `src/types/index.ts`
  - hooks
  - pages
  - components
- Raw database schema column names may stay snake_case. Do NOT rewrite DB column names just to match frontend naming.
- MAPPERS: If mapping is needed, ALWAYS write a explicit mapper function starting with `toPublic` in the controller.
  Example pattern:
  ```javascript
  function toPublicPost(row) {
    return {
      id: row.id,
      title: row.title,
      categoryId: row.category_id,
      createdAt: row.created_at,
      updatedAt: row.updated_at
    };
  }
  ```
### 2. IMPORT SOURCE AND SERVICE MODULE CONVENTIONS
- `src/types/index.ts` is the frontend source of truth for shared resource shapes.
- Hooks and components MUST import shared types from `src/types/index.ts` instead of redefining competing interfaces.
- React built-in hooks (useState, useEffect, useMemo, useContext, useRef, useCallback) MUST ONLY be imported from 'react'. Example:
  `import { useEffect, useState } from "react";`
- NEVER import React hooks from service files, other custom hooks, or utility files.
- SERVICE EXPORTS: Use ONE consistent export convention per service. Either use ONLY named exports (`export async function list(...)`) OR a single default export (`const srv = { list }; export default srv;`). Do NOT mix export styles in the same service.
- When importing from a service, match the service's export style. Do NOT assume a default export exists if the service only uses named exports.

### 3. DATABASE / CONTROLLER ALIGNMENT
- Every SQL query MUST use real column names that actually exist in `server/db/database.ts`.
- If a table defines `category_id`, queries MUST NOT use `categoryId`.
- If a table defines `image_url`, queries MUST NOT use `coverImage`.
- If controllers need a friendlier response shape, they MUST alias columns explicitly in SQL.
- Prefer camelCase for the public JSON/TypeScript contract and keep snake_case inside raw SQL/database definitions.
- SQL JOIN ALIAS DISCIPLINE (CRITICAL):
  - If you alias a table (`posts p`, `users u`, `comments c`), consistently reference columns via that alias (`p.id`, `u.name`, `c.post_id`).
  - NEVER mix aliased and bare-table references in the same query (`p.id` with `posts.title`).
  - NEVER write join filters in `WHERE` that should be in `ON`.
  - ✅ `JOIN users u ON u.id = p.user_id`
  - ✅ `LEFT JOIN comments c ON c.post_id = p.id`
  - ❌ `FROM posts JOIN users JOIN comments WHERE comments.post_id = p.id`
- SQL STRING DISCIPLINE: Every call to `db.exec(...)` or `db.prepare(...)` MUST receive a REAL SQL string wrapped in backticks, single quotes, or double quotes.
- FORBIDDEN: `db.prepare( INSERT INTO ... )`, `db.exec( CREATE TABLE ... )`, or any raw unquoted SQL tokens.
- DRIVER DISCIPLINE: For SQLite in this pipeline, use `better-sqlite3` only with synchronous `db.prepare(...).get/all/run()` access. Never mix callback-style `sqlite3` patterns with `better-sqlite3`.

### 4. API PATH DISCIPLINE
- If `src/services/api.ts` uses `baseURL: '/api'`, then all app calls MUST use relative resource paths like:
  - `api.get('/posts')`
  - `api.post('/auth/login')`
- NEVER call `api.get('/api/posts')` when the base URL already contains `/api`.
- Keep exactly one `/api` prefix in the final request URL.
- HTTP CLIENT LOCK: This pipeline standardizes on AXIOS ONLY through `src/services/api.ts`. Do NOT mix `fetch()` and axios in the generated app. Do NOT import axios directly in pages/components/hooks.

### 4.5. API RESPONSE ENVELOPE DISCIPLINE
- Decide the response envelope once and keep it consistent across controllers, services, hooks, pages, and shared types.
- If a backend controller returns `{ success, data }`, frontend services/hooks/pages MUST unwrap `response.data.data`.
- If the frontend expects raw arrays/objects from `response.data`, backend controllers MUST return raw arrays/objects instead of wrapping them.
- NEVER mix wrapped backend responses with raw frontend reads for the same route.

### 5. ROUTE REGISTRATION DISCIPLINE
- Every backend controller that exists for a page/hook must be mounted in `server/index.ts`.
- If you create `statsController.ts`, you MUST also create/register its route file.
- Do not leave orphan controllers or orphan pages.

### 7. DESIGN SYSTEM CONTINUITY (CRITICAL)
- STANDARDIZED TOKENS: You MUST use the following token names for Tailwind classes to match the generated variables.css:
  - `text-foreground` (for primary text)
  - `bg-background` (for page backgrounds)
  - `bg-card` (for glassmorphic/card backgrounds)
  - `border-border` (for borders)
  - `text-muted-foreground` (for labels/secondary text)
- GLASSMORPHISM: When requested, use `bg-card/50 backdrop-blur-md border-border/50` patterns.
- THEME CONSISTENCY: Every file in a batch MUST use the SAME design tokens. Do NOT invent new colors or classes (e.g. `text-white/80` instead of `text-muted-foreground`).

### 7. BUILD-FIRST DISCIPLINE
- Generated code must be internally consistent before styling polish.
- Prefer a plain working implementation over a stylish but inconsistent one.
- Do not invent fields, routes, controllers, or imports that are not backed by the project structure.

### 8. NO PARTIAL PATCH THINKING
- When fixing or generating a file, think through the connected files that must agree with it.
- If you change a resource contract, update all affected files in the same batch.
- Never "fix" a symptom in one file while leaving the type/schema/API mismatch untouched.

### 9. EXPLICIT FILE OUTPUT DISCIPLINE
- Every generated file MUST declare its exact path explicitly with `// FILE: relative/path.ext`.
- If you are not sure which file a block belongs to, do NOT output that block yet.
- Do NOT rely on the parser to infer a filename from code content.
- Prefer the smallest complete set of files that satisfies the request.
- Do NOT add filler files, duplicate components, or placeholder pages just to make the project look larger.

### 9.5. CSS RUNTIME DISCIPLINE (CRITICAL)
- Tailwind is fully available, and you MUST use Tailwind utility classes for all structural styling, layout, typography, and spacing.
- DO NOT invent custom semantic CSS classes unless strictly necessary. Rely on Tailwind classes.
- To integrate the user's custom color palettes (which are generated into `src/styles/variables.css` as `--color-primary`, etc.), you MUST use Tailwind arbitrary values where needed: e.g. `bg-[var(--color-primary)]` or `text-[var(--color-text)]`.
- Use a rich, highly coordinated color scheme. The design must look professional, coherent, and premium.

### 9.6. NO INVENTED PERSONA DATA (CRITICAL)
- Do NOT invent specific first/last names, email addresses, phone numbers, social handles, company names, or client brands unless the user prompt explicitly provides them.
- For portfolio and creative sites without user-provided identity details, use neutral, product-level copy such as "Creative Portfolio", "Selected Work", or "Get in touch".
- Do not fabricate personal bios or contact details that were never requested.

### 9.7. SINGLE-STACK LOCK (CRITICAL)
- Use ONE backend module system: 100% ESM (import/export) only for `server/`.
- Use ONE SQLite driver: `better-sqlite3@^12.2.0` only.
- Use ONE frontend request client: axios only, through `src/services/api.ts`.
- Use ONE public API response contract per route.
- Use ONE canonical backend entrypoint: `server/index.ts`.
- If any fix would introduce a second stack, second driver, second client, second entrypoint, or second response shape, it is WRONG. Rewrite the existing owner files instead.

### 10. EXECUTION CONTRACT DISCIPLINE
- The planner's execution contract is the architecture source of truth for this run.
- Follow the declared product type, pages, API resources, auth mode, and acceptance checks.
- You may improve implementation quality, UX, naming, and composition, but do NOT invent routes/pages/resources outside the execution contract unless another file in the current batch strictly requires them.
- Keep the final code dynamic and product-specific, but keep the architecture consistent with the execution contract.

### 11. INFRASTRUCTURE CONTRACT DISCIPLINE
- Some core infrastructure files may already be completed by earlier execution units before your turn.
- Do NOT try to rewrite those completed scaffold files unless the current batch explicitly includes them.
- Only core infrastructure files should be treated as shared contract anchors, especially:
  - `package.json`
  - `vite.config.ts`
  - `tsconfig*.json`
  - `index.html`
  - `src/main.tsx`
  - `src/App.tsx`
  - `src/services/api.ts`
  - `server/index.ts`
- Feature/domain files like auth flows, resource routes/controllers, pages, hooks, and business logic should stay product-specific to the user's request unless the current batch says otherwise.
- When those files already exist, treat them as the source of truth and build compatible pages/components around them.
- Match the contracts expected by the shared infrastructure:
  - page files under `src/pages/` should default export the page component matching the filename
  - shared layout components like `Navbar` and `Footer` should default export their component
  - if auth is enabled, expose one clear shared auth API that the related pages/components consistently use
  - do not import `useAuth` from `src/context/AuthContext.tsx` unless that file explicitly exports `useAuth`; otherwise import it from its real owner (for example `src/hooks/useAuth.tsx`)
  - if hooks, pages, or services import `Post`, `Category`, `User`, or other shared resource types, those symbols must exist in `src/types/index.ts`
  - backend route files should use ESM `export default router`

### 12. AUTH SHAPE DISCIPLINE
- Do NOT assume auth is email/password unless the user request or execution contract says so.
- Support the requested auth identifier and flow shape, such as phone number, username, email, magic link, or admin-only login.
- Keep the auth request payload, backend controller fields, shared types, and frontend forms consistent with that chosen auth shape.
- If the frontend auth layer stores `token` and `user`, then backend login/register responses MUST return `{ token, user }` consistently.

### 13. ROOT PROVIDER DISCIPLINE
- If a hook throws `useX must be used within a XProvider`, then any app-wide consumer of that hook MUST be wrapped by `<XProvider>` in `src/main.tsx` or `src/App.tsx`.
- If `Navbar`, `Footer`, `AdminRoute`, or `App.tsx` uses such a hook, treat that provider as app-wide and mount it at the root.
"""

def _design_signal_text(design: DesignSystem) -> str:
    return " ".join(
        filter(
            None,
            [
                getattr(design, "category", ""),
                getattr(getattr(design, "pattern", None), "name", ""),
                str(getattr(getattr(design, "pattern", None), "sections", "")),
                getattr(getattr(design, "style", None), "name", ""),
                getattr(getattr(design, "style", None), "best_for", ""),
                getattr(getattr(design, "style", None), "keywords", ""),
                getattr(getattr(design, "typography", None), "mood", ""),
                getattr(getattr(design, "typography", None), "best_for", ""),
            ],
        )
    ).lower()

def _is_mobile_app_design(design: DesignSystem) -> bool:
    """Return True only when the selected design clearly targets a mobile app."""
    haystack = _design_signal_text(design)
    app_terms = (
        "mobile app",
        "ios app",
        "android app",
        "native app",
        "app store",
        "play store",
        "download app",
        "install app",
        "react native",
        "expo",
    )
    return any(term in haystack for term in app_terms)


def _design_cluster(design: DesignSystem) -> str:
    haystack = _design_signal_text(design)
    clusters = {
        "editorial": ("blog", "news", "media", "magazine", "editorial", "content", "newsletter"),
        "portfolio": ("portfolio", "creative", "photographer", "designer", "studio", "agency", "artist"),
        "commerce": ("commerce", "store", "shop", "catalog", "marketplace", "retail", "product"),
        "dashboard": ("dashboard", "analytics", "saas", "admin", "data", "metrics", "operations"),
        "service": ("spa", "wellness", "beauty", "salon", "clinic", "booking", "appointment", "restaurant", "hotel"),
    }
    for cluster, keywords in clusters.items():
        if any(keyword in haystack for keyword in keywords):
            return cluster
    return ""


def _extract_google_stylesheet_url(design: DesignSystem) -> str:
    typography = getattr(design, "typography", None)
    if not typography:
        return ""

    css_import = str(getattr(typography, "css_import", "") or "").strip()
    match = re.search(r"https://fonts\.googleapis\.com/[^'\"\s)]+", css_import)
    if match:
        return match.group(0)

    google_url = str(getattr(typography, "google_fonts_url", "") or "").strip()
    if "fonts.googleapis.com" in google_url:
        return google_url
    return ""


def _build_visual_direction(design: DesignSystem) -> str:
    category = getattr(design, "category", "General site")
    pattern = getattr(getattr(design, "pattern", None), "name", "Structured landing")
    sections = getattr(getattr(design, "pattern", None), "sections", "")
    color_strategy = getattr(getattr(design, "pattern", None), "color_strategy", "") or getattr(getattr(design, "colors", None), "notes", "")
    style_name = getattr(getattr(design, "style", None), "name", "")
    typography_mood = getattr(getattr(design, "typography", None), "mood", "")
    cluster = _design_cluster(design)

    shared_lines = [
        "### VISUAL TRANSLATION RULES",
        f"- Build the page as a {category} experience, not a generic template.",
        f"- Treat `{pattern}` as the real layout skeleton. Follow this section rhythm: {sections or 'Hero > Features > CTA'}.",
        f"- Let the chosen palette drive the page mood. Apply this color strategy intentionally: {color_strategy or 'Use the background/text pair as the base, with primary/secondary reserved for focal moments and CTA emphasis.'}",
        f"- Typography should visibly reflect `{style_name}` and the mood `{typography_mood or 'clean, product-specific hierarchy'}`.",
        "- Do NOT reuse the same sticky primary navbar, diagonal blue hero gradient, and orange CTA formula across unrelated products.",
        "- Use background surfaces, section contrast, card treatments, borders, imagery, and spacing to express the design system, not only button colors.",
    ]

    cluster_lines = {
        "editorial": [
            "- For editorial/content products, prioritize masthead-style hierarchy, category navigation, article or story cards, strong reading rhythm, and typography-led sections.",
            "- Editorial pages should feel content-first. Avoid download buttons, device frames, or app-store marketing UI.",
        ],
        "portfolio": [
            "- For portfolio/creative products, prioritize image-led storytelling, project showcases, case-study rhythm, and bolder composition than a standard SaaS landing page.",
            "- Portfolio CTAs should stay restrained and credible; the work itself should do most of the selling.",
        ],
        "commerce": [
            "- For commerce/catalog products, prioritize category browsing, product merchandising, trust markers, pricing clarity, and purchase intent over abstract marketing filler.",
            "- Product grids, category strips, offers, and trust/support sections should feel native to retail rather than app-promo UI.",
        ],
        "dashboard": [
            "- For dashboards/admin products, prioritize data density, panels, charts, filters, status chips, and clear operational hierarchy over oversized marketing hero sections.",
            "- Dashboard surfaces should rely more on cards, tables, and information grouping than on decorative gradients.",
        ],
        "service": [
            "- For service/booking products, prioritize trust, benefits, testimonials, booking/contact actions, amenities, and local/social proof.",
            "- Service websites should feel grounded and credible, not like app-launch pages.",
        ],
    }

    if _is_mobile_app_design(design):
        shared_lines.append("- Because this product is explicitly app-oriented, device mockups or install CTAs are allowed only if they match the chosen pattern.")

    shared_lines.extend(cluster_lines.get(cluster, []))
    return "\n".join(shared_lines)


def build_anti_patterns(design: DesignSystem) -> str:
    """Generate anti-pattern guidance from the design system plus platform guardrails."""
    design_anti_patterns = (design.anti_patterns or "").strip()
    design_anti_patterns_block = f"{design_anti_patterns}\n" if design_anti_patterns else ""
    app_guardrails = ""

    if not _is_mobile_app_design(design):
        app_guardrails = (
            "- Unless the selected product is explicitly a mobile app, DO NOT generate `Download App`, `App Store`, `Play Store`, install banners, QR codes, star ratings, or device mockups.\n"
            "- Match navigation labels, hero content, and CTA copy to the chosen site type instead of defaulting to app-marketing UI.\n"
        )

    return f"""
## FORBIDDEN (UUPM Anti-Patterns for {design.category})
{design_anti_patterns_block}- Emojis as icons — use SVG or Lucide React instead.
- Missing `cursor: pointer` on clickable elements.
- Layout-shifting hover effects.
- Low contrast text. Maintain accessible contrast.
- Instant state changes without transitions.
- Invisible focus states.
- Horizontal scroll on mobile.
- Using require() and module.exports instead of 100% ESM.
- `<style jsx>` or scoped inline styling patterns that do not belong in standard Vite React projects.
- Missing frontend UI for backend features. If you create Auth or a model, you MUST create the UI too.
- Fake auth flows that only simulate success (hardcoded token/user, mock login/register, or frontend-only auth without backend persistence).
- Links/navigation that target undeclared routes (for example `/feed` or `/profile` when no route exists in `App.tsx`).
- Showing Login/Sign Up controls unconditionally when auth state already has a logged-in user.
- Unstyled pages. Created pages must have complete layout and styling, not raw forms on a blank screen.
- Raw fetch() calls. ALWAYS use the axios-based `src/services/api.ts` service.
- API double prefixing. The `api` service already adds `/api`.
- Imaginary model methods, routes, columns, or files that are not in the scaffold.
- Passing separate arguments to context auth methods instead of a single object payload.
- Querying phantom columns that were never defined in `server/db/database.ts`.
- Truncating file content or returning partial snippets.
- Putting JSX inside `.ts` files. Use `.tsx` for any file that renders React elements.
- Hardcoding localhost URLs in frontend app code. Use relative `/api/...` paths through the axios wrapper.
- Generating test files unless the user explicitly asks for tests.
- Reusing the same generic sticky primary navbar + diagonal gradient hero + bright CTA recipe for every product type.
{app_guardrails}""".strip()


COMMON_STAGE_RULES_TEMPLATE = """
## CORE EXECUTION RULES
- Write only files from the current `FILES TO WRITE IN THIS TURN` list.
- Output using strict JSON with a top-level `files` array of `{ "path": "...", "content": "..." }` objects.
- Markdown `// FILE:` blocks are fallback-only if JSON serialization absolutely fails.
- Output complete files only. Never return partial snippets.
- CRITICAL CSS RULE: If you are generating `src/styles/global.css`, you MUST ONLY output the three `@tailwind` directives (`base`, `components`, `utilities`) and any minimal base layers. DO NOT write raw element selectors like `body`, `h1`, `button`, or `.btn`. Tailwind handles all of this!
- Keep one naming convention per resource across controllers, types, hooks, pages, and components.
- Respect the execution plan and file contracts already established for this run.
- Do not invent pages, routes, resources, controllers, or imports outside the current batch unless the ProjectSpec strictly requires them.
- Never add `Link`/`NavLink`/`navigate(...)` targets to frontend routes that are not declared in `src/App.tsx`.
- If `src/services/api.ts` uses `baseURL: '/api'`, never generate `api.get('/api/...')`.
- `src/types/index.ts` is the shared frontend type source of truth.
- Do not assume a fixed auth credential shape. Follow the user request and ProjectSpec for phone/email/username or other auth fields.
- Tailwind CSS is ALWAYS available for React components. ALWAYS use Tailwind utility classes for styling.
- **NAVIGATION CONTRACT**: If a resource has a `slug` field, you MUST use the slug for public frontend URLs (e.g., `/posts/:slug`). Do NOT use numeric IDs for routing if a slug is available. The backend controllers should still resolve by slug.
- **HEADER REACTIVITY**: Shared navigation components (Navbar/Header) MUST be reactive to `AuthContext`. Use the `user` object to toggle between "Login/Register" and "Profile/Logout" states in real-time.
- **AUTH CTA STATE**: In auth-enabled projects, shared CTAs for Login/Register in Navbar/Home/Hero must hide or switch when `user` is authenticated.
""".strip()


ARCHITECTURE_STAGE_RULES_TEMPLATE = """
## ARCHITECTURE STAGE RULES
- Focus on shared contracts, auth wiring, route/page ownership, and frontend/backend connectivity.
- Keep backend route mounts, frontend route registration, auth flows, and shared types aligned.
- You may touch both frontend and backend only for files in the current batch.
- Even in mixed batches, backend files must still follow backend rules and frontend files must still follow frontend rules.
- `server/` files MUST use 100% ESM `import` / `export`.
- `src/` React files must use `.tsx` when they render JSX and `.ts` for pure logic.
- Prefer plain, coherent wiring over styling polish in this stage.
- Do not spend tokens on detailed visual implementation, large UUPM search dumps, or section-by-section design direction in this stage.
""".strip()


BACKEND_STAGE_RULES_TEMPLATE = """
## BACKEND STAGE RULES
- Focus only on Express, SQLite, controller/route contracts, auth wiring, and JSON response shape.
- `server/` files MUST use 100% ESM. Never use `require()` / `module.exports`.
- Every controller method referenced by a route must actually be exported by that controller.
- SQL must use real column names from `server/db/database.ts`. Alias output fields intentionally if the public contract is camelCase.
- SQL JOIN aliases must be explicit and consistent (`posts p`, `users u`, `comments c`) with JOIN predicates in `ON`, not ad-hoc in `WHERE`.
- Register every backend route in `server/index.ts`.
- **SCAFFOLD REQUIREMENT**: If the current batch includes `package.json`, you MUST ALSO generate `tailwind.config.js` and `postcss.config.js` in the same batch. Without these files, Tailwind classes render as unstyled HTML in the browser.
- Do not spend tokens on styling, layout, typography, colors, or section composition in this stage.
""".strip()


BACKEND_DB_CONTRACT_RULES_TEMPLATE = """
## DATABASE SOURCE-OF-TRUTH RULES
- Read `server/db/database.ts` before writing any backend file that touches SQL or DB calls.
- `server/db/database.ts` decides the real table names, column names, and DB driver style for the project.
- This builder standardizes on `better-sqlite3` for SQLite projects. `server/db/database.ts` should require `better-sqlite3`, not `sqlite3`.
- Use exact schema column names in SQL. Never invent fields like `createdAt`, `coverImage`, `tags`, or `gallery` unless they really exist in the schema.
- If the public JSON contract needs camelCase, alias or map intentionally after using the real DB column names.
- If a field is not in the schema, omit it or map it to an existing column. Do not silently expand the schema from a controller.
- **CRITICAL DB ACCESS PATTERN (NEVER VIOLATE)**:
  `server/db/database.ts` exports `{ initDatabase, getDatabase }` — NOT the raw db instance.
  - CORRECT pattern in every controller:
    ```js
    import { getDatabase } from '../db/database.js';
    export const myHandler = (req, res) => {
      const db = getDatabase(); // MUST call getDatabase() first
      const row = db.prepare('SELECT ...').get(...);
    };
    ```
  - WRONG (causes runtime TypeError: db.prepare is not a function):
    ```js
    import db from '../db/database.js'; // This is the MODULE EXPORTS OBJECT, not the db instance
    db.prepare('SELECT ...') // FAILS at runtime
    ```
  - Every controller handler MUST call `getDatabase()` at the top of the function body before any DB call.
- Driver lock:
  - REQUIRED: `better-sqlite3` => `db.prepare(...).get/all/run`.
  - FORBIDDEN: `sqlite3` callback style => `db.get/db.all/db.run(..., callback)`.
  - Never mix both styles in one project.
- Before outputting a backend file, validate every query and DB call against `server/db/database.ts`.
""".strip()


FRONTEND_STAGE_RULES_TEMPLATE = """
## FRONTEND STAGE RULES
- Focus on pages, components, hooks, context, services, and shared types used by the UI.
- Use the axios `api` wrapper from `src/services/api.ts` for requests.
- Handle loading, empty, and error states. Do not assume fetched data exists.
- Page files under `src/pages/` should default export the page component matching the filename.
- Shared shell components like `Navbar` and `Footer` should default export their component.
- Components and hooks should import shared types from `src/types/index.ts` instead of redefining them.
- If a page, hook, or service imports a shared type such as `Post`, `Category`, or `User`, make sure `src/types/index.ts` exports it in this batch.
- Keep one clear owner for `useAuth`. Do not import it from `src/context/AuthContext.tsx` unless that file explicitly exports `useAuth`.
- Do not invent backend files or change backend architecture unless the current batch explicitly includes them.
- Tailwind CSS is MANDATORY for this project.
- ALWAYS use Tailwind utility classes (e.g. `className="flex flex-col gap-4 p-6 bg-gray-50 text-gray-900 shadow-md rounded-lg"`) for component styling and layouts.
- DO NOT invent custom semantic class names like `.comment-card` or `.auth-header`. NEVER write structural CSS inside `global.css`; rely entirely on Tailwind utilities.
- DESIGN QUALITY FLOOR (MANDATORY):
  - For `src/pages/Home.tsx` or landing-style pages, include multiple distinct sections (hero + at least two supporting sections such as menu/features/about/contact/testimonials/CTA).
  - Use responsive breakpoints (`sm:`, `md:`, `lg:`) for layout and typography, not only base classes.
  - Include visual hierarchy with at least one depth/surface treatment: gradients, contrast sections, borders/rings, shadows, layered cards, or intentional background variation.
  - Avoid "plain form on blank page" outputs unless the user explicitly asks for ultra-minimal style.
- **REQUIRED TAILWIND CONFIG PATTERN**: If generating `tailwind.config.js`, you MUST map standard CSS variables to theme colors. Example mapping:
  ```js
  module.exports = {
    content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
    theme: {
      extend: {
        colors: {
          border: "var(--color-border)",
          input: "var(--color-input)",
          ring: "var(--color-ring)",
          background: "var(--color-background)",
          foreground: "var(--color-foreground)",
          primary: {
            DEFAULT: "var(--color-primary)",
            foreground: "var(--color-primary-foreground)",
          },
          secondary: {
            DEFAULT: "var(--color-secondary)",
            foreground: "var(--color-secondary-foreground)",
          },
          accent: {
            DEFAULT: "var(--color-accent)",
            foreground: "var(--color-accent-foreground)",
          },
          muted: {
            DEFAULT: "var(--color-muted)",
            foreground: "var(--color-muted-foreground)",
          },
          card: {
            DEFAULT: "var(--color-card)",
            foreground: "var(--color-card-foreground)",
          },
        },
      },
    },
    plugins: [],
  }
  ```
- If you are scaffolding the project (e.g., `package.json`), ensure `tailwindcss`, `postcss`, and `autoprefixer` are installed, and scaffold `tailwind.config.js` and `postcss.config.js`.
- Do not invent portfolio owner names, email addresses, phone numbers, or client brands unless the prompt explicitly gave them.
""".strip()


SCRAPER_FORMAT_RULES_TEMPLATE = f"""
## RESPONSE FORMAT
- Return ONLY valid JSON (no prose, no markdown) with this shape:
  {{
    "files": [
      {{ "path": "relative/path.ext", "content": "complete file contents" }}
    ],
    "commands": []
  }}
- Include only files from the current batch.
- Do not return partial snippets.

Example:
{ticks}json
{{
  "files": [
    {{
      "path": "src/components/Hero.tsx",
      "content": "import React from 'react';\\nexport default function Hero() {{\\n  return <section>Hello</section>;\\n}}\\n"
    }}
  ],
  "commands": []
}}
{ticks}
""".strip()

# 3. Dynamic strings go INSIDE the functions
def build_design_spec(design: DesignSystem, stage_name: str = "full") -> str:
    """Helper to generate the design spec dynamically safely."""
    primary_color = design.colors.primary or '#3B82F6'
    bg_color = design.colors.background or '#F8FAFC'
    text_color = design.colors.text or '#1E293B'
    heading_font = design.typography.heading or 'Inter'
    body_font = design.typography.body or 'Inter'
    google_url = _extract_google_stylesheet_url(design)
    non_app_direction = ""
    component_direction = _build_visual_direction(design)
    css_variables = design.css_variables if str(getattr(design, "css_variables", "") or "").strip() else ""
    if not css_variables:
        css_variables = f"""
:root {{
  --color-primary: {primary_color};
  --color-background: {bg_color};
  --color-text: {text_color};
  --font-heading: '{heading_font}', sans-serif;
  --font-body: '{body_font}', sans-serif;
}}
""".strip()
    decision_rules_block = str(getattr(design, "prompt_decision_rules", "") or "").strip()

    stage_name = str(stage_name or "full").strip().lower()

    if stage_name == "backend":
        return f"""
## FRONTEND DESIGN CONTEXT (REFERENCE ONLY)
- Product Category: {design.category}
- Style: {design.style.name} ({design.style.type})
- Layout Pattern: {design.pattern.name}
- Typography: {heading_font} / {body_font}
- Public contract should stay compatible with the selected frontend design, but do NOT spend tokens generating styling in this stage.
""".strip()

    if stage_name == "architecture":
        return f"""
## DESIGN DIRECTION SUMMARY
- Product Category: {design.category}
- Style: {design.style.name} ({design.style.type})
- Layout Pattern: {design.pattern.name}
- Section Rhythm: {design.pattern.sections}
- Typography: {heading_font} / {body_font}
- Palette Anchor: primary {primary_color}, background {bg_color}, text {text_color}
- Use this only to keep shared architecture aligned with the intended product direction. Detailed visual implementation belongs to frontend batches.
""".strip()

    if not _is_mobile_app_design(design):
        non_app_direction = """
### SITE-TYPE FIT (CRITICAL)
- This project should look like the selected category and pattern above.
- Do not default to app-download or device-marketing UI unless the selected product is explicitly a mobile app.
- Navigation labels and CTA copy must match the actual site type and user intent.
"""
    
    return f"""
## DESIGN SYSTEM (Real UUPM BM25 Engine)

Project Category: {design.category}
Style Name: {design.style.name} ({design.style.type})
Layout Pattern: {design.pattern.name}
Sections to build: {design.pattern.sections}
CTA Strategy: {design.pattern.cta_placement}

### DESIGN SYSTEM — USE THESE EXACT VALUES

Your styles/variables.css MUST use these exact values
generated from the UUPM design engine:

{css_variables}

### CSS IMPORT RULES (CRITICAL)
src/main.tsx MUST have these imports at the top:
  import './styles/variables.css'
  import './styles/global.css'

{f"index.html MUST have Google Fonts link:" if google_url else ""}
{f'  <link href="{google_url}" rel="stylesheet" />' if google_url else ""}

{non_app_direction}

### COMPONENT STYLE RULES
EVERY component MUST use CSS variables — NEVER hardcode colors.
Tailwind is available in this scaffold. Use Tailwind utility classes for layout, spacing, typography, states, and responsive behavior.
Keep `src/styles/global.css` limited to the Tailwind directives plus minimal `@layer base` rules or rare shared utility primitives that cannot live cleanly in JSX.
{component_direction}

{f"### DESIGN DECISION RULES\\n{decision_rules_block}" if decision_rules_block else ""}

### Effects
- Key Effects: {design.key_effects or design.style.effects or 'Subtle transitions and depth only when they support clarity.'}
"""


def build_stage_anti_patterns(design: DesignSystem, stage_name: str = "full") -> str:
    stage = str(stage_name or "full").strip().lower()
    if stage == "backend":
        return """
## BACKEND FORBIDDEN PATTERNS
- Using `require()` or `module.exports`. You MUST use 100% ESM.
- Querying columns that were never defined in `server/db/database.ts`.
- Returning HTML from `/api/*` routes. Backend must return JSON.
- Double-prefixing API routes or mounting a route file without its controller exports.
- Generating frontend-only styling or layout code in backend-only batches.
""".strip()

    if stage == "architecture":
        return """
## ARCHITECTURE FORBIDDEN PATTERNS
- Inventing pages, resources, or auth flows outside the ProjectSpec.
- Leaving frontend/backend halves of the same feature disconnected.
- Rewriting files outside the current batch while trying to fix an architecture issue.
- Fixing one side of a contract while leaving shared types, routes, or services inconsistent.
""".strip()

    return build_anti_patterns(design)

def _truncate_prompt_value(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _format_uupm_domain_result(domain: str, payload: dict) -> str:
    field_sets = {
        "product": [
            ("Product Type", "Product"),
            ("Primary Style Recommendation", "Primary Style"),
            ("Secondary Styles", "Secondary"),
            ("Landing Page Pattern", "Pattern"),
            ("Color Palette Focus", "Palette"),
        ],
        "style": [
            ("Style Category", "Style"),
            ("Type", "Type"),
            ("Best For", "Best For"),
            ("Effects & Animation", "Effects"),
            ("Keywords", "Keywords"),
        ],
        "color": [
            ("Product Type", "Product"),
            ("Primary", "Primary"),
            ("Secondary", "Secondary"),
            ("Accent", "Accent"),
            ("Background", "Background"),
            ("Foreground", "Foreground"),
            ("Notes", "Notes"),
        ],
        "landing": [
            ("Pattern Name", "Pattern"),
            ("Section Order", "Sections"),
            ("Primary CTA Placement", "CTA"),
            ("Conversion Optimization", "Conversion"),
        ],
        "typography": [
            ("Font Pairing Name", "Pairing"),
            ("Heading Font", "Heading"),
            ("Body Font", "Body"),
            ("Mood/Style Keywords", "Mood"),
            ("Best For", "Best For"),
        ],
        "ux": [
            ("Category", "Category"),
            ("Issue", "Issue"),
            ("Description", "Description"),
            ("Do", "Do"),
            ("Don't", "Avoid"),
            ("Severity", "Severity"),
        ],
        "react": [
            ("Category", "Category"),
            ("Issue", "Issue"),
            ("Description", "Description"),
            ("Do", "Do"),
            ("Don't", "Avoid"),
            ("Severity", "Severity"),
        ],
        "web": [
            ("Category", "Category"),
            ("Issue", "Issue"),
            ("Description", "Description"),
            ("Do", "Do"),
            ("Don't", "Avoid"),
            ("Severity", "Severity"),
        ],
        "icons": [
            ("Category", "Category"),
            ("Icon Name", "Icon"),
            ("Library", "Library"),
            ("Best For", "Best For"),
            ("Style", "Style"),
        ],
        "chart": [
            ("Data Type", "Data"),
            ("Best Chart Type", "Chart"),
            ("When to Use", "Use When"),
            ("Accessibility Notes", "A11y"),
            ("Library Recommendation", "Library"),
        ],
    }

    results = list((payload or {}).get("results") or [])[:2]
    if not results:
        return ""

    query = _truncate_prompt_value((payload or {}).get("query", ""), 120)
    lines = [f"### {domain.title()} Search", f"Query: {query}"]
    for index, row in enumerate(results, 1):
        parts = []
        for key, label in field_sets.get(domain, []):
            value = _truncate_prompt_value(row.get(key, ""))
            if value:
                parts.append(f"{label}: {value}")
        if parts:
            lines.append(f"{index}. " + " | ".join(parts))

    return "\n".join(lines)


def build_uupm_workflow_context(uupm_context: dict | None, stage_name: str = "full") -> str:
    """Render the UUPM workflow + supplementary search results into prompt text."""
    if not uupm_context:
        return ""

    stage = str(stage_name or "full").strip().lower()
    if stage == "backend":
        return ""

    workflow = list((uupm_context or {}).get("workflow") or [])
    domains = dict((uupm_context or {}).get("domains") or {})
    if stage == "architecture":
        domain_order = ["product", "style", "landing", "typography", "react"]
    elif stage == "frontend":
        domain_order = [
            "product",
            "style",
            "color",
            "landing",
            "typography",
            "ux",
            "react",
            "web",
            "icons",
            "chart",
        ]
    else:
        domain_order = [
            "product",
            "style",
            "color",
            "landing",
            "typography",
            "ux",
            "react",
            "web",
            "icons",
            "chart",
        ]

    lines = [
        "## UUPM WORKFLOW (FOLLOW THIS DIRECTLY)",
        "Use the UUPM process below when translating the prompt into code.",
    ]
    for index, step in enumerate(workflow, 1):
        lines.append(f"{index}. {step}")

    lines.extend(
        [
            "",
            "## SUPPLEMENTARY UUPM SEARCH CONTEXT",
        "Treat `product`, `style`, `color`, `landing`, and `typography` as high-signal design inputs.",
        "Use `ux`, `react`, `web`, `icons`, and `chart` to refine implementation quality without breaking the selected product direction.",
    ]
    )

    for domain in domain_order:
        block = _format_uupm_domain_result(domain, domains.get(domain, {}))
        if block:
            lines.extend(["", block])

    return "\n".join(lines)


def _coerce_project_spec(project_spec: Any | None) -> dict[str, Any]:
    if not project_spec:
        return {}
    if isinstance(project_spec, dict):
        return project_spec
    if hasattr(project_spec, "to_dict"):
        try:
            return dict(project_spec.to_dict() or {})
        except Exception:
            return {}
    return {}


def build_project_spec_prompt_context(project_spec: Any | None, stage_name: str = "full") -> str:
    spec = _coerce_project_spec(project_spec)
    if not spec:
        return ""

    stage = str(stage_name or "full").strip().lower()
    pages = list(spec.get("pages") or [])
    api_resources = list(spec.get("api_resources") or [])
    auth = dict(spec.get("auth") or {})
    auth_identifiers = [str(item).strip() for item in list(auth.get("identifiers") or []) if str(item).strip()]
    auth_mode = str(auth.get("mode", "") or "").strip()
    auth_registration = bool(auth.get("allow_registration", True))
    auth_login_route = str(auth.get("login_route", "") or "").strip()
    auth_register_route = str(auth.get("register_route", "") or "").strip()
    auth_session_route = str(auth.get("session_route", "") or "").strip()
    auth_state_owner = str(auth.get("state_owner", "") or "").strip()

    lines = ["## PROJECT SPEC"]
    product_type = str(spec.get("product_type", "") or "").strip()
    app_kind = str(spec.get("app_kind", "") or "").strip()
    summary = str(spec.get("summary", "") or "").strip()
    if product_type:
        lines.append(f"Product Type: {product_type}")
    if app_kind:
        lines.append(f"App Kind: {app_kind}")
    if summary:
        lines.append(f"Summary: {summary}")

    features = [str(item).strip() for item in list(spec.get("features") or []) if str(item).strip()]
    if features and stage in {"architecture", "full"}:
        lines.append("Features: " + ", ".join(features[:8]))

    def _camelize(value: str) -> str:
        text = re.sub(r"[^A-Za-z0-9]+", " ", str(value or "").strip())
        parts = [part for part in text.split() if part]
        if not parts:
            return ""
        first = parts[0].lower()
        return first + "".join(part[:1].upper() + part[1:] for part in parts[1:])

    entity_contracts: list[str] = []
    for entity in list(spec.get("entities") or [])[:8]:
        if not isinstance(entity, dict):
            continue
        entity_name = str(entity.get("name", "") or "").strip()
        fields = list(entity.get("fields") or [])
        field_names: list[str] = []
        for field in fields[:12]:
            if not isinstance(field, dict):
                continue
            fname = _camelize(str(field.get("name", "") or ""))
            if fname:
                field_names.append(fname)
        if entity_name and field_names:
            entity_contracts.append(f"{entity_name} {{{', '.join(field_names)}}}")
        elif entity_name:
            entity_contracts.append(entity_name)
    if entity_contracts:
        lines.append(
            "Entity Contracts (use these exact public field names in types/services/hooks/controllers): "
            + "; ".join(entity_contracts)
        )

    if stage == "backend":
        filtered_resources = []
        for resource in api_resources[:8]:
            route = str(resource.get("route", "") or "").strip()
            auth_mode = str(resource.get("auth", "public") or "public").strip()
            frontend = "yes" if bool(resource.get("frontend", True)) else "no"
            name = str(resource.get("name", "") or "").strip()
            if route:
                filtered_resources.append(f"{name} ({route}, auth={auth_mode}, frontend={frontend})")
        if filtered_resources:
            lines.append("API Resources: " + ", ".join(filtered_resources))
        if auth.get("enabled"):
            roles = [str(item).strip() for item in list(auth.get("roles") or []) if str(item).strip()]
            auth_bits = []
            if auth_mode:
                auth_bits.append(auth_mode)
            if auth_identifiers:
                auth_bits.append("identifiers=" + "/".join(auth_identifiers))
            auth_bits.append("registration=" + ("yes" if auth_registration else "no"))
            if roles:
                auth_bits.append("roles=" + ",".join(roles))
            if auth_login_route:
                auth_bits.append(f"login={auth_login_route}")
            if auth_register_route and auth_registration:
                auth_bits.append(f"register={auth_register_route}")
            if auth_session_route:
                auth_bits.append(f"session={auth_session_route}")
            lines.append("Auth: enabled" + (f" ({'; '.join(auth_bits)})" if auth_bits else ""))
    elif stage == "frontend":
        filtered_pages = []
        for page in pages[:10]:
            name = str(page.get("name", "") or "").strip()
            route = str(page.get("route", "") or "").strip()
            auth_mode = str(page.get("auth", "public") or "public").strip()
            if route:
                filtered_pages.append(f"{name} ({route}, auth={auth_mode})")
        if filtered_pages:
            lines.append("Pages: " + ", ".join(filtered_pages))
        filtered_frontend_resources = []
        for resource in api_resources[:8]:
            if not bool(resource.get("frontend", True)):
                continue
            name = str(resource.get("name", "") or "").strip()
            route = str(resource.get("route", "") or "").strip()
            if route:
                filtered_frontend_resources.append(f"{name} ({route})")
        if filtered_frontend_resources:
            lines.append("Frontend API Resources: " + ", ".join(filtered_frontend_resources))
        if auth.get("enabled"):
            auth_ui = "login + register" if auth_registration else "login only"
            lines.append(f"Auth UI: {auth_ui}")
            if auth_identifiers:
                lines.append("Auth Identifier Fields: " + ", ".join(auth_identifiers))
            if auth_state_owner:
                lines.append(f"Auth State Owner: {auth_state_owner}")
    else:
        filtered_pages = []
        for page in pages[:8]:
            name = str(page.get("name", "") or "").strip()
            route = str(page.get("route", "") or "").strip()
            if route:
                filtered_pages.append(f"{name} ({route})")
        if filtered_pages:
            lines.append("Pages: " + ", ".join(filtered_pages))
        filtered_resources = []
        for resource in api_resources[:8]:
            name = str(resource.get("name", "") or "").strip()
            route = str(resource.get("route", "") or "").strip()
            if route:
                filtered_resources.append(f"{name} ({route})")
        if filtered_resources:
            lines.append("API Resources: " + ", ".join(filtered_resources))
        if auth.get("enabled"):
            summary_bits = []
            if auth_mode:
                summary_bits.append(auth_mode)
            if auth_identifiers:
                summary_bits.append("/".join(auth_identifiers))
            summary_bits.append("registration=" + ("yes" if auth_registration else "no"))
            lines.append("Auth: enabled" + (f" ({'; '.join(summary_bits)})" if summary_bits else ""))

    acceptance_checks = [
        str(item).strip()
        for item in list(spec.get("acceptance_checks") or [])
        if str(item).strip()
    ]
    if acceptance_checks:
        lines.append("Acceptance Checks: " + "; ".join(acceptance_checks[:6]))
    return "\n".join(lines)


def build_stage_system_prompt(
    design: DesignSystem,
    stage_name: str,
    sandbox_dir: str = "",
    uupm_context: dict | None = None,
    scraper: bool = False,
) -> str:
    stage = str(stage_name or "architecture").strip().lower()
    sections = [
        f"You are an expert full-stack developer working on the `{stage}` stage of a React + Vite + Express + SQLite project.",
        COMMON_STAGE_RULES_TEMPLATE,
    ]

    if stage == "backend":
        sections.extend([
            BACKEND_STAGE_RULES_TEMPLATE,
            BACKEND_DB_CONTRACT_RULES_TEMPLATE,
            build_stage_anti_patterns(design, stage),
            build_design_spec(design, stage),
        ])
    elif stage == "frontend":
        sections.extend([
            FRONTEND_STAGE_RULES_TEMPLATE,
            build_uupm_workflow_context(uupm_context, stage),
            build_stage_anti_patterns(design, stage),
            build_design_spec(design, stage),
        ])
    else:
        sections.extend([
            ARCHITECTURE_STAGE_RULES_TEMPLATE,
            BACKEND_STAGE_RULES_TEMPLATE,
            BACKEND_DB_CONTRACT_RULES_TEMPLATE,
            build_stage_anti_patterns(design, stage),
            build_design_spec(design, stage),
        ])

    if scraper:
        sections.append(SCRAPER_FORMAT_RULES_TEMPLATE)

    return "\n\n".join(part.strip() for part in sections if str(part or "").strip())


def build_generation_user_prompt(
    *,
    original_prompt: str,
    stage_name: str,
    current_batch: list[str],
    scoped_blueprint: dict[str, Any] | None = None,
    project_context: str = "",
    project_spec: Any | None = None,
    feedback: str = "",
    done_count: int = 0,
    total_count: int = 0,
) -> str:
    stage = str(stage_name or "architecture").strip().lower()
    scoped_blueprint = dict(scoped_blueprint or {})
    spec_block = build_project_spec_prompt_context(project_spec, stage)
    batch_str = "\n".join(f"- {path}" for path in current_batch)
    feedback_block = ""
    if str(feedback or "").strip():
        feedback_block = (
            "### PRIOR ATTEMPT FEEDBACK (FIX THESE ISSUES NOW)\n"
            f"{str(feedback).strip()}\n\n"
        )

    progress_line = ""
    if total_count > 0:
        progress_line = f"Progress: {done_count}/{total_count} planned files complete."

    prompt_parts = [
        original_prompt.strip(),
        f"### CURRENT EXECUTION STAGE\n{stage}",
    ]
    if progress_line:
        prompt_parts.append(progress_line)
    if spec_block:
        prompt_parts.append(spec_block)
    if feedback_block:
        prompt_parts.append(feedback_block.strip())
    if stage in {"backend", "architecture"} and any(str(path).strip().startswith("server/") for path in current_batch):
        prompt_parts.append(
            "### BACKEND PRE-WRITE CHECK\n"
            "- Inspect `server/db/database.ts` from the relevant existing files/context before writing SQL or DB calls.\n"
            "- Match the exact DB driver style used there.\n"
            "- Only use real schema columns.\n"
            "### ABSOLUTE RULE — SERVER FILES ESM PURITY\n"
            "- All files under `server/` MUST use 100% ESM syntax.\n"
            "- NEVER use `require()` anywhere, including inside functions.\n"
            "- ALWAYS declare imports at the top of the file.\n"
            "- NEVER use `module.exports`; use `export` / `export default`.\n"
            "### RULE — ROUTE FILE IMPORTS\n"
            "- Route files in `server/routes/` MUST import controllers using `../controllers/`, never `./`.\n"
            "- ✅ CORRECT: `import { list } from '../controllers/productController.js'`\n"
            "- ❌ WRONG: `import { list } from './productController.js'`\n"
            "- `routes/` and `controllers/` are sibling directories under `server/`."
        )
    if stage == "frontend":
        prompt_parts.append(
            "### FRONTEND DESIGN QUALITY FLOOR (CRITICAL)\n"
            "- Home/landing pages must include multiple visually distinct sections (hero + supporting sections).\n"
            "- Use responsive Tailwind breakpoints (`sm:`/`md:`/`lg:`) in layout and typography.\n"
            "- Include clear visual hierarchy using section contrast, cards, borders/rings, shadows, gradients, or layered backgrounds.\n"
            "- Avoid bare single-column blocks unless the user explicitly requests ultra-minimal design."
        )
    if "package.json" in [str(path).strip() for path in current_batch]:
        prompt_parts.append(
            "### PACKAGE RUNTIME CONTRACT (CRITICAL)\n"
            "- If this project includes a backend, `package.json` MUST include the exact script: `\"server\": \"node --import tsx server/index.ts\"`.\n"
            "- You MUST add `\"type\": \"module\"` because backend `server/` files use 100% ESM in this pipeline.\n"
            "- If SQLite is used, pin `better-sqlite3` to `^12.2.0` in dependencies.\n"
            "- If `better-sqlite3` is present, include `\"postinstall\": \"npm rebuild better-sqlite3\"` in scripts.\n"
            "- Do not add competing server/database stacks like `sqlite3`, `prisma`, `sequelize`, `mongoose`, `knex`, or `pg`.\n"
            "- Keep frontend dependencies and backend dependencies in one coherent package.json instead of switching runtime styles."
        )
    if "vite.config.ts" in [str(path).strip() for path in current_batch]:
        prompt_parts.append(
            "### CRITICAL RULE — VITE PROXY PORT\n"
            "- When writing or fixing `vite.config.ts`, ALWAYS use port `3001` for backend proxy targets.\n"
            "- `server.proxy['/api'].target` MUST be `http://localhost:3001`.\n"
            "- `preview.proxy['/api'].target` MUST be `http://localhost:3001`.\n"
            "- NEVER use `http://localhost:3000` as a backend proxy target. Port 3000 is frontend-only."
        )
    if scoped_blueprint.get("relationships") or scoped_blueprint.get("units"):
        prompt_parts.append(
            "### FILE RELATIONSHIP CONTRACT\n"
            "- Treat `units` and `relationships` in the stage-scoped blueprint as hard constraints.\n"
            "- Keep imports, exports, route paths, API calls, shared types, and component usage aligned across every connected file in this batch.\n"
            "- If you change a symbol, contract, or API shape in one current-batch file, update every other current-batch file linked to it.\n"
            "- Do not invent disconnected files, isolated placeholder code, or alternate naming that breaks the listed relationships."
        )

    # Auth page CSS co-generation enforcement removed.
    pass
    shared_files = [
        str(path).strip()
        for path in list(scoped_blueprint.get("shared_files") or [])
        if str(path).strip()
    ]
    if shared_files:
        prompt_parts.append(
            "### SHARED OWNER FILES IN THIS TURN\n"
            "- Some files in this batch are shared owner files reopened on purpose so the site stays coherent.\n"
            "- If you introduce page/component class names, update the owning stylesheet in this same turn.\n"
            "- If you introduce or register a page route, update `src/App.tsx` in this same turn when it is included.\n"
            "- If frontend/backend contracts change, keep `src/types/index.ts`, `src/services/api.ts`, and the connected route/controller/service files aligned.\n"
            f"- Shared owner files in scope: {', '.join(shared_files)}"
        )
    prompt_parts.append(
        "### STAGE-SCOPED BLUEPRINT (CRITICAL CONTEXT)\n"
        "Follow these contracts for the current batch only:\n"
        f"{ticks}json\n{json.dumps(scoped_blueprint, indent=2)}\n{ticks}"
    )
    if project_context.strip():
        prompt_parts.append(
            "### RELEVANT EXISTING FILES ONLY (DO NOT REGENERATE THESE)\n"
            f"{project_context.strip()}"
        )
    prompt_parts.append(
        "### STRICT BATCH WRITING ENFORCEMENT (CRITICAL)\n"
        f"You are ONLY ALLOWED to write the following {len(current_batch)} files right now:\n"
        f"{batch_str}\n\n"
        "### CRITICAL SAFETY RULES\n"
        "1. DO NOT output code for any OTHER file besides those listed above.\n"
        "2. DO NOT re-generate existing files from the context.\n"
        "3. Keep your response extremely concise for the specified batch only.\n"
        "4. If you output too much code, the stream will truncate and the project will fail.\n"
    )
    prompt_parts.append(
        "### OUTPUT PROTOCOL (STRICT JSON, CRITICAL)\n"
        "Return ONLY valid JSON with this exact top-level shape:\n"
        f"{ticks}json\n"
        "{\n"
        "  \"files\": [\n"
        "    { \"path\": \"relative/path.ext\", \"content\": \"complete file contents\" }\n"
        "  ],\n"
        "  \"commands\": [],\n"
        "  \"chunk_index\": 1,\n"
        "  \"chunk_total\": 1\n"
        "}\n"
        f"{ticks}\n"
        "- `files` is required and must include only current-batch paths.\n"
        "- `content` must be full file content, never summaries/snippets.\n"
        "- No markdown blocks, no `// FILE:` wrappers, no prose outside JSON.\n"
        "- If you cannot finish all files in one response, return the completed subset and set `chunk_total` accordingly."
    )
    return "\n\n".join(part for part in prompt_parts if str(part or "").strip())


def get_system_prompt(design: DesignSystem, sandbox_dir: str = "", uupm_context: dict | None = None) -> str:
    """Standard XML-based system prompt."""
    design_spec = build_design_spec(design)
    anti_patterns = build_anti_patterns(design)
    uupm_workflow = build_uupm_workflow_context(uupm_context)
    return "\n\n".join(
        [
            "You are an expert full-stack developer.",
            MANDATORY_FILES_TEMPLATE.strip(),
            STRICT_GENERATION_RULES_TEMPLATE.strip(),
            uupm_workflow.strip(),
            anti_patterns.strip(),
            design_spec.strip(),
        ]
    )

def build_system_prompt(design: DesignSystem, sandbox_dir: str = "", uupm_context: dict | None = None) -> str:
    return get_system_prompt(design, sandbox_dir, uupm_context)

def get_scraper_prompt(design: DesignSystem, uupm_context: dict | None = None) -> str:
    """Markdown format for scraper models. Uses 'ticks' to prevent truncation."""
    design_spec = build_design_spec(design)
    anti_patterns = build_anti_patterns(design)
    uupm_workflow = build_uupm_workflow_context(uupm_context)
    
    return f"""You are an expert full-stack developer.
Build a complete React + Vite + Express + SQLite project.

ANTI-PATTERNS:
- ❌ Use require() or module.exports anywhere (must be 100% ESM)
- ❌ Raw fetch() calls — use axios api service
- ❌ NO MANDATORY TESTS — Do NOT generate any test files unless explicitly asked.
- ❌ Do NOT invent diagnostic or temporary probe files as part of the generated project output. Temporary triage probes are allowed only when explicitly requested by the decision engine and must live under `.lovable/triage/`.

{MANDATORY_FILES_TEMPLATE}

{STRICT_GENERATION_RULES_TEMPLATE}

{uupm_workflow}

{anti_patterns}

{design_spec}

🔥 CRITICAL FORMAT RULE:
Return ONLY valid JSON with this shape:
{ticks}json
{{
  "files": [
    {{
      "path": "src/components/Hero.tsx",
      "content": "import React from 'react';\\nexport default function Hero() {{\\n  return <section>Hello</section>;\\n}}\\n"
    }}
  ],
  "commands": []
}}
{ticks}
"""

def get_summarization_prompt(history: str) -> str:
    return (
        "You are a technical architect. Summarize the following conversation/history "
        "concisely. You MUST preserve: All important design decisions, all file names "
        "that were written or modified, any encountered errors, and the current state "
        "of the project.\n\n"
        "HISTORY:\n"
        f"{history}"
    )

def get_summary_saving_prompt(prompt: str, design_summary: str) -> str:
    return (
        "Based on the initial request and the resulting design system, generate a "
        "concise 'Project Summary' for future reference. This will be used as a "
        "recap when editing the site later.\n\n"
        f"INITIAL REQUEST: {prompt}\n"
        f"DESIGN SUMMARY: {design_summary}\n\n"
        "Output ONLY the markdown content for .lovable/summary.md starting with # Project Summary."
    )

def get_repair_prompt(
    filename: str,
    error_log: str,
    content: str,
    context: str,
    strategy: str,
    authorized_targets: list[str] | None = None,
) -> str:
    normalized_targets = [
        str(path).strip().replace("\\", "/")
        for path in list(authorized_targets or [])
        if str(path).strip()
    ]
    authorized_scope = ""
    if normalized_targets:
        authorized_scope = (
            "### AUTHORIZED REPAIR SCOPE (CRITICAL)\n"
            "You may rewrite ANY file in this repair batch, and you should update EVERY connected owner file needed "
            "to resolve the issue completely.\n"
            "Do not stop after fixing only the first listed file if the contract spans multiple files.\n"
            + "\n".join(f"- {path}" for path in normalized_targets)
            + "\n"
        )

    return f"""You are fixing a technical error in '{filename}'.

### ERROR STRATEGY (RECOMMENDED FIX):
{strategy}

### ERROR LOG (SPECIFIC ISSUES):
{error_log}

### FULL CURRENT CONTENT OF {filename}:
{ticks}typescript
{content}
{ticks}

{authorized_scope}

PROJECT CONTEXT (ARCHITECTURE & DEPENDENCIES):
{context}

REPAIR RULES:
Fix ALL errors listed in the log.

### 0. PHASED EXECUTION PLANNING (CRITICAL)
Before rewriting the file, mentally map out:
- **Phase 1: Detect Scope**: What other files consume or provide the symbol/contract that failed?
- **Phase 2: Classify the Issue**: Is this a VALIDATOR_FALSE_POSITIVE, IMPORT_SITE_ERROR, MODULE_EXPORT_MISSING, CONVENTION_MISMATCH, API_CONTRACT_DRIFT, GENERATION_ERROR, or TRIAGE_STRATEGY_ERROR?
- **Phase 3: Define Repair Set**: Should I be editing this file, or is the fault actually in the file that generated the request (e.g. the importer)? 

### 1. BLUEPRINT-DRIVEN ANTI-FRAGMENTATION RULE (CRITICAL)
Before any generation or fix, you MUST prioritize the MASTER BLUEPRINT CONTRACT as your primary planning source, treating any local utils/spec fragments as strictly transitional. You MUST ask yourself: 👉 "Which contract node does this belong to? Which files share the same blueprint batch? Which files consume the public contract?" Do not generate isolated fixes. You must regenerate the full coordinated blueprint contract cluster.

### 2. BUG CLASSIFICATION
- **VALIDATOR_FALSE_POSITIVE**: The code is valid, but the validator regex flagged it (e.g., valid SQL `WHERE 1=1`). Do NOT rewrite valid code; explain the false positive if possible, or output the exact same file content to bypass.
- **IMPORT_SITE_ERROR**: The file imports a symbol that does not exist in the target. FIX THE IMPORT. Do NOT invent fake exports in the target module if it is structurally complete.
- **MODULE_EXPORT_MISSING**: The file is structurally missing a required export. Add it.
- **API_CONTRACT_DRIFT**: The file uses mixed naming (snake vs camel). Standardize it immediately, using `toPublic` mappers for DB results.

If the error log includes a "Root cause:" line, treat it as high-signal triage context and use it to guide the rewrite.

If the PROJECT CONTEXT includes a "PROJECT SPEC" or "PHASE CONTEXT" block, treat it as the architecture source of truth for this repair.

Rewrite the COMPLETE file. Never use placeholders like "// ...rest of code".

Use the mandatory // FILE: format below.

DO NOT output any explanation or conversational text.

DO NOT suggest shell-based source edits such as `sed -i`, `perl -pi`, `echo > file`, or Python one-liners that rewrite files. Source changes must be expressed by rewriting the file content in the response.

NO IMAGINARY FILES: Only require/import files that exist. Do not invent new route files (e.g. authRoutes.ts) if they aren't in the project map.

CONTRACT SAFETY:
- If the error suggests a type/field mismatch, inspect the whole resource contract mentally before fixing.
- Keep one naming convention per resource across database, controller, shared types, hooks, pages, and components.
- If you change a field name in this file, also align any directly dependent code referenced in the context.
- Do NOT patch around contract drift by adding one-off fallback fields unless the project intentionally supports both.
- Do NOT leave repair-strategy comments that mention both versions of a field name such as `createdAt` and `created_at`.
- If PROJECT SPEC declares pages, API resources, auth mode, or acceptance checks, repair the file to satisfy that contract instead of inventing alternate architecture.
- If PHASE CONTEXT says the failure is scaffold, backend, or frontend, focus on fixing the owner file for that phase before changing unrelated consumers.

API PREFIX SAFETY:
- If `src/services/api.ts` uses `baseURL: '/api'`, never generate calls like `api.get('/api/...')`.
- Keep exactly one `/api` prefix.

DB SCHEMA SAFETY:
- Read `server/db/database.ts` first; it is the source of truth for table names, column names, and DB driver style.
- SQL in controllers must match real columns in `server/db/database.ts`.
- If the DB uses snake_case columns, do not query camelCase column names unless you are aliasing output fields intentionally.
- If you alias tables in SQL, keep alias usage consistent in SELECT/ON/WHERE (`p.id`, `u.name`, `c.post_id`) and avoid mixing bare table names after aliasing.
- Do not invent extra insert/update fields that are not in the schema.

DB DRIVER SAFETY:
- This pipeline expects `server/db/database.ts` to use `better-sqlite3`.
- Controllers and middleware that touch the DB must use `db.prepare(...).get/all/run`.
- Do not use sqlite-style callbacks anywhere in backend DB consumers.
- Do not change the schema or driver style just to patch a controller unless `server/db/database.ts` is itself part of the repair target.

ROUTE CALLBACK ERROR: If the error is 'Route.get() requires a callback function but got [object Undefined]':
a. The error is NEVER in server/index.ts — it is in a routes/.ts or controllers/.ts file.
b. Open each routes/*.ts file. For every controller.methodName reference, verify that controller file exports that exact method with export const methodName = async (req, res) => {{ ... }}.
c. For middleware: check how authMiddleware.ts exports its function. It must use export const.
d. DO NOT toggle between import styles on consecutive attempts — use ESM consistently.

100% ESM: server/ files MUST use import and export. NEVER use require() or module.exports.

YOU MUST add "type": "module" to package.json.

ESM CONFLICT: If you see "module is not defined" or "require is not defined", ensure "type": "module" is in package.json and you are using ONLY modern import/export syntax.

SVG FORMAT: Even for SVGs and assets, you MUST use the // FILE: path header inside a markdown code block.

JSX EXTENSION RULE (CRITICAL): If the file you are fixing contains JSX (<div/>, <Provider/>, etc.), the file MUST be named with a .tsx extension. If the current filename ends in .ts, you MUST output it as .tsx instead, AND update any corresponding import paths if requested.

🔥 CRITICAL FORMAT RULE:
For EVERY file:

Output ONLY a markdown code block.

The FIRST LINE inside the code block MUST be: // FILE: {filename}

Example:

{ticks}typescript
// FILE: {filename}
import React from 'react';
// ... fixed code ...
{ticks}

STRICT RULES:
DO NOT put // FILE: outside the code block.
DO NOT write any text before or after the code block.
The file path comment MUST be the FIRST line inside the code.
If this rule is violated, the answer is incorrect.
"""
