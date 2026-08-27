<script setup>
import { ref, reactive, computed, onMounted } from "vue";
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

const evalSummary = ref(null);
const evalScores = ref([]);
const badCases = ref([]);
const goldenCases = ref([]);
const evalRuns = ref([]);
const evalReport = ref(null);
const judgeResults = ref(null);
const running = ref("");
const activeTab = ref("overview");
const expandedRun = ref(null); // 展开详情的 run id

// 按类型过滤历史
const offlineRuns = computed(() => evalRuns.value.filter(r => r.run_type === "offline"));
const judgeRuns = computed(() => evalRuns.value.filter(r => r.run_type === "judge"));

// Golden case 编辑表单
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
    console.error("加载评估数据失败", e);
  }
}

async function runEval() {
  running.value = "eval";
  evalReport.value = null;
  try {
    evalReport.value = await runEvalDataset(0);
  } catch (e) {
    evalReport.value = { error: e.message };
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
  } catch (e) {
    judgeResults.value = { error: e.message };
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

function removeKeyword(kw) {
  editForm.expected_keywords = editForm.expected_keywords.filter((k) => k !== kw);
}

async function saveCase() {
  if (!editForm.id || !editForm.question) return;
  try {
    const r = await saveGoldenCase(editForm);
    editing.value = false;
    refresh();
    alert(r.message || "已保存");
  } catch (e) {
    console.error("保存失败", e);
    alert("保存失败: " + e.message);
  }
}

async function removeCase(id) {
  if (!confirm(`确认删除 ${id}？`)) return;
  await deleteGoldenCase(id);
  refresh();
}

async function toggleCase(id) {
  await toggleGoldenCase(id);
  refresh();
}

async function doSeed() {
  if (!confirm("从 YAML 种子文件导入？已有相同 id 会被覆盖。")) return;
  try {
    const r = await seedGoldenCases();
    alert(r.message);
    refresh();
  } catch (e) {
    alert("导入失败: " + e.message);
  }
}

// ---- Bad case 操作 ----
async function removeBadCase(id) {
  if (!confirm("确认删除这条 bad case？")) return;
  await deleteBadCase(id);
  refresh();
}

async function promoteBadCase(id) {
  const r = await badCaseToGolden(id);
  alert(r.message);
  refresh();
}

function formatTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(
    d.getMinutes()
  ).padStart(2, "0")}`;
}

function toggleRun(runId) {
  expandedRun.value = expandedRun.value === runId ? null : runId;
}

onMounted(refresh);
</script>

<template>
  <div>
    <div class="header-row">
      <h3>评估中心</h3>
      <button class="btn-refresh" @click="refresh">🔄 刷新</button>
    </div>

    <div class="tabs">
      <button
        v-for="tab in [
          { key: 'overview', label: '📊 总览' },
          { key: 'eval', label: '🧪 离线评估' },
          { key: 'golden', label: '📋 测试集管理' },
          { key: 'judge', label: '⚖️ LLM-Judge' },
          { key: 'badcases', label: '👎 Bad Cases' },
        ]"
        :key="tab.key"
        :class="['tab', { active: activeTab === tab.key }]"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- 总览 -->
    <div v-if="activeTab === 'overview'" class="section">
      <div v-if="evalSummary" class="stats-grid">
        <div class="stat-card">
          <div class="stat-num">{{ evalSummary.avg_score || 0 }}/5</div>
          <div class="stat-label">Judge 平均分</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">{{ goldenCases.filter(c => c.enabled).length }}/{{ goldenCases.length }}</div>
          <div class="stat-label">测试用例（启用）</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">{{ badCases.length }}</div>
          <div class="stat-label">Bad Cases</div>
        </div>
      </div>
      <div v-if="evalScores.length" class="section">
        <h4>最近 Judge 打分</h4>
        <div v-for="s in evalScores.slice(0, 10)" :key="s.id" class="score-row">
          <span class="score-badge" :class="s.score >= 4 ? 'good' : s.score === 3 ? 'mid' : 'bad'">{{ s.score }}/5</span>
          <span class="score-question">{{ s.question.slice(0, 40) }}</span>
          <span v-if="s.comment" class="score-comment">{{ s.comment.slice(0, 50) }}</span>
          <span class="score-time">{{ formatTime(s.judged_at) }}</span>
        </div>
      </div>
    </div>

    <!-- 离线评估 -->
    <div v-if="activeTab === 'eval'" class="section">
      <div class="action-bar">
        <div>
          <h4>🧪 离线评估测试集</h4>
          <p class="action-desc">从数据库加载启用的 golden cases，逐条问答并规则打分（关键词+来源+完整性）。</p>
        </div>
        <button class="btn-run" :disabled="running !== ''" @click="runEval">
          {{ running === "eval" ? "评估中..." : "▶ 运行评估" }}
        </button>
      </div>
      <div v-if="running === 'eval'" class="running-hint">⏳ 正在逐条问答打分，可能需要 1-2 分钟...</div>
      <div v-if="evalReport && !evalReport.error" class="report">
        <div class="report-header">
          <span class="report-passrate">{{ evalReport.passed }}/{{ evalReport.total }} 通过</span>
          <span class="report-meta">通过率 {{ (evalReport.pass_rate * 100).toFixed(1) }}% · 平均分 {{ evalReport.avg_score }} · {{ evalReport.duration_ms }}ms</span>
        </div>
        <div v-for="r in evalReport.results" :key="r.id" class="eval-result" :class="{ fail: !r.passed }">
          <span class="result-icon">{{ r.passed ? "✅" : "❌" }}</span>
          <span class="result-id">{{ r.id }}</span>
          <span class="result-question">{{ r.question.slice(0, 40) }}</span>
          <span class="result-score">得分 {{ r.score }}（阈值 {{ r.min_score }}）</span>
          <div v-if="r.details" class="result-details">
            关键词 {{ r.details.keyword_score }} · 来源 {{ r.details.source_score }} · 完整性 {{ r.details.complete_score }}
            <span v-if="r.details.missed_keywords?.length" class="missed">· 未命中: {{ r.details.missed_keywords.join(", ") }}</span>
          </div>
        </div>
      </div>

      <!-- 离线评估历史 -->
      <div v-if="offlineRuns.length" class="history-section">
        <h4 class="history-title">📜 历史记录（{{ offlineRuns.length }} 次）</h4>
        <div v-for="r in offlineRuns" :key="r.id" class="run-card offline">
          <div class="run-summary" :class="{ clickable: r.details?.results?.length }" @click="r.details?.results?.length && toggleRun(r.id)">
            <div class="run-header">
              <span class="run-type-badge offline">🧪 离线评估</span>
              <span class="run-time">{{ formatTime(r.created_at) }}</span>
            </div>
            <div class="run-stats">
              <span>通过 {{ r.passed }}/{{ r.total }}（{{ r.pass_rate ? (r.pass_rate * 100).toFixed(0) : 0 }}%）</span>
              <span>平均分 {{ r.avg_score }}</span>
              <span v-if="r.duration_ms">⏱ {{ r.duration_ms }}ms</span>
              <span v-if="r.details?.results?.length" class="run-expand">{{ expandedRun === r.id ? "收起 ▲" : "展开 ▼" }}</span>
            </div>
          </div>
          <div v-if="expandedRun === r.id" class="run-detail-body">
            <div v-for="res in r.details.results" :key="res.id" class="eval-result" :class="{ fail: !res.passed }">
              <span class="result-icon">{{ res.passed ? "✅" : "❌" }}</span>
              <span class="result-id">{{ res.id }}</span>
              <span class="result-question">{{ res.question?.slice(0, 35) }}</span>
              <span class="result-score">{{ res.score }}（阈值 {{ res.min_score }}）</span>
              <div v-if="res.details" class="result-details">
                关键词 {{ res.details.keyword_score }} · 来源 {{ res.details.source_score }} · 完整性 {{ res.details.complete_score }}
                <span v-if="res.details.missed_keywords?.length" class="missed">· 未命中: {{ res.details.missed_keywords.join(", ") }}</span>
              </div>
              <div v-if="res.error" class="result-error">{{ res.error.slice(0, 80) }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 测试集管理 -->
    <div v-if="activeTab === 'golden'" class="section">
      <div class="action-bar">
        <h4>📋 Golden Cases 管理</h4>
        <div class="action-buttons">
          <button class="btn-sm" @click="doSeed">📥 从 YAML 导入</button>
          <button class="btn-sm btn-primary" @click="startNewCase">➕ 新增用例</button>
        </div>
      </div>

      <!-- 编辑弹窗触发在列表里，弹窗在页面末尾 -->

      <!-- 用例列表 -->
      <div v-for="c in goldenCases" :key="c.id" class="golden-card" :class="{ disabled: !c.enabled }">
        <div class="golden-header">
          <span class="golden-id">{{ c.id }}</span>
          <span class="golden-toggle" :class="{ on: c.enabled }" @click="toggleCase(c.id)">{{ c.enabled ? "🟢 启用" : "⚪ 禁用" }}</span>
        </div>
        <div class="golden-question">{{ c.question }}</div>
        <div class="golden-meta">
          <span>关键词: {{ c.expected_keywords.join(", ") || "（无）" }}</span>
          <span>及格分: {{ c.min_score }}</span>
        </div>
        <div class="golden-actions">
          <button class="btn-sm" @click="startEditCase(c)">✏️ 编辑</button>
          <button class="btn-sm btn-danger" @click="removeCase(c.id)">🗑 删除</button>
        </div>
      </div>
      <div v-if="!goldenCases.length" class="empty-hint">暂无用例。点「从 YAML 导入」加载种子，或「新增用例」。</div>
    </div>

    <!-- LLM-Judge -->
    <div v-if="activeTab === 'judge'" class="section">
      <div class="action-bar">
        <div>
          <h4>⚖️ LLM-as-Judge 抽样</h4>
          <p class="action-desc">抽 10% 最近问答，用 DeepSeek 当裁判打分（1-5 分 + 维度 + 评语）。</p>
        </div>
        <button class="btn-run" :disabled="running !== ''" @click="runJudge">
          {{ running === "judge" ? "评估中..." : "▶ 抽样打分" }}
        </button>
      </div>
      <div v-if="running === 'judge'" class="running-hint">⏳ LLM 正在逐条评估...</div>
      <div v-if="judgeResults && !judgeResults.error" class="report">
        <div class="report-header"><span class="report-passrate">已评估 {{ judgeResults.judged }} 条</span></div>
        <div v-for="(r, i) in judgeResults.results" :key="i" class="judge-result">
          <span class="score-badge" :class="r.score >= 4 ? 'good' : r.score === 3 ? 'mid' : 'bad'">{{ r.score }}/5</span>
          <span v-if="r.dimensions" class="judge-dims">相关{{ r.dimensions.relevance }} · 准确{{ r.dimensions.accuracy }} · 完整{{ r.dimensions.completeness }}</span>
          <span v-if="r.comment" class="judge-comment">{{ r.comment }}</span>
        </div>
      </div>

      <!-- Judge 历史 -->
      <div v-if="judgeRuns.length" class="history-section">
        <h4 class="history-title">📜 历史记录（{{ judgeRuns.length }} 次）</h4>
        <div v-for="r in judgeRuns" :key="r.id" class="run-card judge">
          <div class="run-summary" :class="{ clickable: r.details?.results?.length }" @click="r.details?.results?.length && toggleRun(r.id)">
            <div class="run-header">
              <span class="run-type-badge judge">⚖️ Judge 抽样</span>
              <span class="run-time">{{ formatTime(r.created_at) }}</span>
            </div>
            <div class="run-stats">
              <span>抽样 {{ r.total }} 条</span>
              <span>平均分 {{ r.avg_score }}</span>
              <span v-if="r.duration_ms">⏱ {{ r.duration_ms }}ms</span>
              <span v-if="r.details?.results?.length" class="run-expand">{{ expandedRun === r.id ? "收起 ▲" : "展开 ▼" }}</span>
            </div>
          </div>
          <div v-if="expandedRun === r.id" class="run-detail-body">
            <div v-for="(res, i) in r.details.results" :key="i" class="judge-result">
              <span class="score-badge" :class="res.score >= 4 ? 'good' : res.score === 3 ? 'mid' : 'bad'">{{ res.score }}/5</span>
              <span v-if="res.dimensions" class="judge-dims">相关{{ res.dimensions.relevance }} · 准确{{ res.dimensions.accuracy }} · 完整{{ res.dimensions.completeness }}</span>
              <span v-if="res.comment" class="judge-comment">{{ res.comment }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Bad Cases -->
    <div v-if="activeTab === 'badcases'" class="section">
      <h4>👎 Bad Cases（点踩 / 失败收集）</h4>
      <div v-if="!badCases.length" class="empty-hint">暂无 bad case。</div>
      <div v-for="c in badCases" :key="c.id" class="badcase-card">
        <div class="badcase-header">
          <span class="badcase-reason">{{ c.reason }}</span>
          <span class="badcase-time">{{ formatTime(c.collected_at) }}</span>
        </div>
        <div class="badcase-q">问：{{ c.question?.slice(0, 60) }}</div>
        <div class="badcase-a">答：{{ c.answer?.slice(0, 100) || "（空）" }}</div>
        <div class="badcase-actions">
          <button class="btn-sm btn-primary" @click="promoteBadCase(c.id)">📋 转 Golden</button>
          <button class="btn-sm btn-danger" @click="removeBadCase(c.id)">🗑 删除</button>
        </div>
      </div>
    </div>

    <!-- 编辑弹窗（modal） -->
    <div v-if="editing" class="modal-overlay" @click.self="editing = false">
      <div class="modal">
        <div class="modal-header">
          <h4>{{ goldenCases.find(c => c.id === editForm.id) ? "编辑" : "新增" }}用例</h4>
          <span class="modal-close" @click="editing = false">×</span>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <label>ID</label>
            <input v-model="editForm.id" :disabled="!!goldenCases.find(c => c.id === editForm.id)" placeholder="如 eval_001" />
          </div>
          <div class="form-row">
            <label>问题</label>
            <textarea v-model="editForm.question" rows="2" placeholder="用户问题"></textarea>
          </div>
          <div class="form-row">
            <label>期望关键词</label>
            <div class="tag-input">
              <span v-for="kw in editForm.expected_keywords" :key="kw" class="tag">
                {{ kw }} <span class="tag-remove" @click="removeKeyword(kw)">×</span>
              </span>
              <input v-model="keywordInput" @keydown.enter.prevent="addKeyword" placeholder="输入后回车" />
            </div>
          </div>
          <div class="form-row">
            <label>期望来源 (note_id)</label>
            <input v-model="editForm.expected_sources" placeholder="逗号分隔，可空" />
          </div>
          <div class="form-row">
            <label>及格分</label>
            <input v-model.number="editForm.min_score" type="number" min="0" max="1" step="0.1" />
          </div>
          <div class="form-row">
            <label>启用</label>
            <input v-model="editForm.enabled" type="checkbox" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-sm" @click="editing = false">取消</button>
          <button class="btn-sm btn-primary" @click="saveCase">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.header-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.btn-refresh { padding: 6px 14px; background: var(--primary); color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 13px; }
.tabs { display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
.tab { padding: 8px 14px; background: none; border: none; border-bottom: 2px solid transparent; color: var(--text-dim); cursor: pointer; font-size: 14px; }
.tab.active { color: var(--primary); border-bottom-color: var(--primary); font-weight: 600; }
.section { margin-bottom: 24px; }
.section h4 { margin-bottom: 10px; font-size: 15px; }
.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 20px; }
.stat-card { text-align: center; padding: 18px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; }
.stat-num { font-size: 24px; font-weight: 700; color: var(--primary); font-family: var(--font-mono); }
.stat-label { font-size: 13px; color: var(--text-dim); margin-top: 4px; }
.action-bar { display: flex; align-items: center; justify-content: space-between; padding: 16px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 16px; }
.action-desc { font-size: 12px; color: var(--text-dim); margin-top: 4px; }
.action-buttons { display: flex; gap: 8px; }
.btn-run { padding: 10px 20px; background: var(--success); color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 600; }
.btn-run:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-sm { padding: 6px 12px; background: var(--bg-panel); border: 1px solid var(--border); border-radius: 6px; cursor: pointer; font-size: 13px; color: var(--text-main); }
.btn-sm.btn-primary { background: var(--primary); color: #fff; border-color: var(--primary); }
.btn-sm.btn-danger { color: var(--danger); }
.btn-sm:disabled { opacity: 0.5; }
.running-hint { padding: 12px; text-align: center; color: var(--primary); font-size: 13px; }
.report-header { display: flex; gap: 16px; padding: 12px 16px; background: var(--bg-deep); border-radius: 8px; margin-bottom: 12px; }
.report-passrate { font-size: 18px; font-weight: 700; color: var(--primary); }
.report-meta { font-size: 13px; color: var(--text-dim); }
.eval-result { display: flex; flex-wrap: wrap; gap: 10px; padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; }
.eval-result.fail { border-left: 3px solid var(--danger); }
.result-icon { font-size: 16px; }
.result-id { font-size: 12px; color: var(--text-faint); font-family: var(--font-mono); }
.result-question { font-size: 13px; color: var(--text-main); flex: 1; }
.result-score { font-size: 13px; font-weight: 600; color: var(--text-dim); }
.result-details { width: 100%; font-size: 12px; color: var(--text-faint); }
.missed { color: var(--danger); }
.score-row { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px dashed var(--border); font-size: 13px; }
.score-badge { padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 12px; }
.score-badge.good { background: rgba(16,185,129,0.15); color: var(--success); }
.score-badge.mid { background: rgba(243,156,18,0.15); color: #f39c12; }
.score-badge.bad { background: rgba(239,68,68,0.15); color: var(--danger); }
.score-question { color: var(--text-main); flex: 1; }
.score-comment { color: var(--text-dim); font-size: 12px; }
.score-time { color: var(--text-faint); font-family: var(--font-mono); font-size: 11px; }
.judge-result { display: flex; flex-wrap: wrap; gap: 10px; padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; }
.judge-dims { font-size: 12px; color: var(--text-dim); }
.judge-comment { font-size: 13px; color: var(--text-main); flex: 1; }
/* 编辑弹窗 modal */
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  width: 520px;
  max-width: 90vw;
  max-height: 85vh;
  overflow-y: auto;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
}
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}
.modal-header h4 { font-size: 16px; margin: 0; }
.modal-close {
  font-size: 22px;
  cursor: pointer;
  color: var(--text-dim);
  line-height: 1;
}
.modal-close:hover { color: var(--text-main); }
.modal-body { padding: 20px; }
.modal-footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  padding: 12px 20px;
  border-top: 1px solid var(--border);
}
.form-row { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 14px; }
.form-row label { width: 110px; font-size: 13px; color: var(--text-dim); padding-top: 6px; flex-shrink: 0; }
.form-row input, .form-row textarea { flex: 1; padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-card); color: var(--text-main); font-size: 13px; font-family: inherit; }
.tag-input { display: flex; flex-wrap: wrap; gap: 6px; flex: 1; padding: 6px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-card); }
.tag-input input { border: none; background: none; flex: 1; min-width: 80px; color: var(--text-main); font-size: 13px; }
.tag { background: var(--primary); color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.tag-remove { cursor: pointer; margin-left: 4px; }
/* golden card */
.golden-card { padding: 12px 14px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; }
.golden-card.disabled { opacity: 0.5; }
.golden-header { display: flex; justify-content: space-between; margin-bottom: 6px; }
.golden-id { font-size: 13px; font-weight: 600; color: var(--primary); font-family: var(--font-mono); }
.golden-toggle { font-size: 12px; cursor: pointer; }
.golden-toggle.on { color: var(--success); }
.golden-question { font-size: 14px; color: var(--text-main); margin-bottom: 6px; }
.golden-meta { display: flex; gap: 16px; font-size: 12px; color: var(--text-dim); margin-bottom: 8px; }
.golden-actions { display: flex; gap: 8px; }
/* bad case */
.badcase-card { padding: 12px 14px; border: 1px solid var(--border); border-left: 3px solid var(--danger); border-radius: 8px; margin-bottom: 8px; }
.badcase-header { display: flex; justify-content: space-between; margin-bottom: 6px; }
.badcase-reason { font-size: 12px; color: var(--danger); font-weight: 600; }
.badcase-time { font-size: 11px; color: var(--text-faint); }
.badcase-q, .badcase-a { font-size: 13px; color: var(--text-dim); margin-top: 4px; }
.badcase-actions { display: flex; gap: 8px; margin-top: 8px; }
.empty-hint { padding: 30px; text-align: center; color: var(--text-dim); font-size: 14px; }
/* 评估历史 */
.history-section { margin-top: 20px; }
.history-title { font-size: 14px; color: var(--text-dim); margin-bottom: 10px; }
.run-card { padding: 12px 14px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; }
.run-card.offline { border-left: 3px solid var(--primary); }
.run-card.judge { border-left: 3px solid var(--accent); }
.run-summary.clickable { cursor: pointer; }
.run-summary.clickable:hover { background: var(--bg-hover); }
.run-header { display: flex; justify-content: space-between; margin-bottom: 6px; }
.run-type-badge { font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 4px; }
.run-type-badge.offline { background: rgba(0,132,255,0.15); color: var(--primary); }
.run-type-badge.judge { background: rgba(0,184,212,0.15); color: var(--accent); }
.run-time { font-size: 11px; color: var(--text-faint); font-family: var(--font-mono); }
.run-stats { display: flex; gap: 16px; font-size: 13px; color: var(--text-dim); align-items: center; }
.run-expand { margin-left: auto; font-size: 12px; color: var(--primary); }
.run-detail-body { margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--border); }
.run-details { margin-top: 6px; font-size: 12px; color: var(--text-faint); }
.run-fail { color: var(--danger); margin-left: 4px; }
</style>
