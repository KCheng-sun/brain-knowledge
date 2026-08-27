<script setup>
import { ref, onMounted } from "vue";
import { getRecentTraces, getTraceDetail } from "../../api/index.js";

const traces = ref([]);
const selectedTrace = ref(null);
const traceDetail = ref(null);
const expandedEvents = ref(new Set());
const loading = ref(true);

async function refresh() {
  loading.value = true;
  try {
    traces.value = await getRecentTraces(20);
    selectedTrace.value = null;
    traceDetail.value = null;
  } catch (e) {
    console.error("加载调用链失败", e);
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
  expandedEvents.value = new Set();
  try {
    traceDetail.value = await getTraceDetail(traceId);
  } catch (e) {
    console.error("加载 trace 详情失败", e);
  }
}

function toggleEvent(eventId) {
  const s = new Set(expandedEvents.value);
  if (s.has(eventId)) s.delete(eventId);
  else s.add(eventId);
  expandedEvents.value = s;
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
  const avgLatency = latencies.length ? Math.round(latencies.reduce((s, v) => s + v, 0) / latencies.length) : 0;
  return { tokens, tools, avgLatency };
}

function formatTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(
    d.getSeconds()
  ).padStart(2, "0")}`;
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
  <div>
    <div class="header-row">
      <h3>最近调用链</h3>
      <button class="btn-refresh" :disabled="loading" @click="refresh">
        {{ loading ? "刷新中..." : "🔄 刷新" }}
      </button>
    </div>

    <div v-if="traces.length" class="section">
      <div class="trace-list">
        <div
          v-for="t in traces"
          :key="t.trace_id"
          class="trace-item"
          :class="{ expanded: selectedTrace === t.trace_id }"
        >
          <div class="trace-summary" @click="toggleTrace(t.trace_id)">
            <span class="trace-time">{{ formatTime(t.started_at) }}</span>
            <span class="trace-id">{{ t.trace_id }}</span>
            <span class="trace-meta">
              ⏱ {{ t.duration_ms }}ms · 🔧 {{ t.tool_calls }} · 🪙 {{ t.tokens }}
            </span>
            <span class="trace-expand">
              {{ selectedTrace === t.trace_id ? "▼" : "▶" }}
            </span>
          </div>

          <div v-if="selectedTrace === t.trace_id" class="trace-detail">
            <div v-if="!traceDetail" class="detail-loading">加载中...</div>
            <div v-else>
              <div v-if="traceMetricsSummary(traceDetail.metrics)" class="metrics-bar">
                <span>🪙 {{ traceMetricsSummary(traceDetail.metrics).tokens }} token</span>
                <span>🔧 {{ traceMetricsSummary(traceDetail.metrics).tools }} 次工具</span>
                <span>⏱ {{ traceMetricsSummary(traceDetail.metrics).avgLatency }}ms 平均</span>
              </div>

              <div v-if="traceDetail.events?.length" class="events-list">
                <div
                  v-for="e in traceDetail.events"
                  :key="e.id"
                  class="event-card"
                  :class="[e.event_type, { 'has-io': e.input || e.output, expanded: expandedEvents.has(e.id) }]"
                >
                  <div
                    class="event-header"
                    :class="{ clickable: e.input || e.output }"
                    @click="e.input || e.output ? toggleEvent(e.id) : null"
                  >
                    <span class="event-badge" :class="e.event_type">
                      {{ eventIcon(e.event_type) }} {{ eventLabel(e.event_type) }}
                    </span>
                    <span v-if="e.name" class="event-name">{{ e.name }}</span>
                    <span v-if="e.latency_ms" class="event-latency">⏱ {{ e.latency_ms }}ms</span>
                    <span v-if="e.token_usage" class="event-tokens">🪙 {{ e.token_usage.total }}</span>
                    <span class="event-seq">#{{ e.seq }}</span>
                    <span v-if="e.input || e.output" class="event-toggle">
                      {{ expandedEvents.has(e.id) ? "收起" : "展开" }}
                    </span>
                  </div>
                  <div v-if="expandedEvents.has(e.id)" class="event-io-body">
                    <div v-if="e.input" class="event-io">
                      <div class="io-label">📥 入参</div>
                      <pre class="io-content">{{ e.input }}</pre>
                    </div>
                    <div v-if="e.output" class="event-io">
                      <div class="io-label">📤 出参</div>
                      <pre class="io-content">{{ e.output }}</pre>
                    </div>
                  </div>
                </div>
              </div>

              <div
                v-if="!traceDetail.events?.length && !traceDetail.metrics?.length"
                class="detail-empty"
              >无详细事件</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="!loading" class="empty-hint">
      暂无调用链数据。进行一次问答后，这里会显示调用链。
    </div>
  </div>
</template>

<style scoped>
.header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
.btn-refresh {
  padding: 8px 16px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
}
.btn-refresh:hover { opacity: 0.85; }
.btn-refresh:disabled { opacity: 0.5; cursor: not-allowed; }

.section { margin-bottom: 28px; }

.trace-list { display: flex; flex-direction: column; gap: 6px; }
.trace-item {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 8px; overflow: hidden; transition: border-color 0.15s;
}
.trace-item.expanded { border-color: var(--border-glow); }
.trace-summary {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 14px; cursor: pointer; transition: background 0.15s;
}
.trace-summary:hover { background: var(--bg-hover); }
.trace-time { font-size: 12px; color: var(--text-faint); font-family: var(--font-mono); flex-shrink: 0; }
.trace-id { font-size: 12px; color: var(--primary); font-family: var(--font-mono); flex-shrink: 0; }
.trace-meta { flex: 1; font-size: 13px; color: var(--text-dim); }
.trace-expand { color: var(--text-faint); font-size: 12px; }

.trace-detail { border-top: 1px solid var(--border); padding: 8px 14px; background: var(--bg-deep); }
.detail-loading, .detail-empty { padding: 12px; font-size: 13px; color: var(--text-dim); text-align: center; }

.metrics-bar {
  display: flex; gap: 16px; padding: 8px 12px; margin-bottom: 10px;
  background: var(--bg-deep); border-radius: 6px;
  font-size: 12px; color: var(--text-dim); font-family: var(--font-mono);
}

.events-list { display: flex; flex-direction: column; gap: 4px; }
.event-card { border: 1px solid var(--border); border-radius: 6px; background: var(--bg-panel); overflow: hidden; }
.event-card.expanded { border-color: var(--border-glow); }
.event-card.llm { border-left: 3px solid var(--primary); }
.event-card.tool { border-left: 3px solid var(--accent); }
.event-header { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 6px 10px; }
.event-header.clickable { cursor: pointer; }
.event-header.clickable:hover { background: var(--bg-hover); }
.event-badge { font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px; flex-shrink: 0; }
.event-badge.llm { background: rgba(0, 132, 255, 0.15); color: var(--primary); }
.event-badge.tool { background: rgba(0, 184, 212, 0.15); color: var(--accent); }
.event-name { font-size: 12px; color: var(--text-main); font-family: var(--font-mono); }
.event-latency, .event-tokens { font-size: 11px; color: var(--text-dim); font-family: var(--font-mono); }
.event-seq { margin-left: auto; font-size: 11px; color: var(--text-faint); font-family: var(--font-mono); }
.event-toggle { font-size: 11px; color: var(--primary); flex-shrink: 0; }

.event-io-body { padding: 0 10px 8px; border-top: 1px dashed var(--border); }
.event-io { margin-top: 6px; }
.io-label { font-size: 11px; color: var(--text-faint); margin-bottom: 3px; }
.io-content {
  background: var(--bg-deep); border: 1px solid var(--border); border-radius: 4px;
  padding: 8px 10px; font-size: 12px; color: var(--text-main); font-family: var(--font-mono);
  white-space: pre-wrap; word-break: break-word; max-height: 200px; overflow-y: auto; margin: 0;
}

.empty-hint { padding: 40px; text-align: center; color: var(--text-dim); font-size: 14px; }
</style>
