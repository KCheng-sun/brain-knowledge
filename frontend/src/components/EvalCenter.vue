<script setup>
import { ref, reactive, computed, h, onMounted } from "vue";
import { message, Modal } from "ant-design-vue";
import {
  getEvalScoreSummary,
  getEvalScores,
  runEvalDataset,
  runJudgeSample,
  getBadCases,
  deleteBadCase,
  badCaseToGolden,
  getGoldenCases,
  saveGoldenCase,
  deleteGoldenCase,
  toggleGoldenCase,
  seedGoldenCases,
  getEvalRuns,
} from "../api/index.js";
import {
  ReloadOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ImportOutlined,
} from "@ant-design/icons-vue";

const evalSummary = ref(null);
const evalScores = ref([]);
const badCases = ref([]);
const goldenCases = ref([]);
const evalRuns = ref([]);
const evalReport = ref(null);
const judgeResults = ref(null);
const running = ref("");
const activeTab = ref("overview");

const offlineRuns = computed(() => evalRuns.value.filter((r) => r.run_type === "offline"));
const judgeRuns = computed(() => evalRuns.value.filter((r) => r.run_type === "judge"));

// Golden case 编辑
const editing = ref(false);
const editForm = reactive({
  id: "",
  question: "",
  expected_keywords: [],
  expected_sources: [],
  min_score: 0.7,
  enabled: true,
});
const keywordInput = ref("");

async function refresh() {
  try {
    const [s, sc, bc, gc, er] = await Promise.all([
      getEvalScoreSummary(),
      getEvalScores(50),
      getBadCases(),
      getGoldenCases(),
      getEvalRuns(20),
    ]);
    evalSummary.value = s;
    evalScores.value = sc;
    badCases.value = bc;
    goldenCases.value = gc;
    evalRuns.value = er;
  } catch (e) {
    console.error(e);
  }
}

async function runEval() {
  running.value = "eval";
  evalReport.value = null;
  try {
    evalReport.value = await runEvalDataset(0);
    message.success("评估完成");
  } catch (e) {
    message.error("评估失败: " + e.message);
  } finally {
    running.value = "";
    refresh();
  }
}

async function runJudge() {
  running.value = "judge";
  judgeResults.value = null;
  try {
    judgeResults.value = await runJudgeSample(0.1, 10);
    message.success("Judge 完成");
  } catch (e) {
    message.error("Judge 失败: " + e.message);
  } finally {
    running.value = "";
    refresh();
  }
}

// ---- Golden case CRUD ----
function startNewCase() {
  Object.assign(editForm, {
    id: "",
    question: "",
    expected_keywords: [],
    expected_sources: [],
    min_score: 0.7,
    enabled: true,
  });
  editing.value = true;
}

function startEditCase(c) {
  Object.assign(editForm, {
    id: c.id,
    question: c.question,
    expected_keywords: [...c.expected_keywords],
    expected_sources: [...c.expected_sources],
    min_score: c.min_score,
    enabled: c.enabled,
  });
  editing.value = true;
}

function addKeyword() {
  const kw = keywordInput.value.trim();
  if (kw && !editForm.expected_keywords.includes(kw)) {
    editForm.expected_keywords.push(kw);
  }
  keywordInput.value = "";
}

async function saveCase() {
  if (!editForm.id || !editForm.question) {
    message.warning("请填写 ID 和问题");
    return;
  }
  try {
    await saveGoldenCase(editForm);
    message.success("已保存");
    editing.value = false;
    refresh();
  } catch (e) {
    message.error("保存失败: " + e.message);
  }
}

function removeCase(id) {
  Modal.confirm({
    title: "删除用例",
    content: `确认删除 ${id}？`,
    okText: "删除",
    okType: "danger",
    cancelText: "取消",
    onOk: async () => {
      await deleteGoldenCase(id);
      message.success("已删除");
      refresh();
    },
  });
}

async function toggleCase(id) {
  await toggleGoldenCase(id);
  refresh();
}

function doSeed() {
  Modal.confirm({
    title: "从 YAML 导入",
    content: "已有相同 id 会被覆盖，确认导入？",
    onOk: async () => {
      try {
        const r = await seedGoldenCases();
        message.success(r.message);
        refresh();
      } catch (e) {
        message.error("导入失败: " + e.message);
      }
    },
  });
}

function removeBadCase(id) {
  Modal.confirm({
    title: "删除 Bad Case",
    okText: "删除",
    okType: "danger",
    cancelText: "取消",
    onOk: async () => {
      await deleteBadCase(id);
      message.success("已删除");
      refresh();
    },
  });
}

async function promoteBadCase(id) {
  try {
    const r = await badCaseToGolden(id);
    message.success(r.message);
    refresh();
  } catch (e) {
    message.error("转换失败");
  }
}

function formatTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(
    d.getMinutes()
  ).padStart(2, "0")}`;
}

function scoreColor(score) {
  return score >= 4 ? "success" : score === 3 ? "warning" : "error";
}

onMounted(refresh);
</script>

<template>
  <div>
    <div style="display: flex; justify-content: flex-end; margin-bottom: 16px">
      <a-button :icon="h(ReloadOutlined)" @click="refresh">刷新</a-button>
    </div>

    <a-tabs v-model:activeKey="activeTab">
      <!-- 总览 -->
      <a-tab-pane key="overview" tab="📊 总览">
        <a-row :gutter="12" style="margin-bottom: 20px">
          <a-col :span="8">
            <a-card><a-statistic title="Judge 平均分" :value="evalSummary?.avg_score || 0" suffix="/5" /></a-card>
          </a-col>
          <a-col :span="8">
            <a-card><a-statistic title="测试用例（启用）" :value="`${goldenCases.filter(c => c.enabled).length}/${goldenCases.length}`" /></a-card>
          </a-col>
          <a-col :span="8">
            <a-card><a-statistic title="Bad Cases" :value="badCases.length" /></a-card>
          </a-col>
        </a-row>

        <a-card v-if="evalScores.length" size="small" title="最近 Judge 打分">
          <a-list :data-source="evalScores.slice(0, 10)" size="small">
            <template #renderItem="{ item }">
              <a-list-item>
                <a-space>
                  <a-tag :color="scoreColor(item.score)">{{ item.score }}/5</a-tag>
                  <span>{{ item.question.slice(0, 40) }}</span>
                  <a-typography-text v-if="item.comment" type="secondary" style="font-size: 12px">
                    {{ item.comment.slice(0, 50) }}
                  </a-typography-text>
                  <span style="font-size: 11px; color: #bfbfbf">{{ formatTime(item.judged_at) }}</span>
                </a-space>
              </a-list-item>
            </template>
          </a-list>
        </a-card>
      </a-tab-pane>

      <!-- 离线评估 -->
      <a-tab-pane key="eval" tab="🧪 离线评估">
        <a-card size="small" style="margin-bottom: 16px">
          <div style="display: flex; justify-content: space-between; align-items: center">
            <div>
              <h4 style="margin: 0">离线评估测试集</h4>
              <a-typography-text type="secondary" style="font-size: 12px">
                从数据库加载启用的 golden cases，逐条问答并规则打分
              </a-typography-text>
            </div>
            <a-button type="primary" :icon="h(PlayCircleOutlined)" :loading="running === 'eval'" @click="runEval">
              运行评估
            </a-button>
          </div>
        </a-card>

        <a-alert v-if="running === 'eval'" type="info" show-icon message="⏳ 正在逐条问答打分，可能需要 1-2 分钟..." style="margin-bottom: 16px" />

        <a-card v-if="evalReport && !evalReport.error" size="small" style="margin-bottom: 16px">
          <a-result
            :status="evalReport.passed === evalReport.total ? 'success' : 'warning'"
            :title="`${evalReport.passed}/${evalReport.total} 通过`"
            :sub-title="`通过率 ${(evalReport.pass_rate * 100).toFixed(1)}% · 平均分 ${evalReport.avg_score} · ${evalReport.duration_ms}ms`"
          />
          <a-list :data-source="evalReport.results" size="small">
            <template #renderItem="{ item }">
              <a-list-item>
                <a-space>
                  <span>{{ item.passed ? "✅" : "❌" }}</span>
                  <code style="font-size: 12px; color: #8c8c8c">{{ item.id }}</code>
                  <span>{{ item.question.slice(0, 40) }}</span>
                  <a-tag>得分 {{ item.score }}（阈值 {{ item.min_score }}）</a-tag>
                </a-space>
                <div v-if="item.details" style="font-size: 12px; color: #8c8c8c; margin-top: 4px">
                  关键词 {{ item.details.keyword_score }} · 来源 {{ item.details.source_score }} · 完整性 {{ item.details.complete_score }}
                  <span v-if="item.details.missed_keywords?.length" style="color: #ff4d4f">
                    · 未命中: {{ item.details.missed_keywords.join(", ") }}
                  </span>
                </div>
              </a-list-item>
            </template>
          </a-list>
        </a-card>

        <a-card v-if="offlineRuns.length" size="small" title="📜 历史记录">
          <a-collapse>
            <a-collapse-panel v-for="r in offlineRuns" :key="r.id"
              :header="`🧪 离线评估 · ${formatTime(r.created_at)} · 通过 ${r.passed}/${r.total}（${r.pass_rate ? (r.pass_rate * 100).toFixed(0) : 0}%）`"
            >
              <a-list v-if="r.details?.results" :data-source="r.details.results" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <a-space>
                      <span>{{ item.passed ? "✅" : "❌" }}</span>
                      <code style="font-size: 12px">{{ item.id }}</code>
                      <span>{{ item.question?.slice(0, 35) }}</span>
                      <a-tag>{{ item.score }}（阈值 {{ item.min_score }}）</a-tag>
                    </a-space>
                  </a-list-item>
                </template>
              </a-list>
            </a-collapse-panel>
          </a-collapse>
        </a-card>
      </a-tab-pane>

      <!-- 测试集管理 -->
      <a-tab-pane key="golden" tab="📋 测试集管理">
        <div style="display: flex; justify-content: space-between; margin-bottom: 16px">
          <h4 style="margin: 0">Golden Cases</h4>
          <a-space>
            <a-button :icon="h(ImportOutlined)" @click="doSeed">从 YAML 导入</a-button>
            <a-button type="primary" :icon="h(PlusOutlined)" @click="startNewCase">新增用例</a-button>
          </a-space>
        </div>

        <a-list :data-source="goldenCases">
          <template #renderItem="{ item }">
            <a-list-item>
              <a-card size="small" style="width: 100%" :bordered="true">
                <template #title>
                  <a-space>
                    <code>{{ item.id }}</code>
                    <a-switch :checked="item.enabled" size="small" @change="toggleCase(item.id)" />
                  </a-space>
                </template>
                <template #extra>
                  <a-space>
                    <a-button type="text" size="small" :icon="h(EditOutlined)" @click="startEditCase(item)" />
                    <a-button type="text" size="small" danger :icon="h(DeleteOutlined)" @click="removeCase(item.id)" />
                  </a-space>
                </template>
                <p style="margin: 0 0 8px">{{ item.question }}</p>
                <a-space wrap>
                  <a-tag v-for="kw in item.expected_keywords" :key="kw">{{ kw }}</a-tag>
                  <a-tag color="blue">及格分 {{ item.min_score }}</a-tag>
                </a-space>
              </a-card>
            </a-list-item>
          </template>
        </a-list>
        <a-empty v-if="!goldenCases.length" description="暂无用例" />
      </a-tab-pane>

      <!-- LLM-Judge -->
      <a-tab-pane key="judge" tab="⚖️ LLM-Judge">
        <a-card size="small" style="margin-bottom: 16px">
          <div style="display: flex; justify-content: space-between; align-items: center">
            <div>
              <h4 style="margin: 0">LLM-as-Judge 抽样</h4>
              <a-typography-text type="secondary" style="font-size: 12px">
                抽 10% 最近问答，用 DeepSeek 当裁判打分
              </a-typography-text>
            </div>
            <a-button type="primary" :icon="h(PlayCircleOutlined)" :loading="running === 'judge'" @click="runJudge">
              抽样打分
            </a-button>
          </div>
        </a-card>

        <a-alert v-if="running === 'judge'" type="info" show-icon message="⏳ LLM 正在逐条评估..." style="margin-bottom: 16px" />

        <a-card v-if="judgeResults && !judgeResults.error" size="small" style="margin-bottom: 16px">
          <a-list :data-source="judgeResults.results" size="small">
            <template #renderItem="{ item }">
              <a-list-item>
                <a-space wrap>
                  <a-tag :color="scoreColor(item.score)">{{ item.score }}/5</a-tag>
                  <a-typography-text v-if="item.dimensions" type="secondary" style="font-size: 12px">
                    相关{{ item.dimensions.relevance }} · 准确{{ item.dimensions.accuracy }} · 完整{{ item.dimensions.completeness }}
                  </a-typography-text>
                  <span>{{ item.comment }}</span>
                </a-space>
              </a-list-item>
            </template>
          </a-list>
        </a-card>

        <a-card v-if="judgeRuns.length" size="small" title="📜 历史记录">
          <a-collapse>
            <a-collapse-panel v-for="r in judgeRuns" :key="r.id"
              :header="`⚖️ Judge 抽样 · ${formatTime(r.created_at)} · 抽样 ${r.total} 条 · 平均分 ${r.avg_score}`"
            >
              <a-list v-if="r.details?.results" :data-source="r.details.results" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <a-space>
                      <a-tag :color="scoreColor(item.score)">{{ item.score }}/5</a-tag>
                      <span>{{ item.comment }}</span>
                    </a-space>
                  </a-list-item>
                </template>
              </a-list>
            </a-collapse-panel>
          </a-collapse>
        </a-card>
      </a-tab-pane>

      <!-- Bad Cases -->
      <a-tab-pane key="badcases" tab="👎 Bad Cases">
        <a-empty v-if="!badCases.length" description="暂无 bad case" />
        <a-list :data-source="badCases">
          <template #renderItem="{ item }">
            <a-list-item>
              <a-card size="small" style="width: 100%" :bordered="true" :body-style="{ borderLeft: '3px solid #ff4d4f' }">
                <template #title>
                  <a-space>
                    <a-tag color="error">{{ item.reason }}</a-tag>
                    <span style="font-size: 11px; color: #bfbfbf">{{ formatTime(item.collected_at) }}</span>
                  </a-space>
                </template>
                <template #extra>
                  <a-space>
                    <a-button size="small" type="primary" @click="promoteBadCase(item.id)">转 Golden</a-button>
                    <a-button size="small" danger :icon="h(DeleteOutlined)" @click="removeBadCase(item.id)" />
                  </a-space>
                </template>
                <p style="margin: 0 0 4px">问：{{ item.question?.slice(0, 60) }}</p>
                <p style="margin: 0; color: #8c8c8c">答：{{ item.answer?.slice(0, 100) || "（空）" }}</p>
              </a-card>
            </a-list-item>
          </template>
        </a-list>
      </a-tab-pane>
    </a-tabs>

    <!-- 编辑弹窗 -->
    <a-modal
      v-model:open="editing"
      :title="goldenCases.find(c => c.id === editForm.id) ? '编辑用例' : '新增用例'"
      @ok="saveCase"
      ok-text="保存"
      cancel-text="取消"
    >
      <a-form layout="vertical">
        <a-form-item label="ID">
          <a-input
            v-model:value="editForm.id"
            :disabled="!!goldenCases.find(c => c.id === editForm.id)"
            placeholder="如 eval_001"
          />
        </a-form-item>
        <a-form-item label="问题">
          <a-textarea v-model:value="editForm.question" :rows="2" placeholder="用户问题" />
        </a-form-item>
        <a-form-item label="期望关键词">
          <a-select
            v-model:value="editForm.expected_keywords"
            mode="tags"
            placeholder="输入后回车"
            :token-separators="[',']"
          />
        </a-form-item>
        <a-form-item label="期望来源 (note_id)">
          <a-input v-model:value="editForm.expected_sources" placeholder="逗号分隔，可空" />
        </a-form-item>
        <a-form-item label="及格分">
          <a-input-number v-model:value="editForm.min_score" :min="0" :max="1" :step="0.1" style="width: 100%" />
        </a-form-item>
        <a-form-item label="启用">
          <a-switch v-model:checked="editForm.enabled" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>
