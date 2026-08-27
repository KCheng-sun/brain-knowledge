<script setup>
import { ref, h, onMounted } from "vue";
import { getHealth, getMetricsSummary, getEvalScoreSummary } from "../../api/index.js";
import { ReloadOutlined } from "@ant-design/icons-vue";

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
    console.error(e);
  } finally {
    loading.value = false;
  }
}

function barHeight(count, max) {
  if (!max) return 0;
  return Math.max(4, (count / max) * 100);
}

const hourlyMax = () =>
  summary.value?.by_hour?.reduce((m, h) => Math.max(m, h.ask_count), 0) || 0;

onMounted(refresh);
</script>

<template>
  <a-spin :spinning="loading">
    <div style="display: flex; justify-content: flex-end; margin-bottom: 16px">
      <a-space>
        <a-select v-model:value="hours" style="width: 140px" @change="refresh">
          <a-select-option :value="1">最近 1 小时</a-select-option>
          <a-select-option :value="6">最近 6 小时</a-select-option>
          <a-select-option :value="24">最近 24 小时</a-select-option>
          <a-select-option :value="72">最近 3 天</a-select-option>
          <a-select-option :value="168">最近 7 天</a-select-option>
        </a-select>
        <a-button :icon="h(ReloadOutlined)" @click="refresh">刷新</a-button>
      </a-space>
    </div>

    <a-space direction="vertical" :size="24" style="width: 100%">
      <!-- 健康状态 -->
      <a-card v-if="health" size="small" title="🏥 组件健康">
        <a-row :gutter="12">
          <a-col :span="6" v-for="(status, comp) in health.components" :key="comp">
            <a-card :bordered="false" :body-style="{ textAlign: 'center', padding: '16px' }">
              <a-badge
                :status="status === 'ok' ? 'success' : status === 'skipped' ? 'default' : 'error'"
              />
              <div style="font-weight: 600; margin-top: 8px">{{ comp }}</div>
              <div style="font-size: 11px; color: #8c8c8c">{{ status }}</div>
            </a-card>
          </a-col>
        </a-row>
        <a-alert
          :type="health.status === 'healthy' ? 'success' : health.status === 'degraded' ? 'warning' : 'error'"
          :message="`总体状态: ${health.status}`"
          style="margin-top: 12px"
          show-icon
        />
      </a-card>

      <!-- 指标看板 -->
      <a-card v-if="summary" size="small" title="📊 指标看板">
        <a-row :gutter="12">
          <a-col :span="6">
            <a-statistic title="问答次数" :value="summary.ask_count" />
          </a-col>
          <a-col :span="6">
            <a-statistic title="平均延迟 (ms)" :value="summary.avg_ask_latency_ms" />
          </a-col>
          <a-col :span="6">
            <a-statistic title="工具调用" :value="summary.tool_call_count" />
          </a-col>
          <a-col :span="6">
            <a-statistic title="LLM Token" :value="summary.llm_token_total" />
          </a-col>
        </a-row>
        <a-typography-text v-if="summary.ingest_count" type="secondary" style="margin-top: 12px; display: block">
          📥 摄入 {{ summary.ingest_count }} 次 · 平均耗时 {{ summary.avg_ingest_latency_ms }} ms
        </a-typography-text>

        <div v-if="summary.by_hour?.length" style="margin-top: 16px">
          <div style="font-size: 13px; color: #8c8c8c; margin-bottom: 12px">问答数按小时分布</div>
          <div style="display: flex; align-items: flex-end; gap: 4px; height: 110px">
            <div
              v-for="h in summary.by_hour"
              :key="h.hour"
              style="flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%"
              :title="`${h.hour}点: ${h.ask_count} 次问答, ${h.token_total} token`"
            >
              <div
                :style="{
                  width: '70%',
                  height: barHeight(h.ask_count, hourlyMax()) + 'px',
                  background: 'linear-gradient(180deg, #4f6df5, #3b54d4)',
                  borderRadius: '4px 4px 0 0',
                  minHeight: '4px',
                }"
              ></div>
              <div style="font-size: 10px; color: #8c8c8c; margin-top: 6px">{{ h.hour }}</div>
            </div>
          </div>
        </div>
      </a-card>

      <!-- 评估看板 -->
      <a-card v-if="evalSummary && evalSummary.total > 0" size="small" title="🧪 评估质量">
        <a-row :gutter="12">
          <a-col :span="8">
            <a-statistic title="平均分" :value="evalSummary.avg_score" suffix="/5" />
          </a-col>
          <a-col :span="8">
            <a-statistic title="评估总数" :value="evalSummary.total" />
          </a-col>
          <a-col :span="8">
            <a-statistic title="优质（4-5分）" :value="evalSummary.distribution.good" />
          </a-col>
        </a-row>
        <div style="margin-top: 16px">
          <div style="display: flex; justify-content: space-between; font-size: 13px; color: #8c8c8c; margin-bottom: 6px">
            <span>质量分布</span>
            <span>👍 {{ evalSummary.distribution.good }} · 😐 {{ evalSummary.distribution.mid }} · 👎 {{ evalSummary.distribution.bad }}</span>
          </div>
          <div style="display: flex; height: 12px; border-radius: 6px; overflow: hidden">
            <div :style="{ width: (evalSummary.total ? evalSummary.distribution.good / evalSummary.total * 100 : 0) + '%', background: '#36b37e' }"></div>
            <div :style="{ width: (evalSummary.total ? evalSummary.distribution.mid / evalSummary.total * 100 : 0) + '%', background: '#ff9f43' }"></div>
            <div :style="{ width: (evalSummary.total ? evalSummary.distribution.bad / evalSummary.total * 100 : 0) + '%', background: '#f56565' }"></div>
          </div>
        </div>
      </a-card>
    </a-space>
  </a-spin>
</template>
