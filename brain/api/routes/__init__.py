"""API 路由包——按业务域拆分的独立子包。

每个子包自包含 router（端点）+ models（Request/Response）。
app.py 通过导入各子包的 router 并 include_router 装配。
"""
