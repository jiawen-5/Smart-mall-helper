"""Skill 共用的 LLM 调用封装（DeepSeek）。

设计原则：所有 Skill 在无 API Key / 调用失败时都必须能降级返回兜底结果，
因此这里统一返回 None 而不是抛异常，由各 Skill 自己决定兜底话术。
"""
import json
import re

import httpx

from ..config import settings


async def llm_chat(
    messages: list[dict],
    *,
    temperature: float = 0.7,
    max_tokens: int = 900,
) -> str | None:
    """调用 DeepSeek 对话补全，失败返回 None。"""
    if not settings.deepseek_api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=45) as c:
            r = await c.post(
                settings.deepseek_api_url,
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                json={
                    "model": "deepseek-chat",
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "messages": messages,
                },
            )
            if r.status_code != 200:
                return None
            return r.json()["choices"][0]["message"]["content"]
    except Exception:
        return None


def extract_json(text: str | None):
    """从 LLM 回复里提取 JSON（容忍 ```json 代码块与前后废话），失败返回 None。"""
    if not text:
        return None
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = raw.find(opener)
        end = raw.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except Exception:
                continue
    return None
