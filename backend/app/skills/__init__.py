"""Skill 注册表.

每个 Skill 声明：
  name    —— 唯一标识，会随响应返回给前端
  matcher —— 意图识别函数 (question) -> bool
  run     —— 执行函数 (db, question, platform, **kwargs) -> dict 或 Awaitable[dict]
  polish  —— True 表示返回的 JSON 需再由 LLM 做语言整理（查数类）；
             False 表示 Skill 自己已产出最终话术（文案/客服类）

顺序即优先级：越具体的意图放前面，避免被宽泛的查数意图抢走。
"""
from .copywriting import looks_like_copywriting_query, run as run_copywriting
from .customer_service import looks_like_customer_service_query, run as run_customer_service
from .product_metrics import looks_like_product_query, run as run_product_metrics

SKILLS = [
    # 客服/售后意图最具体，优先匹配（FAQ 命中可完全免 LLM）
    {"name": "customer_service", "matcher": looks_like_customer_service_query, "run": run_customer_service, "polish": False},
    # 文案创意（标题/卖点/口播）
    {"name": "copywriting", "matcher": looks_like_copywriting_query, "run": run_copywriting, "polish": False},
    # 商品与核心指标查数（数值全部由代码计算）
    {"name": "product_metrics", "matcher": looks_like_product_query, "run": run_product_metrics, "polish": True},
]
