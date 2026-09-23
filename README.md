# 智能电商助手（前后端分离）

```
智能电商助手/
├── frontend/   # Vue3 + Vite 前端
├── backend/    # FastAPI + MySQL 后端
└── api/        # Vercel serverless（AI 代理）
```

## 1. 后端运行

```powershell
cd backend
copy .env.example .env   # 按本地 MySQL 改账号密码库名
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

打开 `http://127.0.0.1:8000/docs` 联调接口：
`GET /api/meta/health` 先确认能连上 MySQL 并读到 user/product/order 数量。

> 注意：`order` 是 MySQL 保留字，若建表时未用反引号会报错，届时把模型表名改成实际表名（如 `orders`）即可。

## 2. 前端运行

```powershell
cd frontend
npm install
npm run dev
```

前端 `vite.config.ts` 已把 `/api`（除 `/api/ai` 外）代理到 `http://127.0.0.1:8000`，
所以页面请求 `/api/dashboard/metrics` 等会自动打到 FastAPI，无需改业务代码。
`src/utils/backendApi.ts` 是新加的统一调用层，各页面把原来的假数据替换为它即可。

## 3. 接口一览

| 页面 | 接口 |
|---|---|
| 仪表盘 KPI | `GET /api/dashboard/metrics?platform=` |
| 趋势图 | `GET /api/dashboard/trend?range=7d&platform=` |
| 漏斗 | `GET /api/dashboard/funnel?platform=` |
| 商品 | `GET /api/products?keyword=&category=&platform=&page=&page_size=` |
| 用户分层 | `GET /api/users/segments?platform=` |
| 订单 | `GET /api/orders?status=&platform=&page=&page_size=` |
| 字典/自检 | `GET /api/meta/platforms|order-status|payment-methods|shipping-methods|health` |
| Agent 预留 | `POST /api/agent/ask {question, platform}` |
