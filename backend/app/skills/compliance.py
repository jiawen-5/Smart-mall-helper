"""广告法极限词检测 / 违禁词替换 / 敏感词过滤（Skill 2、Skill 3 共用规则引擎）。

规则引擎由代码负责，不交给 LLM 判断，避免漏检与幻觉。
"""
import re

# ---------- 广告法绝对化用语（正则, 类别, 合规替换建议） ----------
_EXTREME_RULES: list[tuple[str, str, str]] = [
    (r"全网(第一|最低|最优|最便宜)", "绝对化-范围", "全网热销"),
    (r"全国(第一|最低|最优|最便宜)", "绝对化-范围", "全国热销"),
    (r"(世界|全球)(第一|领先|顶级)", "绝对化-范围", "行业领先"),
    (r"销量(第一|冠军|领先第一)", "绝对化-销量", "销量领先"),
    (r"第一品牌|行业第一|排名第一|(第一|冠军)(?!时间|次|步|批|季度|名)", "绝对化-排名", "热门"),
    (r"国家级|世界级|国际级", "绝对化-级别", "高品质"),
    (r"顶级|顶尖|王牌|至尊|巅峰", "绝对化-级别", "优质"),
    (r"最(好|佳|优|强|大|小|高|低|快|慢|便宜|实惠|先进|专业|新|流行|时尚|受欢迎)", "绝对化-最高级", "更优"),
    (r"唯一|独家|仅此一家|绝无仅有|独一无二", "绝对化-唯一性", "精选"),
    (r"首个|首创|首款|史无前例|前所未有|开创性", "绝对化-首创", "新推出"),
    (r"绝对|100%|百分百|百分之百|完全|彻底|永久|终生", "绝对化-保证", "有效"),
    (r"无敌|完美|万能|包治|根治|药到病除", "绝对化-夸张", "表现出色"),
    (r"永不|终身|一辈子|永远不", "绝对化-时效", "持久"),
    (r"史上最低|跳楼价|清仓甩卖|血亏|亏本甩卖", "价格-夸张", "限时优惠"),
    (r"零风险|稳赚|包过|保证升值|投资回报", "承诺-风险", "值得信赖"),
    (r"假一赔十|假一赔万", "承诺-需资质", "官方正品渠道"),
    (r"秒杀一切|碾压|吊打|无对手", "贬低-竞品", "表现优秀"),
]

# ---------- 敏感词（客服回复输出前过滤） ----------
_SENSITIVE_WORDS = [
    "傻逼", "傻B", "滚蛋", "去死", "废物", "白痴", "神经病", "智障", "垃圾货", "骗子",
    "赌博", "博彩", "代开发票", "刷单", "刷好评", "假货", "高仿", "走私", "违禁品",
    "色情", "援交", "枪支", "毒品", "办证", "套现", "洗钱", "传销",
]


def scan_extreme(text: str) -> list[dict]:
    """扫描极限词，返回 [{word, category, suggestion, index}]，按出现顺序去重。"""
    hits: list[dict] = []
    seen: set[str] = set()
    for pattern, category, suggestion in _EXTREME_RULES:
        for m in re.finditer(pattern, text or ""):
            word = m.group(0)
            if word in seen:
                continue
            seen.add(word)
            hits.append({"word": word, "category": category, "suggestion": suggestion, "index": m.start()})
    hits.sort(key=lambda x: x["index"])
    return hits


def sanitize_extreme(text: str) -> str:
    """把极限词替换为合规建议词，返回整改后的文本（合并重复的相邻建议词）。"""
    result = text or ""
    for pattern, _category, suggestion in _EXTREME_RULES:
        result = re.sub(pattern, suggestion, result)
    # 相邻重复建议词合并，如“有效有效”->“有效”、“精选精选”->“精选”
    for _pattern, _category, suggestion in _EXTREME_RULES:
        result = re.sub(rf"({re.escape(suggestion)})(\1)+", r"\1", result)
    return result


def scan_sensitive(text: str) -> list[str]:
    """扫描敏感词，返回命中的词列表。"""
    return [w for w in _SENSITIVE_WORDS if w in (text or "")]


def mask_sensitive(text: str, mask: str = "＊") -> str:
    """敏感词打码。"""
    result = text or ""
    for w in _SENSITIVE_WORDS:
        if w in result:
            result = result.replace(w, mask * len(w))
    return result


def check_text(text: str) -> dict:
    """组合校验：极限词 + 敏感词，并给出整改文本。"""
    extreme = scan_extreme(text)
    sensitive = scan_sensitive(text)
    return {
        "passed": not extreme and not sensitive,
        "extreme_words": extreme,
        "sensitive_words": sensitive,
        "sanitized": mask_sensitive(sanitize_extreme(text)),
    }
