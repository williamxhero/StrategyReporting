"""Workspace-only readback for Apex behavior descriptor presentation."""

from __future__ import annotations

from pydantic import ValidationError

from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.contracts.behavior_descriptors import (
    BehaviorDescriptor,
    BehaviorDescriptorReadModel,
    BehaviorDescriptorRef,
    BehaviorTaxonomy,
    DescriptorSourceRef,
    DiscoveryBehaviorDescriptor,
    FormalBehaviorDescriptor,
    PublishedRef,
    StrategyRevisionRef,
)
from strategy_reporting.contracts.evidence_v2 import PublicationReadback
from strategy_reporting.errors import ContractError, ReportingError, SourceError


class BehaviorDescriptorReadModelBuilder:
    """Preserve Apex assignments and add only an explicit presentation-tier label."""

    def __init__(self, workspace: WorkspaceAdapter) -> None:
        self.workspace = workspace

    def read(self, reference: BehaviorDescriptorRef) -> BehaviorDescriptorReadModel:
        if not isinstance(reference, BehaviorDescriptorRef):
            raise TypeError("behavior reader requires a typed BehaviorDescriptorRef")
        try:
            publication = self._publication(reference)
            descriptor = self._descriptor(publication, reference)
            self._verify_descriptor_publication(publication, descriptor)
            taxonomy_publication = self._publication(descriptor.taxonomy)
            taxonomy = BehaviorTaxonomy.model_validate(taxonomy_publication.payload, strict=True)
            if (
                taxonomy.taxonomy_id != descriptor.taxonomy.record_id
                or taxonomy_publication.payload != taxonomy.model_dump(mode="json", by_alias=True)
                or taxonomy_publication.artifacts
                or taxonomy_publication.lineage
            ):
                raise ContractError(
                    "behavior_taxonomy_readback_mismatch",
                    "behavior taxonomy publication differs from its frozen contract",
                )
            self._verify_published_ref(descriptor.candidate)
            for source in descriptor.sources:
                self._verify_source(source)
            for outcome in descriptor.dimensions:
                for source in outcome.sources:
                    self._verify_source(source)
            tier = descriptor.evidence_tier
            return BehaviorDescriptorReadModel(
                presentation_label=(
                    "exploration descriptor"
                    if tier == "discovery"
                    else "formal evidence descriptor"
                ),
                evidence_tier=tier,
                descriptor=descriptor,
                taxonomy=taxonomy,
            )
        except ReportingError:
            raise
        except ValidationError as exc:
            raise ContractError("behavior_descriptor_contract_invalid", str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("behavior_descriptor_readback_invalid", str(exc)) from exc
        except Exception as exc:
            raise SourceError(
                "behavior_descriptor_source_failed",
                f"cannot read behavior descriptor owner facts: {exc}",
            ) from exc

    def _publication(self, reference: PublishedRef) -> PublicationReadback:
        try:
            raw = self.workspace.client.get_record(reference.record_id)
        except Exception as exc:
            raise SourceError(
                "behavior_descriptor_record_missing",
                f"cannot read {reference.record_type} {reference.record_id}: {exc}",
            ) from exc
        publication = PublicationReadback.model_validate(raw, strict=True)
        if (
            publication.record_id != reference.record_id
            or publication.record_type != reference.record_type
            or publication.payload.get("schema") != reference.record_type
        ):
            raise ContractError(
                "behavior_descriptor_reference_mismatch",
                "behavior descriptor record differs from its exact typed reference",
            )
        return publication

    @staticmethod
    def _descriptor(
        publication: PublicationReadback,
        reference: BehaviorDescriptorRef,
    ) -> BehaviorDescriptor:
        if reference.record_type == "apex-research.discovery-behavior-descriptor.v1":
            value: BehaviorDescriptor = DiscoveryBehaviorDescriptor.model_validate(
                publication.payload, strict=True
            )
        else:
            value = FormalBehaviorDescriptor.model_validate(publication.payload, strict=True)
        if value.descriptor_id != reference.record_id:
            raise ContractError(
                "behavior_descriptor_identity_mismatch",
                "behavior descriptor payload identity differs from its publication",
            )
        return value

    @staticmethod
    def _verify_descriptor_publication(
        publication: PublicationReadback,
        descriptor: BehaviorDescriptor,
    ) -> None:
        if isinstance(descriptor, DiscoveryBehaviorDescriptor):
            lineage = [
                {
                    "source_kind": descriptor.candidate.record_type,
                    "source_id": descriptor.candidate.record_id,
                    "relation": "descriptor-candidate",
                },
                {
                    "source_kind": descriptor.taxonomy.record_type,
                    "source_id": descriptor.taxonomy.record_id,
                    "relation": "descriptor-taxonomy",
                },
            ]
        else:
            lineage = [
                {
                    "source_kind": descriptor.taxonomy.record_type,
                    "source_id": descriptor.taxonomy.record_id,
                    "relation": "descriptor-taxonomy",
                },
                *(
                    {
                        "source_kind": source.record_type,
                        "source_id": source.record_id,
                        "relation": "descriptor-source",
                    }
                    for source in descriptor.sources
                ),
            ]
        if (
            publication.payload != descriptor.model_dump(mode="json", by_alias=True)
            or [item.model_dump(mode="json") for item in publication.lineage] != lineage
            or publication.artifacts
        ):
            raise ContractError(
                "behavior_descriptor_lineage_mismatch",
                "behavior descriptor payload, lineage, or artifact closure differs",
            )

    def _verify_published_ref(self, reference: PublishedRef) -> None:
        publication = self._publication(reference)
        if publication.artifacts:
            raise ContractError(
                "behavior_descriptor_source_artifacts",
                "behavior descriptor source unexpectedly claims artifacts",
            )

    def _verify_source(self, source: DescriptorSourceRef | StrategyRevisionRef) -> None:
        if isinstance(source, StrategyRevisionRef):
            self._verify_published_ref(source)
            return
        if source.record_type != "quant-research.run-record.v1":
            self._verify_published_ref(
                PublishedRef(record_id=source.record_id, record_type=source.record_type)
            )
            return
        try:
            run = self.workspace.client.get_run(source.record_id)
            result = self.workspace.client.get_result(source.record_id)
        except Exception as exc:
            raise SourceError(
                "behavior_descriptor_runtime_missing",
                f"cannot read Runtime owner fact {source.record_id}: {exc}",
            ) from exc
        if (
            run.get("run_id") != source.record_id
            or run.get("current_attempt_id") != source.attempt_id
            or run.get("request_hash") != source.request_hash
            or canonical_sha256(run.get("request")) != source.request_hash
            or canonical_sha256(run.get("result")) != source.result_hash
            or result.get("result") != run.get("result")
        ):
            raise ContractError(
                "behavior_descriptor_runtime_mismatch",
                "Runtime owner readback differs from the frozen descriptor source",
            )


__all__ = ["BehaviorDescriptorReadModelBuilder"]
