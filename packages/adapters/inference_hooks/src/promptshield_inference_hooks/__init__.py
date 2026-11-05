"""Inference hooks do Claude Enterprise (beta). Protocolo: docs/inference-hooks.md (lido em 2026-10-15)."""
from .frames import Block, Frame, parse_frame
from .signature import SignatureError, verify
from .verdict import allow, deny

__all__ = ["Block", "Frame", "SignatureError", "allow", "deny", "parse_frame", "verify"]
