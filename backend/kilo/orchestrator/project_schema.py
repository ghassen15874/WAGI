from __future__ import annotations

import re
from typing import Any

from .project_spec import ApiResourceSpec, EntitySpec, ProjectSpec, _pascal, _singular_slug, _slug


def _snake_case(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "item"
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    return text.strip("_").lower() or "item"


def _camel_case(value: str) -> str:
    parts = _snake_case(value).split("_")
    if not parts:
        return "item"
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _plural_slug(value: str) -> str:
    slug = _slug(value)
    if slug.endswith("ies") or slug.endswith("ses"):
        return slug
    if slug.endswith("y") and len(slug) > 1:
        return slug[:-1] + "ies"
    if slug.endswith("s"):
        return slug
    return f"{slug}s"


def _field(
    public_name: str,
    db_name: str | None = None,
    field_type: str = "string",
    *,
    required: bool = False,
    stored: bool = True,
    expose: bool = True,
    create: bool = True,
    update: bool = True,
    auto: bool = False,
    unique: bool = False,
) -> dict[str, Any]:
    public = str(public_name or "").strip()
    db = str(db_name or _snake_case(public)).strip()
    return {
        "public": public,
        "db": db,
        "type": str(field_type or "string").strip().lower(),
        "required": bool(required),
        "stored": bool(stored),
        "expose": bool(expose),
        "create": bool(create),
        "update": bool(update),
        "auto": bool(auto),
        "unique": bool(unique),
    }


def _entity_for_name(project_spec: ProjectSpec, entity_name: str) -> EntitySpec:
    needle = str(entity_name or "").strip().lower()
    for entity in project_spec.entities:
        if str(entity.name or "").strip().lower() == needle:
            return entity
    return EntitySpec(name=_pascal(entity_name or "Item"), fields=[])


def _resource_route_parts(resource: ApiResourceSpec) -> list[str]:
    return [
        part
        for part in str(resource.route or "").strip("/").split("/")
        if part and part != "api"
    ]


def _resource_slug(resource: ApiResourceSpec) -> str:
    route_name = str(resource.route or "").strip("/")
    if route_name.startswith("api/"):
        route_name = route_name[len("api/"):]
    route_name = route_name.split("/", 1)[0]
    return _slug(resource.name or route_name or "items")


def _resource_entity_name(project_spec: ProjectSpec, resource: ApiResourceSpec) -> str:
    explicit = str(resource.entity or "").strip()
    if explicit:
        return explicit

    candidates: list[str] = []
    route_parts = [
        part
        for part in str(resource.route or "").strip("/").split("/")
        if part and part != "api" and not part.startswith(":")
    ]
    if route_parts:
        candidates.append(_pascal(_singular_slug(route_parts[-1])))
    if str(resource.name or "").strip():
        name_parts = [part for part in _slug(resource.name).split("_") if part]
        if name_parts:
            candidates.append(_pascal(_singular_slug(name_parts[-1])))
    candidates.append(_pascal(_singular_slug(_resource_slug(resource))))

    known_entities = {
        str(entity.name or "").strip().lower(): str(entity.name or "").strip()
        for entity in project_spec.entities
        if str(entity.name or "").strip()
    }
    for candidate in candidates:
        known = known_entities.get(candidate.lower())
        if known:
            return known

    return candidates[0] if candidates else "Item"


def _entity_for_resource(project_spec: ProjectSpec, resource: ApiResourceSpec) -> EntitySpec:
    entity_name = _resource_entity_name(project_spec, resource)
    return _entity_for_name(project_spec, entity_name)


def _resource_table_name(project_spec: ProjectSpec, resource: ApiResourceSpec) -> str:
    entity_name = _resource_entity_name(project_spec, resource)
    if entity_name:
        return _plural_slug(entity_name)
    return _plural_slug(_resource_slug(resource))


def canonical_entity_fields(project_spec: ProjectSpec, entity: EntitySpec) -> list[dict[str, Any]]:
    name = str(entity.name or "").strip().lower()

    if list(entity.fields or []):
        fields: list[dict[str, Any]] = [
            _field("id", "id", "integer", required=True, create=False, update=False, auto=True),
        ]
        seen_public: set[str] = {"id"}
        seen_db: set[str] = {"id"}
        for source_field in list(entity.fields or []):
            public = _camel_case(source_field.name)
            db_name = _snake_case(source_field.name)
            if public in seen_public or db_name in seen_db:
                continue
            seen_public.add(public)
            seen_db.add(db_name)
            fields.append(
                _field(
                    public,
                    db_name,
                    source_field.type or "string",
                    required=bool(source_field.required),
                    unique=public in {"email", "username", "slug"},
                    update=public not in {"slug"},
                    expose=public != "password",
                )
            )

        if not any(field["public"] == "slug" for field in fields) and any(
            field["public"] in {"title", "name", "username"} for field in fields
        ):
            fields.append(_field("slug", "slug", "slug", required=True, unique=True, update=False))

        if not any(field["public"] == "createdAt" for field in fields):
            fields.append(_field("createdAt", "created_at", "datetime", create=False, update=False, auto=True))

        return fields

    if name in {"user", "users"}:
        return [
            _field("id", "id", "integer", required=True, create=False, update=False, auto=True),
            _field("username", "username", "string", required=True, unique=True),
            _field("email", "email", "string", required=True, unique=True),
            _field("password", "password", "string", required=True, expose=False, update=False),
            _field("role", "role", "string", required=True, create=False, update=False),
            _field("createdAt", "created_at", "datetime", stored=True, expose=True, create=False, update=False, auto=True),
        ]

    if name in {"post", "article"} or (project_spec.app_kind == "blog" and name in {"post", "posts"}):
        return [
            _field("id", "id", "integer", required=True, create=False, update=False, auto=True),
            _field("title", "title", "string", required=True),
            _field("slug", "slug", "slug", required=True, unique=True, update=False),
            _field("content", "content", "text", required=True),
            _field("excerpt", "excerpt", "text"),
            _field("imageUrl", "image_url", "string"),
            _field("categoryId", "category_id", "integer"),
            _field("categoryName", "category_name", "string", stored=False, create=False, update=False),
            _field("authorId", "author_id", "integer", create=False, update=False),
            _field("isPublished", "is_published", "boolean", create=False, update=True),
            _field("publishedAt", "published_at", "datetime", create=False, update=False, auto=True),
            _field("createdAt", "created_at", "datetime", create=False, update=False, auto=True),
            _field("updatedAt", "updated_at", "datetime", create=False, update=False, auto=True),
        ]

    if name in {"category", "categories"}:
        return [
            _field("id", "id", "integer", required=True, create=False, update=False, auto=True),
            _field("name", "name", "string", required=True, unique=True),
            _field("slug", "slug", "slug", required=True, unique=True, update=False),
            _field("description", "description", "text"),
            _field("createdAt", "created_at", "datetime", create=False, update=False, auto=True),
        ]

    if name in {"comment", "comments"}:
        return [
            _field("id", "id", "integer", required=True, create=False, update=False, auto=True),
            _field("postId", "post_id", "integer", required=True),
            _field("authorName", "author_name", "string", required=True),
            _field("content", "content", "text", required=True),
            _field("createdAt", "created_at", "datetime", create=False, update=False, auto=True),
        ]

    if name in {"product", "products"}:
        return [
            _field("id", "id", "integer", required=True, create=False, update=False, auto=True),
            _field("name", "name", "string", required=True),
            _field("slug", "slug", "slug", required=True, unique=True, update=False),
            _field("description", "description", "text"),
            _field("price", "price", "number", required=True),
            _field("imageUrl", "image_url", "string"),
            _field("createdAt", "created_at", "datetime", create=False, update=False, auto=True),
            _field("updatedAt", "updated_at", "datetime", create=False, update=False, auto=True),
        ]

    return [
        _field("id", "id", "integer", required=True, create=False, update=False, auto=True),
        _field("createdAt", "created_at", "datetime", create=False, update=False, auto=True),
    ]


def resource_specs(project_spec: ProjectSpec) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for resource in project_spec.api_resources:
        entity = _entity_for_resource(project_spec, resource)
        fields = canonical_entity_fields(project_spec, entity)
        table = _resource_table_name(project_spec, resource)
        singular = _singular_slug(_resource_slug(resource))
        specs.append(
            {
                "resource": resource,
                "entity": entity,
                "fields": fields,
                "table": table,
                "singular": singular,
                "component": _pascal(singular),
            }
        )
    return specs
