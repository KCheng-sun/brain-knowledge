<script setup>
import { ref, computed, watch, onMounted, provide, h } from "vue";
import { theme } from "ant-design-vue";
import { useRouter, useRoute } from "vue-router";
import {
  PlusOutlined,
  SearchOutlined,
  EditOutlined,
  InboxOutlined,
  BulbOutlined,
  ApartmentOutlined,
  ClockCircleOutlined,
  WifiOutlined,
  DashboardOutlined,
  HeartOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  DesktopOutlined,
} from "@ant-design/icons-vue";
import { frontTools, adminTools } from "./router/index.js";
import Ask from "./components/Ask.vue";
import { listSessions, deleteSession } from "./api/index.js";

const router = useRouter();
const route = useRoute();

const sessions = ref([]);
const askRefreshKey = ref(0);
const askSeed = ref(null);
const searchSeed = ref(null);

// 图标映射
const iconMap = {
  add: EditOutlined,
  import: InboxOutlined,
  search: SearchOutlined,
  fragments: BulbOutlined,
  graph: ApartmentOutlined,
  review: ClockCircleOutlined,
  rss: WifiOutlined,
  dashboard: DashboardOutlined,
  observability: DesktopOutlined,
  eval: ExperimentOutlined,
  prompts: FileTextOutlined,
};

const allTools = [...frontTools, ...adminTools];

const isAdmin = computed(() => route.path.startsWith("/admin"));
const isAsk = computed(() => route.name === "ask");
const isWidePanel = computed(() =>
  ["graph", "observability", "eval", "prompts"].includes(route.name)
);
const currentTool = computed(() => {
  const t = allTools.find((t) => t.key === route.name);
  return t || { icon: "🤖", label: "智能问答" };
});

// 侧边栏选中项
const selectedKeys = computed(() => {
  if (isAsk.value) return ["/ask"];
  return [route.path];
});

// 当前侧边栏模式
const sidebarMode = computed(() => (isAdmin.value ? "admin" : "front"));
const currentTools = computed(() =>
  isAdmin.value ? adminTools : frontTools
);

function navigate(path) {
  router.push(path);
}

function switchSidebar(mode) {
  if (mode === "admin") {
    router.push("/admin/observability");
  } else {
    router.push("/ask");
  }
}

function jumpToAsk(question) {
  askSeed.value = { question, ts: Date.now() };
  router.push("/ask");
}

function jumpToSearch(query) {
  searchSeed.value = { query, ts: Date.now() };
  router.push("/search");
}

provide("jumpToAsk", jumpToAsk);
provide("jumpToSearch", jumpToSearch);

async function refreshSessions() {
  try {
    sessions.value = await listSessions();
  } catch (e) {
    console.error("加载会话列表失败", e);
  }
}

function newConversation() {
  router.push("/ask");
  askRefreshKey.value++;
}

async function selectSession(id) {
  router.push(`/ask/${id}`);
  askRefreshKey.value++;
}

async function removeSession(id) {
  try {
    await deleteSession(id);
    if (route.params.sessionId === id) {
      newConversation();
    }
    await refreshSessions();
  } catch (e) {
    console.error("删除会话失败", e);
  }
}

function onSessionCreated(id) {
  router.replace(`/ask/${id}`);
  refreshSessions();
}

function onSessionUpdated() {
  refreshSessions();
}

watch(
  () => route.path,
  (path) => {
    if (path.startsWith("/ask")) {
      refreshSessions();
    }
  }
);

onMounted(refreshSessions);

// 折叠状态
const collapsed = ref(false);

// Layout 统一浅色主题
const themeConfig = {
  components: {
    Layout: {
      headerBg: "#ffffff",
      headerHeight: 56,
      headerColor: "rgba(0, 0, 0, 0.88)",
      siderBg: "#ffffff",
      bodyBg: "#f5f5f5",
      triggerBg: "#ffffff",
    },
  },
};
</script>

<template>
  <a-config-provider :theme="themeConfig">
  <a-layout style="height: 100vh; overflow: hidden">
    <!-- 顶部标题栏 -->
    <a-layout-header style="background: #fff; display: flex; align-items: center; justify-content: space-between; padding: 0 24px">
      <a-space style="cursor: pointer" @click="navigate('/ask')">
        <span style="font-size: 22px">🧠</span>
        <a-typography-title :level=4 style="margin: 0">BRAIN</a-typography-title>
        <a-typography-text type="secondary">个人知识管家</a-typography-text>
      </a-space>
      <a-space size="large">
        <a-segmented
          v-model:value="sidebarMode"
          :options="[
            { label: '前台', value: 'front' },
            { label: '后台', value: 'admin' },
          ]"
          size="small"
          @change="switchSidebar"
        />
        <a-badge status="success" text="本地知识库在线" />
      </a-space>
    </a-layout-header>

    <a-layout style="height: calc(100vh - 56px); overflow: hidden">
      <!-- 侧边栏 -->
      <a-layout-sider
        v-model:collapsed="collapsed"
        collapsible
        theme="light"
        :width="220"
        :collapsed-width="64"
      >
        <!-- 前台：新对话 + 会话列表 -->
        <template v-if="!isAdmin">
          <div style="padding: 12px">
            <a-button
              type="primary"
              block
              :icon="h(PlusOutlined)"
              @click="newConversation"
            >
              <span v-if="!collapsed">新对话</span>
            </a-button>
          </div>

          <!-- 会话列表 -->
          <a-list
            v-if="!collapsed && sessions.length"
            :data-source="sessions"
            :split="false"
            size="small"
            style="padding: 0 8px; max-height: 35vh; overflow-y: auto"
          >
            <template #header>
              <a-typography-text type="secondary" style="font-size: 11px; padding-left: 4px">历史会话</a-typography-text>
            </template>
            <template #renderItem="{ item }">
              <a-tooltip :title="item.title" placement="right">
                <a-list-item style="padding: 4px 8px; border-radius: 6px; cursor: pointer"
                  :style="{ background: route.params.sessionId === item.id && isAsk ? 'var(--ant-color-primary-bg)' : 'transparent' }"
                  @click="selectSession(item.id)"
                >
                  <div style="display: flex; align-items: center; gap: 4px; width: 100%">
                    <span style="flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px">{{ item.title }}</span>
                    <a-button type="text" size="small" style="flex-shrink: 0" @click.stop="removeSession(item.id)">✕</a-button>
                  </div>
                </a-list-item>
              </a-tooltip>
            </template>
          </a-list>
        </template>

        <!-- 分割线 + 分组标题 -->
        <a-divider v-if="!collapsed" style="margin: 8px 0" />
        <a-typography-text v-if="!collapsed" type="secondary" style="font-size: 11px; padding: 0 24px; display: block">{{ isAdmin ? '系统管理' : '工具' }}</a-typography-text>

        <!-- 工具菜单 -->
        <a-menu
          mode="inline"
          :selected-keys="selectedKeys"
          :inline-collapsed="collapsed"
          style="border: none"
        >
          <a-menu-item v-for="t in currentTools" :key="t.path" @click="navigate(t.path)">
            <component :is="iconMap[t.key]" />
            <span>{{ t.label }}</span>
          </a-menu-item>
        </a-menu>
      </a-layout-sider>

      <!-- 主内容区 -->
      <a-layout-content :style="{ padding: 0, overflow: isAsk ? 'hidden' : 'auto', display: 'flex', flexDirection: 'column' }">
        <!-- 问答页 -->
        <Ask
          v-if="isAsk"
          :key="askRefreshKey"
          :session-id="route.params.sessionId || null"
          :seed="askSeed"
          @session-created="onSessionCreated"
          @session-updated="onSessionUpdated"
        />

        <!-- 工具页 -->
        <div v-else :style="{ maxWidth: isWidePanel ? 'none' : '900px', margin: '0 auto', padding: '24px', width: '100%', overflowY: 'auto' }">
          <a-space align="center" style="margin-bottom: 20px">
            <component :is="iconMap[currentTool.key]" v-if="currentTool.key" />
            <a-typography-title :level=4 style="margin: 0">{{ currentTool.label }}</a-typography-title>
          </a-space>
          <router-view v-slot="{ Component }">
            <component :is="Component" :seed="route.name === 'search' ? searchSeed : null" />
          </router-view>
        </div>
      </a-layout-content>
    </a-layout>
  </a-layout>
  </a-config-provider>
</template>

<style>
body { margin: 0; }
</style>
