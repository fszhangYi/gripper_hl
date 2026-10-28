"""CLI: ``gripper-hl web`` | ``gripper-hl probe`` | ``gripper-hl ports``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gripper_hl_app.paths import project_root
from gripper_hl_app.service import GripperHlService, load_host_config


def _resolve_cfg(path: str) -> tuple[Path, Path]:
    cwd = Path.cwd()
    p = Path(path)
    if p.is_file():
        return p.resolve(), cwd
    alt = project_root() / path
    if alt.is_file():
        return alt.resolve(), project_root()
    raise FileNotFoundError(f"config not found: {path}")


def _load(args: argparse.Namespace):
    cfg_path, cwd = _resolve_cfg(args.config)
    cfg = load_host_config(cfg_path, cwd=cwd)
    if getattr(args, "no_dry_run", False):
        cfg.dry_run = False
    elif getattr(args, "dry_run", False):
        cfg.dry_run = True
    if getattr(args, "host", None):
        cfg.web_host = str(args.host)
    if getattr(args, "port", None):
        cfg.web_port = int(args.port)
    return cfg


def cmd_web(args: argparse.Namespace) -> int:
    from gripper_hl_app.web.server import main as web_main

    cfg = _load(args)
    argv = list(sys.argv)
    service = GripperHlService(cfg, restart_argv=argv)
    print(
        f"[gripper-hl] web http://{cfg.web_host}:{cfg.web_port}/  "
        f"host={cfg.host_config} sensors={cfg.sensors_config}"
    )
    web_main(service, host=cfg.web_host, port=cfg.web_port)
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    cfg = _load(args)
    service = GripperHlService(cfg)
    out = service.probe()
    print(json.dumps(out, indent=2, ensure_ascii=True))
    return 0 if out.get("ok") else 1


def cmd_ports(args: argparse.Namespace) -> int:
    cfg = _load(args)
    service = GripperHlService(cfg)
    out = service.list_ports()
    for p in out.get("ports") or []:
        print(p)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gripper-hl", description="慧灵 Z-EFG-C65 gripper host"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    def _add_config(p: argparse.ArgumentParser) -> None:
        p.add_argument("-c", "--config", default="configs/default.yaml")

    p_web = sub.add_parser("web", help="start FastAPI web UI")
    _add_config(p_web)
    p_web.add_argument("--host", default=None)
    p_web.add_argument("--port", type=int, default=None)
    p_web.add_argument("--dry-run", action="store_true")
    p_web.add_argument("--no-dry-run", action="store_true")
    p_web.set_defaults(func=cmd_web)

    p_probe = sub.add_parser("probe", help="probe gripper (no persistent open)")
    _add_config(p_probe)
    p_probe.add_argument("--dry-run", action="store_true")
    p_probe.add_argument("--no-dry-run", action="store_true")
    p_probe.set_defaults(func=cmd_probe)

    p_ports = sub.add_parser("ports", help="list serial ports")
    _add_config(p_ports)
    p_ports.set_defaults(func=cmd_ports)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
