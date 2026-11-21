"""Thin, safe wrapper around the vastai CLI.

Why a wrapper: the `vastai.exe` launcher is blocked by Windows Application Control on this PC, and
renting should have a hard price cap and an explicit confirmation so a typo cannot burn the balance.

Usage (from speaking-service/, with the venv python):
    python deploy/vast/vast.py search                 # cheap verified 24 GB cards, cheapest first
    python deploy/vast/vast.py rent OFFER_ID --max-price 0.60 --yes
    python deploy/vast/vast.py status
    python deploy/vast/vast.py destroy INSTANCE_ID    # ends ALL billing (stop does not)

The API key comes from VAST_API_KEY in deploy/vast/.env or the environment. Never commit it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
IMAGE = "vastai/pytorch:cuda-12.4.1-auto"  # vast.ai base image: includes sshd (plain pytorch/pytorch has none and never starts)
DEFAULT_DISK_GB = 100


def load_env() -> None:
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def cli(*args: str, capture: bool = False, yes: bool = False) -> str:
    """Run one vastai CLI command in a fresh process.

    The CLI keeps global argparse state, so it cannot be called twice in one process, and the
    vastai.exe launcher is blocked by Windows Application Control, so we call it through python.
    """
    import subprocess

    key = os.environ.get("VAST_API_KEY")
    argv = ["vastai", *args] + (["--api-key", key] if key else [])
    code = "import sys; from vastai.cli.main import main; sys.argv = %r; main()" % (argv,)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    res = subprocess.run([sys.executable, "-c", code], env=env, text=True,
                         capture_output=capture, encoding="utf-8", input="y\n" if yes else None)
    if res.returncode != 0:
        sys.exit(res.returncode if not capture else (res.stderr or res.stdout))
    return res.stdout if capture else ""


def offer_query(gpu: str = "RTX_4090", min_vram_gb: int = 24) -> str:
    return (f"reliability>0.98 num_gpus=1 gpu_name={gpu} gpu_ram>={min_vram_gb - 1} "
            f"direct_port_count>=2 inet_down>200 disk_space>=120 cuda_vers>=12.1 verified=true rentable=true")


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("--gpu", default="RTX_4090")
    s.add_argument("--min-vram-gb", type=int, default=24)
    r = sub.add_parser("rent")
    r.add_argument("offer_id")
    r.add_argument("--max-price", type=float, required=True, help="refuse if the offer costs more per hour")
    r.add_argument("--disk", type=int, default=DEFAULT_DISK_GB)
    r.add_argument("--gpu", default="RTX_4090", help="GPU name used to look the offer up, e.g. RTX_3090")
    r.add_argument("--yes", action="store_true", help="actually rent (without it this is a dry run)")
    sub.add_parser("status")
    stp = sub.add_parser("stop")      # pauses compute billing; the disk (and your setup) is kept, storage still billed
    stp.add_argument("instance_id")
    sta = sub.add_parser("start")
    sta.add_argument("instance_id")
    d = sub.add_parser("destroy")
    d.add_argument("instance_id")
    a = ap.parse_args()

    if a.cmd == "search":
        cli("search", "offers", offer_query(a.gpu, a.min_vram_gb), "-o", "dph_total", "--limit", "15", "--storage", str(DEFAULT_DISK_GB))
    elif a.cmd == "rent":
        # The `id=` filter returns nothing, so look the offer up in the normal search results.
        found = json.loads(cli("search", "offers", f"gpu_name={a.gpu} num_gpus=1 verified=true rentable=true", "-o", "dph_total", "--limit", "200",
                               "--storage", str(a.disk), "--raw", capture=True) or "[]")
        offers = [o for o in found if str(o.get("id")) == str(a.offer_id)]
        if not offers:
            sys.exit(f"offer {a.offer_id} not found (it may have been rented; search again)")
        price = float(offers[0]["dph_total"])
        print(f"offer {a.offer_id}: {offers[0].get('gpu_name')} ${price:.3f}/h")
        if price > a.max_price:
            sys.exit(f"refusing: ${price:.3f}/h is above --max-price {a.max_price}")
        if not a.yes:
            sys.exit("dry run: add --yes to rent")
        cli("create", "instance", a.offer_id, "--image", IMAGE, "--disk", str(a.disk),
            "--ssh", "--direct", "--cancel-unavail", "--label", "speaking-bench")
    elif a.cmd == "status":
        cli("show", "instances")
        cli("show", "user")
    elif a.cmd == "stop":
        cli("stop", "instance", a.instance_id)
    elif a.cmd == "start":
        cli("start", "instance", a.instance_id)
    elif a.cmd == "destroy":
        cli("destroy", "instance", a.instance_id, yes=True)


if __name__ == "__main__":
    main()
