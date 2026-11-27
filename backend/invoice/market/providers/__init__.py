"""Search-provider adapters used by ClaimGuard market research."""

from .serper import search_serper
from .searxng import search_searxng

__all__ = ["search_serper", "search_searxng"]
