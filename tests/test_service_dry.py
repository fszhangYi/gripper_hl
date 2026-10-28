"""Dry-run smoke for gripper_hl host config loading."""

from __future__ import annotations

from pathlib import Path

from gripper_hl_app.service import load_host_config


def test_load_host_config() -> None:
    root = Path(__file__).resolve().parents[1]
    cfg = load_host_config(root / "configs" / "default.yaml", cwd=root)
    assert cfg.sensor_id == "gripper-huiling"
    assert cfg.web_port == 7021
    assert cfg.sensors_config.name == "sensors_gripper.yaml"
