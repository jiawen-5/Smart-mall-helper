"""Skill 注册表：后续 skill2/skill3 在此注册后即可被 agent 路由调用。"""
from .product_metrics import run as run_product_metrics, looks_like_product_query

SKILLS = [
    {"name": "product_metrics", "matcher": looks_like_product_query, "run": run_product_metrics},
]
