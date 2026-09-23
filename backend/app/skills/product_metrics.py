"""Skill 1：商品与核心指标查询.

职责边界（防幻觉）：
- 所有数值（销量/GMV/转化率/环比/同比）全部由本模块 SQL + Python 算出；
- 大模型只负责把本模块返回的 JSON 翻译成自然语言，禁止改动任何数字。
"""
import re
from datetime import datetime, timedelta, date
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from .. import models

# ---------- 1. 意图识别 ----------

_INTENT_RE = re.compile(
    r"(销量|销售额|销售总额|销售总|总额|gmv|营业额|转化率|库存|价格|标价|品牌|品类|sku|对比|环比|同比|"
    r"卖了多少|卖得|滞销|热销|爆款|查询|查一下|什么价|多少钱|哪个规格|有多少|"
    r"总销售额|总订单|订单数|订单量|成交额|成交量|平台.*销|销.*平台)",
    re.IGNORECASE,
)
_PRODUCT_HINT_RE = re.compile(r"(商品|产品|货|单品|SKU|sku|款|牌)")

# 平台别名：问句里的中文名 -> platform.code
PLATFORM_ALIASES = {
    "抖音": "douyin",
    "淘宝": "taobao",
    "天猫": "taobao",
    "京东": "jd",
    "拼多多": "pinduoduo",
    "douyin": "douyin",
    "taobao": "taobao",
    "tmall": "taobao",
    "jd": "jd",
    "pinduoduo": "pinduoduo",
    "pdd": "pinduoduo",
}

# 平台级汇总意图：没提具体商品、只问平台/全站总数
_AGG_RE = re.compile(r"(总销售额|销售总额|销售总|总额|总订单|订单数|订单量|成交额|成交量|一共卖|总共卖|平台.*(销|订单)|全站|所有平台)")


def detect_platform(question: str, explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    q = question or ""
    for alias, code in PLATFORM_ALIASES.items():
        if alias in q or alias.lower() in q.lower():
            return code
    return None


# 生成/创意类任务词：命中即视为普通对话，不进查数 Skill（避免“帮我优化商品标题”误判）
_CREATIVE_RE = re.compile(
    r"(优化标题|生成文案|写一段|写个|取个名|起个名|帮(我)?(优化|改写|生成|起|写)|文案|"
    r"标题优化|营销方案|活动策划|客服话术|回复一下|润色|扩写|续写|翻译|总结一下这篇文章)",
    re.IGNORECASE,
)


def looks_like_product_query(question: str) -> bool:
    q = question or ""
    if not q:
        return False
    # 创意/生成类指令优先放行，不进入查数 Skill
    if _CREATIVE_RE.search(q):
        return False
    # 命中指标词，或（提到商品词且至少有一串有效字符）视为查询
    return bool(_INTENT_RE.search(q) or (_PRODUCT_HINT_RE.search(q) and re.search(r"[一-鿿A-Za-z0-9]{2,}", q)))


# ---------- 2. 参数提取 ----------

# 中文数字 -> 阿拉伯数字（近七天 / 最近三十天 这类写法）
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
           "两": 2, "半": 0.5}


def _cn_to_int(s: str) -> int | None:
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s in _CN_NUM and isinstance(_CN_NUM[s], int):
        return _CN_NUM[s]  # type: ignore[return-value]
    # 十几 / 几十 / 几十几
    if "十" in s:
        try:
            left, _, right = s.partition("十")
            tens = 1 if left in ("", "一") else _CN_NUM.get(left, 0)
            ones = 0 if not right else _CN_NUM.get(right, 0)
            if isinstance(tens, int) and isinstance(ones, int) and (tens or ones):
                return tens * 10 + ones
        except Exception:
            return None
    return None


_RANGE_RE = re.compile(r"近\s*([0-9一二三四五六七八九十两半]+)\s*天|最近\s*([0-9一二三四五六七八九十两半]+)\s*天")
_DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_STOPWORDS = set("的了呢吗啊吧我你他她它这那是个在和与或要查一下看对比环比同比近最天销数据商品产品信息基础多少卖了得如何怎么样GMV销售额营业额转化率库存价格标价品牌品类SKU款单号订单时间范围 multi".split())


def parse_time_range(question: str) -> tuple[datetime, datetime, str]:
    """返回 (start, end, label)。支持 今天/昨天/本周/本月/近N天/明确日期区间，默认近30天。"""
    now = datetime.now()
    q = question or ""
    if "今天" in q or "今日" in q:
        s = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return s, now, "今天"
    if "昨天" in q or "昨日" in q:
        y = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return y, y + timedelta(days=1) - timedelta(seconds=1), "昨天"
    if "本周" in q or "这周" in q:
        s = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return s, now, "本周"
    if "本月" in q or "这个月" in q:
        s = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return s, now, "本月"
    m = _RANGE_RE.search(q)
    if m:
        n = _cn_to_int(m.group(1) or m.group(2) or "")
        if n:
            n = max(1, min(int(n), 365))
            return now - timedelta(days=n), now, f"近{n}天"
    dates = _DATE_RE.findall(question or "")
    if dates:
        try:
            pts = sorted(datetime(int(a), int(b), int(c)) for a, b, c in dates)
            s = pts[0]
            if len(pts) >= 2:
                e = pts[-1] + timedelta(days=1) - timedelta(seconds=1)
                return s, e, f"{pts[0]:%Y-%m-%d}~{pts[-1]:%Y-%m-%d}"
            return s, s + timedelta(days=1) - timedelta(seconds=1), f"{pts[0]:%Y-%m-%d}"
        except ValueError:
            pass
    return now - timedelta(days=30), now, "近30天"


def _tokens(question: str) -> list[str]:
    q = re.sub(r"https?://\S+|\d{4}-\d{1,2}-\d{1,2}|近\s*[0-9一二三四五六七八九十两半]+\s*天|最近\s*[0-9一二三四五六七八九十两半]+\s*天", " ", question or "")
    parts = [t for t in re.split(r"[\s,，、；;|/\\？?！!：:。\.。\"'“”‘’（）\(\)\[\]]+", q) if t]
    out: list[str] = []
    for p in parts:
        p = p.strip("的了呢吗啊吧")
        if len(p) >= 2 and p not in _STOPWORDS and not _INTENT_RE.fullmatch(p):
            out.append(p)
    return out[:8]


def resolve_products(db: Session, question: str, platform: str | None, limit: int = 5):
    """按 ID 精确匹配优先，其次按名称/品牌/品类模糊匹配。返回 (products, matched_by)。"""
    q = (question or "").strip()
    # 1) 精确 ID
    exact = (
        db.query(models.Product)
        .filter(or_(models.Product.global_product_id == q, models.Product.platform_product_id == q))
        .first()
    )
    if exact:
        return [exact], "id"
    # 2) token 模糊匹配
    scored: dict[str, object] = {}
    for tok in _tokens(q):
        rows = (
            db.query(models.Product)
            .filter(
                or_(
                    models.Product.product_name.like(f"%{tok}%"),
                    models.Product.platform_product_id.like(f"%{tok}%"),
                    models.Product.brand.like(f"%{tok}%"),
                    models.Product.category.like(f"%{tok}%"),
                )
            )
            .limit(10)
            .all()
        )
        if platform:
            rows = [r for r in rows if r.platform == platform]
        for r in rows:
            scored[r.global_product_id] = r
        if len(scored) >= limit:
            break
    return list(scored.values())[:limit], "fuzzy"


# ---------- 3. 指标计算（全部由代码算） ----------

def _period_agg(db: Session, product_id: str, start: datetime, end: datetime, platform: str | None):
    """单个商品单个周期：销量/订单数/GMV。时间以 order.order_time 为准。"""
    q = (
        db.query(
            func.coalesce(func.sum(models.OrderItem.quantity), 0),
            func.coalesce(func.sum(models.OrderItem.item_total), 0),
            func.count(func.distinct(models.OrderItem.order_id)),
        )
        .join(models.Order, models.OrderItem.order_id == models.Order.order_id)
        .filter(
            models.OrderItem.global_product_id == product_id,
            models.Order.order_time >= start,
            models.Order.order_time <= end,
        )
    )
    if platform:
        q = q.filter(models.Order.platform == platform)
    qty, gmv, orders = q.one()
    pv = (
        db.query(func.count(models.UserBehavior.behavior_id))
        .filter(
            models.UserBehavior.global_product_id == product_id,
            models.UserBehavior.behavior_time >= start,
            models.UserBehavior.behavior_time <= end,
            models.UserBehavior.behavior_type.in_(["浏览", "view", "pv", "visit"]),
        )
        .scalar()
        or 0
    )
    if platform:
        pv = (
            db.query(func.count(models.UserBehavior.behavior_id))
            .filter(
                models.UserBehavior.global_product_id == product_id,
                models.UserBehavior.behavior_time >= start,
                models.UserBehavior.behavior_time <= end,
                models.UserBehavior.behavior_type.in_(["浏览", "view", "pv", "visit"]),
                models.UserBehavior.platform == platform,
            )
            .scalar()
            or 0
        )
    qty, orders, pv = int(qty or 0), int(orders or 0), int(pv or 0)
    gmv = float(gmv or 0)
    conversion = round(orders / pv * 100, 2) if pv else None
    avg_price = round(gmv / qty, 2) if qty else None
    return {"qty": qty, "gmv": round(gmv, 2), "orders": orders, "pv": pv, "conversion_pct": conversion, "avg_price": avg_price}


def _rate(cur: float, base: float | None):
    if base is None or base == 0:
        return None
    return round((cur - base) / abs(base) * 100, 2)


def _order_totals(db: Session, start: datetime, end: datetime, platform: str | None):
    """平台/全站级汇总：GMV + 订单数（直接按 order 表聚合，不依赖商品匹配）。"""
    q = db.query(
        func.coalesce(func.sum(models.Order.total_amount), 0),
        func.count(models.Order.order_id),
    ).filter(models.Order.order_time >= start, models.Order.order_time <= end)
    if platform:
        q = q.filter(models.Order.platform == platform)
    gmv, orders = q.one()
    return {"gmv": round(float(gmv or 0), 2), "orders": int(orders or 0)}


def run(db: Session, question: str, platform: str | None = None) -> dict:
    """Skill 主入口：返回可直接给 LLM 做语言整理的 JSON。"""
    start, end, label = parse_time_range(question)
    platform = detect_platform(question, platform)
    span_days = max((end - start).days or 1, 1)
    prev_start, prev_end = start - timedelta(days=span_days), start - timedelta(seconds=1)
    try:
        yoy_start, yoy_end = start.replace(year=start.year - 1), end.replace(year=end.year - 1)
    except ValueError:
        yoy_start = yoy_end = None

    products, matched_by = resolve_products(db, question, platform)
    if not products:
        # 全站/平台级汇总兜底：没能匹配到具体商品时，一律按 order 表聚合全站（或指定平台）指标。
        # 无论问的是“本月GMV”“近7天销售额”“全站成交额”等，只要进入了 Skill 且没提具体商品，
        # 就返回汇总结果，避免漏判为“没匹配到商品”。
        cur = _order_totals(db, start, end, platform)
        prev = _order_totals(db, prev_start, prev_end, platform)
        scope = f"{platform}平台" if platform else "全站"
        return {
            "skill": "product_metrics",
            "matched": True,
            "matched_by": "platform_total",
            "time_range": {"label": label, "start": start.strftime("%Y-%m-%d %H:%M"), "end": end.strftime("%Y-%m-%d %H:%M")},
            "platform": platform,
            "items": [],
            "total": {
                "scope": scope,
                "gmv": cur["gmv"],
                "orders": cur["orders"],
                "wow_pct": {"gmv": _rate(cur["gmv"], prev["gmv"]), "orders": _rate(cur["orders"], prev["orders"])},
            },
            "notes": "平台级总销售额=order.total_amount求和；环比=与上一等长周期对比。",
        }

    items = []
    for p in products:
        cur = _period_agg(db, p.global_product_id, start, end, platform)
        prev = _period_agg(db, p.global_product_id, prev_start, prev_end, platform)
        yoy = _period_agg(db, p.global_product_id, yoy_start, yoy_end, platform) if yoy_start else None
        items.append(
            {
                "global_product_id": p.global_product_id,
                "platform_product_id": p.platform_product_id,
                "product_name": p.product_name,
                "category": p.category,
                "brand": p.brand,
                "price": float(p.price) if p.price is not None else None,
                "stock_status": p.stock_status,
                "current": cur,
                "wow_pct": {"qty": _rate(cur["qty"], prev["qty"]), "gmv": _rate(cur["gmv"], prev["gmv"])},
                "yoy_pct": {"qty": _rate(cur["qty"], yoy["qty"]), "gmv": _rate(cur["gmv"], yoy["gmv"])} if yoy else None,
            }
        )
    items.sort(key=lambda x: x["current"]["gmv"], reverse=True)
    total_gmv = round(sum(i["current"]["gmv"] for i in items), 2)
    total_qty = sum(i["current"]["qty"] for i in items)
    return {
        "skill": "product_metrics",
        "matched": True,
        "matched_by": matched_by,
        "time_range": {
            "label": label,
            "start": start.strftime("%Y-%m-%d %H:%M"),
            "end": end.strftime("%Y-%m-%d %H:%M"),
            "prev": f"{prev_start.strftime('%Y-%m-%d')}~{prev_end.strftime('%Y-%m-%d')}",
        },
        "platform": platform,
        "items": items,
        "compare": {
            "count": len(items),
            "total_gmv": total_gmv,
            "total_qty": total_qty,
            "top_by_gmv": items[0]["product_name"] if items else None,
        },
        "notes": "转化率=订单数/商品浏览PV；环比=与上一等长周期对比；同比=与去年同期对比（无去年数据则为null）。",
    }
