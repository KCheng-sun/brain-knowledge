<script setup>
import { ref, computed, h, onMounted } from "vue";
import { message } from "ant-design-vue";
import { ReloadOutlined, EyeOutlined } from "@ant-design/icons-vue";
import axios from "axios";

const items = ref([]);
const loading = ref(false);
const currentIndex = ref(0);
const revealed = ref(false);
const noteContent = ref("");

const current = computed(() => items.value[currentIndex.value] || null);
const progress = computed(() =>
  items.value.length
    ? `${currentIndex.value + 1}/${items.value.length}`
    : "0/0"
);

async function refresh() {
  loading.value = true;
  try {
    const { data } = await axios.get("/api/review", { params: { limit: 20 } });
    items.value = data.items || [];
    currentIndex.value = 0;
    revealed.value = false;
    noteContent.value = "";
  } catch (e) {
    console.error(e);
  } finally {
    loading.value = false;
  }
}

async function reveal() {
  if (revealed.value) return;
  try {
    const { data } = await axios.get(
      `/api/notes/${current.value.note_id}/content`
    );
    noteContent.value = data.content || "(内容为空)";
  } catch (e) {
    noteContent.value = "(内容取回失败)";
  }
  revealed.value = true;
}

async function rate(quality) {
  if (!current.value) return;
  try {
    await axios.post("/api/review/record", {
      note_id: current.value.note_id,
      quality,
    });
  } catch (e) {
    message.error("评分记录失败");
  }
  revealed.value = false;
  noteContent.value = "";
  if (currentIndex.value < items.value.length - 1) {
    currentIndex.value++;
  } else {
    await refresh();
  }
}

onMounted(refresh);
</script>

<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px">
      <a-typography-text type="secondary">
        先回想，再展开验证，最后诚实评分——SM-2 会据此安排下次复习
      </a-typography-text>
      <a-button :icon="h(ReloadOutlined)" :loading="loading" @click="refresh">
        刷新
      </a-button>
    </div>

    <a-result
      v-if="!loading && items.length === 0"
      status="success"
      title="今日复习完成！"
      sub-title="没有到期的卡片。新笔记摄入后会自动加入复习队列"
    />

    <div v-else-if="current" style="max-width: 560px; margin: 0 auto">
      <a-progress
        :percent="Math.round(((currentIndex.value) / items.length) * 100)"
        :format="() => progress"
        size="small"
        style="margin-bottom: 16px"
      />

      <a-card>
        <template #title>
          <a-space>
            <a-tag :color="current.is_new ? 'blue' : 'green'">
              {{ current.is_new ? "新卡片" : `第 ${current.review_count} 次复习` }}
            </a-tag>
            <span v-if="!current.is_new" style="font-size: 12px; color: #8c8c8c">
              熟练度 {{ current.ease_factor?.toFixed?.(2) ?? "2.50" }} · 间隔 {{ current.interval_days }} 天
            </span>
          </a-space>
        </template>

        <h3 style="font-size: 20px; margin-bottom: 16px">{{ current.title }}</h3>

        <div v-if="!revealed" style="text-align: center; padding: 30px 0">
          <a-typography-text type="secondary">
            🤔 先试着回想这篇笔记讲了什么...
          </a-typography-text>
        </div>

        <div v-else>
          <a-typography-paragraph
            style="white-space: pre-wrap; max-height: 240px; overflow-y: auto"
          >
            {{ noteContent }}
          </a-typography-paragraph>
        </div>

        <div style="margin-top: 20px">
          <a-button
            v-if="!revealed"
            type="primary"
            block
            size="large"
            :icon="h(EyeOutlined)"
            @click="reveal"
          >
            显示内容
          </a-button>
          <a-row v-else :gutter="8">
            <a-col :span="6">
              <a-button block danger size="large" @click="rate(1)">😵 忘记</a-button>
            </a-col>
            <a-col :span="6">
              <a-button block size="large" @click="rate(3)">😅 困难</a-button>
            </a-col>
            <a-col :span="6">
              <a-button block size="large" @click="rate(4)">🙂 良好</a-button>
            </a-col>
            <a-col :span="6">
              <a-button block type="primary" size="large" @click="rate(5)">🤩 简单</a-button>
            </a-col>
          </a-row>
        </div>
      </a-card>
    </div>
  </div>
</template>
