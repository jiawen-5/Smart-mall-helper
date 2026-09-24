"""Skill 3：客服回复.

职责边界：
- FAQ 命中直接返回标准答案，不调用 LLM（省成本、答案稳定）；
- 未命中才把「商品 + 订单」上下文交给 LLM 生成话术；
- 输出前统一过敏感词过滤，话术模板与场景由代码控制。

工作流：
  意图识别 -> 提取参数（订单号/问题）-> 优先检索本地 FAQ
  -> 命中：直接返回标准答案；未命中：拼上下文调 LLM
  -> 敏感词过滤 -> 输出话术
"""
import re

from sqlalchemy.orm import Session

from .. import models
from . import compliance, faq
from .llm import llm_chat

# ---------- 1. 意图识别 ----------

_INTENT_RE = re.compile(
    r"(客服|售后|退货|退款|换货|发货|物流|快递|缺货|补货|发票|运费|邮费|包邮|尺码|尺寸|"
    r"多久到|什么时候发|怎么退|申请退|破损|漏发|少发|错发|发错|签收|拒收|投诉|价保|降价|"
    r"常见问题|faq|买家问|客户问|买家说|回复买家|回复客户|回复一下买家|话术|催发货|催件|"
    r"能不能退|可以退|能不能换|怎么处理|售后处理|售后话术)",
    re.IGNORECASE,
)


def looks_like_customer_service_query(question: str) -> bool:
    return bool(_INTENT_RE.search(question or ""))


# ---------- 2. 参数提取 ----------

_ORDER_ID_RE = re.compile(
    r"(?:订单号|订单|order[_ ]?id)\s*[:：]?\s*([A-Za-z0-9\-_]{6,40})",
    re.IGNORECASE,
)
_ORDER_ID_BARE_RE = re.compile(r"\b([A-Z]{2,4}[-_]?\d{8,20}|\d{12,24})\b")


def extract_order_id(question: str, explicit: str | None = None) -> str | None:
    if explicit:
        return explicit.strip()
    q = question or ""
    m = _ORDER_ID_RE.search(q)
    if m:
        return m.group(1)
    m = _ORDER_ID_BARE_RE.search(q)
    return m.group(1) if m else None


_SCENE_RULES = [
    (r"(催|还没发|未发货|延迟|超时)", "发货延迟"),
    (r"(退货|退款|怎么退|申请退|不要了)", "退换货"),
    (r"(换货|换一个|换码|换颜色)", "换货"),
    (r"(缺货|没货|断货|补货)", "缺货"),
    (r"(物流|快递|运单|到哪|没更新|没收到|未收到|收不到|没到货)", "物流查询"),
    (r"(破损|坏了|碎了|压坏)", "商品破损"),
    (r"(漏发|少发|少件)", "漏发少发"),
    (r"(发错|错发|不是我要)", "错发"),
    (r"(发票|开票)", "发票"),
    (r"(尺码|尺寸|多大|偏大|偏小)", "尺码咨询"),
    (r"(材质|成分|面料|参数|规格)", "商品咨询"),
    (r"(优惠|券|折扣|活动)", "优惠活动"),
    (r"(价保|降价|买贵)", "价保"),
    (r"(支付|付款|花呗|分期)", "支付问题"),
    (r"(取消订单|撤销)", "取消订单"),
]


def detect_scene(question: str) -> str:
    q = question or ""
    for pattern, scene in _SCENE_RULES:
        if re.search(pattern, q):
            return scene
    return "通用咨询"


# ---------- 3. 上下文（订单 + 商品） ----------

def load_order_context(db: Session, order_id: str | None) -> dict | None:
    """查订单 + 明细商品，用于话术里的个性化信息。"""
    if not order_id:
        return None
    order = db.query(models.Order).filter(models.Order.order_id == order_id).first()
    if not order:
        return {"order_id": order_id, "found": False}
    items = db.query(models.OrderItem).filter(models.OrderItem.order_id == order_id).limit(5).all()
    product_ids = [i.global_product_id for i in items if i.global_product_id]
    names = []
    if product_ids:
        rows = db.query(models.Product).filter(models.Product.global_product_id.in_(product_ids)).all()
        names = [p.product_name for p in rows]
    return {
        "order_id": order.order_id,
        "found": True,
        "platform": order.platform,
        "order_status": order.order_status,
        "order_time": order.order_time.strftime("%Y-%m-%d %H:%M") if order.order_time else None,
        "payment_time": order.payment_time.strftime("%Y-%m-%d %H:%M") if order.payment_time else None,
        "payment_method": order.payment_method,
        "shipping_method": order.shipping_method,
        "total_amount": float(order.total_amount) if order.total_amount is not None else None,
        "products": names,
        "item_count": len(items),
    }


def find_product_context(db: Session, question: str) -> dict | None:
    """问题里提到商品时，取一个做话术背景。"""
    tokens = [t for t in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", question or "") if len(t) >= 2][:5]
    for tok in tokens:
        row = (
            db.query(models.Product)
            .filter(models.Product.product_name.like(f"%{tok}%"))
            .first()
        )
        if row:
            return {
                "product_name": row.product_name,
                "category": row.category,
                "brand": row.brand,
                "stock_status": row.stock_status,
            }
    return None


# ---------- 4. LLM 生成 ----------

_SYSTEM = (
    "你是专业、耐心的电商客服。基于给定上下文回答买家问题，要求："
    "1) 先共情致歉（如涉及问题）；2) 给出明确可执行的解决方案与时间承诺；"
    "3) 涉及金额/时间/订单状态时只使用上下文中的真实数据，没有就给通用说明，绝不编造；"
    "4) 不使用极限词与攻击性语言；5) 输出 80-200 字纯文本，不要 Markdown、不要列表符号。"
)


def build_prompt(question: str, scene: str, order_ctx: dict | None, product_ctx: dict | None) -> str:
    lines = [f"【买家问题】{question}", f"【问题场景】{scene}"]
    if order_ctx and order_ctx.get("found"):
        lines += [
            "【订单信息】",
            f"订单号：{order_ctx['order_id']}，状态：{order_ctx['order_status']}",
            f"下单时间：{order_ctx['order_time']}，支付时间：{order_ctx['payment_time']}",
            f"支付方式：{order_ctx['payment_method']}，配送方式：{order_ctx['shipping_method']}",
            f"订单金额：{order_ctx['total_amount']}，商品：{'、'.join(order_ctx['products']) or '—'}",
        ]
    elif order_ctx and not order_ctx.get("found"):
        lines.append(f"【订单信息】用户提供了订单号 {order_ctx['order_id']}，但系统未查到，请引导其核对订单号。")
    if product_ctx:
        lines.append(
            f"【商品信息】{product_ctx.get('product_name')}，品类：{product_ctx.get('category') or '—'}，"
            f"品牌：{product_ctx.get('brand') or '—'}，库存状态：{product_ctx.get('stock_status') or '—'}"
        )
    lines.append("请输出给买家的回复话术。")
    return "\n".join(lines)


def _fallback_answer(scene: str, order_ctx: dict | None) -> str:
    """无 LLM 时的兜底话术模板。"""
    oid = (order_ctx or {}).get("order_id") or "（未提供）"
    templates = {
        "发货延迟": f"非常抱歉让您久等了！订单 {oid} 已为您标记加急，预计 24 小时内发出，发出后会第一时间推送物流单号。",
        "退换货": "您好，支持 7 天无理由退换货。请在订单页点击「申请售后」选择退货原因，审核通过后按提示寄回，我们收到后 1-3 个工作日原路退款。",
        "换货": "您好，签收后 7 天内可申请换货。请在订单页提交「换货」申请并备注需要的规格，审核通过后按提示寄回即可。",
        "缺货": "您好，非常抱歉该商品暂时缺货。我们可为您登记到货提醒、更换其他规格，或直接全额退款，请问您倾向哪种方式？",
        "物流查询": f"您好，订单 {oid} 的物流可在「我的订单 → 查看物流」实时查看。若超过 48 小时未更新，我可帮您向快递公司发起催件。",
        "商品破损": "非常抱歉商品在运输中受损！请提供破损照片，我们为您走「补寄/退款」快速通道，无需寄回，一般当天审核。",
        "漏发少发": "非常抱歉出现漏发！麻烦您拍一下包裹与商品合照，我立即核实出库记录，确认后当天为您补发并承担运费。",
        "错发": "非常抱歉发错商品！请拍照告知收到的款式，我们立即安排正确商品补发，并承担退回运费。",
        "发票": "您好，支持开具电子普通发票与增值税专用发票，请在订单页「申请开票」填写抬头与邮箱，电子发票 1-2 个工作日送达。",
        "尺码咨询": "您好，请提供身高体重，我帮您推荐合适尺码；商品详情页也有尺码对照表可参考，不合适可 7 天内免费换码一次。",
        "优惠活动": "您好，优惠券可在商品页或店铺首页领取，结算时选择可用券自动抵扣。若无法使用，通常是未达门槛或与活动价互斥。",
        "价保": f"您好，支持 7 天价保。请提供订单号 {oid} 与当前价格截图，核实后我们以优惠券或原路退款方式返还差价。",
    }
    return templates.get(
        scene,
        f"您好，感谢您的咨询！关于订单 {oid} 的问题，我们已记录并会尽快为您核实处理，请您稍等，也欢迎补充更多细节以便我们更快解决。",
    )


# ---------- 5. 主入口 ----------

async def run(
    db: Session,
    question: str,
    platform: str | None = None,
    *,
    order_id: str | None = None,
    history: list[dict] | None = None,
    product_name: str | None = None,
) -> dict:
    q = (question or "").strip()
    scene = detect_scene(q)
    oid = extract_order_id(q, order_id)
    order_ctx = load_order_context(db, oid)
    product_ctx = find_product_context(db, q)
    if product_name and not product_ctx:
        product_ctx = {"product_name": product_name}

    # 1) FAQ 优先：命中即免 LLM
    hit = faq.search_faq(q)
    if hit:
        item = hit["item"]
        answer = faq.render_faq_answer(item, order_ctx if order_ctx and order_ctx.get("found") else None)
        masked = compliance.mask_sensitive(answer)
        return {
            "skill": "customer_service",
            "source": "faq",
            "scene": item["category"],
            "answer": masked,
            "faq": {"id": item["id"], "category": item["category"], "question": item["question"], "score": hit["score"]},
            "order": order_ctx,
            "product": product_ctx,
            "compliance": {"sensitive_hits": compliance.scan_sensitive(answer), "passed": not compliance.scan_sensitive(answer)},
            "notes": "命中本地 FAQ 知识库，直接返回标准答案，未调用大模型。",
        }

    # 2) 未命中：交给 LLM
    messages: list[dict] = [{"role": "system", "content": _SYSTEM}]
    for h in (history or [])[-6:]:
        role = h.get("role")
        content = (h.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": build_prompt(q, scene, order_ctx, product_ctx)})

    text = await llm_chat(messages, temperature=0.5, max_tokens=600)
    source = "llm"
    if not text or not text.strip():
        source = "fallback"
        text = _fallback_answer(scene, order_ctx)

    sensitive = compliance.scan_sensitive(text)
    extreme = compliance.scan_extreme(text)
    answer = compliance.mask_sensitive(compliance.sanitize_extreme(text)).strip()

    return {
        "skill": "customer_service",
        "source": source,
        "scene": scene,
        "answer": answer,
        "faq": None,
        "order": order_ctx,
        "product": product_ctx,
        "compliance": {
            "sensitive_hits": sensitive,
            "extreme_words": extreme,
            "passed": not sensitive and not extreme,
        },
        "notes": "FAQ 未命中，已结合订单/商品上下文由大模型生成，并完成敏感词与极限词过滤。",
    }
