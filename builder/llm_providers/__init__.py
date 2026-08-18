"""Plain-text LLM completion providers, one small module each, all sharing
the same shape: call(api_key, model, system, prompt, timeout) -> str.

Callers resolve a provider by name string via resolve_text_provider().
Switching providers is one config value; adding a new one is one new module
here, no changes to any caller.
"""
from __future__ import annotations

import importlib
import logging
from typing import Callable

logger = logging.getLogger(__name__)


def _resolve(name: str, attr: str) -> Callable[..., str]:
    try:
        module = importlib.import_module(f"builder.llm_providers.{name}")
    except ModuleNotFoundError as e:
        raise ValueError(
            f"Unknown provider {name!r} -- no builder/llm_providers/{name}.py module found"
        ) from e

    fn = getattr(module, attr, None)
    if not callable(fn):
        raise ValueError(f"builder/llm_providers/{name}.py has no callable {attr}(...)")
    return fn


def resolve_text_provider(name: str) -> Callable[..., str]:
    return _resolve(name, "call")


def resolve_vision_provider(name: str) -> Callable[..., str]:
    return _resolve(name, "call_vision")


def call_text_capability(
    provider, api_key, model, system, prompt,
    fallback_model=None, timeout=90.0, parse=None,
):
    """Run one plain-text LLM call end to end: resolve the provider, call
    `model`, and on ANY failure retry `fallback_model` once (if given).
    Returns the model's text, or `parse(text)` if a parse callable is given.
    """
    call = resolve_text_provider(provider)
    run = parse if parse is not None else (lambda text: text)
    try:
        return run(call(api_key, model, system, prompt, timeout=timeout))
    except Exception as e:
        if not fallback_model:
            raise
        logger.warning(
            "text capability primary attempt failed (provider=%s model=%r): %s: %s"
            " -- retrying fallback_model=%r",
            provider, model, type(e).__name__, e, fallback_model,
        )
        return run(call(api_key, fallback_model, system, prompt, timeout=timeout))
