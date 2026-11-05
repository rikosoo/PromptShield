"""Motor de detecção do PromptShield (biblioteca pura, sem dependência de web)."""

from .engine import analyze, context_from_event
from .models import Analysis, Span

__version__ = "0.2.0"
__all__ = ["analyze", "context_from_event", "Analysis", "Span", "__version__"]
