<script setup>
import { ref, onMounted } from "vue";
import {
  getHealth,
  getMetricsSummary,
  getRecentTraces,
  getTraceDetail,
  getCostSummary,
  getEvalScoreSummary,
} from "../api/index.js";

const health = ref(null);
const summary = ref(null);
const costSummary = ref(null);
const evalSummary = ref(null);
const traces = ref([]);
const selectedTrace = ref(null); // 展开的 trace_id
const traceDetail = ref(null);
const expandedEvents = ref(new Set()); // 展开了入参出参的事件 id 集合
const loading = ref(true);
const hours = ref(24);

async function refresh() {
  loading.value = true;
  try {
    const [h, s, c, es, t] = await Promise.all([
      getHealth(),
      getMetricsSummary(hours.value),
      getCostSummary(),
      getEvalScoreSummary(),
      getRecentTraces(20),
    ]);
    health.value = h;
    summary.value = s;
    costSummary.value = c;
    evalSummary.value = es;
    traces.value = t;
    selectedTrace.value = null;
    traceDetail.value = null;
  } catch (e) {
    console.error("加载可观测性数据失败", e);
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
  expandedEvents.value = new Set(); // 切换 trace 时重置展开状态
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

// 从 metrics 汇总该 trace 的数值指标，内联显示在链路顶部
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
  return {
    llm: "LLM 调用",
    tool: "工具调用",
  }[type] || type;
}

// 配额进度百分比（用于进度条）
function usagePct(used, limit) {
  if (!limit) return 0;
  return Math.min(100, ((used || 0) / limit) * 100);
}

// 按小时分布柱状图的最大值（用于归一化高度）
function barHeight(count, max) {
  if (!max) return 0;
  return Math.max(4, (count / max) * 100); // 最小 4px 保证可见
}

const hourlyMax = () =>
  summary.value?.by_hour?.reduce((m, h) => Math.max(m, h.ask_count), 0) || 0;

onMounted(refresh);
</script>

<template>
  <div>
    <div class="header-row">
      <h3>系统可观测性</h3>
      <div class="header-controls">
        <select v-model.number="hours" @change="refresh" class="hours-select">
          <option :value="1">最近 1 小时</option>
          <option :value="6">最近 6 小时</option>
          <option :value="24">最近 24 小时</option>
          <option :value="72">最近 3 天</option>
          <option :value="168">最近 7 天</option>
        </select>
        <button class="btn-refresh" :disabled="loading" @click="refresh">
          {{ loading ? "刷新中..." : "🔄 刷新" }}
        </button>
      </div>
    </div>

    <!-- 健康状态 -->
    <div v-if="health" class="section">
      <h4>🏥 组件健康</h4>
      <div class="health-grid">
        <div
          v-for="(status, comp) in health.components"
          :key="comp"
          class="health-card"
          :class="{
            ok: status === 'ok',
            skipped: status === 'skipped',
            error: status.startsWith('error'),
          }"
        >
          <div class="health-icon">
            {{ status === "ok" ? "✅" : status === "skipped" ? "⏭️" : "❌" }}
          </div>
          <div class="health-name">{{ comp }}</div>
          <div class="health-status">{{ status }}</div>
        </div>
      </div>
      <div class="health-total" :class="health.status">
        总体状态: <strong>{{ health.status }}</strong>
      </div>
    </div>

    <!-- 指标看板 -->
    <div v-if="summary" class="section">
      <h4>📊 指标看板</h4>
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-num">{{ summary.ask_count }}</div>
          <div class="stat-label">问答次数</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">{{ summary.avg_ask_latency_ms }}</div>
          <div class="stat-label">平均延迟 (ms)</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">{{ summary.tool_call_count }}</div>
          <div class="stat-label">工具调用</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">{{ summary.llm_token_total }}</div>
          <div class="stat-label">LLM Token</div>
        </div>
      </div>

      <!-- 摄入指标 -->
      <div v-if="summary.ingest_count" class="ingest-row">
        📥 摄入 {{ summary.ingest_count }} 次 · 平均耗时
        {{ summary.avg_ingest_latency_ms }} ms
      </div>

      <!-- 按小时分布柱状图 -->
      <div v-if="summary.by_hour?.length" class="chart">
        <div class="chart-title">问答数按小时分布</div>
        <div class="bar-chart">
          <div
            v-for="h in summary.by_hour"
            :key="h.hour"
            class="bar-col"
            :title="`${h.hour}点: ${h.ask_count} 次问答, ${h.token_total} token`"
          >
            <div
              class="bar"
              :style="{ height: barHeight(h.ask_count, hourlyMax()) + 'px' }"
            ></div>
            <div class="bar-label">{{ h.hour }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 成本看板（Phase 5B） -->
    <div v-if="costSummary" class="section">
      <h4>💰 成本治理</h4>
      <div class="cost-grid">
        <div class="cost-card">
          <div class="cost-num">¥{{ costSummary.today.cost.toFixed(4) }}</div>
          <div class="cost-label">今日成本</div>
        </div>
        <div class="cost-card">
          <div class="cost-num">¥{{ costSummary.month.cost.toFixed(2) }}</div>
          <div class="cost-label">本月成本</div>
        </div>
        <div class="cost-card">
          <div class="cost-num">¥{{ costSummary.total.cost.toFixed(2) }}</div>
          <div class="cost-label">总累计</div>
        </div>
      </div>

      <!-- 配额进度条 -->
      <div v-if="costSummary.budget" class="quota-section">
        <div class="quota-item">
          <div class="quota-header">
            <span>日 Token 配额</span>
            <span :class="{ 'quota-warn': usagePct(costSummary.today.tokens, costSummary.budget.limits.daily_token) >= 80 }">
              {{ costSummary.today.tokens?.toLocaleString() }} / {{ costSummary.budget.limits.daily_token?.toLocaleString() }}
            </span>
          </div>
          <div class="quota-bar">
            <div
              class="quota-fill"
              :class="{ 'quota-danger': usagePct(costSummary.today.tokens, costSummary.budget.limits.daily_token) >= 100, 'quota-warn': usagePct(costSummary.today.tokens, costSummary.budget.limits.daily_token) >= 80 }"
              :style="{ width: usagePct(costSummary.today.tokens, costSummary.budget.limits.daily_token) + '%' }"
            ></div>
          </div>
        </div>
        <div class="quota-item">
          <div class="quota-header">
            <span>日成本上限</span>
            <span :class="{ 'quota-warn': usagePct(costSummary.today.cost, costSummary.budget.limits.daily_cost) >= 80 }">
              ¥{{ costSummary.today.cost?.toFixed(4) }} / ¥{{ costSummary.budget.limits.daily_cost }}
            </span>
          </div>
          <div class="quota-bar">
            <div
              class="quota-fill"
              :class="{ 'quota-danger': usagePct(costSummary.today.cost, costSummary.budget.limits.daily_cost) >= 100, 'quota-warn': usagePct(costSummary.today.cost, costSummary.budget.limits.daily_cost) >= 80 }"
              :style="{ width: usagePct(costSummary.today.cost, costSummary.budget.limits.daily_cost) + '%' }"
            ></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 评估看板（Phase 5D FR55） -->
    <div v-if="evalSummary && evalSummary.total > 0" class="section">
      <h4>🧪 评估质量</h4>
      <div class="cost-grid">
        <div class="cost-card">
          <div class="cost-num">{{ evalSummary.avg_score }}/5</div>
          <div class="cost-label">平均分</div>
        </div>
        <div class="cost-card">
          <div class="cost-num">{{ evalSummary.total }}</div>
          <div class="cost-label">评估总数</div>
        </div>
        <div class="cost-card">
          <div class="cost-num">{{ evalSummary.distribution.good }}</div>
          <div class="cost-label">优质（4-5分）</div>
        </div>
      </div>
      <div class="quota-section">
        <div class="quota-item">
          <div class="quota-header">
            <span>质量分布</span>
            <span>👍 {{ evalSummary.distribution.good }} · 😐 {{ evalSummary.distribution.mid }} · 👎 {{ evalSummary.distribution.bad }}</span>
          </div>
          <div class="quota-bar" style="height: 12px; display: flex;">
            <div class="quota-fill" style="width: 0; background: var(--success);" :style="{ width: (evalSummary.total ? evalSummary.distribution.good / evalSummary.total * 100 : 0) + '%' }"></div>
            <div style="background: #f39c12;" :style="{ width: (evalSummary.total ? evalSummary.distribution.mid / evalSummary.total * 100 : 0) + '%' }"></div>
            <div style="background: var(--danger);" :style="{ width: (evalSummary.total ? evalSummary.distribution.bad / evalSummary.total * 100 : 0) + '%' }"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 最近调用链 -->
    <div v-if="traces.length" class="section">
      <h4>🔁 最近调用链</h4>
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

          <!-- 调用链详情 -->
          <div v-if="selectedTrace === t.trace_id" class="trace-detail">
            <div v-if="!traceDetail" class="detail-loading">加载中...</div>
            <div v-else>
              <!-- 数值指标汇总条（内联在链路顶部，不单独占区） -->
              <div v-if="traceMetricsSummary(traceDetail.metrics)" class="metrics-bar">
                <span>🪙 {{ traceMetricsSummary(traceDetail.metrics).tokens }} token</span>
                <span>🔧 {{ traceMetricsSummary(traceDetail.metrics).tools }} 次工具</span>
                <span>⏱ {{ traceMetricsSummary(traceDetail.metrics).avgLatency }}ms 平均</span>
              </div>

              <!-- 调用链事件（点击展开入参出参） -->
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
                    <span v-if="e.token_usage" class="event-tokens">
                      🪙 {{ e.token_usage.total }}
                    </span>
                    <span class="event-seq">#{{ e.seq }}</span>
                    <span
                      v-if="e.input || e.output"
                      class="event-toggle"
                    >{{ expandedEvents.has(e.id) ? "收起" : "展开" }}</span>
                  </div>
                  <!-- 入参出参（默认收起，点击展开） -->
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
      暂无可观测性数据。进行一次问答后，这里会显示调用链和指标。
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
.header-controls {
  display: flex;
  gap: 10px;
  align-items: center;
}
.hours-select {
  padding: 7px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-panel);
  font-size: 13px;
  color: var(--text-main);
  cursor: pointer;
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
.btn-refresh:hover {
  opacity: 0.85;
}
.btn-refresh:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.section {
  margin-bottom: 28px;
}
.section h4 {
  margin-bottom: 12px;
  font-size: 16px;
  color: var(--text-main);
}

/* 健康状态卡片 */
.health-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.health-card {
  text-align: center;
  padding: 16px 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  transition: all 0.2s;
}
.health-card.ok {
  border-color: var(--success);
  background: rgba(16, 185, 129, 0.06);
}
.health-card.skipped {
  border-color: var(--text-faint);
  background: rgba(147, 168, 196, 0.08);
}
.health-card.error {
  border-color: var(--danger);
  background: rgba(239, 68, 68, 0.06);
}
.health-icon {
  font-size: 22px;
}
.health-name {
  font-size: 14px;
  font-weight: 600;
  margin-top: 6px;
  color: var(--text-main);
  text-transform: capitalize;
}
.health-status {
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 4px;
  font-family: var(--font-mono);
  word-break: break-all;
}
.health-total {
  margin-top: 12px;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 14px;
  text-align: center;
}
.health-total.healthy {
  background: rgba(16, 185, 129, 0.1);
  color: var(--success);
}
.health-total.degraded {
  background: rgba(243, 156, 18, 0.1);
  color: #f39c12;
}
.health-total.unhealthy {
  background: rgba(239, 68, 68, 0.1);
  color: var(--danger);
}

/* 指标看板 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 12px;
}
.stat-card {
  text-align: center;
  padding: 20px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
}
.stat-num {
  font-size: 28px;
  font-weight: 700;
  color: var(--primary);
  font-family: var(--font-mono);
}
.stat-label {
  font-size: 13px;
  color: var(--text-dim);
  margin-top: 4px;
}
.ingest-row {
  font-size: 13px;
  color: var(--text-dim);
  padding: 8px 0;
}

/* 成本看板 */
.cost-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.cost-card {
  text-align: center;
  padding: 20px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
}
.cost-num {
  font-size: 24px;
  font-weight: 700;
  color: var(--success);
  font-family: var(--font-mono);
}
.cost-label {
  font-size: 13px;
  color: var(--text-dim);
  margin-top: 4px;
}

/* 配额进度条 */
.quota-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.quota-item {
  padding: 4px 0;
}
.quota-header {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: var(--text-dim);
  margin-bottom: 6px;
}
.quota-header .quota-warn {
  color: #f39c12;
  font-weight: 600;
}
.quota-bar {
  height: 8px;
  background: var(--bg-deep);
  border-radius: 4px;
  overflow: hidden;
}
.quota-fill {
  height: 100%;
  background: var(--success);
  border-radius: 4px;
  transition: width 0.3s;
}
.quota-fill.quota-warn {
  background: #f39c12;
}
.quota-fill.quota-danger {
  background: var(--danger);
}

/* 柱状图 */
.chart {
  margin-top: 16px;
  padding: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
}
.chart-title {
  font-size: 13px;
  color: var(--text-dim);
  margin-bottom: 12px;
}
.bar-chart {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  height: 110px;
}
.bar-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  height: 100%;
}
.bar {
  width: 70%;
  background: linear-gradient(180deg, var(--primary), var(--primary-dim));
  border-radius: 4px 4px 0 0;
  min-height: 4px;
  transition: height 0.3s;
}
.bar-label {
  font-size: 10px;
  color: var(--text-faint);
  margin-top: 6px;
  font-family: var(--font-mono);
}

/* 调用链 */
.trace-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.trace-item {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  transition: border-color 0.15s;
}
.trace-item.expanded {
  border-color: var(--border-glow);
}
.trace-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  cursor: pointer;
  transition: background 0.15s;
}
.trace-summary:hover {
  background: var(--bg-hover);
}
.trace-time {
  font-size: 12px;
  color: var(--text-faint);
  font-family: var(--font-mono);
  flex-shrink: 0;
}
.trace-id {
  font-size: 12px;
  color: var(--primary);
  font-family: var(--font-mono);
  flex-shrink: 0;
}
.trace-meta {
  flex: 1;
  font-size: 13px;
  color: var(--text-dim);
}
.trace-expand {
  color: var(--text-faint);
  font-size: 12px;
}

/* 调用链详情 */
.trace-detail {
  border-top: 1px solid var(--border);
  padding: 8px 14px;
  background: var(--bg-deep);
}
.detail-loading,
.detail-empty {
  padding: 12px;
  font-size: 13px;
  color: var(--text-dim);
  text-align: center;
}

/* 调用链事件卡片 */
/* 数值指标汇总条（内联在链路顶部） */
.metrics-bar {
  display: flex;
  gap: 16px;
  padding: 8px 12px;
  margin-bottom: 10px;
  background: var(--bg-deep);
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-dim);
  font-family: var(--font-mono);
}

/* 调用链事件列表 */
.events-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.event-card {
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-panel);
  /* 收起状态下更紧凑 */
  overflow: hidden;
}
.event-card.expanded {
  border-color: var(--border-glow);
}
.event-card.llm {
  border-left: 3px solid var(--primary);
}
.event-card.tool {
  border-left: 3px solid var(--accent);
}
.event-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 6px 10px;
}
.event-header.clickable {
  cursor: pointer;
}
.event-header.clickable:hover {
  background: var(--bg-hover);
}
.event-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 4px;
  flex-shrink: 0;
}
.event-badge.llm {
  background: rgba(0, 132, 255, 0.15);
  color: var(--primary);
}
.event-badge.tool {
  background: rgba(0, 184, 212, 0.15);
  color: var(--accent);
}
.event-name {
  font-size: 12px;
  color: var(--text-main);
  font-family: var(--font-mono);
}
.event-latency,
.event-tokens {
  font-size: 11px;
  color: var(--text-dim);
  font-family: var(--font-mono);
}
.event-seq {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-faint);
  font-family: var(--font-mono);
}
.event-toggle {
  font-size: 11px;
  color: var(--primary);
  flex-shrink: 0;
}

/* 入参出参（展开时显示） */
.event-io-body {
  padding: 0 10px 8px;
  border-top: 1px dashed var(--border);
}
.event-io {
  margin-top: 6px;
}
.io-label {
  font-size: 11px;
  color: var(--text-faint);
  margin-bottom: 3px;
}
.io-content {
  background: var(--bg-deep);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 12px;
  color: var(--text-main);
  font-family: var(--font-mono);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
  margin: 0;
}

.empty-hint {
  padding: 40px;
  text-align: center;
  color: var(--text-dim);
  font-size: 14px;
}
</style>
