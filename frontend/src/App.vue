<script setup>
import { ref, computed, onMounted, provide } from "vue";
import AddNote from "./components/AddNote.vue";
import ImportFiles from "./components/ImportFiles.vue";
import Search from "./components/Search.vue";
import Ask from "./components/Ask.vue";
import Dashboard from "./components/Dashboard.vue";
import Fragments from "./components/Fragments.vue";
import RssFeeds from "./components/RssFeeds.vue";
import GraphView from "./components/GraphView.vue";
import Review from "./components/Review.vue";
import Observability from "./components/Observability.vue";
import EvalCenter from "./components/EvalCenter.vue";
import { listSessions, deleteSession } from "./api/index.js";

// 工具按「前台 / 后台」分组
// 前台：面向日常知识管理使用
const frontTools = [
  { key: "add", label: "快速记录", icon: "✍️", component: AddNote },
  { key: "import", label: "导入文件", icon: "📥", component: ImportFiles },
  { key: "search", label: "语义搜索", icon: "🔍", component: Search },
  { key: "fragments", label: "知识片段", icon: "💡", component: Fragments },
  { key: "graph", label: "知识图谱", icon: "🕸️", component: GraphView },
  { key: "review", label: "间隔复习", icon: "🎴", component: Review },
  { key: "rss", label: "RSS 订阅", icon: "📡", component: RssFeeds },
  { key: "dashboard", label: "知识概览", icon: "📊", component: Dashboard },
];
// 后台：系统运维与评估
const adminTools = [
  { key: "observability", label: "系统监控", icon: "🩺", component: Observability },
  { key: "eval", label: "评估中心", icon: "🧪", component: EvalCenter },
];
const allTools = [...frontTools, ...adminTools];

const sidebarMode = ref("front"); // front | admin
const activeView = ref("ask"); // 默认主页面就是问答
const sessions = ref([]);
const currentSessionId = ref(null);
const askRefreshKey = ref(0); // 切换会话时强制 Ask 重载

// 跨页跳转种子: 其他页面跳问答/搜索时携带初始内容
const askSeed = ref(null); // { question: string, ts: number }
const searchSeed = ref(null); // { query: string, ts: number }

const currentTools = computed(() =>
  sidebarMode.value === "admin" ? adminTools : frontTools
);
const currentTool = computed(() => allTools.find((t) => t.key === activeView.value));
// 后台工具用宽面板铺满
const isWidePanel = computed(() =>
  ["graph", "observability", "eval"].includes(activeView.value)
);

function showAsk() {
  activeView.value = "ask";
  sidebarMode.value = "front";
}

function switchSidebar(mode) {
  sidebarMode.value = mode;
  // 切到后台时默认选第一个后台工具；切回前台时回到问答
  if (mode === "admin" && !adminTools.some((t) => t.key === activeView.value)) {
    activeView.value = adminTools[0].key;
  } else if (mode === "front" && activeView.value !== "ask") {
    // 仅当当前在后台页时才回问答，避免打断前台工具浏览
    if (adminTools.some((t) => t.key === activeView.value)) {
      activeView.value = "ask";
    }
  }
}

// 跳转问答页并预填问题（图谱/片段页调用）
function jumpToAsk(question) {
  askSeed.value = { question, ts: Date.now() };
  activeView.value = "ask";
  sidebarMode.value = "front";
}

// 跳转搜索页并预填查询（问答引用点击调用）
function jumpToSearch(query) {
  searchSeed.value = { query, ts: Date.now() };
  activeView.value = "search";
  sidebarMode.value = "front";
}

// 供任意子组件注入使用
provide("jumpToAsk", jumpToAsk);
provide("jumpToSearch", jumpToSearch);

async function refreshSessions() {
  try {
    sessions.value = await listSessions();
  } catch (e) {
    console.error("加载会话列表失败", e);
  }
}

async function newConversation() {
  // 新对话 = 无 session_id，Ask 会在首条消息时让后端创建
  currentSessionId.value = null;
  activeView.value = "ask";
  askRefreshKey.value++;
}

async function selectSession(id) {
  currentSessionId.value = id;
  activeView.value = "ask";
  askRefreshKey.value++;
}

async function removeSession(id, event) {
  event.stopPropagation(); // 防止触发 selectSession
  try {
    await deleteSession(id);
    if (currentSessionId.value === id) {
      newConversation();
    }
    await refreshSessions();
  } catch (e) {
    console.error("删除会话失败", e);
  }
}

// Ask 收到后端新会话 ID 时回调
function onSessionCreated(id) {
  currentSessionId.value = id;
  refreshSessions();
}

function onSessionUpdated() {
  refreshSessions();
}

onMounted(refreshSessions);
</script>

<template>
  <div class="shell">
    <!-- 顶部标题栏 -->
    <header class="topbar">
      <div class="brand" @click="showAsk">
        <span class="brand-logo">🧠</span>
        <span class="brand-name">BRAIN</span>
        <span class="brand-sub">个人知识管家</span>
      </div>
      <div class="topbar-right">
        <div class="sidebar-mode-switch">
          <button
            class="mode-btn"
            :class="{ active: sidebarMode === 'front' }"
            @click="switchSidebar('front')"
          >前台</button>
          <button
            class="mode-btn"
            :class="{ active: sidebarMode === 'admin' }"
            @click="switchSidebar('admin')"
          >后台</button>
        </div>
        <span class="status-dot"></span>
        <span class="status-text">本地知识库在线</span>
      </div>
    </header>

    <div class="layout">
      <!-- 侧边工具栏 -->
      <aside class="sidebar">
        <!-- 前台：新对话 + 会话列表 -->
        <template v-if="sidebarMode === 'front'">
          <button class="side-item new-chat" @click="newConversation">
            <span class="side-label">新对话</span>
          </button>

          <!-- 会话列表 -->
          <div v-if="sessions.length" class="session-list">
            <div class="side-section-label">历史会话</div>
            <button
              v-for="s in sessions"
              :key="s.id"
              class="session-item"
              :class="{ active: currentSessionId === s.id && activeView === 'ask' }"
              @click="selectSession(s.id)"
            >
              <span class="session-title">{{ s.title }}</span>
              <span class="session-delete" title="删除会话" @click="removeSession(s.id, $event)">✕</span>
            </button>
          </div>

          <div class="side-divider"></div>
          <div class="side-section-label">工具</div>
        </template>

        <!-- 后台标题 -->
        <template v-else>
          <div class="side-section-label">系统管理</div>
        </template>

        <button
          v-for="t in currentTools"
          :key="t.key"
          class="side-item"
          :class="{ active: activeView === t.key }"
          @click="activeView = t.key"
        >
          <span class="side-icon">{{ t.icon }}</span>
          <span class="side-label">{{ t.label }}</span>
        </button>
      </aside>

      <!-- 主内容区 -->
      <main class="main">
        <!-- 问答主页面 -->
        <Ask
          v-show="activeView === 'ask'"
          :key="askRefreshKey"
          :session-id="currentSessionId"
          :seed="askSeed"
          @session-created="onSessionCreated"
          @session-updated="onSessionUpdated"
        />

        <!-- 工具页（图谱/系统监控/评估中心用宽面板） -->
        <div
          v-if="activeView !== 'ask'"
          :class="['tool-panel', { 'tool-panel-wide': isWidePanel }]"
        >
          <div class="tool-panel-header">
            <span class="tool-panel-icon">{{ currentTool?.icon }}</span>
            <h2>{{ currentTool?.label }}</h2>
          </div>
          <component
            :is="currentTool?.component"
            :seed="activeView === 'search' ? searchSeed : null"
          />
        </div>
      </main>
    </div>
  </div>
</template>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

:root {
  --bg-deep: #eef3fa;
  --bg-panel: #ffffff;
  --bg-card: #f5f9ff;
  --bg-hover: #e3eefc;
  --border: #d5e2f0;
  --border-glow: rgba(0, 132, 255, 0.45);
  --primary: #0084ff;
  --primary-dim: #0066cc;
  --accent: #00b8d4;
  --text-main: #1a2c45;
  --text-dim: #5a7294;
  --text-faint: #93a8c4;
  --success: #10b981;
  --danger: #ef4444;
  --font-mono: "JetBrains Mono", "Cascadia Code", Consolas, monospace;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Microsoft YaHei", sans-serif;
  background: var(--bg-deep);
  color: var(--text-main);
  min-height: 100vh;
}

/* ============ 顶部标题栏 ============ */
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  padding: 0 20px;
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 10;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  user-select: none;
}

.brand-logo {
  font-size: 22px;
}

.brand-name {
  font-family: var(--font-mono);
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 2px;
  background: linear-gradient(90deg, var(--primary), var(--accent));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.brand-sub {
  font-size: 12px;
  color: var(--text-dim);
  padding-left: 10px;
  border-left: 1px solid var(--border);
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--success);
  box-shadow: 0 0 8px var(--success);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.status-text {
  font-size: 12px;
  color: var(--text-dim);
  font-family: var(--font-mono);
}

/* ============ 布局 ============ */
.layout {
  display: flex;
  height: calc(100vh - 56px);
}

/* ============ 侧边栏 ============ */
.sidebar {
  width: 200px;
  flex-shrink: 0;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  padding: 16px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow-y: auto;
}

.side-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  color: var(--text-dim);
  transition: all 0.15s;
  width: 100%;
  text-align: left;
}

.side-item:hover {
  background: var(--bg-hover);
  color: var(--text-main);
}

.side-item.active {
  background: var(--bg-hover);
  border-color: var(--border-glow);
  color: var(--primary);
}

.side-item.new-chat {
  color: var(--primary);
  font-weight: 600;
  border: 1px dashed var(--border-glow);
  margin-bottom: 8px;
  justify-content: center;
}

.side-item.new-chat:hover {
  background: rgba(0, 132, 255, 0.06);
}

.side-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.side-label {
  white-space: nowrap;
}

/* 会话列表 */
.session-list {
  margin-bottom: 4px;
  max-height: 40vh;
  overflow-y: auto;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  width: 100%;
  background: transparent;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-dim);
  transition: all 0.12s;
  text-align: left;
}

.session-item:hover {
  background: var(--bg-hover);
}

.session-item.active {
  background: var(--bg-hover);
  color: var(--primary);
}

.session-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-delete {
  opacity: 0;
  font-size: 12px;
  color: var(--text-faint);
  padding: 2px 4px;
  border-radius: 4px;
  transition: all 0.12s;
}

.session-item:hover .session-delete {
  opacity: 1;
}

.session-delete:hover {
  color: var(--danger);
  background: rgba(239, 68, 68, 0.1);
}

.side-divider {
  height: 1px;
  background: var(--border);
  margin: 8px 4px;
}

.side-section-label {
  font-size: 11px;
  color: var(--text-faint);
  letter-spacing: 1px;
  padding: 0 12px 6px;
  font-family: var(--font-mono);
}

/* 前/后台切换 */
.sidebar-mode-switch {
  display: flex;
  gap: 2px;
  padding: 3px;
  background: var(--bg-card);
  border-radius: 7px;
  border: 1px solid var(--border);
}

.mode-btn {
  padding: 4px 14px;
  background: transparent;
  border: none;
  border-radius: 5px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-dim);
  transition: all 0.15s;
  font-family: var(--font-mono);
}

.mode-btn:hover {
  color: var(--text-main);
}

.mode-btn.active {
  background: var(--bg-panel);
  color: var(--primary);
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

/* ============ 主内容区 ============ */
.main {
  flex: 1;
  overflow-y: auto;
  background:
    radial-gradient(ellipse at 20% 0%, rgba(0, 132, 255, 0.05), transparent 50%),
    radial-gradient(ellipse at 80% 100%, rgba(0, 184, 212, 0.05), transparent 50%),
    var(--bg-deep);
}

.tool-panel {
  max-width: 820px;
  margin: 0 auto;
  padding: 28px 24px 60px;
}

/* 知识图谱等宽幅工具页占满内容区 */
.tool-panel-wide {
  max-width: none;
  padding: 20px 24px 40px;
}

.tool-panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}

.tool-panel-icon {
  font-size: 22px;
}

.tool-panel-header h2 {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-main);
}
</style>
