"""Orchestrates deception plan → AD provision → Neo4j → monitoring registration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.core.ad_provisioner import ADProvisioner, new_deployment_id, stamp_provision_names
from app.core.config import Settings
from app.core.connection_manager import LDAPConfig
from app.core.deception_engine import DeceptionEngine, HoneyObject, deployment_to_dict
from app.core.deployment_history import DeploymentHistoryStore, DeploymentRecord
from app.core.graph_store import GraphStore
from app.core.monitoring_engine import MonitoringEngine


def build_provisioner(settings: Settings) -> ADProvisioner:
    return ADProvisioner(
        honey_ou=settings.ad_honey_ou,
        name_prefix=settings.ad_honey_name_prefix,
        require_prefix=settings.ad_require_name_prefix,
    )


def _as_honey(item: dict[str, Any]) -> HoneyObject:
    return HoneyObject(
        object_type=str(item.get("object_type", "")),
        name=str(item.get("name", "")),
        role=str(item.get("role", "")),
        color=str(item.get("color") or (item.get("attributes") or {}).get("color") or "blue"),
        notes=str(item.get("notes", "")),
        attributes=dict(item.get("attributes") or {}),
    )


def run_deception_deploy(
    *,
    modules: list[str],
    settings: Settings,
    deception_engine: DeceptionEngine,
    monitoring_engine: MonitoringEngine,
    graph_store: GraphStore,
    history: DeploymentHistoryStore,
    ldap_config: LDAPConfig | None,
    actor: str,
    sync_to_graph: bool = False,
    provision_ad: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Build a deception plan and optionally provision AD + sync Neo4j."""

    deployment = deception_engine.build_deployment(modules)
    payload = deployment_to_dict(deployment)
    deployment_id = new_deployment_id()
    payload["deployment_id"] = deployment_id

    stamped_objects = stamp_provision_names(payload["objects"], settings.ad_honey_name_prefix)
    payload["objects"] = stamped_objects
    payload["cypher_queries"] = [
        deception_engine.to_cypher(_as_honey(item)) for item in stamped_objects
    ]

    ad_result: dict[str, Any] | None = None
    if provision_ad:
        if ldap_config is None or not ldap_config.host.strip():
            ad_result = {
                "success": False,
                "message": "LDAP profile is required to provision Active Directory objects.",
                "results": [],
                "created": [],
            }
        else:
            provisioner = build_provisioner(settings)
            ad_result = provisioner.provision_objects(
                ldap_config,
                stamped_objects,
                dry_run=dry_run,
            )
        payload["ad_provision"] = ad_result
    else:
        payload["ad_provision"] = {
            "success": True,
            "skipped": True,
            "message": "AD provisioning skipped (plan/graph only).",
            "results": [],
            "created": [],
        }

    payload["monitored_objects"] = monitoring_engine.register_deployment(stamped_objects)

    graph_result = None
    if sync_to_graph and not dry_run:
        graph_result = graph_store.execute_queries(payload.get("cypher_queries", []))
        payload["graph_sync"] = graph_result
        if graph_result.get("success"):
            health = graph_store.health()
            payload["graph_node_count"] = health.node_count
            payload["honey_count"] = health.honey_count
    elif sync_to_graph and dry_run:
        payload["graph_sync"] = {
            "success": True,
            "dry_run": True,
            "executed": 0,
            "message": "Dry-run: graph sync skipped.",
        }
    else:
        payload["graph_sync"] = None

    provisioned = list((ad_result or {}).get("created") or [])
    ad_ok = bool((ad_result or {}).get("success", True))
    graph_ok = True if graph_result is None else bool(graph_result.get("success"))
    overall = ad_ok and graph_ok

    status = "plan_only"
    if provision_ad and ad_ok and provisioned and not dry_run:
        status = "active"
    elif provision_ad and dry_run:
        status = "plan_only"

    record = DeploymentRecord(
        deployment_id=deployment_id,
        created_at=payload["created_at"],
        actor=actor,
        modules=list(modules),
        objects=stamped_objects,
        provisioned=provisioned,
        graph_synced=bool(graph_result and graph_result.get("success")),
        ad_provisioned=bool(provision_ad and ad_ok and provisioned and not dry_run),
        dry_run=dry_run,
        status=status,
        notes=(ad_result or {}).get("message", ""),
    )
    history.add(record)

    payload["success"] = overall
    payload["history"] = record.to_dict()
    return payload


def run_deception_teardown(
    *,
    deployment_id: str,
    settings: Settings,
    history: DeploymentHistoryStore,
    ldap_config: LDAPConfig | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    record = history.get(deployment_id)
    if record is None:
        return {"success": False, "message": f"Deployment {deployment_id} not found."}
    if record.status == "torn_down" and not dry_run:
        return {"success": True, "message": "Deployment already torn down.", "deployment_id": deployment_id}

    if not record.provisioned:
        if not dry_run:
            history.mark_torn_down(deployment_id, notes="No AD objects to remove.")
        return {
            "success": True,
            "message": "No AD objects were provisioned for this deployment.",
            "deployment_id": deployment_id,
            "results": [],
        }

    if ldap_config is None or not ldap_config.host.strip():
        return {
            "success": False,
            "message": "LDAP profile is required for teardown.",
            "deployment_id": deployment_id,
        }

    provisioner = build_provisioner(settings)
    result = provisioner.teardown_objects(ldap_config, record.provisioned, dry_run=dry_run)
    if result.get("success") and not dry_run:
        history.mark_torn_down(deployment_id, notes=result.get("message", ""))
    result["deployment_id"] = deployment_id
    return result


def run_preflight(
    *,
    settings: Settings,
    ldap_config: LDAPConfig | None,
) -> dict[str, Any]:
    if ldap_config is None or not ldap_config.host.strip():
        return {
            "ok": False,
            "message": "Save and validate an LDAP profile before AD preflight.",
            "checks": {},
        }
    return asdict(build_provisioner(settings).preflight(ldap_config))
