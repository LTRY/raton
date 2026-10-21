"""The notes + résumé court prompt as the app builds it today (the nightly batch's)."""

from app.services.llm.prompts import build_auto_notes_prompt as build

NAME = "current"
__all__ = ["NAME", "build"]
