<script setup>
import { ref, onMounted } from "vue";
import { getHealth, getMetricsSummary, getEvalScoreSummary } from "../../api/index.js";

const health = ref(null);
const summary = ref(null);
const evalSummary = ref(null);
const loading = ref(true);
const hours = ref(24);

async function refresh() {
  loading.value = true;
  try {
    const [h, s, es] = await Promise.all([
      getHealth(),
      getMetricsSummary(hours.value),
      getEvalScoreSummary(),
    ]);
    health.value = h;
    summary.value = s;
    evalSummary.value = es;
  } catch (e) {
    console.error("加载健康/指标/评估数据失败", e);
  } finally {
    loading.value = false;
  }
}

// 按小时分布柱状图的最大值（用于归一化高度）
function barHeight(count, max) {
  if (!max) return 0;
  return Math.max(4, (count / max) * 100);
}

const hourlyMax = () =>
  summary.value?.by_hour?.reduce((m, h) => Math.max(m, h.ask_count), 0) || 0;

onMounted(refresh);
</script>

<template>
  <div>
    <div class="header-row">
      <h3>健康 · 指标 · 评估</h3>
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

      <div v-if="summary.ingest_count" class="ingest-row">
        📥 摄入 {{ summary.ingest_count }} 次 · 平均耗时
        {{ summary.avg_ingest_latency_ms }} ms
      </div>

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
.btn-refresh:hover { opacity: 0.85; }
.btn-refresh:disabled { opacity: 0.5; cursor: not-allowed; }

.section { margin-bottom: 28px; }
.section h4 { margin-bottom: 12px; font-size: 16px; color: var(--text-main); }

.health-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.health-card {
  text-align: center; padding: 16px 12px;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 12px; transition: all 0.2s;
}
.health-card.ok { border-color: var(--success); background: rgba(16, 185, 129, 0.06); }
.health-card.skipped { border-color: var(--text-faint); background: rgba(147, 168, 196, 0.08); }
.health-card.error { border-color: var(--danger); background: rgba(239, 68, 68, 0.06); }
.health-icon { font-size: 22px; }
.health-name { font-size: 14px; font-weight: 600; margin-top: 6px; color: var(--text-main); text-transform: capitalize; }
.health-status { font-size: 11px; color: var(--text-dim); margin-top: 4px; font-family: var(--font-mono); word-break: break-all; }
.health-total { margin-top: 12px; padding: 8px 14px; border-radius: 8px; font-size: 14px; text-align: center; }
.health-total.healthy { background: rgba(16, 185, 129, 0.1); color: var(--success); }
.health-total.degraded { background: rgba(243, 156, 18, 0.1); color: #f39c12; }
.health-total.unhealthy { background: rgba(239, 68, 68, 0.1); color: var(--danger); }

.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 12px; }
.stat-card { text-align: center; padding: 20px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; }
.stat-num { font-size: 28px; font-weight: 700; color: var(--primary); font-family: var(--font-mono); }
.stat-label { font-size: 13px; color: var(--text-dim); margin-top: 4px; }
.ingest-row { font-size: 13px; color: var(--text-dim); padding: 8px 0; }

.chart { margin-top: 16px; padding: 16px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; }
.chart-title { font-size: 13px; color: var(--text-dim); margin-bottom: 12px; }
.bar-chart { display: flex; align-items: flex-end; gap: 4px; height: 110px; }
.bar-col { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; }
.bar { width: 70%; background: linear-gradient(180deg, var(--primary), var(--primary-dim)); border-radius: 4px 4px 0 0; min-height: 4px; transition: height 0.3s; }
.bar-label { font-size: 10px; color: var(--text-faint); margin-top: 6px; font-family: var(--font-mono); }

.cost-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 16px; }
.cost-card { text-align: center; padding: 20px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; }
.cost-num { font-size: 24px; font-weight: 700; color: var(--success); font-family: var(--font-mono); }
.cost-label { font-size: 13px; color: var(--text-dim); margin-top: 4px; }

.quota-section { display: flex; flex-direction: column; gap: 12px; }
.quota-item { padding: 4px 0; }
.quota-header { display: flex; justify-content: space-between; font-size: 13px; color: var(--text-dim); margin-bottom: 6px; }
.quota-header .quota-warn { color: #f39c12; font-weight: 600; }
.quota-bar { height: 8px; background: var(--bg-deep); border-radius: 4px; overflow: hidden; }
.quota-fill { height: 100%; background: var(--success); border-radius: 4px; transition: width 0.3s; }
</style>
