<script setup>
import { ref, h, watch, onMounted } from "vue";
import { getStatus, getDigest, getReview } from "../api/index.js";
import {
  ReloadOutlined,
  FileTextOutlined,
  BlockOutlined,
  TagOutlined,
  ApartmentOutlined,
} from "@ant-design/icons-vue";
import axios from "axios";

const status = ref(null);
const digest = ref(null);
const review = ref(null);
const scheduler = ref([]);
const reports = ref([]);
const loading = ref(true);

const RELATION_ICONS = {
  related: "🔗",
  extends: "➡️",
  contradicts: "⚡",
  references: "📖",
};

async function refresh() {
  loading.value = true;
  try {
    const [s, d, r, sch, rp] = await Promise.all([
      getStatus(),
      getDigest(false),
      getReview(5),
      axios.get("/api/scheduler").then((res) => res.data),
      axios.get("/api/digest/reports").then((res) => res.data),
    ]);
    status.value = s;
    digest.value = d;
    review.value = r;
    scheduler.value = sch;
    reports.value = rp;
  } catch (e) {
    console.error(e);
  } finally {
    loading.value = false;
  }
}

function formatTime(iso) {
  const d = new Date(iso);
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(
    d.getMinutes()
  ).padStart(2, "0")}`;
}

function renderMarkdown(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

onMounted(refresh);

const statCards = ref([]);
watch(status, (s) => {
  if (!s) return;
  statCards.value = [
    { title: "笔记总数", value: s.note_count, icon: FileTextOutlined },
    { title: "分块总数", value: s.chunk_count, icon: BlockOutlined },
    { title: "AI 标签", value: s.tag_count, icon: TagOutlined },
    { title: "AI 关联", value: s.connection_count, icon: ApartmentOutlined },
  ];
});
</script>

<template>
  <a-spin :spinning="loading">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px">
      <h3 style="margin: 0">知识库概览</h3>
      <a-button :icon="h(ReloadOutlined)" @click="refresh">刷新</a-button>
    </div>

    <a-space direction="vertical" :size="24" style="width: 100%">
      <!-- 统计卡片 -->
      <a-row :gutter="16">
        <a-col :span="6" v-for="card in statCards" :key="card.title">
          <a-card>
            <a-statistic :title="card.title" :value="card.value">
              <template #prefix>
                <component :is="card.icon" style="font-size: 20px" />
              </template>
            </a-statistic>
          </a-card>
        </a-col>
      </a-row>

      <!-- 热门标签 -->
      <a-card v-if="status?.top_tags?.length" size="small" title="🏷️ 热门标签">
        <a-space wrap>
          <a-tag v-for="t in status.top_tags" :key="t.name" color="blue">
            {{ t.name }} <small>{{ t.count }}</small>
          </a-tag>
        </a-space>
      </a-card>

      <!-- 最近笔记 -->
      <a-card v-if="status?.recent_notes?.length" size="small" title="📝 最近摄入">
        <a-list :data-source="status.recent_notes" size="small">
          <template #renderItem="{ item }">
            <a-list-item>
              <a-list-item-meta>
                <template #title>
                  <span style="font-weight: 500">{{ item.title }}</span>
                </template>
                <template #description>
                  <span style="color: #8c8c8c">[{{ item.date }}]</span>
                  <a-tag v-for="t in item.tags.slice(0, 3)" :key="t" size="small">{{ t }}</a-tag>
                </template>
              </a-list-item-meta>
            </a-list-item>
          </template>
        </a-list>
      </a-card>

      <!-- 关联 -->
      <a-card v-if="status?.connections?.length" size="small" title="🔗 关联一览">
        <a-list :data-source="status.connections" size="small">
          <template #renderItem="{ item }">
            <a-list-item>
              <a-space>
                <span>{{ RELATION_ICONS[item.relation_type] || "🔗" }}</span>
                <a-tag>{{ item.relation_type }}</a-tag>
                <strong>{{ item.source_title }}</strong>
                <span>→</span>
                <strong>{{ item.target_title }}</strong>
              </a-space>
              <div v-if="item.description" style="color: #8c8c8c; font-size: 13px">
                {{ item.description }}
              </div>
            </a-list-item>
          </template>
        </a-list>
      </a-card>

      <!-- 每日摘要 -->
      <a-card v-if="digest?.content" size="small" title="📅 知识摘要">
        <div v-html="renderMarkdown(digest.content)" style="line-height: 1.7"></div>
      </a-card>

      <!-- 复习提醒 -->
      <a-card v-if="review?.items?.length" size="small" :title="`📖 需要复习 (${review.total})`">
        <a-list :data-source="review.items" size="small">
          <template #renderItem="{ item }">
            <a-list-item>
              <a-space>
                <a-badge
                  :color="item.is_new ? 'blue' : item.review_count < 2 ? 'orange' : 'green'"
                />
                <span>{{ item.title }}</span>
                <a-typography-text type="secondary" style="font-size: 12px">
                  {{ item.is_new ? "新卡片" : `第${item.review_count}次 · 间隔${item.interval_days}天` }}
                </a-typography-text>
              </a-space>
            </a-list-item>
          </template>
        </a-list>
      </a-card>

      <!-- 自动摘要报告 -->
      <a-card v-if="reports.length" size="small" title="🗂️ 自动摘要报告">
        <a-collapse>
          <a-collapse-panel
            v-for="rp in reports"
            :key="rp.id"
            :header="`${rp.report_type === 'daily' ? '📅 每日' : '📊 每周'} · ${rp.report_date}`"
          >
            <div v-html="renderMarkdown(rp.content)" style="line-height: 1.7"></div>
          </a-collapse-panel>
        </a-collapse>
      </a-card>

      <!-- 定时任务 -->
      <a-card v-if="scheduler.length" size="small" title="⏰ 定时任务">
        <a-list :data-source="scheduler" size="small">
          <template #renderItem="{ item }">
            <a-list-item>
              <a-list-item-meta>
                <template #title>{{ item.description }}</template>
                <template #description>
                  <a-typography-text type="secondary" style="font-size: 12px">
                    {{ item.last_result || "尚未运行" }}
                  </a-typography-text>
                </template>
              </a-list-item-meta>
              <template #extra>
                <div style="text-align: right; font-size: 12px; color: #8c8c8c">
                  <div>上次: {{ item.last_run_at ? formatTime(item.last_run_at) : "—" }}</div>
                  <div>下次: {{ item.next_run_at ? formatTime(item.next_run_at) : "—" }}</div>
                </div>
              </template>
            </a-list-item>
          </template>
        </a-list>
      </a-card>
    </a-space>
  </a-spin>
</template>
