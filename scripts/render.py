#!/usr/bin/env python3
"""Render repository templates without printing or persisting secrets in Git."""
from __future__ import annotations
import os
import pathlib
import secrets
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

def values():
    required = ["OPENCLAW_HOME", "OWNER_NAME", "OWNER_DISCORD_ID", "OWNER_TIMEZONE", "DISCORD_GUILD_ID"]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise SystemExit("Missing required .env values: " + ", ".join(missing))
    return {
        "__OPENCLAW_HOME__": os.environ["OPENCLAW_HOME"].rstrip("/"),
        "__OWNER_NAME__": os.environ["OWNER_NAME"],
        "__OWNER_DISCORD_ID__": os.environ["OWNER_DISCORD_ID"],
        "__OWNER_TIMEZONE__": os.environ["OWNER_TIMEZONE"],
        "__DISCORD_GUILD_ID__": os.environ["DISCORD_GUILD_ID"],
        "__PERSONAL_GOOGLE_ACCOUNT__": os.environ.get("PERSONAL_GOOGLE_ACCOUNT", "personal@example.com"),
        "__SCHOOL_GOOGLE_ACCOUNT__": os.environ.get("SCHOOL_GOOGLE_ACCOUNT", "school@example.edu"),
        "__GATEWAY_TOKEN__": secrets.token_urlsafe(48),
    }

def render_text(source: pathlib.Path, destination: pathlib.Path, mapping: dict[str, str]):
    text = source.read_text(encoding="utf-8")
    for old, new in mapping.items():
        text = text.replace(old, new)
    unresolved = [key for key in mapping if key in text]
    if unresolved:
        raise SystemExit(f"Unresolved placeholders in {source}: {unresolved}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")

def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: render.py OUTPUT_DIRECTORY")
    out = pathlib.Path(sys.argv[1]).resolve()
    mapping = values()
    selections = {
        ROOT / "config/openclaw.json.tmpl": out / ".openclaw/openclaw.json",
        ROOT / "workspace/USER.md.tmpl": out / ".openclaw/workspace-personal/USER.md",
    }
    for source in (ROOT / "workspace").rglob("*"):
        if source.is_file() and "__pycache__" not in source.parts and source.suffix != ".pyc" and source.name not in {"USER.md.tmpl"}:
            selections[source] = out / ".openclaw/workspace-personal" / source.relative_to(ROOT / "workspace")
    for source in (ROOT / "extensions").rglob("*"):
        if source.is_file() and "__pycache__" not in source.parts and source.suffix != ".pyc": selections[source] = out / ".openclaw/extensions" / source.relative_to(ROOT / "extensions")
    for source in (ROOT / "systemd").rglob("*"):
        if source.is_file():
            name = source.name.removesuffix(".tmpl")
            selections[source] = out / ".config/systemd/user" / name
    for source, destination in selections.items(): render_text(source, destination, mapping)
    print(out)

if __name__ == "__main__": main()
