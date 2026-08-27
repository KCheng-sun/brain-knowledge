<script setup>
import { ref, h, onMounted } from "vue";
import { getCostSummary } from "../../api/index.js";
import { ReloadOutlined } from "@ant-design/icons-vue";

const costSummary = ref(null);
const loading = ref(true);

async function refresh() {
  loading.value = true;
  try {
    costSummary.value = await getCostSummary();
  } catch (e) {
    console.error(e);
  } finally {
    loading.value = false;
  }
}

function usagePct(used, limit) {
  if (!limit) return 0;
  return Math.min(100, ((used || 0) / limit) * 100);
}

onMounted(refresh);
</script>

<template>
  <a-spin :spinning="loading">
    <div style="display: flex; justify-content: flex-end; margin-bottom: 16px">
      <a-button :icon="h(ReloadOutlined)" @click="refresh">刷新</a-button>
    </div>

    <a-space direction="vertical" :size="24" style="width: 100%">
      <a-card v-if="costSummary" size="small" title="💰 成本概览">
        <a-row :gutter="12">
          <a-col :span="8">
            <a-statistic title="今日成本" :value="costSummary.today.cost" prefix="¥" :precision="4" />
          </a-col>
          <a-col :span="8">
            <a-statistic title="本月成本" :value="costSummary.month.cost" prefix="¥" :precision="2" />
          </a-col>
          <a-col :span="8">
            <a-statistic title="总累计" :value="costSummary.total.cost" prefix="¥" :precision="2" />
          </a-col>
        </a-row>

        <div v-if="costSummary.budget" style="margin-top: 24px">
          <div style="margin-bottom: 16px">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; gap: 12px; flex-wrap: wrap">
              <span style="flex-shrink: 0">日 Token 配额</span>
              <span style="text-align: right; word-break: break-all; font-size: 12px">
                {{ costSummary.today.tokens?.toLocaleString() }} /
                {{ costSummary.budget.limits.daily_token?.toLocaleString() }}
              </span>
            </div>
            <a-progress
              :show-info="false"
              :percent="usagePct(costSummary.today.tokens, costSummary.budget.limits.daily_token)"
              :stroke-color="usagePct(costSummary.today.tokens, costSummary.budget.limits.daily_token) >= 100 ? '#ff4d4f' : usagePct(costSummary.today.tokens, costSummary.budget.limits.daily_token) >= 80 ? '#faad14' : '#52c41a'"
            />
          </div>
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; gap: 12px; flex-wrap: wrap">
              <span style="flex-shrink: 0">日成本上限</span>
              <span style="text-align: right; word-break: break-all; font-size: 12px">
                ¥{{ costSummary.today.cost?.toFixed(4) }} /
                ¥{{ costSummary.budget.limits.daily_cost }}
              </span>
            </div>
            <a-progress
              :show-info="false"
              :percent="usagePct(costSummary.today.cost, costSummary.budget.limits.daily_cost)"
              :stroke-color="usagePct(costSummary.today.cost, costSummary.budget.limits.daily_cost) >= 100 ? '#ff4d4f' : usagePct(costSummary.today.cost, costSummary.budget.limits.daily_cost) >= 80 ? '#faad14' : '#52c41a'"
            />
          </div>
        </div>
      </a-card>
    </a-space>
  </a-spin>
</template>
