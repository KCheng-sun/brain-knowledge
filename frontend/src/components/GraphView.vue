<script setup>
import { ref, h, onMounted, onBeforeUnmount, inject } from "vue";
import { ReloadOutlined, CloseOutlined, MessageOutlined } from "@ant-design/icons-vue";
import * as echarts from "echarts";
import axios from "axios";

const jumpToAsk = inject("jumpToAsk", null);

const chartEl = ref(null);
const chart = ref(null);
const loading = ref(true);
const selectedNode = ref(null);
const empty = ref(false);

const RELATION_COLORS = {
  related: "#94a3b8",
  extends: "#1677ff",
  contradicts: "#f56565",
  references: "#36b37e",
};

const RELATION_LABELS = {
  related: "相关",
  extends: "延续",
  contradicts: "矛盾",
  references: "引用",
};

async function refresh() {
  loading.value = true;
  try {
    const { data } = await axios.get("/api/graph");
    renderGraph(data);
    empty.value = data.nodes.length === 0;
  } catch (e) {
    console.error(e);
  } finally {
    loading.value = false;
  }
}

function renderGraph(data) {
  if (!chart.value) {
    chart.value = echarts.init(chartEl.value);
    chart.value.on("click", (params) => {
      if (params.dataType === "node") {
        showNodeDetail(params.data);
      }
    });
  }

  const maxDegree = Math.max(1, ...data.nodes.map((n) => n.degree));
  const connectedIds = new Set();
  data.edges.forEach((e) => {
    connectedIds.add(e.source);
    connectedIds.add(e.target);
  });

  const CATEGORY_COLORS = [
    "#1677ff", "#4096ff", "#36b37e", "#ff9f43",
    "#f56565", "#ec4899", "#06b6d4", "#64748b",
  ];

  const nodes = data.nodes
    .filter((n) => connectedIds.has(n.id))
    .map((n) => ({
      id: n.id,
      name: n.title,
      symbolSize: 14 + (n.degree / maxDegree) * 22,
      category: n.tags[0] || "未分类",
      value: n.degree,
      label: { show: true, fontSize: 11, color: "#1a1a2e" },
      _detail: n,
    }));

  const edges = data.edges.map((e) => ({
    source: e.source,
    target: e.target,
    lineStyle: {
      color: RELATION_COLORS[e.relation_type] || "#94a3b8",
      width: 1 + e.strength * 2,
      curveness: 0.1,
      opacity: 0.7,
    },
    _detail: e,
  }));

  const categories = [...new Set(nodes.map((n) => n.category))].map((c, i) => ({
    name: c,
    itemStyle: { color: CATEGORY_COLORS[i % CATEGORY_COLORS.length] },
  }));

  chart.value.setOption({
    tooltip: {
      trigger: "item",
      formatter: (p) => {
        if (p.dataType === "edge") {
          const d = p.data._detail || {};
          const label = RELATION_LABELS[d.relation_type] || d.relation_type;
          return `${label}关系<br/>强度: ${Math.round((d.strength || 0) * 100)}%${
            d.description ? `<br/>${d.description.slice(0, 80)}` : ""
          }`;
        }
        const d = p.data._detail || {};
        return `<b>${d.title}</b><br/>标签: ${(d.tags || []).join(", ") || "无"}<br/>关联数: ${d.degree}<br/>${d.date}`;
      },
    },
    legend: [{ data: categories.map((c) => c.name), bottom: 10 }],
    series: [
      {
        type: "graph",
        layout: "force",
        data: nodes,
        links: edges,
        roam: true,
        draggable: true,
        categories,
        force: { repulsion: 260, edgeLength: [80, 200], gravity: 0.08 },
        emphasis: { focus: "adjacency", lineStyle: { width: 3 } },
        label: { show: true, position: "right", formatter: (p) => p.name },
      },
    ],
  });
}

function showNodeDetail(node) {
  selectedNode.value = node;
}

function handleResize() {
  chart.value?.resize();
}

onMounted(() => {
  refresh();
  window.addEventListener("resize", handleResize);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", handleResize);
  chart.value?.dispose();
});
</script>

<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px">
      <a-typography-text type="secondary">
        节点大小 = 关联数量；边颜色 = 关联类型；点击节点查看详情
      </a-typography-text>
      <a-button :icon="h(ReloadOutlined)" :loading="loading" @click="refresh">刷新</a-button>
    </div>

    <a-space style="margin-bottom: 14px">
      <span v-for="(color, type) in RELATION_COLORS" :key="type" class="legend-item">
        <span class="legend-line" :style="{ background: color }"></span>
        {{ RELATION_LABELS[type] }}
      </span>
    </a-space>

    <a-empty v-if="empty && !loading">
      <template #description>
        <p>还没有关联数据</p>
        <p style="color: var(--ant-color-text-secondary); font-size: 13px">摄入多篇同主题笔记后，AI 会自动发现关联</p>
      </template>
    </a-empty>

    <div v-show="!empty" ref="chartEl" class="chart-box"></div>

    <!-- 选中节点详情 -->
    <a-card
      v-if="selectedNode"
      size="small"
      class="node-panel"
      :body-style="{ padding: '16px' }"
    >
      <template #title>
        <span style="font-weight: 600">{{ selectedNode._detail.title }}</span>
      </template>
      <template #extra>
        <a-button type="text" size="small" :icon="h(CloseOutlined)" @click="selectedNode = null" />
      </template>
      <a-space direction="vertical" :size="6">
        <div>🏷️ 标签: {{ selectedNode._detail.tags.join(", ") || "无" }}</div>
        <div>🔗 关联数: {{ selectedNode._detail.degree }}</div>
        <div>📅 {{ selectedNode._detail.date }}</div>
      </a-space>
      <a-button
        v-if="jumpToAsk"
        type="primary"
        block
        size="small"
        :icon="h(MessageOutlined)"
        style="margin-top: 12px"
        @click="jumpToAsk(`关于笔记「${selectedNode._detail.title}」，帮我总结要点并找出相关内容`)"
      >
        就此笔记提问
      </a-button>
    </a-card>
  </div>
</template>

<style scoped>
.chart-box {
  height: calc(100vh - 260px);
  min-height: 480px;
}
.node-panel {
  position: fixed;
  right: 24px;
  bottom: 24px;
  width: 300px;
  z-index: 20;
}

/* 图例 */
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: rgba(0, 0, 0, 0.65);
}
.legend-line {
  display: inline-block;
  width: 20px;
  height: 3px;
  border-radius: 2px;
}
</style>
