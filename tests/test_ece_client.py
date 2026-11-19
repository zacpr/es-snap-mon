from es_snap_mon.ece_client import parse_deployment


def test_parse_deployment_summarizes_health_and_elasticsearch_capacity():
    raw = {
        "id": "deployment-1",
        "name": "Production search",
        "resources": {
            "elasticsearch": [{
                "id": "es-1",
                "ref_id": "main-elasticsearch",
                "info": {
                    "healthy": True,
                    "status": "started",
                    "cluster_info": {
                        "cluster_name": "prod-es",
                        "version": {"number": "8.15.0"},
                    },
                    "topology": {
                        "cluster_instances": [{
                            "instance_name": "instance-0000000000",
                            "healthy": True,
                            "memory": {"capacity": 8192},
                            "storage": {"capacity": 102400},
                            "node_roles": ["data_hot", "master"],
                            "service_running": True,
                        }]
                    },
                },
            }],
            "kibana": [],
        },
    }

    deployment = parse_deployment(raw)

    assert deployment.name == "Production search"
    assert deployment.healthy is True
    assert deployment.elasticsearch_version == "8.15.0"
    assert deployment.instance_count == 1
    assert deployment.memory_mb == 8192
    assert deployment.storage_mb == 102400
    assert deployment.running_instances == 1


def test_unhealthy_resource_makes_deployment_unhealthy():
    raw = {
        "id": "deployment-2",
        "name": "Degraded",
        "resources": {"elasticsearch": [{"info": {"healthy": False}}]},
    }

    assert parse_deployment(raw).healthy is False


def test_fetch_ece_deployments_uses_version_one_api(monkeypatch):
    from unittest.mock import Mock, patch
    from es_snap_mon.ece_client import fetch_ece_deployments

    response = Mock()
    response.json.return_value = {"deployments": [{"id": "one", "name": "One", "resources": {}}]}
    login = Mock()
    login.json.return_value = {"token": "token-value"}
    session = Mock()
    session.headers = {}
    session.get.return_value = response
    session.post.return_value = login
    with patch("es_snap_mon.ece_client.requests.Session", return_value=session):
        result = fetch_ece_deployments("https://ece.example:12443", "admin", "secret")

    assert [item.id for item in result] == ["one"]
    session.get.assert_called_once_with(
        "https://ece.example:12443/api/v1/deployments",
        params={"show_instance_defaults": "true"},
        timeout=30,
    )


def test_parse_legacy_ece_instances_includes_live_capacity_and_pressure():
    deployment = parse_deployment({
        "id": "legacy",
        "name": "Legacy ECE",
        "resources": {"elasticsearch": [{"info": {
            "healthy": True,
            "topology": {"instances": [{
                "instance_name": "instance-0000000003",
                "service_version": "8.19.23",
                "service_running": True,
                "healthy": True,
                "memory": {"instance_capacity": 4096, "memory_pressure": 4, "native_memory_pressure": 62},
                "disk": {"disk_space_available": 131072},
                "node_roles": ["master", "data_hot"],
            }]},
        }}]},
    })

    instance = deployment.instances[0]
    assert deployment.elasticsearch_version == "8.19.23"
    assert instance.memory_mb == 4096
    assert instance.storage_mb == 131072
    assert instance.memory_pressure == 4
    assert instance.native_memory_pressure == 62
