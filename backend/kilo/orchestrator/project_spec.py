from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip()).strip("_").lower()
    return text or "item"


def _pascal(value: str) -> str:
    parts = re.split(r"[^a-zA-Z0-9]+", str(value or "").strip())
    cleaned = [part for part in parts if part]
    return "".join(part[:1].upper() + part[1:] for part in cleaned) or "Item"


def _singular_slug(value: str) -> str:
    slug = _slug(value)
    if slug.endswith("ies") and len(slug) > 3:
        return slug[:-3] + "y"
    if slug.endswith("ses") and len(slug) > 3:
        return slug[:-2]
    if slug.endswith("s") and len(slug) > 1:
        return slug[:-1]
    return slug


def _component_name(name: str, route: str = "") -> str:
    if name:
        return _pascal(name)
    route = str(route or "").strip()
    if route in {"", "/"}:
        return "Home"
    bits = [part for part in route.split("/") if part and not part.startswith(":")]
    return _pascal("_".join(bits)) or "Page"


def _looks_like_login_page(page: "PageSpec") -> bool:
    haystack = " ".join(
        [
            str(getattr(page, "name", "") or ""),
            str(getattr(page, "route", "") or ""),
            str(getattr(page, "purpose", "") or ""),
        ]
    ).lower()
    return any(term in haystack for term in ("login", "sign in", "signin", "auth", "verify", "otp"))


def _looks_like_register_page(page: "PageSpec") -> bool:
    haystack = " ".join(
        [
            str(getattr(page, "name", "") or ""),
            str(getattr(page, "route", "") or ""),
            str(getattr(page, "purpose", "") or ""),
        ]
    ).lower()
    return any(term in haystack for term in ("register", "sign up", "signup", "join", "create account"))


def _looks_like_portfolio_detail_page(page: "PageSpec") -> bool:
    route = str(getattr(page, "route", "") or "").strip().lower()
    haystack = " ".join(
        [
            str(getattr(page, "name", "") or ""),
            str(getattr(page, "route", "") or ""),
            str(getattr(page, "purpose", "") or ""),
        ]
    ).lower()
    if not any(term in haystack for term in ("project", "case study", "case-study", "portfolio", "work")):
        return False
    return ":" in route or any(term in haystack for term in ("detail", "showcase", "single"))


_ALLOWED_REQUIRED_ROOT_PREFIXES = (
    "src/",
    "server/",
    "public/",
    "db/",
    "prisma/",
    "supabase/",
    "migrations/",
)

_ALLOWED_REQUIRED_ROOT_FILES = {
    "package.json",
    "vite.config.ts",
    "vite.config.js",
    "tsconfig.json",
    "tsconfig.node.json",
    "index.html",
    ".env",
    ".gitignore",
    "README.md",
}

_CORE_COMPILER_OWNED_REQUIRED_FILES = {
    "package.json",
    "tailwind.config.js",
    "postcss.config.js",
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
}

_ARCHITECTURE_OWNED_REQUIRED_PREFIXES = (
    "src/pages/",
    "src/services/",
    "src/hooks/",
    "src/context/",
    "src/types/",
    "server/routes/",
    "server/controllers/",
    "server/models/",
    "server/db/",
)

_ALLOWED_EXTENSION_REQUIRED_PREFIXES = (
    "src/components/",
    "src/layouts/",
    "src/styles/",
    "public/",
    "server/utils/",
    "server/lib/",
    "server/middleware/",
    "db/",
    "prisma/",
    "supabase/",
    "migrations/",
)


def _is_allowed_root_required_file(path: str) -> bool:
    normalized = str(path or "").strip()
    if not normalized or "/" in normalized:
        return False
    if normalized in _ALLOWED_REQUIRED_ROOT_FILES:
        return True
    if normalized.startswith(".env"):
        return True
    return bool(re.match(r"^[A-Za-z0-9._-]+\.(json|js|ts|cjs|mjs|md|yaml|yml|css|html|txt)$", normalized))


def _normalize_repo_relative_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    if not normalized or normalized in {".", "/"}:
        return ""
    if normalized.startswith("/"):
        return ""
    parts = PurePosixPath(normalized).parts
    if any(part == ".." for part in parts):
        return ""
    return normalized


def _normalize_route_path(path: str, default: str = "") -> str:
    normalized = str(path or default or "").strip()
    if not normalized:
        return ""
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def _coerce_builder_path(path: str) -> str:
    normalized = _normalize_repo_relative_path(path)
    if not normalized:
        return ""

    lower = normalized.lower()
    if any(lower.startswith(prefix) for prefix in ("src/components/", "src/pages/", "src/context/", "src/hooks/", "src/layouts/")):
        return re.sub(r"\.(ts|jsx|js)$", ".tsx", normalized, flags=re.IGNORECASE)
    if any(lower.startswith(prefix) for prefix in ("src/services/", "src/utils/", "src/store/", "src/types/")):
        return re.sub(r"\.(tsx|jsx|js)$", ".ts", normalized, flags=re.IGNORECASE)
    if lower.startswith("server/"):
        return re.sub(r"\.(js|tsx|jsx)$", ".ts", normalized, flags=re.IGNORECASE)
    if lower == "vite.config.js":
        return "vite.config.ts"
    return normalized


def _sanitize_required_file_path(path: str) -> str:
    normalized = _coerce_builder_path(path)
    if not normalized:
        return ""

    lower = normalized.lower()
    if lower.startswith(("node_modules/", ".git/", ".lovable/")):
        return ""

    if not _is_allowed_root_required_file(normalized) and not any(
        normalized.startswith(prefix) for prefix in _ALLOWED_REQUIRED_ROOT_PREFIXES
    ):
        return ""

    if lower.startswith("src/") and lower.endswith(".sql"):
        return ""
    if lower == "schema.sql":
        return ""
    if lower.startswith("server/") and lower.endswith(".js"):
        return ""

    return normalized


def _sanitize_state_owner_path(path: str) -> str:
    normalized = _coerce_builder_path(path)
    if not normalized:
        return "src/context/AuthContext.tsx"
    lower = normalized.lower()
    if not lower.startswith("src/"):
        return "src/context/AuthContext.tsx"
    if not lower.endswith((".ts", ".tsx")):
        return "src/context/AuthContext.tsx"
    return normalized


def _is_compiler_owned_required_path(path: str) -> bool:
    normalized = _coerce_builder_path(path)
    if not normalized:
        return False

    lower = normalized.lower()
    core_owned = {item.lower() for item in _CORE_COMPILER_OWNED_REQUIRED_FILES}
    return lower in core_owned or lower.startswith(_ARCHITECTURE_OWNED_REQUIRED_PREFIXES) or _is_auth_owned_path(normalized)


def _is_allowed_extension_required_path(path: str) -> bool:
    normalized = _coerce_builder_path(path)
    if not normalized:
        return False
    if normalized == "README.md":
        return True
    return normalized.lower().startswith(_ALLOWED_EXTENSION_REQUIRED_PREFIXES)


def _looks_like_project_resource(resource: "ApiResourceSpec") -> bool:
    haystack = " ".join(
        [
            str(getattr(resource, "name", "") or ""),
            str(getattr(resource, "entity", "") or ""),
            str(getattr(resource, "route", "") or ""),
        ]
    ).lower()
    return any(term in haystack for term in ("project", "case study", "case-study"))


def _classify_auth_resource(resource: "ApiResourceSpec") -> str:
    route = _normalize_route_path(getattr(resource, "route", "") or "")
    name = _slug(getattr(resource, "name", "") or "")
    entity = _slug(getattr(resource, "entity", "") or "")
    haystack = " ".join(part for part in (route, name, entity) if part).lower()
    authish = route.startswith("/api/auth/") or name.startswith("auth") or entity.startswith("auth")

    if route.endswith("/login") or (authish and any(term in haystack for term in ("signin", "sign_in", "sign-in", "login"))):
        return "login"
    if route.endswith("/register") or (authish and any(term in haystack for term in ("signup", "sign_up", "sign-up", "register"))):
        return "register"
    if route.endswith("/me") or (authish and re.search(r"(?:^|[_/\s-])(me|session|current_user|currentuser|profile)(?:$|[_/\s-])", haystack)):
        return "session"
    return ""


def _extract_json_block(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None

    ticks = "`" * 3
    match = re.search(rf"{ticks}(?:json)?\s*([\s\S]*?){ticks}", raw)
    if match:
        raw = match.group(1).strip()

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass

    brace_match = re.search(r"(\{[\s\S]*\})", raw)
    if brace_match:
        try:
            parsed = json.loads(brace_match.group(1))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def _contains_any(text: str, terms: tuple[str, ...] | list[str]) -> bool:
    haystack = str(text or "").lower()
    for term in terms:
        needle = str(term or "").strip().lower()
        if not needle:
            continue
        pattern = r"(?<!\w)" + re.escape(needle) + r"(?!\w)"
        if re.search(pattern, haystack):
            return True
    return False


def _prompt_requests_auth(prompt: str, feature_lines: list[str]) -> bool:
    prompt_text = str(prompt or "").lower()
    feature_text = " ".join(feature_lines or []).lower()
    auth_prompt_terms = ("auth", "login", "register", "sign in", "sign up", "user account", "profile", "admin", "member area")
    auth_feature_terms = ("auth", "authentication", "login", "register", "user account", "profile", "admin", "roles")
    auth_context_terms = ("user", "account", "profile", "dashboard", "portal", "admin", "member", "sign", "login", "register")
    return _contains_any(prompt_text, auth_prompt_terms) or (
        _contains_any(feature_text, auth_feature_terms)
        and _contains_any(prompt_text, auth_context_terms)
    )


def _is_generic_app_kind(value: str) -> bool:
    slug = _slug(value or "")
    return slug in {"", "website", "webapp", "web_app", "app", "site"}


def _is_auth_feature_label(value: str) -> bool:
    return _contains_any(str(value or ""), ("auth", "authentication", "login", "register", "sign in", "sign up", "account", "member"))


def _is_registration_feature_label(value: str) -> bool:
    return _contains_any(str(value or ""), ("register", "registration", "sign up", "signup"))


def _is_auth_acceptance_check(value: str) -> bool:
    return _contains_any(str(value or ""), ("auth", "login", "register", "sign in", "sign up", "session", "account"))


def _is_registration_acceptance_check(value: str) -> bool:
    return _contains_any(str(value or ""), ("register", "registration", "sign up", "signup"))


def _is_auth_owned_path(path: str) -> bool:
    normalized = _coerce_builder_path(path).lower()
    return normalized in {
        "server/utils/jwt.ts",
        "server/middleware/authmiddleware.ts",
        "server/controllers/authcontroller.ts",
        "server/routes/authroutes.ts",
        "src/services/authservice.ts",
        "src/context/authcontext.tsx",
        "src/hooks/useauth.tsx",
        "src/components/adminroute.tsx",
    }


@dataclass
class EntityField:
    name: str
    type: str = "string"
    required: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EntityField":
        return cls(
            name=str(data.get("name", "") or "").strip(),
            type=str(data.get("type", "string") or "string").strip(),
            required=bool(data.get("required", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EntitySpec:
    name: str
    fields: list[EntityField] = field(default_factory=list)
    public: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EntitySpec":
        return cls(
            name=str(data.get("name", "") or "").strip(),
            fields=[EntityField.from_dict(item) for item in list(data.get("fields", []) or []) if isinstance(item, dict)],
            public=bool(data.get("public", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "fields": [field.to_dict() for field in self.fields],
            "public": self.public,
        }


def _default_entity_fields_for_name(app_kind: str, entity_name: str, *, auth_enabled: bool = False) -> list[EntityField]:
    name = str(entity_name or "").strip().lower()

    if auth_enabled and name in {"user", "users"}:
        return [
            EntityField(name="username", required=True),
            EntityField(name="email", required=True),
            EntityField(name="password", required=True),
            EntityField(name="role"),
        ]

    if app_kind == "blog" and name in {"post", "posts", "article", "articles"}:
        return [
            EntityField(name="title", required=True),
            EntityField(name="slug", required=True),
            EntityField(name="content", required=True, type="text"),
            EntityField(name="excerpt", type="text"),
            EntityField(name="categoryId", type="integer"),
        ]
    if app_kind == "blog" and name in {"category", "categories"}:
        return [
            EntityField(name="name", required=True),
            EntityField(name="slug", required=True),
            EntityField(name="description", type="text"),
        ]
    if name in {"comment", "comments"}:
        return [
            EntityField(name="postId", type="integer", required=True),
            EntityField(name="authorName", required=True),
            EntityField(name="content", type="text", required=True),
        ]
    if app_kind == "ecommerce" and name in {"product", "products"}:
        return [
            EntityField(name="name", required=True),
            EntityField(name="slug", required=True),
            EntityField(name="description", type="text"),
            EntityField(name="price", type="number", required=True),
            EntityField(name="imageUrl"),
        ]
    if app_kind == "portfolio" and name in {"project", "projects"}:
        return [
            EntityField(name="title", required=True),
            EntityField(name="slug", required=True),
            EntityField(name="description", type="text", required=True),
            EntityField(name="imageUrl"),
            EntityField(name="category"),
            EntityField(name="year", type="integer"),
            EntityField(name="fullDescription", type="text"),
        ]
    return []


def _field_identity_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


@dataclass
class ApiResourceSpec:
    name: str
    route: str
    methods: list[str] = field(default_factory=list)
    entity: str = ""
    frontend: bool = True
    auth: str = "public"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApiResourceSpec":
        route = str(data.get("route", "") or "").strip()
        if route and not route.startswith("/"):
            route = f"/{route}"
        return cls(
            name=str(data.get("name", "") or "").strip(),
            route=route,
            methods=[str(item).strip().lower() for item in list(data.get("methods", []) or []) if str(item).strip()],
            entity=str(data.get("entity", "") or "").strip(),
            frontend=bool(data.get("frontend", True)),
            auth=str(data.get("auth", "public") or "public").strip().lower(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PageSpec:
    name: str
    route: str
    purpose: str = ""
    auth: str = "public"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PageSpec":
        route = str(data.get("route", "") or "").strip() or "/"
        if not route.startswith("/"):
            route = f"/{route}"
        return cls(
            name=str(data.get("name", "") or "").strip() or _component_name("", route),
            route=route,
            purpose=str(data.get("purpose", "") or "").strip(),
            auth=str(data.get("auth", "public") or "public").strip().lower(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuthSpec:
    enabled: bool = False
    mode: str = "token"
    roles: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)
    allow_registration: bool = True
    login_route: str = "/api/auth/login"
    register_route: str = "/api/auth/register"
    session_route: str = "/api/auth/me"
    state_owner: str = "src/context/AuthContext.tsx"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuthSpec":
        identifiers = [
            str(item).strip().lower()
            for item in list(data.get("identifiers", []) or [])
            if str(item).strip()
        ]
        return cls(
            enabled=bool(data.get("enabled", False)),
            mode=str(data.get("mode", "token") or "token").strip().lower(),
            roles=[str(item).strip().lower() for item in list(data.get("roles", []) or []) if str(item).strip()],
            identifiers=identifiers,
            allow_registration=bool(data.get("allow_registration", True)),
            login_route=str(data.get("login_route", "/api/auth/login") or "/api/auth/login").strip(),
            register_route=str(data.get("register_route", "/api/auth/register") or "/api/auth/register").strip(),
            session_route=str(data.get("session_route", "/api/auth/me") or "/api/auth/me").strip(),
            state_owner=str(data.get("state_owner", "src/context/AuthContext.tsx") or "src/context/AuthContext.tsx").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectSpec:
    product_type: str = "website"
    app_kind: str = "website"
    summary: str = ""
    features: list[str] = field(default_factory=list)
    entities: list[EntitySpec] = field(default_factory=list)
    api_resources: list[ApiResourceSpec] = field(default_factory=list)
    pages: list[PageSpec] = field(default_factory=list)
    auth: AuthSpec = field(default_factory=AuthSpec)
    required_files: list[str] = field(default_factory=list)
    acceptance_checks: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectSpec":
        spec = cls(
            product_type=str(data.get("product_type", "website") or "website").strip().lower(),
            app_kind=str(data.get("app_kind", "website") or "website").strip().lower(),
            summary=str(data.get("summary", "") or "").strip(),
            features=[str(item).strip() for item in list(data.get("features", []) or []) if str(item).strip()],
            entities=[EntitySpec.from_dict(item) for item in list(data.get("entities", []) or []) if isinstance(item, dict)],
            api_resources=[ApiResourceSpec.from_dict(item) for item in list(data.get("api_resources", []) or []) if isinstance(item, dict)],
            pages=[PageSpec.from_dict(item) for item in list(data.get("pages", []) or []) if isinstance(item, dict)],
            auth=AuthSpec.from_dict(data.get("auth", {}) if isinstance(data.get("auth", {}), dict) else {}),
            required_files=[str(item).strip() for item in list(data.get("required_files", []) or []) if str(item).strip()],
            acceptance_checks=[str(item).strip() for item in list(data.get("acceptance_checks", []) or []) if str(item).strip()],
        )
        spec.normalize()
        return spec

    def normalize(self) -> None:
        self.product_type = self.product_type or "website"
        self.app_kind = self.app_kind or "website"
        if not self.features:
            self.features = ["Core"]
        self.auth.roles = [role for index, role in enumerate(self.auth.roles) if role and role not in self.auth.roles[:index]]
        self.auth.identifiers = [
            value
            for index, value in enumerate(self.auth.identifiers or [])
            if value and value not in (self.auth.identifiers or [])[:index]
        ] or (["email"] if self.auth.enabled else [])
        self.auth.login_route = _normalize_route_path(self.auth.login_route, "/api/auth/login")
        self.auth.register_route = _normalize_route_path(self.auth.register_route, "/api/auth/register")
        self.auth.session_route = _normalize_route_path(self.auth.session_route, "/api/auth/me")
        self.auth.state_owner = _sanitize_state_owner_path(self.auth.state_owner or "src/context/AuthContext.tsx")

        dedup_pages: list[PageSpec] = []
        seen_routes: set[str] = set()
        for page in self.pages or []:
            route = page.route or "/"
            if getattr(page, "auth", "") == "protected":
                self.auth.enabled = True
            if route in seen_routes:
                continue
            seen_routes.add(route)
            dedup_pages.append(page)
        self.pages = dedup_pages or [PageSpec(name="Home", route="/", purpose="Primary page", auth="public")]

        auth_route_overrides: dict[str, str] = {}
        non_auth_resources: list[ApiResourceSpec] = []
        for resource in self.api_resources or []:
            if getattr(resource, "auth", "") == "protected":
                self.auth.enabled = True
            auth_kind = _classify_auth_resource(resource)
            if not auth_kind:
                non_auth_resources.append(resource)
                continue

            self.auth.enabled = True
            normalized_route = _normalize_route_path(resource.route)
            if normalized_route:
                auth_route_overrides[auth_kind] = normalized_route
            if auth_kind == "register":
                self.auth.allow_registration = True

        if auth_route_overrides.get("login"):
            self.auth.login_route = auth_route_overrides["login"]
        if auth_route_overrides.get("register"):
            self.auth.register_route = auth_route_overrides["register"]
        if auth_route_overrides.get("session"):
            self.auth.session_route = auth_route_overrides["session"]

        dedup_resources: list[ApiResourceSpec] = []
        seen_resource_routes: set[str] = set()
        auth_routes = {
            _normalize_route_path(self.auth.login_route),
            _normalize_route_path(self.auth.register_route),
            _normalize_route_path(self.auth.session_route),
        }
        for resource in non_auth_resources:
            resource.route = _normalize_route_path(resource.route)
            route = resource.route or ""
            if route in auth_routes:
                continue
            if route in seen_resource_routes:
                continue
            seen_resource_routes.add(route)
            dedup_resources.append(resource)
        self.api_resources = dedup_resources

        if self.app_kind == "portfolio" and not any(_looks_like_project_resource(resource) for resource in self.api_resources):
            self.api_resources.append(
                ApiResourceSpec(
                    name="projects",
                    route="/api/projects",
                    methods=["list", "detail"],
                    entity="Project",
                    frontend=True,
                    auth="public",
                )
            )

        dedup_entities: list[EntitySpec] = []
        seen_entities: set[str] = set()
        for entity in self.entities or []:
            name = str(entity.name or "").strip()
            if not name or name.lower() in seen_entities:
                continue
            seen_entities.add(name.lower())
            default_fields = _default_entity_fields_for_name(
                self.app_kind,
                name,
                auth_enabled=self.auth.enabled,
            )
            if not entity.fields:
                entity.fields = default_fields
            elif default_fields:
                existing_keys = {_field_identity_key(field.name) for field in entity.fields}
                for default_field in default_fields:
                    if _field_identity_key(default_field.name) in existing_keys:
                        continue
                    entity.fields.append(default_field)
                    existing_keys.add(_field_identity_key(default_field.name))
            dedup_entities.append(entity)

        if self.auth.enabled and "user" not in seen_entities:
            dedup_entities.append(
                EntitySpec(
                    name="User",
                    fields=_default_entity_fields_for_name(self.app_kind, "User", auth_enabled=True),
                )
            )
            seen_entities.add("user")

        for resource in self.api_resources:
            entity_name = str(resource.entity or "").strip()
            if not entity_name or entity_name.lower() in seen_entities:
                continue
            default_fields = _default_entity_fields_for_name(
                self.app_kind,
                entity_name,
                auth_enabled=self.auth.enabled,
            )
            if default_fields:
                dedup_entities.append(EntitySpec(name=entity_name, fields=default_fields))
                seen_entities.add(entity_name.lower())
        self.entities = dedup_entities

        if self.app_kind == "portfolio":
            if not any(page.route == "/" for page in self.pages):
                self.pages.insert(0, PageSpec(name="Home", route="/", purpose="Primary portfolio landing", auth="public"))

            detail_page = next((page for page in self.pages if _looks_like_portfolio_detail_page(page)), None)
            if detail_page is None:
                self.pages.append(
                    PageSpec(
                        name="ProjectDetail",
                        route="/projects/:id",
                        purpose="Read a project case study",
                        auth="public",
                    )
                )
            else:
                detail_page.name = detail_page.name or "ProjectDetail"
                detail_page.route = "/projects/:id"
                detail_page.purpose = detail_page.purpose or "Read a project case study"

        dedup_required = []
        seen_required = set()
        for path in self.required_files:
            cleaned = _sanitize_required_file_path(path)
            if not cleaned:
                continue
            if _is_compiler_owned_required_path(cleaned):
                continue
            if not _is_allowed_extension_required_path(cleaned):
                continue
            if cleaned not in seen_required:
                seen_required.add(cleaned)
                dedup_required.append(cleaned)
        self.required_files = dedup_required

        if self.auth.enabled:
            if not any(_looks_like_login_page(page) for page in self.pages):
                self.pages.append(PageSpec(name="Login", route="/login", purpose="User sign-in", auth="public"))
            if self.auth.allow_registration and not any(_looks_like_register_page(page) for page in self.pages):
                self.pages.append(PageSpec(name="Register", route="/register", purpose="User sign-up", auth="public"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_type": self.product_type,
            "app_kind": self.app_kind,
            "summary": self.summary,
            "features": list(self.features),
            "entities": [entity.to_dict() for entity in self.entities],
            "api_resources": [resource.to_dict() for resource in self.api_resources],
            "pages": [page.to_dict() for page in self.pages],
            "auth": self.auth.to_dict(),
            "required_files": list(self.required_files),
            "acceptance_checks": list(self.acceptance_checks),
        }

    def auth_required_page_routes(self) -> list[str]:
        if not self.auth.enabled:
            return []
        routes = ["/login"]
        if self.auth.allow_registration:
            routes.append("/register")
        return routes

    def auth_api_endpoints(self) -> list[str]:
        if not self.auth.enabled:
            return []
        endpoints = [
            f"POST {self.auth.login_route}",
            f"GET {self.auth.session_route}",
        ]
        if self.auth.allow_registration:
            endpoints.append(f"POST {self.auth.register_route}")
        return endpoints


def infer_project_spec(prompt: str, feature_lines: list[str], design_summary: dict[str, Any] | None = None) -> ProjectSpec:
    prompt_text = str(prompt or "").lower()
    feature_text = " ".join(feature_lines).lower()
    text = " ".join(part for part in [prompt_text, feature_text] if part)
    design_summary = dict(design_summary or {})

    if _contains_any(prompt_text, ("dashboard", "analytics", "admin panel", "admin dashboard")):
        app_kind = "dashboard"
    elif _contains_any(prompt_text, ("blog", "news", "articles", "editorial", "magazine", "content platform")):
        app_kind = "blog"
    elif _contains_any(prompt_text, ("shop", "store", "ecommerce", "e-commerce", "products")):
        app_kind = "ecommerce"
    elif _contains_any(prompt_text, ("marketplace",)):
        app_kind = "marketplace"
    elif _contains_any(prompt_text, ("portfolio",)):
        app_kind = "portfolio"
    elif _contains_any(prompt_text, ("landing page", "marketing site", "saas landing")):
        app_kind = "landing_page"
    elif _contains_any(prompt_text, ("app", "booking", "portal", "platform", "account")):
        app_kind = "web_app"
    elif _contains_any(feature_text, ("dashboard", "analytics")):
        app_kind = "dashboard"
    elif _contains_any(feature_text, ("blog", "news", "articles", "editorial")):
        app_kind = "blog"
    elif _contains_any(feature_text, ("shop", "store", "ecommerce", "products")):
        app_kind = "ecommerce"
    else:
        app_kind = "website"

    auth_enabled = _prompt_requests_auth(prompt, feature_lines)
    if _contains_any(text, ("phone", "phone number", "mobile", "sms", "otp", "verification code")):
        auth_identifiers = ["phone"]
    elif _contains_any(text, ("username", "handle")):
        auth_identifiers = ["username"]
    else:
        auth_identifiers = ["email"]
    auth_mode = "otp" if _contains_any(text, ("otp", "sms", "verification code", "magic link")) else "token"
    allow_registration = not _contains_any(
        text,
        ("admin-only", "admin only", "internal tool", "staff only", "private dashboard", "backoffice", "employee only"),
    )
    spec = ProjectSpec(
        product_type=app_kind,
        app_kind=app_kind,
        summary=str(design_summary.get("summary", "") or prompt).strip(),
        features=feature_lines or ["Core"],
        auth=AuthSpec(
            enabled=auth_enabled,
            mode=auth_mode,
            roles=["user", "admin"] if _contains_any(text, ("admin",)) else ["user"],
            identifiers=auth_identifiers if auth_enabled else [],
            allow_registration=allow_registration,
        ),
    )

    spec.pages.append(PageSpec(name="Home", route="/", purpose="Primary application entry", auth="public"))
    if auth_enabled:
        spec.pages.append(PageSpec(name="Login", route="/login", purpose="Sign in", auth="public"))
        if allow_registration:
            spec.pages.append(PageSpec(name="Register", route="/register", purpose="Sign up", auth="public"))
    if _contains_any(text, ("dashboard", "admin", "analytics")):
        spec.pages.append(PageSpec(name="Dashboard", route="/dashboard", purpose="Authenticated dashboard", auth="protected"))

    if app_kind == "blog":
        spec.entities.extend([
            EntitySpec(
                name="Post",
                fields=[
                    EntityField(name="title", required=True),
                    EntityField(name="slug", required=True),
                    EntityField(name="content", type="text", required=True),
                    EntityField(name="excerpt", type="text"),
                    EntityField(name="categoryId", type="integer"),
                ],
            ),
            EntitySpec(
                name="Category",
                fields=[
                    EntityField(name="name", required=True),
                    EntityField(name="slug", required=True),
                    EntityField(name="description", type="text"),
                ],
            ),
        ])
        spec.api_resources.extend([
            ApiResourceSpec(name="posts", route="/api/posts", methods=["list", "detail"], entity="Post", frontend=True, auth="public"),
            ApiResourceSpec(name="categories", route="/api/categories", methods=["list"], entity="Category", frontend=True, auth="public"),
        ])
        if _contains_any(text, ("comment", "comments")):
            spec.entities.append(
                EntitySpec(
                    name="Comment",
                    fields=[
                        EntityField(name="postId", type="integer", required=True),
                        EntityField(name="authorName", required=True),
                        EntityField(name="content", type="text", required=True),
                    ],
                )
            )
            spec.api_resources.append(ApiResourceSpec(name="comments", route="/api/comments", methods=["list", "create"], entity="Comment", frontend=True, auth="public"))
        if "categor" in text:
            spec.pages.append(PageSpec(name="CategoryDetail", route="/categories/:slug", purpose="Browse a category", auth="public"))
        spec.pages.append(PageSpec(name="PostDetail", route="/posts/:slug", purpose="Read a single post", auth="public"))

    if app_kind == "ecommerce":
        spec.entities.append(
            EntitySpec(
                name="Product",
                fields=[
                    EntityField(name="name", required=True),
                    EntityField(name="slug", required=True),
                    EntityField(name="description", type="text"),
                    EntityField(name="price", type="number", required=True),
                    EntityField(name="imageUrl"),
                ],
            )
        )
        spec.api_resources.append(ApiResourceSpec(name="products", route="/api/products", methods=["list", "detail"], entity="Product", frontend=True, auth="public"))
        spec.pages.append(PageSpec(name="ProductDetail", route="/products/:slug", purpose="View a single product", auth="public"))

    if app_kind == "portfolio":
        spec.entities.append(
            EntitySpec(
                name="Project",
                fields=[
                    EntityField(name="title", required=True),
                    EntityField(name="slug", required=True),
                    EntityField(name="description", type="text", required=True),
                    EntityField(name="imageUrl"),
                    EntityField(name="category"),
                    EntityField(name="year", type="integer"),
                    EntityField(name="fullDescription", type="text"),
                ],
            )
        )
        spec.api_resources.append(
            ApiResourceSpec(
                name="projects",
                route="/api/projects",
                methods=["list", "detail"],
                entity="Project",
                frontend=True,
                auth="public",
            )
        )
        spec.pages.append(PageSpec(name="ProjectDetail", route="/projects/:id", purpose="Read a project case study", auth="public"))

    acceptance_checks = [
        "frontend build succeeds",
        "backend health endpoint responds",
        "home page renders",
    ]
    if spec.auth.enabled:
        if spec.auth.allow_registration:
            acceptance_checks.append("login and registration flows are wired to the backend")
        else:
            acceptance_checks.append("login flow is wired to the backend")
    for resource in spec.api_resources:
        acceptance_checks.append(f"{resource.route} is mounted and returns a valid response")
    spec.acceptance_checks = acceptance_checks[:6]

    spec.normalize()
    return spec


def parse_project_spec_response(
    response: str,
    *,
    prompt: str,
    feature_lines: list[str],
    design_summary: dict[str, Any] | None = None,
) -> ProjectSpec:
    def _align_spec_with_prompt_contract(spec: ProjectSpec) -> ProjectSpec:
        inferred = infer_project_spec(prompt, feature_lines, design_summary=design_summary)

        if _is_generic_app_kind(spec.product_type) and not _is_generic_app_kind(inferred.product_type):
            spec.product_type = inferred.product_type
        if _is_generic_app_kind(spec.app_kind) and not _is_generic_app_kind(inferred.app_kind):
            spec.app_kind = inferred.app_kind

        if not inferred.auth.enabled:
            spec.auth.enabled = False
            spec.auth.roles = []
            spec.auth.identifiers = []
            spec.auth.allow_registration = False
            spec.pages = [
                page
                for page in spec.pages
                if not _looks_like_login_page(page) and not _looks_like_register_page(page)
            ]
            spec.api_resources = [
                resource
                for resource in spec.api_resources
                if not _classify_auth_resource(resource)
            ]
            spec.required_files = [path for path in spec.required_files if not _is_auth_owned_path(path)]
            spec.features = [feature for feature in spec.features if not _is_auth_feature_label(feature)]
            spec.acceptance_checks = [
                check for check in spec.acceptance_checks
                if not _is_auth_acceptance_check(check)
            ]
        else:
            spec.auth.enabled = True
            spec.auth.mode = str(spec.auth.mode or inferred.auth.mode or "token").strip() or inferred.auth.mode
            spec.auth.identifiers = list(spec.auth.identifiers or inferred.auth.identifiers or [])
            spec.auth.roles = list(spec.auth.roles or inferred.auth.roles or [])

            if not inferred.auth.allow_registration:
                spec.auth.allow_registration = False
                spec.pages = [page for page in spec.pages if not _looks_like_register_page(page)]
                spec.api_resources = [
                    resource
                    for resource in spec.api_resources
                    if _classify_auth_resource(resource) != "register"
                ]
                spec.features = [feature for feature in spec.features if not _is_registration_feature_label(feature)]
                spec.acceptance_checks = [
                    check for check in spec.acceptance_checks
                    if not _is_registration_acceptance_check(check)
                ]

        if not spec.features:
            spec.features = list(inferred.features or ["Core"])
        if not spec.acceptance_checks:
            spec.acceptance_checks = list(inferred.acceptance_checks)

        spec.normalize()
        return spec

    parsed = _extract_json_block(response)
    if isinstance(parsed, dict):
        try:
            return _align_spec_with_prompt_contract(ProjectSpec.from_dict(parsed))
        except Exception:
            pass
    return infer_project_spec(prompt, feature_lines, design_summary=design_summary)


def _unique_nonempty_strings(values: list[Any] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    return cleaned


def _normalize_blueprint_batch_name(batch_name: str, path: str) -> str:
    raw = str(batch_name or "").strip()
    if raw:
        slug = _slug(raw[6:] if raw.startswith("batch_") else raw)
        return f"batch_{slug}" if slug else "batch_core"

    normalized_path = _coerce_builder_path(path)
    stem = PurePosixPath(normalized_path).stem
    stem = re.sub(r"^(use)(?=[A-Z])", "", stem)
    stem = re.sub(r"(Controller|Routes|Route|Service|Provider|Context|Page)$", "", stem, flags=re.IGNORECASE)
    slug = _slug(stem or PurePosixPath(normalized_path).parent.name or "core")
    return f"batch_{slug}" if slug else "batch_core"


def _normalize_blueprint_imports(values: list[Any] | None) -> list[dict[str, Any]]:
    normalized_imports: list[dict[str, Any]] = []
    seen: set[str] = set()

    for value in list(values or []):
        if not isinstance(value, dict):
            continue

        source = str(value.get("source", "") or "").strip()
        raw_target = str(value.get("target", "") or "").strip()
        target = _sanitize_required_file_path(raw_target) if raw_target else ""
        mode = str(value.get("mode", "") or "").strip()
        role = str(value.get("role", "") or "").strip()
        mount_path = _normalize_route_path(str(value.get("mount_path", "") or "").strip(), "")
        required = value.get("required")

        entry: dict[str, Any] = {}
        if source:
            entry["source"] = source
        if target:
            entry["target"] = target
        if mode:
            entry["mode"] = mode
        if mount_path:
            entry["mount_path"] = mount_path
        if role:
            entry["role"] = role
        if required is not None:
            entry["required"] = bool(required)

        if not entry:
            continue

        marker = json.dumps(entry, sort_keys=True)
        if marker in seen:
            continue
        seen.add(marker)
        normalized_imports.append(entry)

    return normalized_imports


def _normalize_blueprint_endpoint(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""

    match = re.match(r"([A-Za-z]+)\s+(.+)", normalized)
    if not match:
        return normalized

    method = match.group(1).upper()
    route = _normalize_route_path(match.group(2).strip(), match.group(2).strip())
    return f"{method} {route}" if route else f"{method} {match.group(2).strip()}"


def parse_file_blueprint_response(response: str) -> list[dict[str, Any]]:
    parsed = _extract_json_block(response)
    raw_files = parsed.get("files") if isinstance(parsed, dict) else None
    if not isinstance(raw_files, list):
        return []

    blueprint_files: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    for item in raw_files:
        if not isinstance(item, dict):
            continue

        path = _sanitize_required_file_path(str(item.get("path", "") or "").strip())
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)

        depends_on = [
            dep
            for dep in (
                _sanitize_required_file_path(str(dep or "").strip())
                for dep in list(item.get("depends_on", []) or [])
            )
            if dep
        ]
        api_endpoints_used = [
            endpoint
            for endpoint in (_normalize_blueprint_endpoint(value) for value in list(item.get("api_endpoints_used", []) or []))
            if endpoint
        ]
        api_endpoints_provided = [
            endpoint
            for endpoint in (_normalize_blueprint_endpoint(value) for value in list(item.get("api_endpoints_provided", []) or []))
            if endpoint
        ]

        blueprint_files.append(
            {
                "path": path,
                "batch_name": _normalize_blueprint_batch_name(str(item.get("batch_name", "") or "").strip(), path),
                "imports": _normalize_blueprint_imports(item.get("imports", [])),
                "exports": _unique_nonempty_strings(item.get("exports", [])),
                "functions": _unique_nonempty_strings(item.get("functions", [])),
                "variables": _unique_nonempty_strings(item.get("variables", [])),
                "api_endpoints_used": _unique_nonempty_strings(api_endpoints_used),
                "api_endpoints_provided": _unique_nonempty_strings(api_endpoints_provided),
                "depends_on": _unique_nonempty_strings(depends_on),
            }
        )

    return blueprint_files


def compile_file_blueprint(project_spec: ProjectSpec) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    file_index_by_path: dict[str, int] = {}
    helper_components: dict[str, str] = {}
    resource_frontend_links: dict[str, dict[str, str]] = {}

    def add_file(
        path: str,
        *,
        batch_name: str,
        imports: list[dict[str, Any]] | None = None,
        exports: list[str] | None = None,
        functions: list[str] | None = None,
        depends_on: list[str] | None = None,
        api_endpoints_used: list[str] | None = None,
        api_endpoints_provided: list[str] | None = None,
    ) -> None:
        clean_path = str(path).strip().replace("\\", "/")
        if not clean_path or clean_path in seen_paths:
            return
        seen_paths.add(clean_path)
        file_index_by_path[clean_path] = len(files)
        files.append({
            "path": clean_path,
            "batch_name": batch_name,
            "imports": list(imports or []),
            "exports": list(exports or []),
            "functions": list(functions or []),
            "variables": [],
            "api_endpoints_used": list(api_endpoints_used or []),
            "api_endpoints_provided": list(api_endpoints_provided or []),
            "depends_on": list(depends_on or []),
        })

    def merge_file_contract(
        path: str,
        *,
        imports: list[dict[str, Any]] | None = None,
        exports: list[str] | None = None,
        functions: list[str] | None = None,
        depends_on: list[str] | None = None,
        api_endpoints_used: list[str] | None = None,
        api_endpoints_provided: list[str] | None = None,
    ) -> None:
        clean_path = str(path).strip().replace("\\", "/")
        index = file_index_by_path.get(clean_path)
        if index is None:
            return

        item = files[index]

        def merge_list(key: str, values: list[Any] | None) -> None:
            if not values:
                return
            existing = list(item.get(key) or [])
            seen = {
                json.dumps(value, sort_keys=True) if isinstance(value, dict) else str(value)
                for value in existing
            }
            for value in values:
                marker = json.dumps(value, sort_keys=True) if isinstance(value, dict) else str(value)
                if marker in seen:
                    continue
                seen.add(marker)
                existing.append(value)
            item[key] = existing

        merge_list("imports", list(imports or []))
        merge_list("exports", list(exports or []))
        merge_list("functions", list(functions or []))
        merge_list("depends_on", list(depends_on or []))
        merge_list("api_endpoints_used", list(api_endpoints_used or []))
        merge_list("api_endpoints_provided", list(api_endpoints_provided or []))

    type_exports: set[str] = set()
    if project_spec.auth.enabled:
        type_exports.update({"User", "AuthResponse", "LoginCredentials"})
        if project_spec.auth.allow_registration:
            type_exports.add("RegisterCredentials")
    for resource in project_spec.api_resources:
        entity_name = str(resource.entity or "").strip()
        if entity_name:
            type_exports.add(_pascal(entity_name))

    core_files = [
        ("package.json", [], "batch_tooling"),
        ("tailwind.config.js", [], "batch_tooling"),
        ("postcss.config.js", [], "batch_tooling"),
        ("vite.config.ts", [], "batch_tooling"),
        ("tsconfig.json", [], "batch_tooling"),
        ("tsconfig.node.json", [], "batch_tooling"),
        ("index.html", [], "batch_tooling"),
        (".env", [], "batch_tooling"),
        (".gitignore", [], "batch_tooling"),
        ("src/main.tsx", [], "batch_frontend_shell"),
        ("src/App.tsx", ["default"], "batch_frontend_shell"),
        ("src/styles/variables.css", [], "batch_frontend_shell"),
        ("src/styles/global.css", [], "batch_frontend_shell"),
        ("src/services/api.ts", ["api", "default"], "batch_client_shared"),
        ("server/index.ts", ["default"], "batch_server_entry"),
        ("server/db/database.ts", ["default"], "batch_data"),
    ]
    for path, exports, batch_name in core_files:
        add_file(path, batch_name=batch_name, exports=exports)
    add_file("src/types/index.ts", batch_name="batch_client_shared", exports=sorted(type_exports))

    server_entry_depends_on = ["server/db/database.ts"]
    server_entry_imports: list[dict[str, Any]] = [
        {
            "source": "./db/database",
            "target": "server/db/database.ts",
            "mode": "load",
            "required": True,
            "role": "database_init",
        }
    ]
    server_entry_api_provided = ["GET /api/health"]

    site_like_kinds = {"website", "landing_page", "blog", "portfolio", "ecommerce", "marketplace", "business_site"}
    has_home = any(page.route == "/" for page in project_spec.pages)
    if has_home and project_spec.app_kind in site_like_kinds:
        add_file("src/components/Hero.tsx", batch_name="batch_ui", exports=["default"], depends_on=["src/styles/variables.css"])
    if len(project_spec.pages) > 1 or project_spec.app_kind in site_like_kinds:
        add_file("src/components/Navbar.tsx", batch_name="batch_ui", exports=["default"], depends_on=["src/App.tsx"])
    if project_spec.app_kind in site_like_kinds:
        add_file("src/components/Footer.tsx", batch_name="batch_ui", exports=["default"], depends_on=["src/App.tsx"])

    if project_spec.auth.enabled:
        auth_api_endpoints = project_spec.auth_api_endpoints()
        auth_controller_exports = ["login", "me"]
        auth_service_functions = ["login", "getCurrentUser", "logout"]
        auth_context_functions = ["login", "logout", "refreshSession"]
        if project_spec.auth.allow_registration:
            auth_controller_exports.insert(1, "register")
            auth_service_functions.insert(1, "register")
            auth_context_functions.insert(1, "register")
        add_file(
            "server/utils/jwt.ts",
            batch_name="batch_auth",
            exports=["generateToken", "verifyToken"],
            functions=["generateToken", "verifyToken"],
        )
        add_file(
            "server/middleware/authMiddleware.ts",
            batch_name="batch_auth",
            exports=["protect"],
            depends_on=["server/utils/jwt.ts"],
        )
        add_file(
            "server/controllers/authController.ts",
            batch_name="batch_auth",
            exports=auth_controller_exports,
            functions=auth_controller_exports,
            depends_on=["server/db/database.ts", "server/utils/jwt.ts"],
            api_endpoints_provided=auth_api_endpoints,
        )
        add_file(
            "server/routes/authRoutes.ts",
            batch_name="batch_auth",
            exports=["default"],
            depends_on=["server/controllers/authController.ts", "server/middleware/authMiddleware.ts"],
            api_endpoints_provided=auth_api_endpoints,
        )
        server_entry_depends_on.append("server/routes/authRoutes.ts")
        server_entry_imports.append(
            {
                "source": "./routes/authRoutes",
                "target": "server/routes/authRoutes.ts",
                "mode": "mount",
                "mount_path": "/api/auth",
                "required": True,
            }
        )
        server_entry_api_provided.extend(auth_api_endpoints)
        add_file(
            "src/services/authService.ts",
            batch_name="batch_auth",
            exports=auth_service_functions,
            functions=auth_service_functions,
            depends_on=["src/services/api.ts"],
            api_endpoints_used=auth_api_endpoints,
        )
        add_file(
            project_spec.auth.state_owner,
            batch_name="batch_auth",
            exports=["AuthContext", "AuthProvider", "useAuth"],
            functions=auth_context_functions,
            depends_on=["src/services/authService.ts", "src/types/index.ts"],
            api_endpoints_used=auth_api_endpoints,
        )
        add_file(
            "src/hooks/useAuth.tsx",
            batch_name="batch_auth",
            exports=["default", "useAuth"],
            functions=["useAuth"],
            depends_on=[project_spec.auth.state_owner, "src/types/index.ts"],
        )
        if "admin" in project_spec.auth.roles:
            add_file(
                "src/components/AdminRoute.tsx",
                batch_name="batch_auth",
                exports=["default"],
                depends_on=[project_spec.auth.state_owner],
            )

    for resource in project_spec.api_resources:
        slug = _slug(resource.name or resource.route.strip("/").split("/")[-1])
        singular = _singular_slug(slug)
        batch_name = f"batch_{singular}"
        controller_path = f"server/controllers/{singular}Controller.ts"
        route_path = f"server/routes/{singular}Routes.ts"
        service_path = f"src/services/{singular}Service.ts"
        hook_path = f"src/hooks/use{_pascal(slug)}.tsx"

        method_exports = {
            "list": "list",
            "detail": "getById",
            "create": "create",
            "update": "update",
            "delete": "remove",
        }
        controller_functions = [method_exports[m] for m in resource.methods if m in method_exports] or ["list"]
        add_file(
            controller_path,
            batch_name=batch_name,
            exports=controller_functions,
            functions=controller_functions,
            depends_on=["server/db/database.ts"],
            api_endpoints_provided=[f"{method.upper()} {resource.route}" for method in resource.methods] or [f"GET {resource.route}"],
        )
        add_file(
            route_path,
            batch_name=batch_name,
            exports=["default"],
            depends_on=[controller_path] + (["server/middleware/authMiddleware.ts"] if resource.auth != "public" and project_spec.auth.enabled else []),
            api_endpoints_provided=[f"{method.upper()} {resource.route}" for method in resource.methods] or [f"GET {resource.route}"],
        )
        server_entry_depends_on.append(route_path)
        server_entry_imports.append(
            {
                "source": f"./routes/{singular}Routes",
                "target": route_path,
                "mode": "mount",
                "mount_path": resource.route,
                "required": True,
            }
        )
        server_entry_api_provided.extend(
            [f"{method.upper()} {resource.route}" for method in resource.methods] or [f"GET {resource.route}"]
        )
        if resource.frontend:
            add_file(
                service_path,
                batch_name=batch_name,
                exports=["default"],
                functions=controller_functions,
                depends_on=["src/services/api.ts", "src/types/index.ts"],
                api_endpoints_used=[f"{method.upper()} {resource.route}" for method in resource.methods] or [f"GET {resource.route}"],
            )
            add_file(
                hook_path,
                batch_name=batch_name,
                exports=[f"use{_pascal(slug)}"],
                functions=[f"use{_pascal(slug)}"],
                depends_on=[service_path, "src/types/index.ts"],
                api_endpoints_used=[f"{method.upper()} {resource.route}" for method in resource.methods] or [f"GET {resource.route}"],
            )

            helper_component_map = {
                "post": "src/components/PostCard.tsx",
                "article": "src/components/ArticleCard.tsx",
                "product": "src/components/ProductCard.tsx",
                "project": "src/components/ProjectCard.tsx",
                "category": "src/components/CategoryList.tsx",
                "comment": "src/components/CommentSection.tsx",
            }
            helper_component_path = helper_component_map.get(singular)
            if helper_component_path:
                helper_components[singular] = helper_component_path
                helper_depends_on = ["src/types/index.ts"]
                if singular in {"post", "article", "product", "project"}:
                    helper_depends_on.append(service_path)
                add_file(
                    helper_component_path,
                    batch_name=batch_name,
                    exports=["default"],
                    depends_on=helper_depends_on,
                )
                if singular == "project":
                    add_file(
                        "src/components/ProjectGrid.tsx",
                        batch_name=batch_name,
                        exports=["default"],
                        depends_on=[
                            hook_path,
                            helper_component_path,
                            "src/types/index.ts",
                        ],
                    )
            resource_frontend_links[singular] = {
                "slug": slug,
                "service": service_path,
                "hook": hook_path,
                "component": helper_component_path or "",
                "grid": "src/components/ProjectGrid.tsx" if singular == "project" else "",
            }

    for page in project_spec.pages:
        component = _component_name(page.name, page.route)
        batch_slug = _slug(page.name or page.route.strip("/") or "pages")
        depends_on = ["src/App.tsx", "src/types/index.ts"]
        page_haystack = " ".join(
            [
                str(page.name or "").lower(),
                str(page.route or "").lower(),
                str(page.purpose or "").lower(),
            ]
        )
        def add_dep(path: str) -> None:
            clean = str(path or "").strip()
            if clean and clean not in depends_on:
                depends_on.append(clean)
        if page.auth != "public" and project_spec.auth.enabled:
            add_dep(project_spec.auth.state_owner)

        if project_spec.app_kind == "blog":
            if helper_components.get("post") and (
                page.route == "/"
                or "landing" in page_haystack
                or "home" in page_haystack
                or "categor" in page_haystack
            ):
                add_dep(helper_components["post"])
            if helper_components.get("category") and (
                page.route == "/"
                or "landing" in page_haystack
                or "home" in page_haystack
                or "categor" in page_haystack
            ):
                add_dep(helper_components["category"])
            if helper_components.get("comment") and (
                "post" in page_haystack
                or "detail" in page_haystack
            ):
                add_dep(helper_components["comment"])
        elif project_spec.app_kind == "ecommerce":
            if helper_components.get("product") and (
                page.route == "/"
                or "product" in page_haystack
                or "catalog" in page_haystack
            ):
                add_dep(helper_components["product"])
        elif project_spec.app_kind == "portfolio":
            project_link = resource_frontend_links.get("project")
            if project_link:
                if page.route == "/" or any(term in page_haystack for term in ("home", "portfolio", "work")):
                    add_dep(project_link.get("hook", ""))
                    add_dep(project_link.get("grid", "") or project_link.get("component", ""))
                if page.route.startswith("/projects/") or any(term in page_haystack for term in ("project", "detail", "case study", "case-study")):
                    add_dep(project_link.get("hook", ""))
                    add_dep(project_link.get("component", ""))

        home_like_page = page.route == "/" and project_spec.app_kind in {"blog", "ecommerce", "marketplace", "website"}
        for singular, resource_files in resource_frontend_links.items():
            slug = str(resource_files.get("slug", "") or "")
            term_variants = {
                singular,
                slug,
                f"{singular}s",
                f"{slug}s",
            }
            if home_like_page and singular in {"post", "article", "category", "product"}:
                add_dep(resource_files.get("hook", ""))
                if singular in {"post", "article", "category", "product"}:
                    add_dep(resource_files.get("component", ""))
                continue

            if any(term and term in page_haystack for term in term_variants):
                add_dep(resource_files.get("hook", ""))
                if singular == "category":
                    add_dep(resource_files.get("component", ""))

        add_file(
            f"src/pages/{component}.tsx",
            batch_name=f"batch_{batch_slug}",
            exports=["default"],
            depends_on=depends_on,
        )

    for required in project_spec.required_files:
        normalized_required = str(required or "").strip().replace("\\", "/")
        if normalized_required in {"package.json", "vite.config.ts", "tsconfig.json", "tsconfig.node.json", "index.html", ".env", ".gitignore"}:
            batch_name = "batch_tooling"
        elif normalized_required in {"src/main.tsx", "src/App.tsx", "src/styles/variables.css", "src/styles/global.css"}:
            batch_name = "batch_frontend_shell"
        elif normalized_required in {"src/services/api.ts", "src/types/index.ts"}:
            batch_name = "batch_client_shared"
        elif normalized_required == "server/index.ts":
            batch_name = "batch_server_entry"
        elif normalized_required == "server/db/database.ts":
            batch_name = "batch_data"
        else:
            batch_name = "batch_custom"
        add_file(required, batch_name=batch_name)

    merge_file_contract(
        "server/index.ts",
        imports=server_entry_imports,
        depends_on=server_entry_depends_on,
        api_endpoints_provided=server_entry_api_provided,
    )

    return files
