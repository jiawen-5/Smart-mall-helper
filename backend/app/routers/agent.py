"""Agent 路由：意图识别 -> Skill 执行 -> （可选）LLM 语言整理.

Skill 1 product_metrics ：查数，数值全部由代码计算，LLM 只做语言整理
Skill 2 copywriting     ：文案创意，LLM 产出草稿 + 代码做极限词校验
Skill 3 customer_service：客服回复，FAQ 优先命中免 LLM，输出前敏感词过滤
"""
import asyncio
import inspect
import json
import re

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..config import settings
from ..skills import SKILLS
from ..skills.copywriting import parse_fields as _parse_copy_fields

router = APIRouter(prefix="/api/agent", tags=["agent"])


class AskIn(BaseModel):
    question: str
    platform: str | None = None
    # Skill 2 文案参数
    style: str | None = None
    variants: int = 3
    length: int | None = None
    regenerate: bool = False
    avoid: list[str] | None = None
    # Skill 3 客服参数
    order_id: str | None = None
    history: list[dict] | None = None


def _skill_kwargs(body: AskIn) -> dict:
    """把请求里 Skill 2/3 用到的可选参数透传给 Skill（各 Skill 自行忽略无关项）。"""
    return {
        "style": body.style,
        "variants": body.variants,
        "length": body.length,
        "regenerate": body.regenerate,
        "avoid": body.avoid,
        "order_id": body.order_id,
        "history": body.history,
    }


def _fmt_pct(v) -> str:
    if v is None:
        return "暂无对比数据"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v}%"


def _concise_metric(question: str) -> str:
    """用户说只返回某指标时，识别是哪个：gmv / qty / orders / conversion，默认 gmv。"""
    q = question or ""
    if re.search(r"(销量|卖了多少|件数)", q):
        return "qty"
    if re.search(r"(订单)", q):
        return "orders"
    if re.search(r"(转化率)", q):
        return "conversion"
    return "gmv"


def template_answer(data: dict, question: str = "") -> str:
    """无 LLM 可用时的兜底话术：纯模板拼接 JSON 中的数字。"""
    concise = bool(re.search(r"(只返回|只要|仅返回|只告诉我|只显示|只给)", question or ""))
    if concise:
        metric = _concise_metric(question)
        tr = data["time_range"]
        if data.get("total"):
            t = data["total"]
            val = {"gmv": f"¥{t['gmv']:,.2f}", "orders": f"{t['orders']} 笔"}.get(metric, f"¥{t['gmv']:,.2f}")
            return f"{tr['label']}{t['scope']}：{val}"
        if data.get("matched") and data.get("items"):
            lines = []
            for it in data["items"]:
                c = it["current"]
                val = {
                    "gmv": f"¥{c['gmv']:,.2f}",
                    "qty": f"{c['qty']} 件",
                    "orders": f"{c['orders']} 笔",
                    "conversion": f"{c['conversion_pct']}%" if c["conversion_pct"] is not None else "无数据",
                }[metric]
                lines.append(f"{it['product_name']}：{val}")
            return f"{tr['label']}：" + "；".join(lines)
    if data.get("total") and not data.get("items"):
        t = data["total"]
        tr = data["time_range"]
        return (
            f"{tr['label']}{t['scope']}销售总额：¥{t['gmv']:,.2f}，"
            f"订单 {t['orders']} 笔，环比GMV {_fmt_pct(t['wow_pct']['gmv'])}。"
        )
    if not data.get("matched"):
        return f"在{data['time_range']['label']}内没有匹配到相关商品。{data.get('hint','')}"
    tr = data["time_range"]
    if data.get("matched_by") == "platform_total":
        t = data["total"]
        return (
            f"【{t['scope']}{tr['label']}汇总（{tr['start']} ~ {tr['end']}）】\n"
            f"· 总销售额（GMV）：¥{t['gmv']:,.2f}，环比 {_fmt_pct(t['wow_pct']['gmv'])}；\n"
            f"· 总订单数：{t['orders']} 笔，环比 {_fmt_pct(t['wow_pct']['orders'])}。"
        )
    tr = data["time_range"]
    lines = [f"【{tr['label']}（{tr['start']} ~ {tr['end']}）指标】"]
    for it in data["items"]:
        c, w = it["current"], it["wow_pct"]
        conv = f"{c['conversion_pct']}%" if c["conversion_pct"] is not None else "无浏览数据"
        lines.append(
            f"· {it['product_name']}（{it['global_product_id']}）：销量 {c['qty']} 件，"
            f"GMV ¥{c['gmv']:,.2f}，订单 {c['orders']} 笔，转化率 {conv}，"
            f"环比销量 {_fmt_pct(w['qty'])}、环比GMV {_fmt_pct(w['gmv'])}。"
        )
    if data["compare"]["count"] > 1:
        lines.append(
            f"对比结论：共 {data['compare']['count']} 个商品，合计 GMV ¥{data['compare']['total_gmv']:,.2f}，"
            f"GMV 最高的是「{data['compare']['top_by_gmv']}」。"
        )
    return "\n".join(lines)


async def llm_polish(question: str, data: dict) -> str | None:
    """调用 DeepSeek 做语言整理；失败返回 None 由模板兜底。"""
    if not settings.deepseek_api_key:
        return None
    concise_rule = (
        "用户要求只返回销售总额，因此你的回答只能有一行：时间范围+范围+销售总额数字，"
        "不许加环比、订单数、结论等任何多余内容。"
        if re.search(r"(只返回|只要|仅返回|只告诉我)", question or "")
        else "最后给1-2句对比结论。"
    )
    sys = (
        "你是电商数据分析助手。请把 <DATA> 中的结构化指标整理成简洁中文回答："
        "若 DATA 有 total 字段（平台/全站汇总），直接报总销售额和总订单数及环比；"
        "若有 items 数组，保留每个商品的销量/GMV/订单数/转化率/环比数字，原样引用；"
        "不得编造、不得四舍五入改动任何数字；null 值就说暂无对比数据；"
        f"{concise_rule}不要输出JSON。"
    )
    try:
        async with httpx.AsyncClient(timeout=25) as c:
            r = await c.post(
                settings.deepseek_api_url,
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                json={
                    "model": "deepseek-chat",
                    "temperature": 0.3,
                    "messages": [
                        {"role": "system", "content": sys},
                        {"role": "user", "content": f"问题：{question}\n<DATA>{data}</DATA>"},
                    ],
                },
            )
            if r.status_code != 200:
                return None
            return r.json()["choices"][0]["message"]["content"]
    except Exception:
        return None


def format_copywriting_answer(data: dict, question: str = "") -> str:
    """把文案 Skill 的 JSON 整理成文本，按需输出：用户要什么给什么。

    fields 来自 Skill params（parse_fields 解析标题/卖点/口播意图），
    只要标题就只列标题，不多带卖点/口播。
    """
    params = data.get("params") or {}
    versions = data.get("versions") or []
    fields = params.get("fields") or ["title", "selling_points", "script"]
    if question:
        try:
            q_fields = _parse_copy_fields(question)
            if q_fields != ["title", "selling_points", "script"]:
                fields = q_fields
        except Exception:
            pass
    only_title = fields == ["title"]
    only_script = fields == ["script"]
    if only_script:
        # 短文案按需输出：一条一行，不套标题/卖点/口播模板
        lines = [f"【短文案 · {params.get('length', {}).get('label', '')} · 共 {len(versions)} 条】"]
        for i, v in enumerate(versions, 1):
            text = (v.get("script") or v.get("title") or "").strip()
            lines.append(f"{i}. {text}")
            if v.get("compliant") is False:
                words = "、".join(h.get("word", "") for h in (v.get("violations") or []))
                lines.append(f"   ⚠️ 含极限词 {words}，建议改用：{(v.get('sanitized') or {}).get('script') or ''}")
        return "\n".join(lines)
    head = (
        f"【{params.get('platform_name', '')} · {params.get('style', '')}风格 · "
        f"{params.get('length', {}).get('label', '')} · 共 {len(versions)} 套】"
    )
    lines = [head]
    for v in versions:
        lines.append("")
        lines.append(f"方案 {v.get('index')}｜{v.get('angle')}")
        if "title" in fields:
            lines.append(f"标题：{v.get('title')}")
        if "selling_points" in fields and v.get("selling_points"):
            lines.append("卖点：" + "；".join(v["selling_points"]))
        if "script" in fields:
            lines.append(f"口播：{v.get('script')}")
        if v.get("compliant") is False:
            words = "、".join(h.get("word", "") for h in (v.get("violations") or []))
            lines.append(f"⚠️ 检测到广告极限词：{words}（该方案已附合规改写版，建议采用整改文本）")
    if (data.get("compliance") or {}).get("passed") and not only_title:
        lines.append("")
        lines.append("✅ 全部方案已通过广告法极限词校验。")
    if data.get("source") == "fallback":
        lines.append("（当前为规则兜底文案，配置 LLM 后可获得更丰富的创意版本）")
    return "\n".join(lines)


def format_customer_service_answer(data: dict) -> str:
    """客服 Skill 的 answer 已是最终话术，这里补一行来源说明。"""
    source = "本地 FAQ 知识库直答（未调用大模型）" if data.get("source") == "faq" else "AI 结合订单/商品上下文生成"
    tail = f"\n\n—— 来源：{source} · 场景：{data.get('scene', '通用咨询')}"
    comp = data.get("compliance") or {}
    if comp.get("sensitive_hits"):
        tail += f" · 已过滤敏感词 {len(comp['sensitive_hits'])} 处"
    return f"{data.get('answer', '')}{tail}"


async def _run_skill(skill: dict, body: "AskIn", db: Session) -> dict:
    """执行 Skill：按函数签名过滤参数，并兼容同步/异步实现。"""
    fn = skill["run"]
    kwargs = _skill_kwargs(body)
    try:
        accepted = set(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        accepted = set(kwargs)
    result = fn(db, body.question, body.platform, **{k: v for k, v in kwargs.items() if k in accepted})
    if inspect.isawaitable(result):
        result = await result
    return result


@router.post("/ask")
async def ask(body: AskIn, db: Session = Depends(get_db)):
    skill_name, answer, data = await _build_answer(body, db)
    if skill_name is None:
        return {"skill": None, "answer": answer, "data": data}
    return {"skill": skill_name, "answer": answer, "data": data}


@router.post("/ask/stream")
async def ask_stream(body: AskIn, db: Session = Depends(get_db)):
    """Skill 流式接口：先发 meta 事件，再按字符分片发 delta 事件，最后发 done。

    前端用 fetch 读 SSE：`data: {...}\\n\\n`，其中 delta 事件为
    `{"delta": "文本片段"}`，done 事件为 `{"done": true, "skill": ..., "data": ...}`。
    这样文案 / 客服等 polish=False 的 Skill 也能逐字输出，不再一次性返回。
    """

    async def gen():
        skill_name, answer, data = await _build_answer(body, db)
        yield f"data: {json.dumps({'skill': skill_name}, ensure_ascii=False)}\n\n"
        chunk_size = 12
        for i in range(0, len(answer), chunk_size):
            yield f"data: {json.dumps({'delta': answer[i:i + chunk_size]}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.015)
        yield f"data: {json.dumps({'done': True, 'skill': skill_name, 'data': data}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


async def _build_answer(body: "AskIn", db: Session) -> tuple:
    """统一构建 Skill 回答：返回 (skill_name, answer, data)，供 /ask 与 /ask/stream 共用。"""
    for s in SKILLS:
        if not s["matcher"](body.question):
            continue

        data = await _run_skill(s, body, db)

        # 查数类（polish=True）：数值由代码算好，LLM 只做语言整理
        if s.get("polish"):
            concise = bool(re.search(r"(只返回|只要|仅返回|只告诉我|只显示|只给)", body.question or ""))
            if concise:
                # 用户明确只要一个数：直接返回模板结果，不经过 LLM，防止加戏
                return (s["name"], template_answer(data, body.question), data)
            polished = await llm_polish(body.question, data)
            return (s["name"], polished or template_answer(data, body.question), data)

        # 文案 / 客服类（polish=False）：Skill 自己已产出最终话术，代码整理即可，不再多花一次 LLM
        if s["name"] == "copywriting":
            answer = format_copywriting_answer(data, body.question)
        else:
            answer = format_customer_service_answer(data)
        return (s["name"], answer, data)

    # 非 skill 问题：返回全站概况
    sales = db.query(func.coalesce(func.sum(models.Order.total_amount), 0)).scalar() or 0
    orders = db.query(func.count(models.Order.order_id)).scalar() or 0
    answer = f"当前共 {orders} 笔订单，累计 GMV ¥{float(sales):,.2f}。（问题：{body.question}）"
    return (None, answer, {"orders": orders, "gmv": float(sales)})


@router.get("/skill/product-metrics")
def skill_product_metrics(
    q: str = "",
    product_id: str | None = None,
    platform: str | None = None,
    db: Session = Depends(get_db),
):
    """结构化直调接口（给前端精确查询/调试用）：返回纯 JSON，不经过 LLM。"""
    from ..skills.product_metrics import run

    question = f"{q} {product_id or ''}".strip() or (product_id or "")
    data = run(db, question or "近30天销量", platform)
    if product_id and data.get("matched"):
        data["items"] = [i for i in data["items"] if i["global_product_id"] == product_id] or data["items"]
    return data


class CopywritingIn(BaseModel):
    question: str = ""
    product_name: str | None = None
    platform: str | None = None
    style: str | None = None  # 简约 / 种草 / 直播风
    variants: int = 3
    length: int | None = None
    regenerate: bool = False
    avoid: list[str] | None = None
    fields: list[str] | None = None  # 如 ["title"]：只要标题就只返回标题


@router.post("/skill/copywriting")
async def skill_copywriting(body: CopywritingIn, db: Session = Depends(get_db)):
    """Skill 2 结构化直调：返回多套文案 JSON（含极限词校验结果）。"""
    from ..skills.copywriting import run

    question = (body.question or "").strip() or (body.product_name or "").strip()
    return await run(
        db,
        question,
        body.platform,
        style=body.style,
        variants=body.variants,
        length=body.length,
        regenerate=body.regenerate,
        avoid=body.avoid,
        fields=body.fields,
    )


class CustomerServiceIn(BaseModel):
    question: str
    platform: str | None = None
    order_id: str | None = None
    product_name: str | None = None
    history: list[dict] | None = None


@router.post("/skill/customer-service")
async def skill_customer_service(body: CustomerServiceIn, db: Session = Depends(get_db)):
    """Skill 3 结构化直调：FAQ 命中直接返回标准答案，否则走 LLM。"""
    from ..skills.customer_service import run

    return await run(
        db,
        body.question,
        body.platform,
        order_id=body.order_id,
        history=body.history,
        product_name=body.product_name,
    )


@router.get("/faq")
def faq_list(category: str | None = None):
    """FAQ 知识库列表（前端展示 / 调试用）。"""
    from ..skills.faq import list_faq

    return list_faq(category)
