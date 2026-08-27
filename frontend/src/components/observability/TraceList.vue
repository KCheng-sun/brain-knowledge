<script setup>
import { ref, h, onMounted } from "vue";
import { getRecentTraces, getTraceDetail } from "../../api/index.js";
import { ReloadOutlined } from "@ant-design/icons-vue";

const traces = ref([]);
const selectedTrace = ref(null);
const traceDetail = ref(null);
const expandedKeys = ref({});
const loading = ref(true);

async function refresh() {
  loading.value = true;
  try {
    traces.value = await getRecentTraces(20);
    selectedTrace.value = null;
    traceDetail.value = null;
  } catch (e) {
    console.error(e);
  } finally {
    loading.value = false;
  }
}

async function toggleTrace(traceId) {
  if (selectedTrace.value === traceId) {
    selectedTrace.value = null;
    traceDetail.value = null;
    return;
  }
  selectedTrace.value = traceId;
  traceDetail.value = null;
  expandedKeys.value = {};
  try {
    traceDetail.value = await getTraceDetail(traceId);
  } catch (e) {
    console.error(e);
  }
}

function traceMetricsSummary(metrics) {
  if (!metrics?.length) return null;
  const tokens = metrics
    .filter((m) => m.metric_type === "llm_call")
    .reduce((s, m) => s + m.value, 0);
  const tools = metrics.filter((m) => m.metric_type === "tool_call").length;
  const latencies = metrics
    .filter((m) => m.metric_type === "ask" && m.metric_name === "latency_ms")
    .map((m) => m.value);
  const avgLatency = latencies.length
    ? Math.round(latencies.reduce((s, v) => s + v, 0) / latencies.length)
    : 0;
  return { tokens, tools, avgLatency };
}

function formatTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(
    d.getMinutes()
  ).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

function eventIcon(type) {
  return { llm: "🤖", tool: "🔧" }[type] || "•";
}

function eventLabel(type) {
  return { llm: "LLM 调用", tool: "工具调用" }[type] || type;
}

onMounted(refresh);
</script>

<template>
  <a-spin :spinning="loading">
    <div style="display: flex; justify-content: flex-end; margin-bottom: 16px">
      <a-button :icon="h(ReloadOutlined)" @click="refresh">刷新</a-button>
    </div>

    <a-list v-if="traces.length" :data-source="traces" :split="true">
      <template #renderItem="{ item }">
        <a-list-item>
          <a-space direction="vertical" style="width: 100%" :size="8">
            <a-space block style="width: 100%; cursor: pointer" :size="12" align="center" @click="toggleTrace(item.trace_id)">
              <a-typography-text type="secondary" style="font-size: 12px">{{ formatTime(item.started_at) }}</a-typography-text>
              <a-typography-text style="font-size: 12px; color: #1677ff">{{ item.trace_id }}</a-typography-text>
              <a-typography-text style="flex: 1; font-size: 13px">
                ⏱ {{ item.duration_ms }}ms · 🔧 {{ item.tool_calls }} · 🪙 {{ item.tokens }}
              </a-typography-text>
              <a-typography-text type="secondary">{{ selectedTrace === item.trace_id ? "▼" : "▶" }}</a-typography-text>
            </a-space>

            <div v-if="selectedTrace === item.trace_id" style="padding-left: 12px; width: 100%">
              <a-spin v-if="!traceDetail" size="small" />
              <div v-else>
                <a-space v-if="traceMetricsSummary(traceDetail.metrics)" style="margin-bottom: 12px">
                  <a-tag>🪙 {{ traceMetricsSummary(traceDetail.metrics).tokens }} token</a-tag>
                  <a-tag>🔧 {{ traceMetricsSummary(traceDetail.metrics).tools }} 次工具</a-tag>
                  <a-tag>⏱ {{ traceMetricsSummary(traceDetail.metrics).avgLatency }}ms 平均</a-tag>
                </a-space>

                <a-list
                  v-if="traceDetail.events?.length"
                  :data-source="traceDetail.events"
                  size="small"
                  :split="false"
                >
                  <template #renderItem="{ item: e }">
                    <a-list-item style="padding: 6px 0">
                      <a-card
                        size="small"
                        :bordered="true"
                        :body-style="{ padding: '8px 12px' }"
                        :style="{ borderLeft: e.event_type === 'llm' ? '3px solid #1677ff' : '3px solid #722ed1' }"
                      >
                        <a-space block style="width: 100%" :size="8" wrap>
                          <a-tag :color="e.event_type === 'llm' ? 'blue' : 'purple'">
                            {{ eventIcon(e.event_type) }} {{ eventLabel(e.event_type) }}
                          </a-tag>
                          <a-typography-text v-if="e.name" style="font-size: 12px">{{ e.name }}</a-typography-text>
                          <a-typography-text v-if="e.latency_ms" type="secondary" style="font-size: 11px">⏱ {{ e.latency_ms }}ms</a-typography-text>
                          <a-typography-text v-if="e.token_usage" type="secondary" style="font-size: 11px">🪙 {{ e.token_usage.total }}</a-typography-text>
                          <a-typography-text type="secondary" style="font-size: 11px; margin-left: auto">#{{ e.seq }}</a-typography-text>
                        </a-space>

                        <a-collapse
                          v-if="e.input || e.output"
                          v-model:active-key="expandedKeys[e.id]"
                          :bordered="false"
                          ghost
                          size="small"
                          style="margin-top: 4px"
                        >
                          <a-collapse-panel key="detail" header="查看入参/出参">
                            <a-descriptions v-if="e.input" :column="1" size="small" bordered style="margin-bottom: 8px">
                              <a-descriptions-item label="📥 入参">
                                <a-typography-paragraph
                                  style="margin: 0; font-size: 12px; white-space: pre-wrap; word-break: break-word; max-height: 200px; overflow-y: auto"
                                  :copyable="{ text: e.input }"
                                >{{ e.input }}</a-typography-paragraph>
                              </a-descriptions-item>
                            </a-descriptions>
                            <a-descriptions v-if="e.output" :column="1" size="small" bordered>
                              <a-descriptions-item label="📤 出参">
                                <a-typography-paragraph
                                  style="margin: 0; font-size: 12px; white-space: pre-wrap; word-break: break-word; max-height: 200px; overflow-y: auto"
                                  :copyable="{ text: e.output }"
                                >{{ e.output }}</a-typography-paragraph>
                              </a-descriptions-item>
                            </a-descriptions>
                          </a-collapse-panel>
                        </a-collapse>
                      </a-card>
                    </a-list-item>
                  </template>
                </a-list>

                <a-empty
                  v-if="!traceDetail.events?.length && !traceDetail.metrics?.length"
                  description="无详细事件"
                />
              </div>
            </div>
          </a-space>
        </a-list-item>
      </template>
    </a-list>

    <a-empty v-else-if="!loading" description="暂无调用链数据。进行一次问答后会显示调用链。" />
  </a-spin>
</template>
