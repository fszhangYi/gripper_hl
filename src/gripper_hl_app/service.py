"""Gripper sampling + command service on hik-sensors ``kind=gripper_huiling``."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from gripper_hl_app.paths import ensure_sensors_import, resolve_config_path

ensure_sensors_import()

from sensors.runtime.manager import SensorManager  # noqa: E402


@dataclass
class HostConfig:
    host_config: Path
    sensors_config: Path
    dry_run: bool = True
    sensor_id: str = "gripper-huiling"
    sample_hz: float = 20.0
    web_host: str = "127.0.0.1"
    web_port: int = 7021


def load_host_config(path: str | Path, *, cwd: Path | None = None) -> HostConfig:
    p = resolve_config_path(path, cwd=cwd)
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"host config must be a mapping: {p}")
    sc = raw.get("sensors_config") or "./sensors_gripper.yaml"
    sc_path = resolve_config_path(sc, cwd=p.parent)
    rt = raw.get("runtime") if isinstance(raw.get("runtime"), dict) else {}
    dry = raw.get("dry_run")
    if dry is None:
        dry = True
    return HostConfig(
        host_config=p.resolve(),
        sensors_config=sc_path,
        dry_run=bool(dry),
        sensor_id=str(raw.get("sensor_id") or "gripper-huiling"),
        sample_hz=float(rt.get("sample_hz") or 20.0),
        web_host=str(rt.get("web_host") or "127.0.0.1"),
        web_port=int(rt.get("web_port") or 7021),
    )


@dataclass
class SampleSnapshot:
    ts: float = 0.0
    seq: int = 0
    connected: bool = False
    dry_run: bool = True
    hz: float = 0.0
    port: str | None = None
    initialized: bool = False
    position_mm: float | None = None
    speed_mm_s: float | None = None
    current_a: float | None = None
    position_norm: float | None = None
    init_code: int | None = None
    grip_code: int | None = None
    init_text: str | None = None
    grip_text: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "seq": self.seq,
            "connected": self.connected,
            "dry_run": self.dry_run,
            "hz": self.hz,
            "port": self.port,
            "initialized": self.initialized,
            "position_mm": self.position_mm,
            "speed_mm_s": self.speed_mm_s,
            "current_a": self.current_a,
            "position_norm": self.position_norm,
            "init_code": self.init_code,
            "grip_code": self.grip_code,
            "init_text": self.init_text,
            "grip_text": self.grip_text,
            "error": self.error,
        }


class GripperHlService:
    def __init__(self, cfg: HostConfig, *, restart_argv: list[str] | None = None) -> None:
        self.cfg = cfg
        self.restart_argv = list(restart_argv) if restart_argv else None
        self._lock = threading.RLock()
        self._manager: SensorManager | None = None
        self._sensor = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._latest = SampleSnapshot(dry_run=cfg.dry_run)
        self._read_times: list[float] = []

    def status(self) -> dict[str, Any]:
        with self._lock:
            snap = self._latest.to_dict()
        return {
            "sensor_id": self.cfg.sensor_id,
            "host_config": str(self.cfg.host_config),
            "sensors_config": str(self.cfg.sensors_config),
            "sample_hz_target": self.cfg.sample_hz,
            "web_host": self.cfg.web_host,
            "web_port": self.cfg.web_port,
            "kind": "gripper_huiling",
            **snap,
        }

    @property
    def latest(self) -> SampleSnapshot:
        with self._lock:
            d = self._latest.to_dict()
        return SampleSnapshot(
            ts=float(d["ts"]),
            seq=int(d["seq"]),
            connected=bool(d["connected"]),
            dry_run=bool(d["dry_run"]),
            hz=float(d["hz"]),
            port=d.get("port"),
            initialized=bool(d["initialized"]),
            position_mm=d.get("position_mm"),
            speed_mm_s=d.get("speed_mm_s"),
            current_a=d.get("current_a"),
            position_norm=d.get("position_norm"),
            init_code=d.get("init_code"),
            grip_code=d.get("grip_code"),
            init_text=d.get("init_text"),
            grip_text=d.get("grip_text"),
            error=d.get("error"),
        )

    def connect(self, *, dry_run: bool | None = None) -> dict[str, Any]:
        with self._lock:
            if self._sensor is not None and getattr(self._sensor, "_opened", False):
                return {"ok": True, "message": "already connected", **self.status()}
            if dry_run is not None:
                self.cfg.dry_run = bool(dry_run)
            self._manager = SensorManager.from_yaml(
                self.cfg.sensors_config, dry_run=self.cfg.dry_run
            )
            sensor = self._manager.get(self.cfg.sensor_id)
            sensor.open()
            self._sensor = sensor
            self._latest = SampleSnapshot(dry_run=bool(self.cfg.dry_run), seq=0, connected=False)
            self._read_times = []
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="gripper-hl-sample", daemon=True)
            self._thread.start()
            return {"ok": True, "message": "connected", **self.status()}

    def disconnect(self) -> dict[str, Any]:
        with self._lock:
            self._stop.set()
            thr = self._thread
            sensor = self._sensor
            self._thread = None
            self._sensor = None
        if thr and thr.is_alive():
            thr.join(timeout=2.0)
        if sensor is not None:
            try:
                sensor.close()
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            self._latest.connected = False
            self._latest.error = None
        return {"ok": True, "message": "disconnected", **self.status()}

    def probe(self) -> dict[str, Any]:
        ensure_sensors_import()
        mgr = SensorManager.from_yaml(self.cfg.sensors_config, dry_run=self.cfg.dry_run)
        sensor = mgr.get(self.cfg.sensor_id)
        report = sensor.probe()
        return {
            "ok": True,
            "sensor_id": self.cfg.sensor_id,
            "status": getattr(report.status, "value", str(report.status)),
            "message": report.message,
            "checks": [
                {
                    "name": c.name,
                    "ok": bool(c.ok),
                    "detail": c.detail,
                    "critical": bool(getattr(c, "critical", False)),
                }
                for c in (report.checks or [])
            ],
            "metrics": dict(report.metrics or {}),
            "hints": list(report.hints or []),
        }

    def rate_probe(self, duration_s: float = 3.0) -> dict[str, Any]:
        with self._lock:
            sensor = self._sensor
            opened = bool(sensor and getattr(sensor, "_opened", False))
        if not opened or sensor is None:
            return {"ok": False, "error": "connect first"}
        try:
            out = sensor.probe_max_read_hz(duration_s=float(duration_s))
            return {"ok": True, **(out if isinstance(out, dict) else {"result": out})}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def list_ports(self) -> dict[str, Any]:
        ports: list[str] = []
        try:
            from sensors.drivers.bus.serial_bus import list_serial_by_id

            ports.extend(list_serial_by_id())
        except Exception:  # noqa: BLE001
            pass
        try:
            import serial.tools.list_ports

            for p in serial.tools.list_ports.comports():
                ports.append(str(p.device))
        except Exception:  # noqa: BLE001
            pass
        seen: set[str] = set()
        uniq: list[str] = []
        for p in ports:
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        return {"ok": True, "ports": uniq}

    def initialize(self, *, timeout_s: float = 15.0) -> dict[str, Any]:
        with self._lock:
            sensor = self._sensor
        if sensor is None or not getattr(sensor, "_opened", False):
            return {"ok": False, "error": "connect first"}
        try:
            return dict(sensor.initialize(timeout_s=float(timeout_s)))
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def command(self, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            sensor = self._sensor
        if sensor is None or not getattr(sensor, "_opened", False):
            return {"ok": False, "error": "connect first"}
        try:
            return dict(sensor.write(body))
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def prepare_restart(self) -> dict[str, Any]:
        try:
            self.disconnect()
        except Exception:  # noqa: BLE001
            pass
        import sys

        argv = [
            sys.executable,
            "-m",
            "gripper_hl_app",
            "web",
            "-c",
            str(self.cfg.host_config),
            "--host",
            str(self.cfg.web_host),
            "--port",
            str(self.cfg.web_port),
        ]
        if self.cfg.dry_run:
            argv.append("--dry-run")
        else:
            argv.append("--no-dry-run")
        return {
            "ok": True,
            "message": "restart scheduled",
            "executable": sys.executable,
            "argv": argv,
        }

    def _loop(self) -> None:
        period = 1.0 / max(1.0, float(self.cfg.sample_hz))
        while not self._stop.is_set():
            t0 = time.perf_counter()
            try:
                self._sample_once()
            except Exception as e:  # noqa: BLE001
                with self._lock:
                    self._latest.error = str(e)
                    self._latest.connected = False
            elapsed = time.perf_counter() - t0
            self._stop.wait(max(0.001, period - elapsed))

    def _sample_once(self) -> None:
        with self._lock:
            sensor = self._sensor
        if sensor is None:
            return
        sample = sensor.read()
        now = time.time()
        with self._lock:
            self._read_times.append(now)
            cutoff = now - 1.0
            self._read_times = [t for t in self._read_times if t >= cutoff]
            hz = float(len(self._read_times))
            seq = int(self._latest.seq) + 1
            port = str(getattr(sensor, "port", None) or self.cfg.sensors_config)
            err = sample.get("error") if isinstance(sample, dict) else None
            self._latest = SampleSnapshot(
                ts=now,
                seq=seq,
                connected=True,
                dry_run=bool(self.cfg.dry_run or sample.get("dry_run")),
                hz=hz,
                port=port,
                initialized=bool(sample.get("initialized")),
                position_mm=_f(sample.get("position_mm")),
                speed_mm_s=_f(sample.get("speed_mm_s")),
                current_a=_f(sample.get("current_a")),
                position_norm=_f(sample.get("position_norm")),
                init_code=_i(sample.get("init_code")),
                grip_code=_i(sample.get("grip_code")),
                init_text=str(sample.get("init_text") or "") or None,
                grip_text=str(sample.get("grip_text") or "") or None,
                error=str(err) if err else None,
            )


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _i(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
