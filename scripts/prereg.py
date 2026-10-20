"""
Pre-registration: freeze a forecast and make the freeze verifiable.

A forecast is only falsifiable if a third party can confirm it existed, unchanged,
before the event. This script writes a manifest containing a SHA-256 of every
frozen artifact. Committing that manifest before kickoff means the commit
timestamp plus the hashes are sufficient evidence -- if any input or output is
edited later, `--verify` fails.

Freeze before the event:
    python scripts/prereg.py freeze --event WC2026 --deadline 2026-06-11T15:00:00Z

Verify at any later point:
    python scripts/prereg.py verify --event WC2026
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

ARTIFACTS = [
    "data/ratings_20260610.csv",
    "forecast/model.py",
    "forecast/output/probabilities.json",
    "forecast/FROZEN_FORECAST.md",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str | None:
    try:
        return subprocess.check_output(["git", *args], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def manifest_path(event: str) -> Path:
    return Path(f"prereg/{event}.manifest.json")


def freeze(event: str, deadline: str | None) -> None:
    entries = {}
    for rel in ARTIFACTS:
        p = Path(rel)
        if not p.exists():
            raise SystemExit(f"missing artifact: {rel} (run forecast/model.py first)")
        entries[rel] = {"sha256": sha256(p), "bytes": p.stat().st_size}

    now = dt.datetime.now(dt.timezone.utc)
    manifest = {
        "event": event,
        "frozen_at_utc": now.isoformat(),
        "deadline_utc": deadline,
        "before_deadline": (now < dt.datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                            if deadline else None),
        "git_commit": git("rev-parse", "HEAD"),
        "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "artifacts": entries,
        "combined_sha256": hashlib.sha256(
            "".join(entries[k]["sha256"] for k in sorted(entries)).encode()).hexdigest(),
    }

    out = manifest_path(event)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2))

    print(f"Froze {len(entries)} artifacts for {event}")
    for rel, meta in entries.items():
        print(f"  {meta['sha256'][:16]}  {rel}")
    print(f"\ncombined: {manifest['combined_sha256']}")
    print(f"manifest: {out}")
    if deadline:
        status = "BEFORE" if manifest["before_deadline"] else "AFTER (!)"
        print(f"frozen {status} deadline {deadline}")
    print("\nNext: commit and push this manifest BEFORE the event starts.")
    print("      git add prereg/ && git commit -m 'prereg: freeze " + event + "'")


def verify(event: str) -> None:
    path = manifest_path(event)
    if not path.exists():
        raise SystemExit(f"no manifest at {path}")
    manifest = json.loads(path.read_text())

    ok = True
    print(f"Verifying {event} (frozen {manifest['frozen_at_utc']})")
    for rel, meta in manifest["artifacts"].items():
        p = Path(rel)
        if not p.exists():
            print(f"  MISSING   {rel}")
            ok = False
            continue
        current = sha256(p)
        if current == meta["sha256"]:
            print(f"  ok        {rel}")
        else:
            print(f"  MODIFIED  {rel}\n            frozen  {meta['sha256']}\n            current {current}")
            ok = False

    if manifest.get("git_commit"):
        ts = git("show", "-s", "--format=%cI", manifest["git_commit"])
        print(f"\n  freeze commit {manifest['git_commit'][:12]} committed {ts or 'unknown'}")
    if manifest.get("deadline_utc"):
        print(f"  deadline {manifest['deadline_utc']} — frozen before: {manifest['before_deadline']}")

    print("\n" + ("PASS — artifacts match the pre-registered hashes."
                  if ok else "FAIL — artifacts differ from the pre-registration."))
    raise SystemExit(0 if ok else 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--event", required=True)
    f.add_argument("--deadline", help="ISO8601 UTC, e.g. 2026-06-11T15:00:00Z")
    v = sub.add_parser("verify")
    v.add_argument("--event", required=True)
    args = ap.parse_args()
    freeze(args.event, args.deadline) if args.cmd == "freeze" else verify(args.event)


if __name__ == "__main__":
    main()
