"""ITDR policy enforcement: honey OU, naming, deny-logon, multi-domain."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings


def domain_from_dn(dn: str) -> str:
    """Extract DNS domain from a DN (e.g. OU=Honey,DC=lab,DC=local → lab.local)."""

    parts: list[str] = []
    for piece in (dn or "").split(","):
        piece = piece.strip()
        if piece.upper().startswith("DC="):
            parts.append(piece.split("=", 1)[1].strip())
    return ".".join(parts).lower() if parts else ""


def parse_monitored_domains(raw: str) -> list[str]:
    return [part.strip().lower() for part in (raw or "").split(",") if part.strip()]


@dataclass
class PolicyCheck:
    id: str
    title: str
    status: str  # pass | warn | fail | info
    message: str
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PolicyReport:
    ok: bool
    score: int
    checked_at: str
    checks: list[PolicyCheck] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    deny_logon: dict[str, Any] = field(default_factory=dict)
    naming: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "score": self.score,
            "checked_at": self.checked_at,
            "checks": [item.to_dict() for item in self.checks],
            "domains": self.domains,
            "deny_logon": self.deny_logon,
            "naming": self.naming,
        }


class PolicyEngine:
    """Evaluates lab policy posture and gates AD provisioning."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def monitored_domains(self) -> list[str]:
        domains: list[str] = []
        for candidate in (
            domain_from_dn(self.settings.ad_honey_ou),
            domain_from_dn(self.settings.ldap_base_dn),
            *parse_monitored_domains(getattr(self.settings, "ad_monitored_domains", "") or ""),
        ):
            if candidate and candidate not in domains:
                domains.append(candidate)
        return domains

    def deny_logon_artifacts(
        self,
        usernames: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate deny-logon GPO / workstations restriction guidance for honey users."""

        names = [name for name in (usernames or []) if name]
        gpo_name = "ActiveDecoy-Honey-DenyLogon"
        ou = self.settings.ad_honey_ou or "OU=Honey,<domain>"
        user_rights = (
            "Computer Configuration → Policies → Windows Settings → Security Settings → "
            "Local Policies → User Rights Assignment → Deny log on locally / "
            "Deny log on through Remote Desktop Services / Deny log on as a batch job / "
            "Deny log on as a service"
        )
        powershell = (
            "# Lab helper — run on a domain-joined admin workstation with RSAT\n"
            f"# Target OU: {ou}\n"
            "$gpoName = '{gpo_name}'\n"
            "# New-GPO -Name $gpoName | New-GPLink -Target '{ou}'\n"
            "# Then set User Rights Assignment to Deny logon for honey accounts,\n"
            "# or set userWorkstations to an unused host and keep UAC disabled.\n"
        ).format(gpo_name=gpo_name, ou=ou)
        lgpo_snippet = (
            "[Unicode]\nUnicode=yes\n[Version]\nsignature=\"$CHICAGO$\"\nRevision=1\n"
            "[Privilege Rights]\n"
            "SeDenyInteractiveLogonRight = *S-1-5-32-546\n"
            "SeDenyRemoteInteractiveLogonRight = *S-1-5-32-546\n"
            "SeDenyBatchLogonRight = *S-1-5-32-546\n"
            "SeDenyServiceLogonRight = *S-1-5-32-546\n"
        )
        return {
            "gpo_name": gpo_name,
            "link_ou": ou,
            "principle": "Honey accounts must have no legitimate interactive or service logon path.",
            "user_rights_path": user_rights,
            "accounts": names,
            "account_uac": "ACCOUNTDISABLE (already applied by ActiveDecoy provisioner)",
            "workstations_restriction": (
                "Optional: set userWorkstations to a non-existent host so even if "
                "re-enabled, logons fail."
            ),
            "powershell_skeleton": powershell,
            "inf_snippet": lgpo_snippet,
            "checklist": [
                "Create / link GPO to the honey OU only (never Domain Controllers OU).",
                "Add honey user SIDs (or Domain Guests placeholder during lab build) to Deny logon rights.",
                "Confirm accounts remain disabled after provisioning.",
                "Verify 4768/4769/4625 on any interaction → high-confidence alert.",
            ],
        }

    def evaluate(
        self,
        *,
        objects: list[dict[str, Any]] | None = None,
        provision_ad: bool = False,
        agent_healthy: int = 0,
    ) -> PolicyReport:
        checks: list[PolicyCheck] = []
        objects = objects or []
        prefix = self.settings.ad_honey_name_prefix or "hw_"
        honey_ou = self.settings.ad_honey_ou.strip()
        domains = self.monitored_domains()

        if honey_ou:
            checks.append(
                PolicyCheck(
                    id="honey_ou",
                    title="Dedicated honey OU",
                    status="pass",
                    message=f"Honey OU configured: {honey_ou}",
                    remediation="",
                )
            )
        else:
            checks.append(
                PolicyCheck(
                    id="honey_ou",
                    title="Dedicated honey OU",
                    status="fail" if provision_ad else "warn",
                    message="AD_HONEY_OU is empty — honey objects lack an isolated OU.",
                    remediation="Set AD_HONEY_OU=OU=Honey,OU=Lab,DC=lab,DC=local (lab-specific).",
                )
            )

        if self.settings.ad_require_name_prefix and prefix:
            checks.append(
                PolicyCheck(
                    id="naming_prefix",
                    title="Honey naming prefix required",
                    status="pass",
                    message=f"Prefix enforcement enabled ({prefix}).",
                )
            )
        else:
            checks.append(
                PolicyCheck(
                    id="naming_prefix",
                    title="Honey naming prefix required",
                    status="warn",
                    message="Name prefix enforcement is off — decoys may be harder to identify.",
                    remediation="Set AD_REQUIRE_NAME_PREFIX=true and AD_HONEY_NAME_PREFIX=hw_.",
                )
            )

        provisionable = [
            item
            for item in objects
            if str(item.get("object_type") or "") in {"HoneyUser", "HoneyServer"}
        ]
        bad_names = [
            str(item.get("name") or "")
            for item in provisionable
            if self.settings.ad_require_name_prefix
            and prefix
            and not str(item.get("name") or "").startswith(prefix)
        ]
        if not provisionable:
            checks.append(
                PolicyCheck(
                    id="object_names",
                    title="Object naming convention",
                    status="info",
                    message="No AD-provisionable objects in the current plan.",
                )
            )
        elif bad_names:
            checks.append(
                PolicyCheck(
                    id="object_names",
                    title="Object naming convention",
                    status="fail",
                    message=f"{len(bad_names)} object(s) missing prefix {prefix}: {', '.join(bad_names[:5])}",
                    remediation=f"Redeploy so names are stamped with {prefix}.",
                )
            )
        else:
            checks.append(
                PolicyCheck(
                    id="object_names",
                    title="Object naming convention",
                    status="pass",
                    message=f"All {len(provisionable)} provisionable object(s) use prefix {prefix}.",
                )
            )

        deny = self.deny_logon_artifacts(
            [
                str(item.get("name") or "")
                for item in provisionable
                if str(item.get("object_type") or "") == "HoneyUser"
            ]
        )
        checks.append(
            PolicyCheck(
                id="deny_logon",
                title="Deny-logon GPO for honey accounts",
                status="pass" if honey_ou else "warn",
                message=(
                    f"Deny-logon artifacts ready for GPO '{deny['gpo_name']}'."
                    if honey_ou
                    else "Configure honey OU before linking the deny-logon GPO."
                ),
                remediation="Apply the GPO checklist from the Policy page after first AD provision.",
            )
        )

        if self.settings.ad_provision_enabled:
            checks.append(
                PolicyCheck(
                    id="provision_flag",
                    title="AD provisioning feature flag",
                    status="pass",
                    message="AD_PROVISION_ENABLED=true.",
                )
            )
        else:
            checks.append(
                PolicyCheck(
                    id="provision_flag",
                    title="AD provisioning feature flag",
                    status="info",
                    message="AD provisioning is off — plans stay graph/plan-only until enabled.",
                    remediation="Set AD_PROVISION_ENABLED=true after honey OU exists.",
                )
            )

        if self.settings.agent_ingest_token:
            status = "pass" if agent_healthy > 0 else "warn"
            checks.append(
                PolicyCheck(
                    id="telemetry",
                    title="Agent / SIEM ingest",
                    status=status,
                    message=(
                        f"Ingest enabled; {agent_healthy} healthy Washu Agent(s)."
                        if agent_healthy > 0
                        else "Ingest token set but no healthy agent heartbeat yet."
                    ),
                    remediation="Run python -m washu_agent run on the monitoring VM.",
                )
            )
        else:
            checks.append(
                PolicyCheck(
                    id="telemetry",
                    title="Agent / SIEM ingest",
                    status="warn",
                    message="AGENT_INGEST_TOKEN empty — real telemetry ingest is disabled.",
                    remediation="Set AGENT_INGEST_TOKEN and deploy Washu Agent.",
                )
            )

        if domains:
            checks.append(
                PolicyCheck(
                    id="domains",
                    title="Monitored domains",
                    status="pass",
                    message=f"Tracking {len(domains)} domain(s): {', '.join(domains)}.",
                )
            )
        else:
            checks.append(
                PolicyCheck(
                    id="domains",
                    title="Monitored domains",
                    status="info",
                    message="No domain derived yet — set AD_HONEY_OU, LDAP_BASE_DN, or AD_MONITORED_DOMAINS.",
                    remediation="AD_MONITORED_DOMAINS=lab.local,corp.lab",
                )
            )

        fails = sum(1 for item in checks if item.status == "fail")
        warns = sum(1 for item in checks if item.status == "warn")
        passes = sum(1 for item in checks if item.status == "pass")
        total_scored = max(1, fails + warns + passes)
        score = int(round(100 * passes / total_scored))
        ok = fails == 0 and (not provision_ad or bool(honey_ou))

        return PolicyReport(
            ok=ok,
            score=score,
            checked_at=datetime.now(timezone.utc).isoformat(),
            checks=checks,
            domains=domains,
            deny_logon=deny,
            naming={
                "prefix": prefix,
                "require_prefix": self.settings.ad_require_name_prefix,
                "honey_ou": honey_ou,
            },
        )

    def gate_provision(
        self,
        objects: list[dict[str, Any]],
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Block live AD writes when critical policy checks fail."""

        if dry_run:
            report = self.evaluate(objects=objects, provision_ad=False)
            return {"blocked": False, "reason": "", "report": report.to_dict()}

        report = self.evaluate(objects=objects, provision_ad=True)
        blockers = [item for item in report.checks if item.status == "fail"]
        if blockers:
            reasons = "; ".join(item.message for item in blockers)
            return {
                "blocked": True,
                "reason": reasons,
                "report": report.to_dict(),
            }
        return {"blocked": False, "reason": "", "report": report.to_dict()}
