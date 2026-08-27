import { createRouter, createWebHistory } from "vue-router";

import Search from "../components/Search.vue";
import AddNote from "../components/AddNote.vue";
import ImportFiles from "../components/ImportFiles.vue";
import Tags from "../components/Tags.vue";
import Fragments from "../components/Fragments.vue";
import GraphView from "../components/GraphView.vue";
import Review from "../components/Review.vue";
import RssFeeds from "../components/RssFeeds.vue";
import Dashboard from "../components/Dashboard.vue";
import Observability from "../components/Observability.vue";
import EvalCenter from "../components/EvalCenter.vue";
import PromptManager from "../components/PromptManager.vue";

const routes = [
  { path: "/", redirect: "/ask" },
  { path: "/ask/:sessionId?", name: "ask", component: { render: () => null } },
  { path: "/search", name: "search", component: Search },
  { path: "/add", name: "add", component: AddNote },
  { path: "/import", name: "import", component: ImportFiles },
  { path: "/tags", name: "tags", component: Tags },
  { path: "/fragments", name: "fragments", component: Fragments },
  { path: "/graph", name: "graph", component: GraphView },
  { path: "/review", name: "review", component: Review },
  { path: "/rss", name: "rss", component: RssFeeds },
  { path: "/dashboard", name: "dashboard", component: Dashboard },
  { path: "/admin/observability", name: "observability", component: Observability },
  { path: "/admin/eval", name: "eval", component: EvalCenter },
  { path: "/admin/prompts", name: "prompts", component: PromptManager },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

export default router;

// 工具清单（供侧边栏渲染 + 路由判断）
export const frontTools = [
  { key: "add", label: "快速记录", icon: "✍️", path: "/add" },
  { key: "import", label: "导入文件", icon: "📥", path: "/import" },
  { key: "search", label: "语义搜索", icon: "🔍", path: "/search" },
  { key: "tags", label: "标签浏览", icon: "🏷️", path: "/tags" },
  { key: "fragments", label: "知识片段", icon: "💡", path: "/fragments" },
  { key: "graph", label: "知识图谱", icon: "🕸️", path: "/graph" },
  { key: "review", label: "间隔复习", icon: "🎴", path: "/review" },
  { key: "rss", label: "RSS 订阅", icon: "📡", path: "/rss" },
  { key: "dashboard", label: "知识概览", icon: "📊", path: "/dashboard" },
];

export const adminTools = [
  { key: "observability", label: "系统监控", icon: "🩺", path: "/admin/observability" },
  { key: "eval", label: "评估中心", icon: "🧪", path: "/admin/eval" },
  { key: "prompts", label: "提示词管理", icon: "📝", path: "/admin/prompts" },
];
