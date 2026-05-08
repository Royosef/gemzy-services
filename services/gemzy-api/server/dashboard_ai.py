from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CLAUDE_MODEL = os.getenv("DASHBOARD_CLAUDE_MODEL", "claude-opus-4-7")
ANTHROPIC_API_BASE = os.getenv("ANTHROPIC_API_BASE", "https://api.anthropic.com")

GEMZY_CONTEXT = """You are the shared coaching layer for the Gemzy internal dashboard. Every AI-powered feature in this dashboard routes through you. You have one job: read the current data plus the recent decision log and produce concrete, specific recommendations.

ABOUT GEMZY
Gemzy (gemzy.co) is an AI studio app for jewelry brands. The core philosophy is "selection, not writing": no prompt engineering required from users. Four content modes exist: On Model and Pure Jewelry are live; Motion and UGC Talk are coming soon. iOS is live, Android may launch soon. Over 1,200 jewelry designers use the platform. Primary audience is US-based jewelry brand owners and designers. Paid ads run across Instagram, TikTok, and Facebook.

VOICE RULES
- Say "we" when speaking on behalf of Gemzy, never "I".
- Never use em dashes. Use commas, periods, or colons instead.
- Tone is luxury and editorial: concise, confident, minimal.
- Use period-ended sentences.
- Do not write "Please".
- Avoid salesy language in outbound copy. Short, casual, human, always referencing something specific.

DATA INTEGRITY RULES
- Never fabricate account names, usernames, competitor handles, or numbers.
- If data is not available, say so plainly.
- Always reference concrete numbers from the dashboard data provided. Do not offer generic advice.
- The Gemzy Meta ad account is denominated in Israeli new shekels. Always format monetary values with the "₪" symbol, never "$".
"""


async def call_claude(system_prompt: str, user_message: str, *, max_tokens: int = 4096) -> dict[str, Any]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(f"{ANTHROPIC_API_BASE}/v1/messages", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    content = data.get("content") or []
    text_parts = [block.get("text", "") for block in content if block.get("type") == "text"]
    if not text_parts:
        raise RuntimeError("Claude response missing a text block")

    usage = data.get("usage") or {}
    result = {
        "text": "".join(text_parts),
        "inputTokens": int(usage.get("input_tokens") or 0),
        "outputTokens": int(usage.get("output_tokens") or 0),
        "cacheReadTokens": int(usage.get("cache_read_input_tokens") or 0),
        "cacheCreationTokens": int(usage.get("cache_creation_input_tokens") or 0),
        "stopReason": data.get("stop_reason"),
    }
    logger.info(
        "Claude call complete",
        extra={
            "model": CLAUDE_MODEL,
            "inputTokens": result["inputTokens"],
            "outputTokens": result["outputTokens"],
            "stopReason": result["stopReason"],
        },
    )
    return result
