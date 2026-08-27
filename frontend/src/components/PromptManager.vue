<script setup>
import { ref, computed, h, onMounted } from "vue";
import { message, Modal } from "ant-design-vue";
import {
  listPrompts,
  getPrompt,
  updatePrompt,
  listPromptVersions,
  getPromptVersion,
  restorePromptVersion,
} from "../api/index.js";
import {
  ReloadOutlined,
  HistoryOutlined,
  RollbackOutlined,
} from "@ant-design/icons-vue";

const SPLIT_MARKER = "---USER---";

const prompts = ref([]);
const selectedKey = ref(null);
const editing = ref(null);
const systemPart = ref("");
const userPart = ref("");
const singleDraft = ref("");
const saving = ref(false);
const loading = ref(true);

// 历史版本弹窗
const showHistoryModal = ref(false);
const versions = ref([]);
const selectedHistVersion = ref(null);
const restoring = ref(false);

const isSplit = computed(() => {
  const content = editing.value ? editing.value.content : "";
  return content.includes(SPLIT_MARKER);
});

async function refresh() {
  loading.value = true;
  try {
    prompts.value = await listPrompts();
    if (prompts.value.length && !selectedKey.value) {
      await selectPrompt(prompts.value[0].prompt_key);
    }
  } catch (e) {
    console.error(e);
  } finally {
    loading.value = false;
  }
}

async function selectPrompt(key) {
  selectedKey.value = key;
  try {
    editing.value = await getPrompt(key);
    splitDraft(editing.value.content);
  } catch (e) {
    console.error(e);
  }
}

function splitDraft(content) {
  if (content.includes(SPLIT_MARKER)) {
    const [sys, usr] = content.split(SPLIT_MARKER, 2);
    systemPart.value = sys.trimEnd();
    userPart.value = usr.trim();
    singleDraft.value = "";
  } else {
    singleDraft.value = content;
    systemPart.value = "";
    userPart.value = "";
  }
}

function joinDraft() {
  if (isSplit.value) {
    return systemPart.value + "\n\n" + SPLIT_MARKER + "\n" + userPart.value;
  }
  return singleDraft.value;
}

async function save() {
  if (!editing.value) return;
  saving.value = true;
  try {
    await updatePrompt(editing.value.prompt_key, joinDraft());
    message.success("已保存");
    editing.value = await getPrompt(editing.value.prompt_key);
    splitDraft(editing.value.content);
    await refresh();
  } catch (e) {
    message.error("保存失败：" + (e.response?.data?.detail || e.message));
  } finally {
    saving.value = false;
  }
}

function resetDraft() {
  if (editing.value) splitDraft(editing.value.content);
}

// ---- 历史版本弹窗 ----

async function openHistory() {
  selectedHistVersion.value = null;
  try {
    versions.value = await listPromptVersions(editing.value.prompt_key);
    showHistoryModal.value = true;
  } catch (e) {
    console.error(e);
  }
}

function closeHistory() {
  showHistoryModal.value = false;
  selectedHistVersion.value = null;
}

async function viewVersion(version) {
  try {
    selectedHistVersion.value = await getPromptVersion(
      editing.value.prompt_key,
      version
    );
  } catch (e) {
    console.error(e);
  }
}

const histSystemPart = computed(
  () => selectedHistVersion.value?.content.split(SPLIT_MARKER)[0]?.trimEnd() || ""
);
const histUserPart = computed(
  () => selectedHistVersion.value?.content.split(SPLIT_MARKER, 2)[1]?.trim() || ""
);
const histIsSplit = computed(
  () =>
    selectedHistVersion.value &&
    selectedHistVersion.value.content.includes(SPLIT_MARKER)
);

function restoreVersion() {
  if (!selectedHistVersion.value) return;
  Modal.confirm({
    title: "恢复历史版本",
    content: `确认恢复 v${selectedHistVersion.value.version} 为最新版本？`,
    okText: "恢复",
    cancelText: "取消",
    onOk: async () => {
      restoring.value = true;
      try {
        await restorePromptVersion(
          editing.value.prompt_key,
          selectedHistVersion.value.version
        );
        message.success(`已恢复 v${selectedHistVersion.value.version}`);
        editing.value = await getPrompt(editing.value.prompt_key);
        splitDraft(editing.value.content);
        versions.value = await listPromptVersions(editing.value.prompt_key);
        selectedHistVersion.value = null;
        await refresh();
        closeHistory();
      } catch (e) {
        message.error("恢复失败");
      } finally {
        restoring.value = false;
      }
    },
  });
}

const charCount = computed(() => {
  if (!editing.value) return 0;
  return joinDraft().length;
});
const isDirty = computed(
  () => editing.value && joinDraft() !== editing.value.content
);

onMounted(refresh);
</script>

<template>
  <div>
    <div style="display: flex; justify-content: flex-end; margin-bottom: 16px">
      <a-button :icon="h(ReloadOutlined)" :loading="loading" @click="refresh">
        刷新
      </a-button>
    </div>

    <a-row :gutter="16">
      <!-- 左侧列表 -->
      <a-col :span="6">
        <a-card size="small" title="提示词列表">
          <a-list :data-source="prompts" :split="false" size="small">
            <template #renderItem="{ item }">
              <a-list-item
                style="cursor: pointer; padding: 8px 12px; border-radius: 6px"
                :style="{ background: selectedKey === item.prompt_key ? '#eef2ff' : 'transparent' }"
                @click="selectPrompt(item.prompt_key)"
              >
                <a-space direction="vertical" :size="2" style="width: 100%">
                  <span :style="{ fontWeight: selectedKey === item.prompt_key ? 600 : 400 }">
                    {{ item.name }}
                  </span>
                  <a-space :size="4">
                    <code style="font-size: 11px; color: #8c8c8c">{{ item.prompt_key }}</code>
                    <a-tag v-if="item.is_template" color="cyan" :bordered="false">模板</a-tag>
                    <span style="font-size: 11px; color: #bfbfbf">v{{ item.version }}</span>
                  </a-space>
                </a-space>
              </a-list-item>
            </template>
          </a-list>
        </a-card>
      </a-col>

      <!-- 右侧编辑区 -->
      <a-col :span="18">
        <a-card v-if="editing" size="small">
          <template #title>
            <a-space>
              <span>{{ editing.name }}</span>
              <a-tag>{{ editing.is_template ? "含占位符模板" : "纯文本" }}</a-tag>
              <a-tag color="blue">v{{ editing.version }}</a-tag>
              <span style="font-size: 12px; color: #8c8c8c">{{ charCount }} 字</span>
            </a-space>
          </template>
          <template #extra>
            <a-button :icon="h(HistoryOutlined)" @click="openHistory">历史版本</a-button>
          </template>

          <a-alert
            v-if="editing.is_template"
            type="info"
            show-icon
            message="此提示词含 {占位符}，运行时用 str.format() 渲染。请勿删除占位符变量。"
            style="margin-bottom: 16px"
          />

          <!-- 拆分模式 -->
          <div v-if="isSplit">
            <a-space direction="vertical" :size="16" style="width: 100%">
              <div>
                <div style="margin-bottom: 8px">
                  <a-tag color="blue">🔧 System</a-tag>
                  <span style="font-size: 12px; color: #8c8c8c">角色设定·评分标准·输出格式</span>
                </div>
                <a-textarea
                  v-model:value="systemPart"
                  :rows="10"
                  :spellcheck="false"
                />
              </div>
              <div>
                <div style="margin-bottom: 8px">
                  <a-tag color="cyan">👤 User</a-tag>
                  <span style="font-size: 12px; color: #8c8c8c">具体问题·回答·上下文</span>
                </div>
                <a-textarea
                  v-model:value="userPart"
                  :rows="6"
                  :spellcheck="false"
                />
              </div>
            </a-space>
          </div>

          <!-- 单文本模式 -->
          <a-textarea v-else v-model:value="singleDraft" :rows="16" :spellcheck="false" />

          <div style="margin-top: 16px; display: flex; justify-content: flex-end; gap: 8px">
            <a-typography-text v-if="isDirty" type="warning" style="margin-right: auto; align-self: center">
              ⚠️ 有未保存的修改
            </a-typography-text>
            <a-button @click="resetDraft" :disabled="!isDirty">还原</a-button>
            <a-button type="primary" :loading="saving" :disabled="!isDirty" @click="save">
              保存
            </a-button>
          </div>
        </a-card>

        <a-empty v-else description="请从左侧选择一个提示词" />
      </a-col>
    </a-row>

    <!-- 历史版本弹窗 -->
    <a-modal
      v-model:open="showHistoryModal"
      :title="`📜 ${editing?.name} · 历史版本`"
      width="800px"
      :footer="null"
      @cancel="closeHistory"
    >
      <a-row :gutter="16">
        <!-- 左侧版本列表 -->
        <a-col :span="7">
          <a-empty v-if="!versions.length" description="暂无历史版本" />
          <a-list v-else :data-source="versions" size="small">
            <template #renderItem="{ item }">
              <a-list-item
                style="cursor: pointer; padding: 8px 12px; border-radius: 6px"
                :style="{ background: selectedHistVersion?.version === item.version ? '#eef2ff' : 'transparent' }"
                @click="viewVersion(item.version)"
              >
                <a-space direction="vertical" :size="0">
                  <span style="font-weight: 600; color: #4f6df5">v{{ item.version }}</span>
                  <span style="font-size: 11px; color: #8c8c8c">
                    {{ item.saved_at?.slice(5, 16).replace("T", " ") }}
                  </span>
                </a-space>
              </a-list-item>
            </template>
          </a-list>
        </a-col>

        <!-- 右侧内容预览 -->
        <a-col :span="17">
          <a-empty v-if="!selectedHistVersion" description="← 从左侧选择一个版本查看内容" />
          <div v-else>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px">
              <a-typography-text type="secondary">
                v{{ selectedHistVersion.version }}（只读）
              </a-typography-text>
              <a-button
                type="primary"
                :icon="h(RollbackOutlined)"
                :loading="restoring"
                @click="restoreVersion"
              >
                恢复此版本
              </a-button>
            </div>

            <div v-if="histIsSplit">
              <div style="margin-bottom: 16px">
                <a-tag color="blue" style="margin-bottom: 8px">🔧 System</a-tag>
                <a-textarea :value="histSystemPart" :rows="8" readonly />
              </div>
              <div>
                <a-tag color="cyan" style="margin-bottom: 8px">👤 User</a-tag>
                <a-textarea :value="histUserPart" :rows="5" readonly />
              </div>
            </div>
            <a-textarea v-else :value="selectedHistVersion.content" :rows="14" readonly />
          </div>
        </a-col>
      </a-row>
    </a-modal>
  </div>
</template>
