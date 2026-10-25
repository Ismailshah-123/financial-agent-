"""
app.agents.llm_client
=======================
Single entry point every agent uses to call an LLM — never import
`groq`/`anthropic`/`openai` directly inside an agent. This is what lets
`settings.llm.default_provider` and `settings.llm.fallback_chain`
(app.core.config) actually mean something: if Groq is down or unconfigured,
the same call transparently retries against the next provider in the
chain instead of the agent needing its own try/except per provider.

WHY A FALLBACK CHAIN, NOT JUST RETRIES
------------------------------------------
`tenacity` retries handle *transient* failures (a timeout, a 500) against
the *same* provider. The fallback chain handles *provider-level*
failures (API key missing, provider outage, provider deprecated a
model) by trying the next provider entirely. Both matter for a platform
that can't afford "the AP agent is down because Groq had an incident."

USAGE
-----
    client = LLMClient()
    response = await client.complete(
        system_prompt="You are a financial reasoning assistant.",
        user_prompt="Summarize this invoice match result: ...",
    )
    response.content  # str
    response.provider  # which provider actually served it, for audit logging

OUTPUT PARSING
--------------
Agents that need structured output should instruct the model to return
JSON in the prompt and parse it themselves (see
`app.agents.prompts.accounts_payable_prompts` for the pattern) — this
client deliberately stays provider-agnostic and returns raw text; it
does not assume every caller wants JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LLMResponse:
    content: str
    provider: str
    model: str


class _ProviderCaller(Protocol):
    async def __call__(self, *, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int) -> str: ...


class LLMClient:
    def __init__(self) -> None:
        self._llm = settings.llm

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> LLMResponse:
        chain = self._llm.fallback_chain or [self._llm.default_provider]
        last_error: Exception | None = None

        for provider in chain:
            caller = self._resolve_caller(provider)
            if caller is None:
                continue  # provider not configured (no API key) — skip silently
            try:
                content = await self._call_with_retry(
                    caller,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return LLMResponse(
                    content=content,
                    provider=provider,
                    model=self._model_for(provider),
                )
            except Exception as exc:  # noqa: BLE001 — deliberately try next provider
                logger.warning(
                    "llm_provider_failed", provider=provider, error=str(exc)
                )
                last_error = exc
                continue

        raise ExternalServiceError(
            "All configured LLM providers failed or are unconfigured.",
            details={"tried_providers": chain, "last_error": str(last_error)},
        )

    async def _call_with_retry(self, caller: _ProviderCaller, **kwargs) -> str:
        @retry(
            stop=stop_after_attempt(self._llm.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            reraise=True,
        )
        async def _do_call() -> str:
            return await caller(**kwargs)

        return await _do_call()

    def _resolve_caller(self, provider: str) -> _ProviderCaller | None:
        if provider == "groq" and self._llm.groq_api_key:
            return self._call_groq
        if provider == "anthropic" and self._llm.anthropic_api_key:
            return self._call_anthropic
        if provider == "openai" and self._llm.openai_api_key:
            return self._call_openai
        if provider == "gemini" and self._llm.gemini_api_key:
            return self._call_gemini
        return None

    def _model_for(self, provider: str) -> str:
        return {
            "groq": self._llm.groq_model,
            "anthropic": self._llm.anthropic_model,
            "openai": self._llm.openai_model,
            "gemini": self._llm.gemini_model,
        }[provider]

    # ------------------------------------------------------------------
    # Provider-specific implementations. Each imports its SDK lazily so
    # a deployment that only configured Groq doesn't need the anthropic/
    # openai/google packages importable at module load time.
    # ------------------------------------------------------------------
    async def _call_groq(
        self, *, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int
    ) -> str:
        from groq import AsyncGroq

        client = AsyncGroq(api_key=self._llm.groq_api_key.get_secret_value())
        response = await client.chat.completions.create(
            model=self._llm.groq_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=self._llm.request_timeout_seconds,
        )
        return response.choices[0].message.content or ""

    async def _call_anthropic(
        self, *, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int
    ) -> str:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=self._llm.anthropic_api_key.get_secret_value())
        response = await client.messages.create(
            model=self._llm.anthropic_model,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=self._llm.request_timeout_seconds,
        )
        return "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )

    async def _call_openai(
        self, *, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int
    ) -> str:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._llm.openai_api_key.get_secret_value())
        response = await client.chat.completions.create(
            model=self._llm.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=self._llm.request_timeout_seconds,
        )
        return response.choices[0].message.content or ""

    async def _call_gemini(
        self, *, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int
    ) -> str:
        import google.generativeai as genai

        genai.configure(api_key=self._llm.gemini_api_key.get_secret_value())
        model = genai.GenerativeModel(
            model_name=self._llm.gemini_model, system_instruction=system_prompt
        )
        response = await model.generate_content_async(
            user_prompt,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            },
        )
        return response.text or ""


_llm_client_singleton: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _llm_client_singleton
    if _llm_client_singleton is None:
        _llm_client_singleton = LLMClient()
    return _llm_client_singleton
