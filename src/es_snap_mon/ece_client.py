"""Elastic Cloud Enterprise deployment API client."""
from __future__ import annotations

from dataclasses import dataclass, field

import requests

from .ssh_tunnel import configure_tunnel


@dataclass
class EceInstance:
    name: str
    healthy: bool | None
    running: bool | None
    memory_mb: int
    storage_mb: int
    roles: list[str] = field(default_factory=list)
    memory_pressure: int | None = None
    native_memory_pressure: int | None = None


@dataclass
class EceDeployment:
    id: str
    name: str
    healthy: bool | None
    elasticsearch_version: str | None
    instances: list[EceInstance] = field(default_factory=list)

    @property
    def instance_count(self) -> int:
        return len(self.instances)

    @property
    def running_instances(self) -> int:
        return sum(instance.running is True for instance in self.instances)

    @property
    def memory_mb(self) -> int:
        return sum(instance.memory_mb for instance in self.instances)

    @property
    def storage_mb(self) -> int:
        return sum(instance.storage_mb for instance in self.instances)


def _capacity(value: dict | None) -> int:
    try:
        return int((value or {}).get("capacity", 0))
    except (TypeError, ValueError):
        return 0


def parse_deployment(raw: dict) -> EceDeployment:
    resources = raw.get("resources") or {}
    instances: list[EceInstance] = []
    health: list[bool] = []
    version = None
    for kind in ("elasticsearch", "kibana", "apm", "integrations_server"):
        for resource in resources.get(kind) or []:
            info = resource.get("info") or {}
            if "healthy" in info:
                health.append(bool(info["healthy"]))
            if kind == "elasticsearch":
                cluster_info = info.get("cluster_info") or {}
                version = (cluster_info.get("version") or {}).get("number") or version
                topology = info.get("topology") or {}
                for item in topology.get("cluster_instances") or topology.get("instances") or []:
                    memory = item.get("memory") or {}
                    disk = item.get("disk") or {}
                    instances.append(EceInstance(
                        name=item.get("instance_name") or item.get("instance_id") or "unknown",
                        healthy=item.get("healthy"),
                        running=item.get("service_running"),
                        memory_mb=memory.get("instance_capacity", _capacity(memory)),
                        storage_mb=disk.get("disk_space_available", _capacity(item.get("storage"))),
                        roles=item.get("node_roles") or [],
                        memory_pressure=memory.get("memory_pressure"),
                        native_memory_pressure=memory.get("native_memory_pressure"),
                    ))
                    version = item.get("service_version") or version
    return EceDeployment(
        id=str(raw.get("id", "")),
        name=raw.get("name") or raw.get("id") or "Unnamed deployment",
        healthy=all(health) if health else None,
        elasticsearch_version=version,
        instances=instances,
    )


def fetch_ece_deployments(
    coordinator_url: str,
    username: str,
    password: str,
    verify_ssl: bool = True,
    ssh_jump_host: str | None = None,
) -> list[EceDeployment]:
    session = requests.Session()
    session.verify = verify_ssl
    proxy = configure_tunnel(ssh_jump_host)
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    base = coordinator_url.rstrip("/")
    login = session.post(
        f"{base}/api/v1/users/auth/_login",
        json={"username": username, "password": password},
        timeout=15,
    )
    login.raise_for_status()
    token = login.json()["token"]
    session.headers["Authorization"] = f"Bearer {token}"
    response = session.get(
        f"{base}/api/v1/deployments",
        params={"show_instance_defaults": "true"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("deployments", []) if isinstance(payload, dict) else payload
    deployments = []
    for row in rows:
        if isinstance(row.get("resources"), list):
            detail = session.get(f"{base}/api/v1/deployments/{row['id']}", timeout=30)
            detail.raise_for_status()
            row = detail.json()
        deployments.append(parse_deployment(row))
    return deployments
