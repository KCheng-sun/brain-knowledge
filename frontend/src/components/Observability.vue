<script setup>
import { ref, h } from "vue";
import HealthMetrics from "./observability/HealthMetrics.vue";
import CostGovernance from "./observability/CostGovernance.vue";
import TraceList from "./observability/TraceList.vue";
import {
  HeartOutlined,
  DollarOutlined,
  NodeIndexOutlined,
} from "@ant-design/icons-vue";

const activeSub = ref("health");
</script>

<template>
  <a-tabs v-model:activeKey="activeSub" type="card">
    <a-tab-pane key="health">
      <template #tab>
        <span><HeartOutlined /> 健康·指标·评估</span>
      </template>
      <HealthMetrics />
    </a-tab-pane>
    <a-tab-pane key="cost">
      <template #tab>
        <span><DollarOutlined /> 成本治理</span>
      </template>
      <CostGovernance />
    </a-tab-pane>
    <a-tab-pane key="trace">
      <template #tab>
        <span><NodeIndexOutlined /> 调用链</span>
      </template>
      <TraceList />
    </a-tab-pane>
  </a-tabs>
</template>
