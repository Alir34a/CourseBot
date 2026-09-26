"""Central registry of reusable modules.

Usage in a NEW bot project:
    1. Read modules/registry.json (or call list_modules()).
    2. Reuse the module package directory as-is.
    3. Only bot-specific texts/config live outside modules/ (see bot/ and config/).
    4. New generic capability -> create modules/<name>/ + register here.

This file is the programmatic view; registry.json is the human/LLM-readable source.
"""
from __future__ import annotations
import json
from pathlib import Path

REGISTRY_PATH = Path(__file__).with_name("registry.json")


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def list_modules() -> list[dict]:
    return load_registry().get("modules", [])


def get_module(name: str) -> dict | None:
    for m in list_modules():
        if m["name"] == name:
            return m
    return None
