"""Agent 路由：意图识别 -> Skill 查数（代码计算） -> LLM 只做语言整理.

Skill 1（product_metrics）工作流：
  用户问题 -> matcher 判断意图 -> resolve_products/parse_time_range 提参
  -> SQL 查库 -> Python 算销量/GMV/转化率/环比/同比 -> JSON
  -> DeepSeek 整理成自然语言（数字以 JSON 为准，不许改）。
"""
import re

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..config import settings
from ..skills import SKILLS

router = APIRouter(prefix="/api/agent", tags=["agent"])


class AskIn(BaseModel):
    question: str
    platform: str | None = None


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


@router.post("/ask")
async def ask(body: AskIn, db: Session = Depends(get_db)):
    for s in SKILLS:
        if s["matcher"](body.question):
            data = s["run"](db, body.question, body.platform)
            concise = bool(re.search(r"(只返回|只要|仅返回|只告诉我|只显示|只给)", body.question or ""))
            if concise:
                # 用户明确只要一个数：直接返回模板结果，不经过 LLM，防止加戏
                return {"skill": s["name"], "answer": template_answer(data, body.question), "data": data}
            polished = await llm_polish(body.question, data)
            return {"skill": s["name"], "answer": polished or template_answer(data, body.question), "data": data}
    # 非 skill 问题：返回全站概况
    sales = db.query(func.coalesce(func.sum(models.Order.total_amount), 0)).scalar() or 0
    orders = db.query(func.count(models.Order.order_id)).scalar() or 0
    return {
        "skill": None,
        "answer": f"当前共 {orders} 笔订单，累计 GMV ¥{float(sales):,.2f}。（问题：{body.question}）",
        "data": {"orders": orders, "gmv": float(sales)},
    }


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
