<script setup>
import { ref } from "vue";
import { message } from "ant-design-vue";
import { addNote } from "../api/index.js";

const title = ref("");
const text = ref("");
const loading = ref(false);

async function submit() {
  if (!text.value.trim()) {
    message.warning("请输入笔记内容");
    return;
  }
  loading.value = true;
  try {
    const res = await addNote(text.value, title.value);
    message.success(`摄入成功: ${res.note_id}`);
    title.value = "";
    text.value = "";
  } catch (e) {
    message.error(`摄入失败: ${e.message}`);
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <a-form layout="vertical">
    <a-form-item label="标题">
      <a-input
        v-model:value="title"
        placeholder="标题（可选，留空自动提取）"
        size="large"
        allow-clear
      />
    </a-form-item>
    <a-form-item label="内容">
      <a-textarea
        v-model:value="text"
        :rows="8"
        placeholder="开始写你的想法..."
        allow-clear
      />
    </a-form-item>
    <a-form-item>
      <a-button
        type="primary"
        size="large"
        :loading="loading"
        @click="submit"
      >
        摄入笔记
      </a-button>
    </a-form-item>
  </a-form>
</template>
