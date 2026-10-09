#!/usr/bin/env python3
"""Safely inspect or register the OpenSplat LS6 Tapis application.

The default mode is read-only: it authenticates and checks whether the exact
app version already exists.  Creating an app version requires both
``--create`` and ``--confirm-external-write`` so an accidental invocation
cannot mutate Tapis state.

Usage:
    python tapis/register_app.py --dry-run
    python tapis/register_app.py --check
    python tapis/register_app.py --create --confirm-external-write

Credentials are read from TAPIS_USERNAME/TAPIS_PASSWORD or prompted without
printing the password.  The app spec is loaded from the adjacent app.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from getpass import getpass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_JSON_PATH = REPO_ROOT / "app.json"


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(REPO_ROOT.parent / ".env")


def load_app_spec() -> dict:
    with APP_JSON_PATH.open(encoding="utf-8") as handle:
        spec = json.load(handle)
    for key in ("id", "version", "runtime", "containerImage", "jobAttributes"):
        if not spec.get(key):
            raise ValueError(f"app.json is missing required field: {key}")
    return spec


def _print_spec(spec: dict) -> None:
    print(json.dumps(spec, indent=2, sort_keys=True))
    print("\nNo Tapis request was made.")


def _status_code(error: BaseException) -> int | None:
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status
    return None


def _get_exact_app(t, spec: dict):
    """Return the exact app version, or None only for a confirmed 404."""
    try:
        return t.apps.getApp(appId=spec["id"], appVersion=spec["version"])
    except Exception as error:  # tapipy exposes the HTTP response on the exception
        status = _status_code(error)
        if status == 404:
            return None
        if status is None:
            raise RuntimeError(
                "could not determine whether the app exists; refusing to write"
            ) from error
        raise RuntimeError(f"Tapis app lookup failed with HTTP {status}") from error


def _client(base_url: str):
    try:
        from tapipy.tapis import Tapis
    except ImportError as error:
        raise RuntimeError(
            "tapipy is not installed; use the Tapis environment or install tapipy"
        ) from error

    username = os.environ.get("TAPIS_USERNAME") or input("Tapis username: ")
    password = os.environ.get("TAPIS_PASSWORD") or getpass("Tapis password: ")
    client = Tapis(base_url=base_url.rstrip("/"), username=username, password=password)
    client.get_tokens()
    return client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io"),
        help="Tapis tenant URL (default: https://portals.tapis.io)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the app spec without authenticating or calling Tapis",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="authenticate and read the exact app version without changing state",
    )
    parser.add_argument(
        "--create",
        action="store_true",
        help="create the app version if the exact version is absent",
    )
    parser.add_argument(
        "--confirm-external-write",
        action="store_true",
        help="required together with --create to permit Tapis mutation",
    )
    args = parser.parse_args(argv)

    if args.create and args.check:
        parser.error("choose at most one of --check or --create")
    if args.confirm_external_write and not args.create:
        parser.error("--confirm-external-write requires --create")

    _load_dotenv()
    spec = load_app_spec()

    if args.dry_run:
        _print_spec(spec)
        return 0

    if not args.check and not args.create:
        parser.error("choose --dry-run, --check, or --create")
    if args.create and not args.confirm_external_write:
        parser.error("--create requires --confirm-external-write")

    try:
        client = _client(args.base_url)
        existing = _get_exact_app(client, spec)
        if existing is not None:
            print(f"{spec['id']} version {spec['version']} already exists")
            if args.create:
                print("Refusing to overwrite an existing immutable app version.", file=sys.stderr)
                return 2
            return 0

        print(f"{spec['id']} version {spec['version']} is not registered")
        if not args.create:
            return 0

        result = client.apps.createAppVersion(**spec)
        print(f"Registered {spec['id']} version {spec['version']}")
        print(result)
        return 0
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
