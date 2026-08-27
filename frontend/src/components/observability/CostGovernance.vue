<script setup>
import { ref, onMounted } from "vue";
import { getCostSummary } from "../../api/index.js";

const costSummary = ref(null);
const loading = ref(true);

async function refresh() {
  loading.value = true;
  try {
    costSummary.value = await getCostSummary();
  } catch (e) {
    console.error("加载成本数据失败", e);
  } finally {
    loading.value = false;
  }
}

// 配额进度百分比（用于进度条）
function usagePct(used, limit) {
  if (!limit) return 0;
  return Math.min(100, ((used || 0) / limit) * 100);
}

onMounted(refresh);
</script>

<template>
  <div>
    <div class="header-row">
      <h3>成本治理</h3>
      <button class="btn-refresh" :disabled="loading" @click="refresh">
        {{ loading ? "刷新中..." : "🔄 刷新" }}
      </button>
    </div>

    <div v-if="costSummary" class="section">
      <h4>💰 成本概览</h4>
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
.section h4 { margin-bottom: 12px; font-size: 16px; color: var(--text-main); }

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
.quota-fill.quota-warn { background: #f39c12; }
.quota-fill.quota-danger { background: var(--danger); }
</style>
