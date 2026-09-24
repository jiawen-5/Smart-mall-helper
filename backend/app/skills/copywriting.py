"""Skill 2：文案创意生成.

职责边界（防幻觉）：
- 商品属性（名称/品牌/品类/价格/标签）由代码从 product 表取，不让 LLM 编；
- Prompt 模板、风格/平台/长度等参数解析由本模块完成；
- LLM 只产出文案草稿；
- 极限词扫描与整改由 compliance 规则引擎做，不交给 LLM 判断；
- 多版本整理与重新生成由代码控制。

工作流：
  意图识别 -> 提取上下文（商品/平台/风格/长度）-> 填充 Prompt -> LLM 生成
  -> 规则校验极限词 -> 返回多套文案
"""
import re

from sqlalchemy.orm import Session

from .. import models
from . import compliance
from .llm import extract_json, llm_chat
from .product_metrics import resolve_products

# ---------- 1. 意图识别 ----------

_INTENT_RE = re.compile(
    r"(文案|标题|卖点|口播|种草|直播话术|宣传语|标语|slogan|详情页|主图|短标题|"
    r"营销|广告词|脚本|写一段|写个|写条|生成.*(文案|标题|卖点)|帮我写|帮我起|提炼.*卖点|换个说法|改写)",
    re.IGNORECASE,
)
# 客服/售后类意图不属于文案 Skill（交给 Skill 3）
_EXCLUDE_RE = re.compile(r"(客服|售后|退货|退款|换货|投诉|买家问|客户问|回复买家|回复客户)")


def looks_like_copywriting_query(question: str) -> bool:
    q = question or ""
    if not q:
        return False
    if _EXCLUDE_RE.search(q):
        return False
    return bool(_INTENT_RE.search(q))


# ---------- 2. 参数提取 ----------

STYLE_PRESETS: dict[str, dict] = {
    "简约": {
        "desc": "极简克制，短句为主，突出核心功能与参数，不堆砌形容词",
        "tone": "理性、干净",
    },
    "种草": {
        "desc": "第一人称真实体验感，先戳痛点再给方案，口语化、有情绪、有细节",
        "tone": "亲切、有代入感",
    },
    "直播风": {
        "desc": "强节奏、强促单，短句连发，多喊话与限时权益，适合口播朗读",
        "tone": "热烈、有煽动力",
    },
}

_STYLE_ALIASES = {
    "简约": "简约", "简洁": "简约", "极简": "简约", "性冷淡": "简约", "专业": "简约",
    "种草": "种草", "小红书": "种草", "安利": "种草", "生活化": "种草",
    "直播风": "直播风", "直播": "直播风", "带货": "直播风", "口播": "直播风", "热情": "直播风",
}

_PLATFORM_NAMES = {
    "taobao": "淘宝", "jd": "京东", "douyin": "抖音", "pinduoduo": "拼多多",
    "tmall": "天猫", "xiaohongshu": "小红书",
}

_PLATFORM_HINTS = [
    (r"(抖音|douyin)", "douyin"),
    (r"(小红书|xiaohongshu)", "xiaohongshu"),
    (r"(拼多多|pdd)", "pinduoduo"),
    (r"(京东|jd)", "jd"),
    (r"(天猫|tmall)", "tmall"),
    (r"(淘宝|taobao)", "taobao"),
]


_FIELD_TITLE = "title"
_FIELD_POINTS = "selling_points"
_FIELD_SCRIPT = "script"
_ALL_FIELDS = (_FIELD_TITLE, _FIELD_POINTS, _FIELD_SCRIPT)

_TITLE_RE = re.compile(r"(标题|题目|主标题|短标题|题目党)")
_POINTS_RE = re.compile(r"(卖点|亮点|详情页|详情描述|提炼.*卖点)")
_SCRIPT_RE = re.compile(r"(口播|脚本|话术|种草文|推文|直播稿|视频文案|带货稿|解说文)")
_NEG_RE_TMPL = r"(不要|不用|不含|别带|去掉|去{kw})"


def parse_fields(question: str) -> list[str]:
    """用户要什么给什么：只要标题就只返回标题，不多给卖点/口播。

    - 命中标题/卖点/口播任一具体词 -> 只返回命中的那几类；
    - 出现"不要/不用/不含 X" -> 从结果里剔除 X；
    - 泛词短文案（如"营销文案，20字以内/简短有力"）没点具体类型，但有短字数约束
      -> 只返回 script，一条即一条短文案，不展开成标题+卖点+口播；
    - 纯泛词（"生成营销文案"）无任何约束 -> 全量返回（兼容老行为）。
    """
    q = question or ""
    want: set[str] = set()
    if _TITLE_RE.search(q):
        want.add(_FIELD_TITLE)
    if _POINTS_RE.search(q):
        want.add(_FIELD_POINTS)
    if _SCRIPT_RE.search(q):
        want.add(_FIELD_SCRIPT)
    if not want:
        if re.search(r"(\d+\s*字|字以内|字内|简短|短小|精炼|有力|slogan|宣传语|标语|广告词|一句话)", q):
            return [_FIELD_SCRIPT]
        return list(_ALL_FIELDS)
    for field, kw in (
        (_FIELD_TITLE, "标题|题目"),
        (_FIELD_POINTS, "卖点|亮点"),
        (_FIELD_SCRIPT, "口播|脚本|话术"),
    ):
        if re.search(_NEG_RE_TMPL.format(kw=kw), q):
            want.discard(field)
    return [f for f in _ALL_FIELDS if f in want] or list(_ALL_FIELDS)


def parse_style(question: str, explicit: str | None = None) -> str:
    if explicit and explicit in STYLE_PRESETS:
        return explicit
    q = question or ""
    for alias, name in _STYLE_ALIASES.items():
        if alias in q:
            return name
    return "种草"


def parse_platform(question: str, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    q = question or ""
    for pattern, code in _PLATFORM_HINTS:
        if re.search(pattern, q, re.IGNORECASE):
            return code
    return "taobao"


def parse_length(question: str, explicit: int | None = None) -> dict:
    """返回 {'label':.., 'title_max':.., 'points':.., 'script_max':..}"""
    if explicit:
        n = max(6, min(int(explicit), 200))
        return {"label": f"标题≤{n}字", "title_max": n, "points": 4, "script_max": 150}
    q = question or ""
    m = re.search(r"(\d+)\s*字", q)
    if m:
        n = max(6, min(int(m.group(1)), 200))
        return {"label": f"≤{n}字", "title_max": n, "points": 4, "script_max": n}
    if re.search(r"(长|详细|丰富|多写)", q):
        return {"label": "较长", "title_max": 40, "points": 6, "script_max": 260}
    if re.search(r"(短|精简|简洁|一句话)", q):
        return {"label": "简短", "title_max": 16, "points": 3, "script_max": 90}
    return {"label": "适中", "title_max": 30, "points": 4, "script_max": 150}


def _extract_product_hint(question: str) -> str:
    """从问句里抠出商品描述片段（用于没匹配到库内商品时）。"""
    q = re.sub(r"(帮我|请|麻烦|给我|写一段|写个|写条|生成|一份|一段|一个|文案|标题|卖点|口播|种草|直播风|简约|风格|小红书|抖音|淘宝|京东|拼多多)", " ", question or "")
    q = re.sub(r"[\s,，、；;|/\\？?！!：:。\.\"'“”‘’（）\(\)\[\]]+", " ", q)
    tokens = [t for t in q.split() if len(t) >= 2]
    return " ".join(tokens[:6]) or (question or "").strip()


def collect_context(db: Session, question: str, platform: str | None) -> dict:
    """提取商品上下文：优先库内真实商品，其次问句里的描述。"""
    products, matched_by = resolve_products(db, question, platform, limit=3)
    if products:
        p = products[0]
        return {
            "matched": True,
            "matched_by": matched_by,
            "global_product_id": p.global_product_id,
            "product_name": p.product_name,
            "brand": p.brand,
            "category": p.category,
            "subcategory": p.subcategory,
            "price": float(p.price) if p.price is not None else None,
            "stock_status": p.stock_status,
            "tags": p.tags,
            "candidates": [x.product_name for x in products],
        }
    return {
        "matched": False,
        "matched_by": None,
        "product_name": _extract_product_hint(question),
        "brand": None,
        "category": None,
        "price": None,
        "stock_status": None,
        "tags": None,
        "candidates": [],
    }


# ---------- 3. Prompt 模板 ----------

_SYSTEM = (
    "你是资深电商文案策划，擅长把商品卖点写成合规、有转化力的中文文案。"
    "严格遵守广告法：严禁使用“最、第一、全网第一、国家级、顶级、100%、绝对、唯一、独家、永久”等极限词。"
    "只输出 JSON，不要任何解释文字。"
)


def build_prompt(ctx: dict, style: str, platform: str, length: dict, variants: int, avoid: list[str] | None = None, fields: list[str] | None = None) -> str:
    style_info = STYLE_PRESETS[style]
    facts = [
        f"商品名称：{ctx.get('product_name') or '（未提供，请基于通用品类合理创作）'}",
        f"品牌：{ctx.get('brand') or '未提供'}",
        f"品类：{ctx.get('category') or '未提供'}"
        + (f" / {ctx['subcategory']}" if ctx.get("subcategory") else ""),
        f"标价：{ctx.get('price') if ctx.get('price') is not None else '未提供'}",
        f"标签：{ctx.get('tags') or '未提供'}",
        f"库存状态：{ctx.get('stock_status') or '未提供'}",
    ]
    avoid_rule = ""
    if avoid:
        avoid_rule = (
            "\n【去重要求】以下标题已用过，必须换角度、换措辞，不得重复：\n- "
            + "\n- ".join(avoid[:6])
        )
    fields = fields or list(_ALL_FIELDS)
    field_desc = {"title": "title（商品标题）", "selling_points": "selling_points（字符串数组）", "script": "script（短视频口播文案）"}
    wanted = "、".join(field_desc[f] for f in fields if f in field_desc)
    len_rules = []
    if "title" in fields:
        len_rules.append(f"标题不超过 {length['title_max']} 字")
    if "selling_points" in fields:
        len_rules.append(f"详情卖点 {length['points']} 条，每条不超过 20 字")
    if "script" in fields:
        len_rules.append(f"口播文案不超过 {length['script_max']} 字")
    only_rule = f"\n【按需输出】用户只要 {wanted}，JSON 里每套只含 angle 和上述字段，绝不多加其他字段。" if len(fields) < 3 else ""
    json_keys = ",".join(
        '"angle":""' if f == "angle"
        else (f'"{field_desc[f].split("（")[0]}":""' if f != "selling_points" else '"selling_points":["",""]')
        for f in ["angle"] + fields
    )
    return (
        f"【商品事实】（以此为准，不得编造参数）\n" + "\n".join(facts) + "\n\n"
        f"【目标平台】{_PLATFORM_NAMES.get(platform, platform)}\n"
        f"【文案风格】{style}——{style_info['desc']}（语气：{style_info['tone']}）\n"
        f"【长度要求】{'；'.join(len_rules)}\n"
        f"【输出要求】生成 {variants} 套不同角度的文案，每套包含：angle（角度名，如“痛点切入”“场景共鸣”）、"
        f"{wanted}。\n"
        f"【硬性规则】严禁极限词；口播文案要适合朗读，避免书面长句。{avoid_rule}{only_rule}\n\n"
        f'只输出如下 JSON：{{"versions":[{{{json_keys}}}]}}'
    )


# ---------- 4. 兜底生成（无 LLM 时） ----------

def _fallback_versions(ctx: dict, style: str, length: dict, variants: int) -> list[dict]:
    name = ctx.get("product_name") or "精选好物"
    brand = ctx.get("brand") or ""
    category = ctx.get("category") or "品质"
    tags = [t for t in re.split(r"[,，、|/]+", ctx.get("tags") or "") if t.strip()][:5]
    if not tags:
        tags = ["品质优选", "口碑推荐", "现货速发"]
    angles = ["卖点直给", "场景共鸣", "人群定向", "痛点切入", "限时促单"][: max(1, variants)]
    out = []
    for i, angle in enumerate(angles):
        title = f"{brand} {name} {tags[0]}"[: length["title_max"]]
        points = [f"{t}·{category}优选" for t in tags][: length["points"]]
        script = (
            f"{name}，{tags[0]}。{tags[1] if len(tags) > 1 else '品质可靠'}，"
            f"日常使用更省心。现在下单享限时优惠，点击下方链接即可入手。"
        )[: length["script_max"]]
        out.append({"angle": angle, "title": title, "selling_points": points, "script": script})
    return out


# ---------- 5. 规则校验 ----------

def _validate_versions(versions: list[dict]) -> tuple[list[dict], bool]:
    """对每套文案做极限词扫描，附整改版；返回 (versions, all_passed)。"""
    all_passed = True
    for v in versions:
        texts = [v.get("title") or "", v.get("script") or ""] + list(v.get("selling_points") or [])
        joined = "\n".join(texts)
        hits = compliance.scan_extreme(joined)
        v["violations"] = hits
        v["compliant"] = not hits
        if hits:
            all_passed = False
            v["sanitized"] = {
                "title": compliance.sanitize_extreme(v.get("title") or ""),
                "selling_points": [compliance.sanitize_extreme(x) for x in (v.get("selling_points") or [])],
                "script": compliance.sanitize_extreme(v.get("script") or ""),
            }
        else:
            v["sanitized"] = None
    return versions, all_passed


# ---------- 6. 主入口 ----------

async def run(
    db: Session,
    question: str,
    platform: str | None = None,
    *,
    style: str | None = None,
    variants: int = 3,
    length: int | None = None,
    regenerate: bool = False,
    avoid: list[str] | None = None,
    fields: list[str] | None = None,
) -> dict:
    style = parse_style(question, style)
    platform = parse_platform(question, platform)
    length_cfg = parse_length(question, length)
    variants = max(1, min(int(variants or 3), 5))
    fields = [f for f in (fields or parse_fields(question)) if f in _ALL_FIELDS] or list(_ALL_FIELDS)
    ctx = collect_context(db, question, platform)

    prompt = build_prompt(ctx, style, platform, length_cfg, variants, avoid, fields)
    # 重新生成时提高温度并带上去重清单，保证换一批不同角度
    text = await llm_chat(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
        temperature=0.95 if regenerate else 0.8,
        max_tokens=1600,
    )
    parsed = extract_json(text)
    raw_versions = None
    if isinstance(parsed, dict):
        raw_versions = parsed.get("versions")
    elif isinstance(parsed, list):
        raw_versions = parsed

    source = "llm"
    versions: list[dict] = []
    if isinstance(raw_versions, list) and raw_versions:
        for i, v in enumerate(raw_versions[:variants]):
            if not isinstance(v, dict):
                continue
            points = v.get("selling_points")
            if isinstance(points, str):
                points = [p for p in re.split(r"[\n;；]+", points) if p.strip()]
            versions.append(
                {
                    "index": i + 1,
                    "angle": v.get("angle") or f"方案{i + 1}",
                    "title": (v.get("title") or "").strip(),
                    "selling_points": [str(p).strip() for p in (points or []) if str(p).strip()],
                    "script": (v.get("script") or "").strip(),
                }
            )
    if not versions:
        source = "fallback"
        versions = [
            {**v, "index": i + 1} for i, v in enumerate(_fallback_versions(ctx, style, length_cfg, variants))
        ]

    versions, all_passed = _validate_versions(versions)
    return {
        "skill": "copywriting",
        "source": source,
        "params": {
            "style": style,
            "style_desc": STYLE_PRESETS[style]["desc"],
            "platform": platform,
            "platform_name": _PLATFORM_NAMES.get(platform, platform),
            "length": length_cfg,
            "variants": len(versions),
            "regenerate": regenerate,
            "fields": fields,
        },
        "product": ctx,
        "versions": versions,
        "compliance": {
            "passed": all_passed,
            "checked_rules": len(compliance._EXTREME_RULES),
            "note": "已按广告法极限词库扫描；compliant=false 的版本附有 sanitized 合规改写版。",
        },
    }
