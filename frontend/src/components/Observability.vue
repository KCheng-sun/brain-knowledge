<script setup>
import { ref } from "vue";
import HealthMetrics from "./observability/HealthMetrics.vue";
import CostGovernance from "./observability/CostGovernance.vue";
import TraceList from "./observability/TraceList.vue";

// 三个子页面：健康/指标/评估、成本治理、调用链
const subTabs = [
  { key: "health", label: "健康·指标·评估", icon: "🩺", component: HealthMetrics },
  { key: "cost", label: "成本治理", icon: "💰", component: CostGovernance },
  { key: "trace", label: "调用链", icon: "🔁", component: TraceList },
];
const activeSub = ref("health");
</script>

<template>
  <div>
    <!-- 子页面 Tab -->
    <div class="sub-tabs">
      <button
        v-for="t in subTabs"
        :key="t.key"
        class="sub-tab"
        :class="{ active: activeSub === t.key }"
        @click="activeSub = t.key"
      >
        <span class="sub-tab-icon">{{ t.icon }}</span>
        <span>{{ t.label }}</span>
      </button>
    </div>

    <!-- 子页面内容 -->
    <component :is="subTabs.find((t) => t.key === activeSub).component" />
  </div>
</template>

<style scoped>
.sub-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 24px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0;
}
.sub-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 18px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  font-size: 14px;
  color: var(--text-dim);
  transition: all 0.15s;
  margin-bottom: -1px;
}
.sub-tab:hover {
  color: var(--text-main);
}
.sub-tab.active {
  color: var(--primary);
  border-bottom-color: var(--primary);
  font-weight: 600;
}
.sub-tab-icon {
  font-size: 15px;
}
</style>
