from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_value
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.contracts import AppealLinkCandidate, IngestionExecutionResult
from app.models import AppealNode, AppealOutcome, LegalDocument, ValidityStatus


@dataclass(slots=True)
class AppealChainBuildResult:
    source_doc_id: str
    node_ids: list[str]
    propagated_doc_ids: list[str]
    unresolved_references: list[str]


@dataclass(slots=True)
class AppealAuthorityResolution:
    doc_id: str
    use_doc_id: str
    effective_outcome: AppealOutcome | None
    is_final_authority: bool
    warning: str | None
    path_doc_ids: list[str]


class AppealChainBuilder:
    def persist(
        self,
        session: Session,
        execution: IngestionExecutionResult,
        source_doc_id: str,
    ) -> AppealChainBuildResult:
        source_document = session.get(LegalDocument, source_doc_id)
        if source_document is None:
            raise ValueError(f"Unknown source document: {source_doc_id}")

        node_ids: list[str] = []
        propagated_doc_ids: list[str] = []
        unresolved_references: list[str] = []

        for candidate in execution.appeal_links:
            parent_document = self.resolve_document_reference(session, candidate.target_reference)
            if parent_document is None:
                unresolved_references.append(candidate.target_reference or candidate.note or "")
                continue

            outcome = self._coerce_outcome(candidate)
            if outcome is None:
                continue

            is_final_authority = (
                candidate.is_final_authority
                if candidate.is_final_authority is not None
                else True
            )
            judgment_date = self._parse_date(candidate.judgment_date) or source_document.date
            court_level = candidate.court_level or self._court_level(source_document.court)
            court_name = candidate.court_name or source_document.court or "Unknown Court"

            self._clear_final_nodes(source_document)
            node_ids.append(
                self._append_node(
                    owner=source_document,
                    parent_doc_id=parent_document.doc_id,
                    child_doc_id=None,
                    court_name=court_name,
                    court_level=court_level,
                    judgment_date=judgment_date,
                    citation=source_document.citation,
                    outcome=outcome,
                    is_final_authority=is_final_authority,
                    modifies_ratio=candidate.modifies_ratio or outcome is AppealOutcome.MODIFIED,
                ).id
            )

            owners = [parent_document, *self._ancestor_documents(session, parent_document.doc_id)]
            for owner in owners:
                self._clear_final_nodes(owner)
                propagated = self._append_node(
                    owner=owner,
                    parent_doc_id=parent_document.doc_id,
                    child_doc_id=source_document.doc_id,
                    court_name=court_name,
                    court_level=court_level,
                    judgment_date=judgment_date,
                    citation=source_document.citation,
                    outcome=outcome,
                    is_final_authority=is_final_authority,
                    modifies_ratio=candidate.modifies_ratio or outcome is AppealOutcome.MODIFIED,
                )
                node_ids.append(propagated.id)
                propagated_doc_ids = self._append_unique(propagated_doc_ids, owner.doc_id)

            self._apply_direct_parent_status(parent_document, source_document, outcome)

        session.flush()
        return AppealChainBuildResult(
            source_doc_id=source_doc_id,
            node_ids=node_ids,
            propagated_doc_ids=propagated_doc_ids,
            unresolved_references=unresolved_references,
        )

    def resolve_final_authority(
        self,
        session: Session,
        doc_id: str,
    ) -> AppealAuthorityResolution:
        document = session.get(LegalDocument, doc_id)
        if document is None:
            raise ValueError(f"Unknown document: {doc_id}")

        if not document.appeal_history:
            return AppealAuthorityResolution(
                doc_id=doc_id,
                use_doc_id=doc_id,
                effective_outcome=None,
                is_final_authority=True,
                warning=None,
                path_doc_ids=[doc_id],
            )

        path_nodes = self._path_nodes(document)
        final_node = self._final_node(document, path_nodes)
        if final_node is None:
            return AppealAuthorityResolution(
                doc_id=doc_id,
                use_doc_id=doc_id,
                effective_outcome=None,
                is_final_authority=False,
                warning="Appeal history exists but final authority could not be resolved.",
                path_doc_ids=[doc_id],
            )

        use_doc_id = final_node.child_doc_id or doc_id
        effective_outcome = self._effective_outcome(path_nodes or [final_node])
        warning = self._warning_for_outcome(effective_outcome, use_doc_id, doc_id)

        path_doc_ids = [doc_id]
        current_doc_id = doc_id
        for node in path_nodes:
            next_doc_id = node.child_doc_id or current_doc_id
            if next_doc_id != current_doc_id:
                path_doc_ids.append(next_doc_id)
            current_doc_id = next_doc_id

        if use_doc_id not in path_doc_ids:
            path_doc_ids.append(use_doc_id)

        return AppealAuthorityResolution(
            doc_id=doc_id,
            use_doc_id=use_doc_id,
            effective_outcome=effective_outcome,
            is_final_authority=use_doc_id == doc_id,
            warning=warning,
            path_doc_ids=path_doc_ids,
        )

    def build_neo4j_projection(self, session: Session, doc_id: str) -> list[str]:
        document = session.get(LegalDocument, doc_id)
        if document is None:
            raise ValueError(f"Unknown document for appeal projection: {doc_id}")

        statements: list[str] = []
        for node in document.appeal_history:
            if node.parent_doc_id is None:
                continue
            child_doc_id = node.child_doc_id or document.doc_id
            statements.append(
                "\n".join(
                    [
                        f"MERGE (parent:JudgmentNode {{doc_id: '{node.parent_doc_id}'}})",
                        f"MERGE (child:JudgmentNode {{doc_id: '{child_doc_id}'}})",
                        (
                            "MERGE (parent)-[:APPEALED_TO "
                            f"{{outcome: '{node.outcome.value}', "
                            "is_final_authority: "
                            f"{str(node.is_final_authority).lower()}}}]->(child)"
                        ),
                    ]
                )
            )
        return statements

    def resolve_document_reference(
        self,
        session: Session,
        reference: str | None,
    ) -> LegalDocument | None:
        if reference is None:
            return None

        return session.scalar(
            select(LegalDocument).where(
                (LegalDocument.citation == reference)
                | (LegalDocument.neutral_citation == reference)
                | (LegalDocument.source_document_ref == reference)
            )
        )

    def _append_node(
        self,
        *,
        owner: LegalDocument,
        parent_doc_id: str | None,
        child_doc_id: str | None,
        court_name: str,
        court_level: int,
        judgment_date: date_value | None,
        citation: str | None,
        outcome: AppealOutcome,
        is_final_authority: bool,
        modifies_ratio: bool,
    ) -> AppealNode:
        node_id = str(
            uuid5(
                NAMESPACE_URL,
                (
                    f"{owner.doc_id}|{parent_doc_id}|{child_doc_id}|{citation}|"
                    f"{court_level}|{outcome.value}"
                ),
            )
        )
        node = next((item for item in owner.appeal_history if item.id == node_id), None)
        if node is None:
            node = AppealNode(id=node_id)
            owner.appeal_history.append(node)

        node.court_level = court_level
        node.court_name = court_name
        node.judgment_date = judgment_date
        node.citation = citation
        node.outcome = outcome
        node.is_final_authority = is_final_authority
        node.modifies_ratio = modifies_ratio
        node.parent_doc_id = parent_doc_id
        node.child_doc_id = child_doc_id
        return node

    def _ancestor_documents(self, session: Session, doc_id: str) -> list[LegalDocument]:
        owners: list[LegalDocument] = []
        queue = [doc_id]
        seen = {doc_id}

        while queue:
            current = queue.pop(0)
            owner_ids = session.scalars(
                select(AppealNode.document_doc_id).where(AppealNode.child_doc_id == current)
            ).all()
            for owner_id in owner_ids:
                if owner_id in seen:
                    continue
                seen.add(owner_id)
                owner = session.get(LegalDocument, owner_id)
                if owner is None:
                    continue
                owners.append(owner)
                queue.append(owner_id)
        return owners

    def _path_nodes(self, document: LegalDocument) -> list[AppealNode]:
        path: list[AppealNode] = []
        current_doc_id = document.doc_id
        visited = {current_doc_id}

        while True:
            candidates = [
                node
                for node in document.appeal_history
                if node.parent_doc_id == current_doc_id and node.child_doc_id is not None
            ]
            if not candidates:
                break
            next_node = max(
                candidates,
                key=lambda node: (
                    node.is_final_authority,
                    node.court_level,
                    node.judgment_date or date_value.min,
                ),
            )
            path.append(next_node)
            next_doc_id = next_node.child_doc_id
            if next_doc_id is None or next_doc_id in visited:
                break
            visited.add(next_doc_id)
            current_doc_id = next_doc_id

        return path

    def _final_node(
        self,
        document: LegalDocument,
        path_nodes: list[AppealNode],
    ) -> AppealNode | None:
        if path_nodes:
            last_path = path_nodes[-1]
            if last_path.is_final_authority:
                return last_path

        final_nodes = [node for node in document.appeal_history if node.is_final_authority]
        if final_nodes:
            return max(
                final_nodes,
                key=lambda node: (
                    node.court_level,
                    node.judgment_date or date_value.min,
                ),
            )
        return None

    def _effective_outcome(self, nodes: list[AppealNode]) -> AppealOutcome | None:
        if not nodes:
            return None

        status = AppealOutcome.UPHELD
        dismissal_seen = False
        for node in nodes:
            if node.outcome is AppealOutcome.DISMISSED:
                dismissal_seen = True
                continue
            if node.outcome is AppealOutcome.UPHELD:
                continue
            if node.outcome is AppealOutcome.REVERSED:
                status = (
                    AppealOutcome.UPHELD
                    if status is AppealOutcome.REVERSED
                    else AppealOutcome.REVERSED
                )
                continue
            status = node.outcome

        if dismissal_seen and status is AppealOutcome.UPHELD:
            return AppealOutcome.DISMISSED
        return status

    def _warning_for_outcome(
        self,
        outcome: AppealOutcome | None,
        use_doc_id: str,
        source_doc_id: str,
    ) -> str | None:
        if outcome is AppealOutcome.REVERSED and use_doc_id != source_doc_id:
            return f"This judgment was reversed on appeal. Use final authority: {use_doc_id}."
        if outcome is AppealOutcome.MODIFIED and use_doc_id != source_doc_id:
            return f"This judgment was modified on appeal. Use final authority: {use_doc_id}."
        if outcome is AppealOutcome.REMANDED:
            return "This matter was remanded on appeal."
        if outcome is AppealOutcome.DISMISSED and use_doc_id != source_doc_id:
            return f"The appeal was dismissed. Final authority remains: {use_doc_id}."
        return None

    def _coerce_outcome(self, candidate: AppealLinkCandidate) -> AppealOutcome | None:
        raw = (candidate.outcome or candidate.relation).strip().lower()
        mapping = {
            "appeal_from": None,
            "upheld": AppealOutcome.UPHELD,
            "reversed": AppealOutcome.REVERSED,
            "modified": AppealOutcome.MODIFIED,
            "remanded": AppealOutcome.REMANDED,
            "dismissed": AppealOutcome.DISMISSED,
        }
        return mapping.get(raw)

    def _apply_direct_parent_status(
        self,
        parent_document: LegalDocument,
        source_document: LegalDocument,
        outcome: AppealOutcome,
    ) -> None:
        if outcome is AppealOutcome.REVERSED:
            parent_document.current_validity = ValidityStatus.REVERSED_ON_APPEAL
            parent_document.overruled_by = source_document.doc_id
            parent_document.overruled_date = source_document.date
        elif (
            outcome is AppealOutcome.UPHELD
            and parent_document.current_validity is ValidityStatus.REVERSED_ON_APPEAL
        ):
            parent_document.current_validity = ValidityStatus.GOOD_LAW

    def _clear_final_nodes(self, document: LegalDocument) -> None:
        for node in document.appeal_history:
            node.is_final_authority = False

    def _court_level(self, court_name: str | None) -> int:
        if not court_name:
            return 0
        normalized = court_name.lower()
        if "supreme court" in normalized:
            return 4
        if "high court" in normalized:
            return 3
        if "sessions" in normalized or "district" in normalized or "tribunal" in normalized:
            return 2
        return 1

    def _parse_date(self, value: str | None) -> date_value | None:
        if value is None:
            return None
        for fmt in ("%Y-%m-%d", "%B %d, %Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    def _append_unique(self, items: list[str], value: str) -> list[str]:
        if value not in items:
            return [*items, value]
        return items
