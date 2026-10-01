"""上下文 token 预算：前后端同口径的唯一实现。

估算口径（与前端 contextBudget.ts 一致）：中文 1 字 ≈ 2 token，英文 1 词 ≈ 1 token，
每条消息 +4 token 开销。从最新往前累加，超预算即停，丢弃更早消息；
单条超预算则截断头部只保留尾部。单条另有字符上限，防止一条超长粘贴吃掉全部预算。
"""
import re

CONTEXT_BUDGET = 2000
PER_MESSAGE_CHAR_CAP = 800

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\uff00-\uffef]")


def estimate_tokens(text: str) -> int:
    s = text or ""
    cjk = len(_CJK_RE.findall(s))
    rest = _CJK_RE.sub(" ", s)
    words = [w for w in re.split(r"[\s,，、；;|/\\？?！!：:。.\"'“”‘’（）()\[\]{}<>~`@#$%^&*+=_-]+", rest) if w]
    en = sum(1 if re.search(r"[A-Za-z0-9]", w) else -(-len(w) // 4) for w in words)
    return cjk * 2 + en


def _truncate_head(content: str, budget: int) -> str:
    lo, hi = 0, len(content)
    while lo < hi:
        mid = (lo + hi) // 2
        if estimate_tokens(content[mid:]) + 4 <= budget:
            hi = mid
        else:
            lo = mid + 1
    return content[lo:]


def trim_history(
    history: list[dict] | None,
    budget: int = CONTEXT_BUDGET,
    per_msg_cap: int = PER_MESSAGE_CHAR_CAP,
) -> list[dict]:
    clean = []
    for h in history or []:
        if not isinstance(h, dict):
            continue
        content = (h.get("content") or "").strip()
        if not content:
            continue
        role = h.get("role", "user")
        if role not in ("user", "assistant"):
            role = "user"
        # 单条先截断：超长粘贴只保留尾部 per_msg_cap 字
        if len(content) > per_msg_cap:
            content = content[-per_msg_cap:]
        clean.append({"role": role, "content": content})
    kept: list[dict] = []
    used = 0
    for h in reversed(clean):
        cost = estimate_tokens(h["content"]) + 4
        if kept and used + cost > budget:
            break
        if not kept and cost > budget:
            # 最新一条就超预算：截断头部只保留尾部能装下的部分
            kept.insert(0, {"role": h["role"], "content": _truncate_head(h["content"], budget)})
            break
        kept.insert(0, h)
        used += cost
        if used >= budget:
            break
    return kept
