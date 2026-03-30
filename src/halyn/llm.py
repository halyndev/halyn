# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
LLM Connector — Multi-provider abstraction.

Halyn is provider-agnostic. It monitors any AI, regardless of origin.
This module provides connectors for direct LLM integration (optional).
The proxy layer works independently — without any connector configured.

Supported by the proxy (no connector needed):
  Cloud: Anthropic, OpenAI, Google, Mistral, xAI, DeepSeek, Cohere,
         Perplexity, 01.AI, Alibaba, Baidu, Amazon Bedrock, Azure OpenAI,
         NVIDIA NIM, Together AI, Groq, Fireworks AI, and any HTTP API.
  Local: Ollama, LM Studio, Jan.ai, GPT4All, llama.cpp, LocalAI,
         text-generation-webui, KoboldCpp, vLLM, TGI, and any local server.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

log = logging.getLogger(__name__)


# ─── Base ─────────────────────────────────────────────────────────────────────

class LLMResponse:
    def __init__(self, content: str, model: str = "", usage: dict | None = None) -> None:
        self.content = content
        self.model = model
        self.usage = usage or {}


class LLMConnector(ABC):
    """Base class for all LLM connectors."""

    @abstractmethod
    def complete(
        self,
        messages: list[dict],
        system: str = "",
        max_tokens: int = 1024,
    ) -> LLMResponse:
        ...


# ─── Cloud providers ──────────────────────────────────────────────────────────

class AnthropicConnector(LLMConnector):
    """Anthropic — Claude Sonnet 4.6, Opus 4.6, Haiku 4.5."""

    def __init__(self, api_key: str = "", model: str = "claude-sonnet-4-6") -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.endpoint = "https://api.anthropic.com/v1/messages"

    def complete(self, messages: list[dict], system: str = "", max_tokens: int = 1024) -> LLMResponse:
        body: dict[str, Any] = {"model": self.model, "max_tokens": max_tokens, "messages": messages}
        if system:
            body["system"] = system
        data = self._post(self.endpoint, body, {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        })
        content = data["content"][0]["text"]
        return LLMResponse(content, self.model, data.get("usage"))

    def _post(self, url: str, body: dict, headers: dict) -> dict:
        payload = json.dumps(body).encode()
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        for k, v in headers.items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())


class OpenAIConnector(LLMConnector):
    """OpenAI — GPT-4.1, GPT-4.1 mini, GPT-4.1 nano, o3, o4-mini.
    Also compatible with: Azure OpenAI, NVIDIA NIM, Together AI, Groq,
    Fireworks AI, and any OpenAI-compatible endpoint.
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "gpt-4.1",
        endpoint: str = "https://api.openai.com/v1",
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model
        self.endpoint = endpoint.rstrip("/")

    def complete(self, messages: list[dict], system: str = "", max_tokens: int = 1024) -> LLMResponse:
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        body = {"model": self.model, "max_tokens": max_tokens, "messages": msgs}
        data = self._post(f"{self.endpoint}/chat/completions", body)
        content = data["choices"][0]["message"]["content"]
        return LLMResponse(content, self.model, data.get("usage"))

    def _post(self, url: str, body: dict) -> dict:
        payload = json.dumps(body).encode()
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())


class GeminiConnector(LLMConnector):
    """Google — Gemini 3.1 Pro, Gemini 3.1 Flash, Gemini 3.1 Flash-Lite."""

    def __init__(self, api_key: str = "", model: str = "gemini-3.1-flash-lite-preview") -> None:
        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY", "")
        self.model = model

    def complete(self, messages: list[dict], system: str = "", max_tokens: int = 1024) -> LLMResponse:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        contents = [{"role": m["role"].replace("assistant", "model"), "parts": [{"text": m["content"]}]}
                    for m in messages]
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        payload = json.dumps(body).encode()
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        return LLMResponse(content, self.model)


class MistralConnector(LLMConnector):
    """Mistral AI — Mistral Large 2, Mistral Small 3, Codestral."""

    def __init__(self, api_key: str = "", model: str = "mistral-small-latest") -> None:
        self.api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        self.model = model
        self._oa = OpenAIConnector(api_key, model, "https://api.mistral.ai/v1")

    def complete(self, messages: list[dict], system: str = "", max_tokens: int = 1024) -> LLMResponse:
        self._oa.api_key = self.api_key
        return self._oa.complete(messages, system, max_tokens)


class XAIConnector(LLMConnector):
    """xAI — Grok-3, Grok-3 mini."""

    def __init__(self, api_key: str = "", model: str = "grok-3-mini") -> None:
        self.api_key = api_key or os.environ.get("XAI_API_KEY", "")
        self._oa = OpenAIConnector(api_key, model, "https://api.x.ai/v1")

    def complete(self, messages: list[dict], system: str = "", max_tokens: int = 1024) -> LLMResponse:
        self._oa.api_key = self.api_key
        return self._oa.complete(messages, system, max_tokens)


class DeepSeekConnector(LLMConnector):
    """DeepSeek — DeepSeek-V3, DeepSeek-R1."""

    def __init__(self, api_key: str = "", model: str = "deepseek-chat") -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self._oa = OpenAIConnector(api_key, model, "https://api.deepseek.com/v1")

    def complete(self, messages: list[dict], system: str = "", max_tokens: int = 1024) -> LLMResponse:
        self._oa.api_key = self.api_key
        return self._oa.complete(messages, system, max_tokens)


class GroqConnector(LLMConnector):
    """Groq — Llama, Mixtral, Gemma (ultra-fast inference)."""

    def __init__(self, api_key: str = "", model: str = "llama-3.3-70b-versatile") -> None:
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self._oa = OpenAIConnector(api_key, model, "https://api.groq.com/openai/v1")

    def complete(self, messages: list[dict], system: str = "", max_tokens: int = 1024) -> LLMResponse:
        self._oa.api_key = self.api_key
        return self._oa.complete(messages, system, max_tokens)


class PerplexityConnector(LLMConnector):
    """Perplexity — Sonar Pro, Sonar, Sonar Reasoning."""

    def __init__(self, api_key: str = "", model: str = "sonar") -> None:
        self.api_key = api_key or os.environ.get("PERPLEXITY_API_KEY", "")
        self._oa = OpenAIConnector(api_key, model, "https://api.perplexity.ai")

    def complete(self, messages: list[dict], system: str = "", max_tokens: int = 1024) -> LLMResponse:
        self._oa.api_key = self.api_key
        return self._oa.complete(messages, system, max_tokens)


class CohereConnector(LLMConnector):
    """Cohere — Command R+, Command R, Aya."""

    def __init__(self, api_key: str = "", model: str = "command-r-plus") -> None:
        self.api_key = api_key or os.environ.get("COHERE_API_KEY", "")
        self.model = model

    def complete(self, messages: list[dict], system: str = "", max_tokens: int = 1024) -> LLMResponse:
        url = "https://api.cohere.com/v2/chat"
        chat_history = [{"role": m["role"], "content": m["content"]} for m in messages[:-1]]
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
            "max_tokens": max_tokens,
        }
        if system:
            body["system"] = system
        payload = json.dumps(body).encode()
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        content = data["message"]["content"][0]["text"]
        return LLMResponse(content, self.model)


# ─── Local providers ──────────────────────────────────────────────────────────

class OllamaConnector(LLMConnector):
    """Ollama — any local model: Llama 3.3, Qwen2.5, Mistral, DeepSeek-R1,
    Phi-4, Gemma 3, and hundreds more. OpenAI-compatible API.
    """

    def __init__(self, model: str = "llama3.2", host: str = "http://localhost:11434") -> None:
        self.model = model
        self._oa = OpenAIConnector("ollama", model, f"{host}/v1")

    def complete(self, messages: list[dict], system: str = "", max_tokens: int = 1024) -> LLMResponse:
        return self._oa.complete(messages, system, max_tokens)


class LocalAIConnector(LLMConnector):
    """LocalAI / LM Studio / Jan.ai / KoboldCpp / text-generation-webui /
    llama.cpp / vLLM / TGI — any OpenAI-compatible local server.
    """

    def __init__(
        self,
        model: str = "local-model",
        host: str = "http://localhost:8080",
        api_key: str = "local",
    ) -> None:
        self.model = model
        self._oa = OpenAIConnector(api_key, model, host)

    def complete(self, messages: list[dict], system: str = "", max_tokens: int = 1024) -> LLMResponse:
        return self._oa.complete(messages, system, max_tokens)


class HuggingFaceConnector(LLMConnector):
    """HuggingFace — any model via transformers pipeline (fully local)."""

    def __init__(self, model: str = "microsoft/Phi-4") -> None:
        self.model_name = model
        self._pipeline: Any = None

    def _load(self) -> None:
        if self._pipeline is None:
            try:
                from transformers import pipeline  # type: ignore
            except ImportError as e:
                raise ImportError("pip install transformers torch") from e
            log.info("llm.loading model=%s", self.model_name)
            self._pipeline = pipeline("text-generation", model=self.model_name, device_map="auto")
            log.info("llm.loaded model=%s", self.model_name)

    def complete(self, messages: list[dict], system: str = "", max_tokens: int = 1024) -> LLMResponse:
        self._load()
        prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        if system:
            prompt = f"system: {system}\n{prompt}"
        result = self._pipeline(prompt, max_new_tokens=max_tokens, do_sample=False)
        text = result[0]["generated_text"][len(prompt):].strip()
        return LLMResponse(text, self.model_name)


# ─── Factory ──────────────────────────────────────────────────────────────────

def create_connector(provider: str, **kwargs: Any) -> LLMConnector:
    """
    Create a connector by provider name.

    Cloud providers: anthropic, openai, azure, google, gemini, mistral,
                     xai, grok, deepseek, cohere, perplexity, groq,
                     fireworks, together, nvidia, bedrock
    Local providers: ollama, lmstudio, jan, localai, llamacpp, gpt4all,
                     kobold, vllm, tgi, huggingface, openai-compatible
    """
    # Normalize aliases
    aliases = {
        # Anthropic
        "anthropic": "anthropic", "claude": "anthropic",
        # OpenAI
        "openai": "openai", "gpt": "openai", "azure": "openai",
        "nvidia": "openai", "together": "openai", "fireworks": "openai",
        "bedrock": "openai",  # via OpenAI-compat gateway
        # Google
        "google": "google", "gemini": "google",
        # Mistral
        "mistral": "mistral",
        # xAI
        "xai": "xai", "grok": "xai",
        # DeepSeek
        "deepseek": "deepseek",
        # Groq
        "groq": "groq",
        # Perplexity
        "perplexity": "perplexity", "sonar": "perplexity",
        # Cohere
        "cohere": "cohere", "command": "cohere",
        # Local
        "ollama": "ollama",
        "lmstudio": "local", "jan": "local", "janai": "local",
        "localai": "local", "llamacpp": "local", "llama.cpp": "local",
        "kobold": "local", "koboldcpp": "local",
        "vllm": "local", "tgi": "local",
        "gpt4all": "local", "openwebui": "local",
        "local": "local", "openai-compatible": "local",
        # HuggingFace
        "huggingface": "hf", "hf": "hf", "transformers": "hf",
    }

    connectors = {
        "anthropic": AnthropicConnector,
        "openai": OpenAIConnector,
        "google": GeminiConnector,
        "mistral": MistralConnector,
        "xai": XAIConnector,
        "deepseek": DeepSeekConnector,
        "groq": GroqConnector,
        "perplexity": PerplexityConnector,
        "cohere": CohereConnector,
        "ollama": OllamaConnector,
        "local": LocalAIConnector,
        "hf": HuggingFaceConnector,
    }

    key = aliases.get(provider.lower(), provider.lower())
    cls = connectors.get(key)
    if cls is None:
        raise ValueError(
            f"Unknown provider '{provider}'. "
            f"Note: the Halyn proxy works with ANY AI regardless of this connector."
        )
    return cls(**kwargs)
