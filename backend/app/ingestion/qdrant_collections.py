from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    VectorDistanceMetric,
    VectorStoreBackend,
    VectorStoreCollection,
    VectorStorePoint,
)

IndexedFieldType = Literal["keyword", "integer", "datetime", "boolean"]


@dataclass(slots=True, frozen=True)
class QdrantIndexedField:
    name: str
    field_type: IndexedFieldType
    is_array: bool = False

    def to_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "field_type": self.field_type,
            "is_array": self.is_array,
        }


@dataclass(slots=True, frozen=True)
class QdrantCollectionSpec:
    name: str
    vector_size: int
    distance_metric: VectorDistanceMetric
    indexed_payload_fields: tuple[QdrantIndexedField, ...]
    description: str

    @property
    def indexed_field_names(self) -> set[str]:
        return {field.name for field in self.indexed_payload_fields}


class QdrantCollectionManager:
    def __init__(self, *, default_vector_size: int = 1024) -> None:
        self.default_vector_size = default_vector_size

    def ensure_default_collections(
        self,
        session: Session,
        *,
        vector_size: int | None = None,
    ) -> list[VectorStoreCollection]:
        specs = self.default_specs(vector_size=vector_size)
        collections = [
            self._upsert_collection(session, spec)
            for spec in specs.values()
        ]
        session.flush()
        return collections

    def ensure_collection(
        self,
        session: Session,
        collection_name: str,
        *,
        vector_size: int | None = None,
    ) -> VectorStoreCollection:
        specs = self.default_specs(vector_size=vector_size)
        try:
            spec = specs[collection_name]
        except KeyError as exc:
            raise ValueError(f"Unknown Qdrant collection: {collection_name}") from exc
        collection = self._upsert_collection(session, spec)
        session.flush()
        return collection

    def get_collection(
        self,
        session: Session,
        collection_name: str,
    ) -> VectorStoreCollection | None:
        return session.get(VectorStoreCollection, collection_name)

    def filter_points(
        self,
        session: Session,
        collection_name: str,
        query_filter: dict[str, object],
    ) -> list[VectorStorePoint]:
        collection = self.get_collection(session, collection_name)
        if collection is None:
            raise ValueError(f"Collection not found: {collection_name}")

        spec = self.default_specs(vector_size=collection.vector_size)[collection_name]
        must = self._coerce_clauses(query_filter.get("must"))
        should = self._coerce_clauses(query_filter.get("should"))
        must_not = self._coerce_clauses(query_filter.get("must_not"))

        self._validate_filter_keys(spec, must + should + must_not)

        points = session.execute(
            select(VectorStorePoint).where(
                VectorStorePoint.collection_name == collection_name,
                VectorStorePoint.is_active.is_(True),
            )
        ).scalars().all()
        return [
            point
            for point in points
            if self._matches_filter(point.payload, must=must, should=should, must_not=must_not)
        ]

    def default_specs(self, *, vector_size: int | None = None) -> dict[str, QdrantCollectionSpec]:
        size = vector_size or self.default_vector_size
        return {
            "sc_judgments": QdrantCollectionSpec(
                name="sc_judgments",
                vector_size=size,
                distance_metric=VectorDistanceMetric.COSINE,
                indexed_payload_fields=(
                    QdrantIndexedField("current_validity", "keyword"),
                    QdrantIndexedField("date", "datetime"),
                    QdrantIndexedField("jurisdiction_binding", "keyword", is_array=True),
                    QdrantIndexedField("bench_size", "integer"),
                    QdrantIndexedField("court", "keyword"),
                    QdrantIndexedField("practice_area", "keyword", is_array=True),
                ),
                description="Supreme Court judgment chunks",
            ),
            "hc_judgments": QdrantCollectionSpec(
                name="hc_judgments",
                vector_size=size,
                distance_metric=VectorDistanceMetric.COSINE,
                indexed_payload_fields=(
                    QdrantIndexedField("current_validity", "keyword"),
                    QdrantIndexedField("date", "datetime"),
                    QdrantIndexedField("jurisdiction_binding", "keyword", is_array=True),
                    QdrantIndexedField("court", "keyword"),
                    QdrantIndexedField("state", "keyword"),
                    QdrantIndexedField("practice_area", "keyword", is_array=True),
                ),
                description="High Court judgment chunks",
            ),
            "statutes": QdrantCollectionSpec(
                name="statutes",
                vector_size=size,
                distance_metric=VectorDistanceMetric.COSINE,
                indexed_payload_fields=(
                    QdrantIndexedField("current_validity", "keyword"),
                    QdrantIndexedField("act_name", "keyword"),
                    QdrantIndexedField("section_number", "keyword"),
                    QdrantIndexedField("is_in_force", "boolean"),
                    QdrantIndexedField("amendment_date", "datetime"),
                    QdrantIndexedField("jurisdiction", "keyword"),
                ),
                description="Statutory section chunks",
            ),
            "constitution": QdrantCollectionSpec(
                name="constitution",
                vector_size=size,
                distance_metric=VectorDistanceMetric.COSINE,
                indexed_payload_fields=(
                    QdrantIndexedField("section_number", "keyword"),
                    QdrantIndexedField("act_name", "keyword"),
                    QdrantIndexedField("current_validity", "keyword"),
                    QdrantIndexedField("practice_area", "keyword", is_array=True),
                ),
                description="Constitution article chunks",
            ),
            "tribunal_orders": QdrantCollectionSpec(
                name="tribunal_orders",
                vector_size=size,
                distance_metric=VectorDistanceMetric.COSINE,
                indexed_payload_fields=(
                    QdrantIndexedField("current_validity", "keyword"),
                    QdrantIndexedField("date", "datetime"),
                    QdrantIndexedField("court", "keyword"),
                    QdrantIndexedField("jurisdiction_binding", "keyword", is_array=True),
                    QdrantIndexedField("practice_area", "keyword", is_array=True),
                ),
                description="Tribunal order chunks",
            ),
            "lc_reports": QdrantCollectionSpec(
                name="lc_reports",
                vector_size=size,
                distance_metric=VectorDistanceMetric.COSINE,
                indexed_payload_fields=(
                    QdrantIndexedField("report_num", "keyword"),
                    QdrantIndexedField("topic", "keyword"),
                    QdrantIndexedField("year", "integer"),
                    QdrantIndexedField("practice_area", "keyword", is_array=True),
                ),
                description="Law Commission report chunks",
            ),
            "doctrine_clusters": QdrantCollectionSpec(
                name="doctrine_clusters",
                vector_size=size,
                distance_metric=VectorDistanceMetric.COSINE,
                indexed_payload_fields=(
                    QdrantIndexedField("doctrine_name", "keyword"),
                    QdrantIndexedField("area_of_law", "keyword"),
                    QdrantIndexedField("current_validity", "keyword"),
                    QdrantIndexedField("practice_area", "keyword", is_array=True),
                ),
                description="Doctrine summary clusters",
            ),
        }

    def _upsert_collection(
        self,
        session: Session,
        spec: QdrantCollectionSpec,
    ) -> VectorStoreCollection:
        collection = session.get(VectorStoreCollection, spec.name)
        if collection is None:
            collection = VectorStoreCollection(name=spec.name)
            session.add(collection)

        collection.backend = VectorStoreBackend.QDRANT
        collection.vector_size = spec.vector_size
        collection.distance_metric = spec.distance_metric
        collection.indexed_payload_fields = [
            field.to_payload() for field in spec.indexed_payload_fields
        ]
        collection.description = spec.description
        collection.is_active = True
        return collection

    def _coerce_clauses(self, value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        clauses: list[dict[str, object]] = []
        for item in value:
            if isinstance(item, dict):
                clauses.append({str(key): nested for key, nested in item.items()})
        return clauses

    def _validate_filter_keys(
        self,
        spec: QdrantCollectionSpec,
        clauses: list[dict[str, object]],
    ) -> None:
        for clause in clauses:
            key = clause.get("key")
            if not isinstance(key, str):
                raise ValueError("Filter clause missing string key")
            if key not in spec.indexed_field_names:
                raise ValueError(
                    f"Filter key '{key}' is not indexed for collection '{spec.name}'"
                )

    def _matches_filter(
        self,
        payload: dict[str, object],
        *,
        must: list[dict[str, object]],
        should: list[dict[str, object]],
        must_not: list[dict[str, object]],
    ) -> bool:
        if any(not self._matches_clause(payload, clause) for clause in must):
            return False
        if should and not any(self._matches_clause(payload, clause) for clause in should):
            return False
        if any(self._matches_clause(payload, clause) for clause in must_not):
            return False
        return True

    def _matches_clause(self, payload: dict[str, object], clause: dict[str, object]) -> bool:
        key = clause["key"]
        assert isinstance(key, str)
        candidate = payload.get(key)

        if "match" in clause and isinstance(clause["match"], dict):
            match_payload = clause["match"]
            return self._matches_match(candidate, match_payload)

        if "range" in clause and isinstance(clause["range"], dict):
            range_payload = clause["range"]
            return self._matches_range(candidate, range_payload)

        raise ValueError("Unsupported filter clause")

    def _matches_match(self, candidate: object, match_payload: dict[str, object]) -> bool:
        if "value" in match_payload:
            expected = match_payload["value"]
            if isinstance(candidate, list):
                return expected in candidate
            return candidate == expected

        if "any" in match_payload and isinstance(match_payload["any"], list):
            options = match_payload["any"]
            if isinstance(candidate, list):
                return any(option in candidate for option in options)
            return candidate in options

        raise ValueError("Unsupported match clause")

    def _matches_range(self, candidate: object, range_payload: dict[str, object]) -> bool:
        comparable = self._coerce_comparable(candidate)
        if comparable is None:
            return False

        current = comparable
        gte = self._coerce_comparable(range_payload.get("gte"))
        lte = self._coerce_comparable(range_payload.get("lte"))
        gt = self._coerce_comparable(range_payload.get("gt"))
        lt = self._coerce_comparable(range_payload.get("lt"))

        if gte is not None and current < gte:
            return False
        if lte is not None and current > lte:
            return False
        if gt is not None and current <= gt:
            return False
        if lt is not None and current >= lt:
            return False
        return True

    def _coerce_comparable(self, value: object) -> Any | None:
        if value is None:
            return None
        if isinstance(value, (int, float, bool, datetime, date)):
            return value
        if isinstance(value, str):
            for parser in (datetime.fromisoformat, date.fromisoformat):
                try:
                    return parser(value)
                except ValueError:
                    continue
            return value
        return value
