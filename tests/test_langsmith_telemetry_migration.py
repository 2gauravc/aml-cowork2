from src.backend.app import migrate_completed_cdd_state


def test_legacy_runtime_telemetry_is_removed_on_load() -> None:
    state = {"runtime_telemetry": {"schema_version": "runtime_telemetry/v1", "nodes": []}}
    migration = migrate_completed_cdd_state(state)
    assert migration["routines"]["runtime_telemetry"] is True
    assert "runtime_telemetry" not in state
