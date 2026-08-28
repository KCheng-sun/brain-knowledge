<script setup>
import { ref, reactive, nextTick, watch, onMounted, inject } from "vue";
import { getSessionMessages, submitEvalFeedback } from "../api/index.js";

// 跨页跳转：点击答案中的 [笔记引用] 跳搜索页
const jumpToSearch = inject("jumpToSearch", null);

const props = defineProps({
  sessionId: { type: String, default: null },
  // 跨页跳转种子: { question, ts } —— 其他页面跳来时预填问题
  seed: { type: Object, default: null },
});

const emit = defineEmits(["session-created", "session-updated"]);

const question = ref("");
const messages = ref([]);
const loading = ref(false);
const chatEl = ref(null);
const statusMsg = ref(""); // 当前状态提示
let currentSessionId = props.sessionId; // 本地追踪（后端创建新会话时更新）

// 图谱/片段页跳转过来时预填问题（不自动发送，让用户确认）
watch(
  () => props.seed,
  (newSeed) => {
    if (newSeed && newSeed.question) {
      question.value = newSeed.question;
      scrollToBottom();
    }
  },
  { immediate: true }
);

async function thumbsDown(msg) {
  if (msg.thumbsDown) return;
  msg.thumbsDown = true;
  try {
    await submitEvalFeedback(
      msg.traceId || null,
      msg.question || "",
      msg.content || "",
      "user_thumbs_down"
    );
  } catch (e) {
    console.error("反馈失败", e);
    msg.thumbsDown = false;
  }
}

function renderMarkdown(text) {
  if (!text) return "";
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n\n/g, "</p><p>")
    .replace(/\n/g, "<br>")
    .replace(/^/, "<p>")
    .replace(/$/, "</p>");

  // [笔记标题] 引用转可点击标签（跳搜索页查原文）
  if (jumpToSearch) {
    html = html.replace(
      /\[([^\]]{2,60})\]/g,
      '<span class="ref-link" data-title="$1">「$1」</span>'
    );
  }
  return html;
}

// 点击引用标签 → 跳转搜索页（事件委托，避免流式渲染时重复绑事件）
function onRefClick(e) {
  if (!jumpToSearch) return;
  const el = e.target.closest(".ref-link");
  if (el && el.dataset.title) {
    jumpToSearch(el.dataset.title);
  }
}

function scrollToBottom() {
  nextTick(() => {
    chatEl.value?.scrollTo({ top: chatEl.value.scrollHeight, behavior: "smooth" });
  });
}

// 加载会话历史消息
async function loadHistory(sessionId) {
  if (!sessionId) {
    messages.value = [];
    return;
  }
  try {
    const data = await getSessionMessages(sessionId);
    // 历史消息：给 assistant 消息关联前一条 user 消息的内容作为 question（点踩反馈用）
    const msgs = data.messages;
    messages.value = msgs.map((m, i) => {
      const msg = {
        role: m.role,
        content: m.content,
        done: true, // 历史消息已加载完成，点踩按钮可显示
        // 历史消息的 timeline 里 args 是对象，格式化为字符串以便模板显示
        timeline: (m.timeline || []).map((item) => ({
          ...item,
          args: item.kind === "tool" && item.args && typeof item.args === "object"
            ? formatArgs(item.args)
            : item.args,
        })),
      };
      // assistant 消息的 question = 前一条 user 消息
      if (m.role === "assistant" && i > 0 && msgs[i - 1].role === "user") {
        msg.question = msgs[i - 1].content;
      }
      return msg;
    });
    scrollToBottom();
  } catch (e) {
    console.error("加载历史失败", e);
    messages.value = [];
  }
}

// 切换会话时重新加载。
// 注意：后端刚创建会话时 prop 会从 null → 新 ID，
// 此时 currentSessionId 已被 handleEvent 更新为新 ID，
// 跳过重载避免冲掉正在流式渲染的消息。
watch(() => props.sessionId, (newId) => {
  if (newId === currentSessionId) return;
  currentSessionId = newId;
  loadHistory(newId);
});

onMounted(() => loadHistory(props.sessionId));

async function send() {
  const q = question.value.trim();
  if (!q || loading.value) return;

  messages.value.push({ role: "user", content: q });
  question.value = "";
  loading.value = true;
  statusMsg.value = "";

  // 预留 assistant 消息占位——必须用 reactive，否则流式更新不会触发渲染
  const assistantMsg = reactive({
    role: "assistant",
    content: "",
    timeline: [], // 统一时间线: [{kind: 'thought'|'tool', ...}] 按发生顺序
    status: "",
    question: q, // 保存对应问题（点踩反馈用）
    done: false, // 流式是否完成（完成前不显示点踩按钮，避免随 token 闪现）
  });
  messages.value.push(assistantMsg);
  scrollToBottom();

  try {
    // 直连后端，绕过 Vite 代理（代理会缓冲 SSE 流）
    // 带 session_id：后端自动创建/复用会话并持久化消息
    const body = { question: q };
    if (currentSessionId) body.session_id = currentSessionId;

    const interrupted = await readStream(
      "http://127.0.0.1:7860/api/ask/stream",
      body,
      assistantMsg,
    );

    // HIL 中断：等待用户对知识片段的决策，然后调 resume 恢复
    if (interrupted) {
      await waitForDecision(interrupted, assistantMsg);
    }
  } catch (e) {
    assistantMsg.content += `\n\n❌ 出错了: ${e.message}`;
  } finally {
    loading.value = false;
    statusMsg.value = "";
    scrollToBottom();
  }
}

// 读取 SSE 流并处理事件。返回 interrupt 信息（若流被中断）
async function readStream(url, body, assistantMsg) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  if (!response.ok) {
    // 429 预算超限：提取后端返回的 detail 显示友好提示
    if (response.status === 429) {
      try {
        const detail = await response.json();
        const reason = detail?.detail?.reason || detail?.reason || "配额已用尽";
        const today = detail?.detail?.today || detail?.today || {};
        const limits = detail?.detail?.limits || detail?.limits || {};
        throw new Error(
          `⛔ ${reason}\n\n今日用量：${today.tokens || 0} token / ¥${(today.cost || 0).toFixed(4)}\n` +
          `配额上限：日 ${limits.daily_token || "-"} token / ¥${limits.daily_cost || "-"}`
        );
      } catch (parseErr) {
        if (parseErr.message.startsWith("⛔")) throw parseErr;
        throw new Error("⛔ 配额已用尽，请明天再试或调整 BRAIN_COST_* 配置");
      }
    }
    throw new Error(`HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let interruptInfo = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE 按 \n\n 分隔
    const parts = buffer.split("\n\n");
    buffer = parts.pop(); // 剩余不完整部分留到下次

    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data: ")) continue;

      try {
        const event = JSON.parse(line.slice(6));
        const irq = handleEvent(event, assistantMsg);
        if (irq) interruptInfo = irq;
      } catch (e) {
        // 忽略解析错误
      }
    }
    scrollToBottom();
  }
  return interruptInfo;
}

// 显示知识片段确认卡片，等待用户决策，然后恢复流
function waitForDecision(interruptInfo, assistantMsg) {
  return new Promise((resolve) => {
    const sessionId = interruptInfo.session_id;
    const proposals = interruptInfo.proposals || [];

    // 为每个提议的知识片段添加一张待确认卡片（多张可逐一审批）
    const proposalItems = proposals.map((p) => {
      const args = p.args || {};
      return {
        kind: "proposal",
        title: args.title || "知识片段",
        content: args.content || "",
        decided: false,
        decision: null,
      };
    });
    assistantMsg.timeline.push(...proposalItems);

    // 保存决策回调供模板按钮调用（每点一个按钮记录一条决策，全部决策完才恢复）
    assistantMsg._decide = async (decision) => {
      // 找到第一个未决策的卡片并标记
      const item = assistantMsg.timeline.find((t) => t.kind === "proposal" && !t.decided);
      if (item) {
        item.decided = true;
        item.decision = decision.type;
      }

      // 还有未决策的卡片 → 等用户继续点按钮
      const pending = assistantMsg.timeline.filter((t) => t.kind === "proposal" && !t.decided);
      if (pending.length > 0) return;

      // 全部决策完成，按顺序收集 decisions 发给后端恢复
      const decisions = assistantMsg.timeline
        .filter((t) => t.kind === "proposal")
        .map((t) => {
          if (t.decision === "approve") return { type: "approve" };
          if (t.decision === "reject") return { type: "reject", message: "用户拒绝" };
          // edit 暂不支持，按 approve 处理
          return { type: "approve" };
        });

      try {
        await readStream(
          "http://127.0.0.1:7860/api/ask/resume",
          { session_id: sessionId, decisions },
          assistantMsg,
        );
      } catch (e) {
        assistantMsg.content += `\n\n❌ 恢复失败: ${e.message}`;
      }
      emit("session-updated");
      resolve();
    };
  });
}

function handleEvent(event, assistantMsg) {
  switch (event.type) {
    case "session": {
      // 后端创建了新会话（首条消息时）
      if (event.session_id) {
        const isNew = currentSessionId !== event.session_id;
        currentSessionId = event.session_id;
        if (isNew) {
          emit("session-created", event.session_id);
        }
      }
      // 存储 trace_id 供点踩反馈用（Phase 5D）
      if (event.trace_id) {
        assistantMsg.traceId = event.trace_id;
      }
      break;
    }

    case "title":
      // 子智能体已直接写库；done 事件会统一触发列表刷新，无需单独处理
      break;

    case "status":
      statusMsg.value = event.message;
      assistantMsg.status = event.message;
      break;

    case "tool_start": {
      const name = event.name;
      // 跳过空 name 的碎片事件
      if (!name) break;
      // 把工具调用前已流出的文本归档为「思考片段」，
      // 这样中间推理和最终答案不会混在一起
      if (assistantMsg.content.trim()) {
        assistantMsg.timeline.push({ kind: "thought", content: assistantMsg.content });
        assistantMsg.content = "";
      }
      const argsPreview = formatArgs(event.args);
      // 工具条目直接进时间线，保持发生顺序
      assistantMsg.timeline.push({
        kind: "tool",
        name,
        args: argsPreview,
        done: false,
      });
      break;
    }

    case "tool_end": {
      if (!event.name) break;
      const timeline = assistantMsg.timeline;
      // 从后往前找第一个同名的未完成工具
      for (let i = timeline.length - 1; i >= 0; i--) {
        const item = timeline[i];
        if (item.kind === "tool" && item.name === event.name && !item.done) {
          item.done = true;
          break;
        }
      }
      break;
    }

    case "token":
      assistantMsg.content += event.content;
      break;

    case "interrupt":
      // HIL 中断：中断后不会再收到 tool_end，把未完成 tool 标记为 done
      for (const item of assistantMsg.timeline) {
        if (item.kind === "tool" && !item.done) item.done = true;
      }
      // 返回中断信息，由外层 waitForDecision 处理
      return { session_id: event.session_id, proposals: event.proposals || [] };

    case "done":
      // 回答完成，通知父组件刷新会话列表（标题/时间已更新）
      assistantMsg.done = true;
      emit("session-updated");
      break;
  }
  return null;
}

function formatArgs(args) {
  if (!args || Object.keys(args).length === 0) return "";
  return Object.entries(args)
    .map(([k, v]) => `${k}=${String(v).slice(0, 50)}`)
    .join(", ");
}
</script>

<template>
  <div class="ask-page">
    <div ref="chatEl" class="chat-box" @click="onRefClick">
      <!-- 空状态欢迎页 -->
      <div v-if="messages.length === 0" class="welcome">
        <div class="welcome-logo">🧠</div>
        <a-typography-title :level="3">向你的第二大脑提问</a-typography-title>
        <a-typography-paragraph type="secondary">
          深度 Agent 会自动搜索知识库、追踪笔记关联、多步推理后回答
        </a-typography-paragraph>
        <div class="welcome-examples">
          <a-button
            v-for="ex in [
              '我最近关于 LangGraph 的思考有哪些关键结论？',
              '我的知识库中哪些笔记互相关联？',
              '总结一下我对 Agent 架构的理解',
            ]"
            :key="ex"
            block
            @click="question = ex"
          >
            {{ ex }}
          </a-button>
        </div>
      </div>

      <!-- 消息列表 -->
      <a-list
        v-if="messages.length"
        :data-source="messages"
        :split="false"
        item-layout="vertical"
        style="padding: 16px 4px"
      >
        <template #renderItem="{ item: m, index: i }">
          <a-list-item style="border: none; padding: 0 0 16px">
            <div :class="['msg-row', m.role === 'user' ? 'msg-right' : 'msg-left']">
              <!-- 用户消息内容 -->
              <div v-if="m.role === 'user'" class="user-bubble">{{ m.content }}</div>

              <!-- assistant 消息：统一时间线 -->
              <div v-else class="assistant-block">
                <div class="assistant-bubble">
                <a-timeline v-if="(m.timeline || []).length">
                  <a-timeline-item
                    v-for="(tl, k) in m.timeline || []"
                    :key="'tl' + k"
                    :color="tl.kind === 'tool' ? 'blue' : tl.kind === 'proposal' ? 'gold' : 'gray'"
                  >
                    <!-- 思考片段 -->
                    <div
                      v-if="tl.kind === 'thought'"
                      class="thought-text"
                      v-html="renderMarkdown(tl.content)"
                    ></div>

                    <!-- 工具调用 -->
                    <a-tag v-else-if="tl.kind === 'tool'" :color="tl.done ? 'success' : 'processing'">
                      {{ tl.done ? '✓' : '⟳' }} {{ tl.name }}
                      <span v-if="tl.args" style="color: rgba(0,0,0,0.45)"> {{ tl.args }}</span>
                    </a-tag>

                    <!-- 知识片段提案（HIL 确认卡片） -->
                    <a-card
                      v-else-if="tl.kind === 'proposal'"
                      size="small"
                      :bordered="!tl.decided"
                      :style="{ maxWidth: 480 }"
                    >
                      <template #title>
                        <a-space>
                          <span>💡 建议保存知识片段</span>
                          <a-tag v-if="tl.decided" :color="tl.decision === 'reject' ? 'default' : 'success'">
                            {{ tl.decision === 'approve' ? '✅ 已保存' : tl.decision === 'edit' ? '✅ 已保存(编辑)' : '🗑 已拒绝' }}
                          </a-tag>
                        </a-space>
                      </template>
                      <a-typography-title :level="5" style="margin: 0 0 8px">{{ tl.title }}</a-typography-title>
                      <a-typography-paragraph style="margin: 0" type="secondary">{{ tl.content }}</a-typography-paragraph>
                      <a-space v-if="!tl.decided" style="margin-top: 12px">
                        <a-button type="primary" size="small" @click="m._decide({ type: 'approve' })">保存</a-button>
                        <a-button danger size="small" @click="m._decide({ type: 'reject', message: '用户选择不保存' })">拒绝</a-button>
                      </a-space>
                    </a-card>
                  </a-timeline-item>
                </a-timeline>

                <!-- 最终答案 -->
                <div
                  v-if="m.content"
                  class="answer-text"
                  v-html="renderMarkdown(m.content)"
                ></div>

                <!-- 点踩按钮（Phase 5D FR54 bad case 回流） -->
                <div v-if="m.content && m.done" style="margin-top: 4px">
                  <a-button
                    v-if="!m.thumbsDown"
                    size="small"
                    @click="thumbsDown(m)"
                    title="这个回答不好，反馈给开发"
                  >👎 这个回答不好</a-button>
                  <a-tag v-else color="default">已反馈 ✓</a-tag>
                </div>
                </div>

                <!-- 思考中 -->
                <a-space v-if="!m.content && !(m.timeline || []).length && loading && i === messages.length - 1">
                  <a-spin size="small" />
                  <span>{{ statusMsg || 'Agent 正在思考' }}</span>
                </a-space>
              </div>
            </div>
          </a-list-item>
        </template>
      </a-list>
    </div>

    <!-- 输入区 -->
    <div class="input-bar">
      <div class="input-wrap">
        <a-textarea
          v-model:value="question"
          class="input-field"
          placeholder="输入问题，Enter 发送（Shift+Enter 换行）— Agent 将搜索知识库并深度推理"
          :auto-size="{ minRows: 2, maxRows: 6 }"
          :disabled="loading"
          @keydown.enter.exact.prevent="send"
        />
        <a-button
          type="primary"
          class="send-btn"
          :disabled="loading || !question.trim()"
          @click="send"
        >
          {{ loading ? "⏳" : "发送" }}
        </a-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ask-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  max-width: 900px;
  margin: 0 auto;
  padding: 0 24px;
  box-sizing: border-box;
}

/* ============ 聊天区域 ============ */
.chat-box {
  flex: 1;
  overflow-y: auto;
  padding: 8px 4px 16px;
  scroll-behavior: smooth;
}

/* ============ 欢迎页 ============ */
.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 14vh;
  text-align: center;
}

.welcome-logo {
  font-size: 52px;
  margin-bottom: 16px;
}

.welcome-examples {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  max-width: 480px;
}

/* 思考片段：markdown 渲染区 */
.thought-text {
  font-size: 13px;
  line-height: 1.5;
  color: rgba(0, 0, 0, 0.45);
}

/* 消息行：左右对齐 */
.msg-row {
  display: flex;
  width: 100%;
}
.msg-right {
  justify-content: flex-end;
}
.msg-left {
  justify-content: flex-start;
}

/* 用户消息气泡 */
.user-bubble {
  padding: 8px 14px;
  background: rgba(0, 0, 0, 0.04);
  border-radius: 8px;
  width: 80%;
}

/* assistant 区块 */
.assistant-block {
  width: 100%;
}

/* 整体气泡：包含工具链 + 答案 + 反馈 */
.assistant-bubble {
  padding: 8px 14px;
  background: rgba(0, 0, 0, 0.04);
  border-radius: 8px;
}

/* 最终答案：markdown 渲染区 */
.answer-text {
  font-size: 15px;
  line-height: 1.75;
}

/* markdown 首末元素不贴边 */
.answer-text :deep(p:first-child) {
  margin-top: 0;
}
.answer-text :deep(p:last-child) {
  margin-bottom: 0;
}

/* 时间线紧凑：与答案紧贴 */
:deep(.ant-timeline) {
  margin: 4px 0 2px;
}
:deep(.ant-timeline-item) {
  padding-bottom: 0 !important;
}
:deep(.ant-timeline-item-content) {
  margin-inline-start: 18px;
  margin-top: 0;
  padding-bottom: 2px;
}
:deep(.ant-timeline-item-last > .ant-timeline-item-content) {
  padding-bottom: 0;
  margin-bottom: 0;
  min-height: auto;
}

.answer-text :deep(strong) {
  color: var(--ant-color-primary);
}

/* 可点击的笔记引用标签 */
.answer-text :deep(.ref-link),
.thought-text :deep(.ref-link) {
  color: var(--ant-color-primary);
  cursor: pointer;
  text-decoration: underline dotted;
  text-underline-offset: 3px;
}

/* ============ 输入栏 ============ */
.input-bar {
  padding: 12px 0 20px;
}

.input-wrap {
  position: relative;
}

/* textarea 右下留出按钮空间，避免文字被遮挡 */
.input-field :deep(textarea) {
  padding-bottom: 40px;
  resize: none;
}

.send-btn {
  position: absolute;
  right: 8px;
  bottom: 8px;
}
</style>
