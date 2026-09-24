"""电商客服 FAQ 知识库 + 检索（Skill 3 优先匹配，命中即免 LLM 调用）。

每条 FAQ：
  id / category / keywords（命中关键词）/ question（标准问法）/ answer（标准答案模板）
answer 支持占位符：{order_id} {order_status} {order_time} {product_name} {ship_hours}
"""
import re

FAQ_ITEMS: list[dict] = [
    {
        "id": "refund_policy",
        "category": "退换货",
        "keywords": ["七天无理由", "7天无理由", "无理由退货", "可以退吗", "能退吗", "退货政策", "退换货规则"],
        "question": "七天无理由退货政策",
        "answer": "您好，我们支持 7 天无理由退换货：商品签收后 7 天内，在不影响二次销售的前提下可申请退货或换货，运费按平台规则处理。如需申请，请在订单页点击「申请售后」并选择退货原因，我们会在 24 小时内为您审核。",
    },
    {
        "id": "refund_flow",
        "category": "退换货",
        "keywords": ["怎么退货", "如何退货", "申请退货", "退货流程", "退款流程", "怎么申请退款", "退货步骤"],
        "question": "退货退款流程",
        "answer": "您好，退货流程共三步：① 订单页点击「申请售后」→ 选择「退货退款」并填写原因；② 审核通过后按页面提示寄回商品；③ 我们收到并验收后 1-3 个工作日原路退款到账。订单号 {order_id}，我会同步帮您跟进审核进度。",
    },
    {
        "id": "refund_arrival",
        "category": "退换货",
        "keywords": ["退款多久到账", "退款没到", "退款什么时候", "钱没退", "退款进度", "多久退款"],
        "question": "退款到账时间",
        "answer": "您好，退款审核通过后按原支付渠道退回：微信/支付宝通常 1-3 个工作日到账，银行卡 3-7 个工作日，具体以银行处理时间为准。若超过时间仍未到账，请提供订单号，我帮您发起加急查询。",
    },
    {
        "id": "exchange",
        "category": "退换货",
        "keywords": ["换货", "换一个", "换尺码", "换颜色", "想换", "换新"],
        "question": "换货申请",
        "answer": "您好，支持换货服务：在签收后 7 天内、商品不影响二次销售的情况下可申请换同款其他规格/颜色。请在订单页提交「换货」申请，并备注需要的规格，审核通过后按提示寄回即可。",
    },
    {
        "id": "ship_time",
        "category": "发货物流",
        "keywords": ["什么时候发货", "多久发货", "几天发货", "发货时间", "什么时候发", "何时发货"],
        "question": "发货时间",
        "answer": "您好，现货商品在付款后 {ship_hours} 内安排发出，节假日顺延。您订单（{order_id}）当前状态为「{order_status}」，发货后系统会推送物流单号，可在订单页实时查看物流轨迹。",
    },
    {
        "id": "ship_delay",
        "category": "发货物流",
        "keywords": ["还没发货", "发货延迟", "怎么还没发", "超时未发货", "一直不发货", "延迟发货"],
        "question": "发货延迟处理",
        "answer": "非常抱歉让您久等了！订单 {order_id} 因仓库出库高峰出现了延迟，我们已为您标记加急，预计 24 小时内发出。若您不方便等待，也可以直接申请全额退款，我们会优先为您处理，给您带来的不便我们深表歉意。",
    },
    {
        "id": "logistics_track",
        "category": "发货物流",
        "keywords": ["物流信息", "快递到哪", "查快递", "物流不更新", "运单号", "快递单号", "物流查询"],
        "question": "物流查询",
        "answer": "您好，订单 {order_id} 的物流信息可在「我的订单 → 查看物流」中实时查看。如物流超过 48 小时未更新，通常是中转环节扫描延迟，我这边可以帮您向快递公司发起催件查询，请稍等。",
    },
    {
        "id": "out_of_stock",
        "category": "库存缺货",
        "keywords": ["缺货", "没货了", "无货", "补货", "什么时候有货", "断货", "库存不足"],
        "question": "缺货处理",
        "answer": "您好，非常抱歉该商品暂时缺货。您可以选择：① 我们为您登记到货提醒，补货后第一时间通知您；② 更换同价位的其他规格/款式；③ 直接申请全额退款，我们会优先处理。请问您倾向哪种方式？",
    },
    {
        "id": "partial_ship",
        "category": "库存缺货",
        "keywords": ["少发", "漏发", "只收到一件", "少了一件", "漏发商品", "发漏"],
        "question": "漏发少发",
        "answer": "非常抱歉出现漏发！麻烦您拍一下包裹外箱与商品合照发我，我立即为您核实订单 {order_id} 的出库记录。确认漏发后，我们会当天为您补发，并承担全部运费。",
    },
    {
        "id": "damaged",
        "category": "商品质量",
        "keywords": ["破损", "坏了", "碎了", "压坏", "有损坏", "摔坏", "包装破损"],
        "question": "商品破损",
        "answer": "非常抱歉商品在运输中受损！请提供商品破损照片，我为您走「破损补寄/退款」快速通道，无需寄回，一般当天审核、次日安排补发或退款。订单 {order_id} 我已为您标记优先处理。",
    },
    {
        "id": "quality_issue",
        "category": "商品质量",
        "keywords": ["质量问题", "有瑕疵", "做工", "和描述不符", "与图片不符", "色差", "有问题"],
        "question": "质量问题处理",
        "answer": "非常抱歉给您带来不好的体验。请您提供商品实拍图或短视频，我们会为您安排换货或退款；若属于质量问题，来回运费均由我们承担。您也可以直接申请「质量问题退货」，我们会优先审核。",
    },
    {
        "id": "wrong_item",
        "category": "商品质量",
        "keywords": ["发错", "发错了", "不是我要的", "型号不对", "颜色不对", "款式不对", "错发"],
        "question": "错发处理",
        "answer": "非常抱歉发错商品！请您拍照告知收到的款式，我们立即为您安排正确商品补发，并同时提供错发件的退货面单（运费我们承担）。订单 {order_id} 已标记加急，通常 24 小时内发出。",
    },
    {
        "id": "invoice",
        "category": "发票资质",
        "keywords": ["发票", "开票", "电子发票", "专用发票", "增值税", "开发票"],
        "question": "发票申请",
        "answer": "您好，支持开具电子普通发票与增值税专用发票。请在订单页「申请开票」中填写抬头、税号与邮箱，电子发票一般 1-2 个工作日发送至您邮箱；专票需提供完整开票资料，审核后 3-5 个工作日寄出。",
    },
    {
        "id": "shipping_fee",
        "category": "运费配送",
        "keywords": ["运费", "邮费", "包邮", "满多少包邮", "快递费", "要运费吗"],
        "question": "运费与包邮",
        "answer": "您好，单笔订单满额即可享受包邮（具体门槛以商品页标注为准），偏远地区（新疆/西藏/内蒙古等）可能产生额外运费，下单时系统会自动显示实际运费。若您已支付运费但符合包邮条件，我们会在发货后退还差额。",
    },
    {
        "id": "address_change",
        "category": "运费配送",
        "keywords": ["改地址", "修改地址", "地址填错", "换地址", "收货地址改"],
        "question": "修改收货地址",
        "answer": "您好，未发货前可修改收货地址：请把「新地址 + 收件人 + 手机号」发我，我帮您在后台更新。若订单 {order_id} 已发货，可联系快递公司改派或在派送时与快递员沟通，我们也会协助您跟进。",
    },
    {
        "id": "size_guide",
        "category": "商品咨询",
        "keywords": ["尺码", "尺寸", "大小", "偏大偏小", "选多大", "身高体重"],
        "question": "尺码建议",
        "answer": "您好，建议您提供身高体重，我帮您推荐合适尺码；商品详情页也有详细尺码对照表可参考。若收到后尺码不合适，7 天内可免费换码一次（商品不影响二次销售即可）。",
    },
    {
        "id": "material",
        "category": "商品咨询",
        "keywords": ["材质", "成分", "面料", "什么材料", "参数", "规格", "容量"],
        "question": "材质与规格",
        "answer": "您好，该商品的材质、规格与详细参数均已列在商品详情页「规格参数」栏，您也可以告诉我具体想了解的项（如材质/容量/功率），我帮您逐项确认，确保信息准确。",
    },
    {
        "id": "coupon",
        "category": "优惠活动",
        "keywords": ["优惠券", "券", "怎么用券", "优惠", "折扣", "活动价", "领券"],
        "question": "优惠券使用",
        "answer": "您好，优惠券可在商品页或店铺首页领取，结算页「优惠」一栏选择可用券即可自动抵扣。若券无法使用，通常是未达门槛或与活动价互斥，您可以告诉我订单金额，我帮您核算最优组合。",
    },
    {
        "id": "price_protect",
        "category": "优惠活动",
        "keywords": ["降价", "价保", "买贵了", "价格保护", "刚买就降价"],
        "question": "价保申请",
        "answer": "您好，我们支持价保服务：若商品在您下单后 7 天内出现官方降价，可申请差价补偿。请提供订单号 {order_id} 与当前价格截图，核实后我们会以优惠券或原路退款方式返还差价。",
    },
    {
        "id": "payment",
        "category": "支付订单",
        "keywords": ["支付方式", "怎么付款", "花呗", "分期", "能用什么支付", "付款失败"],
        "question": "支付方式",
        "answer": "您好，支持微信支付、支付宝、银行卡及平台分期（以结算页展示为准）。若付款失败，建议更换支付方式或检查银行卡限额；若已扣款但订单未生成，通常 24 小时内自动退回，我们也可帮您加急核查。",
    },
    {
        "id": "cancel_order",
        "category": "支付订单",
        "keywords": ["取消订单", "不想买了", "怎么取消", "撤销订单", "不要了"],
        "question": "取消订单",
        "answer": "您好，未发货订单可在订单页直接点击「取消订单」，款项将原路退回。若订单 {order_id} 已发货，可拒收后申请退款，或收到后走 7 天无理由退货，运费按平台规则处理。",
    },
    {
        "id": "presale",
        "category": "支付订单",
        "keywords": ["预售", "定金", "尾款", "什么时候付尾款", "预售发货"],
        "question": "预售规则",
        "answer": "您好，预售商品需先支付定金锁定库存，尾款请在页面标注的截止时间前支付，逾期订单会自动关闭并退回定金。尾款支付完成后，我们会在 48 小时内按付款顺序发货。",
    },
]

_SHIP_HOURS = "48 小时"

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}")


def _score(item: dict, question: str) -> int:
    """命中关键词计分：长关键词权重更高，标准问法整体包含额外加分。"""
    q = question or ""
    score = 0
    for kw in item["keywords"]:
        if kw in q:
            score += 2 + min(len(kw), 8)
    if item["question"] in q:
        score += 6
    # 类目词命中给一点分（如“退货”“发票”）
    if item["category"] in q:
        score += 3
    return score


def search_faq(question: str, threshold: int = 4) -> dict | None:
    """检索 FAQ，返回最佳命中项 + 得分；低于阈值视为未命中。

    阈值取 4：单个 2 字关键词（如“尺码”“发票”）命中即可作答，
    同时无任何关键词命中（得分 0）的问题仍会走 LLM。
    """
    best: dict | None = None
    best_score = 0
    for item in FAQ_ITEMS:
        s = _score(item, question)
        if s > best_score:
            best_score, best = s, item
    if not best or best_score < threshold:
        return None
    return {"item": best, "score": best_score}


def render_faq_answer(item: dict, ctx: dict | None = None) -> str:
    """用订单/商品上下文填充答案占位符。"""
    ctx = ctx or {}
    data = {
        "order_id": ctx.get("order_id") or "（未提供）",
        "order_status": ctx.get("order_status") or "处理中",
        "order_time": ctx.get("order_time") or "—",
        "product_name": ctx.get("product_name") or "该商品",
        "ship_hours": _SHIP_HOURS,
    }
    try:
        return item["answer"].format(**data)
    except Exception:
        return item["answer"]


def list_faq(category: str | None = None) -> list[dict]:
    """列出 FAQ（给前端展示/调试）。"""
    items = FAQ_ITEMS if not category else [i for i in FAQ_ITEMS if i["category"] == category]
    return [
        {"id": i["id"], "category": i["category"], "question": i["question"], "keywords": i["keywords"]}
        for i in items
    ]
