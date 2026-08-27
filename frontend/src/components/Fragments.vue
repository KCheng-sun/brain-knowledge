<script setup>
import { ref, h, onMounted, inject } from "vue";
import { message, Modal } from "ant-design-vue";
import { listFragments } from "../api/index.js";
import { ReloadOutlined, DeleteOutlined, MessageOutlined } from "@ant-design/icons-vue";
import axios from "axios";

const jumpToAsk = inject("jumpToAsk", null);

const fragments = ref([]);
const loading = ref(false);

async function refresh() {
  loading.value = true;
  try {
    fragments.value = await listFragments();
  } catch (e) {
    console.error(e);
  } finally {
    loading.value = false;
  }
}

async function removeFragment(id) {
  try {
    await axios.delete(`/api/fragments/${id}`);
    message.success("已删除");
    await refresh();
  } catch (e) {
    message.error("删除失败");
  }
}

onMounted(refresh);

function onDelete(id) {
  Modal.confirm({
    title: "删除知识片段",
    content: "确定删除这条知识片段？",
    okText: "删除",
    okType: "danger",
    cancelText: "取消",
    onOk: () => removeFragment(id),
  });
}
</script>

<template>
  <a-space direction="vertical" :size="16" style="width: 100%">
    <div style="display: flex; justify-content: space-between; align-items: center">
      <a-typography-text type="secondary">
        对话中经你确认保存的结论沉淀在这里，问答时 Agent 可以引用它们
      </a-typography-text>
      <a-button :icon="h(ReloadOutlined)" :loading="loading" @click="refresh">
        刷新
      </a-button>
    </div>

    <a-empty
      v-if="!loading && fragments.length === 0"
      description="还没有保存的知识片段"
    >
      <template #description>
        <p>还没有保存的知识片段</p>
        <p style="color: #8c8c8c; font-size: 13px">
          在问答中，当 Agent 提议保存知识时点击「保存」即可沉淀到这里
        </p>
      </template>
    </a-empty>

    <a-card
      v-for="f in fragments"
      :key="f.id"
      size="small"
      hoverable
    >
      <template #title>
        <span style="font-weight: 600">{{ f.title }}</span>
      </template>
      <template #extra>
        <a-space>
          <span style="font-size: 12px; color: #8c8c8c">
            {{ f.created_at?.slice(0, 10) }}
          </span>
          <a-button
            type="text"
            size="small"
            danger
            :icon="h(DeleteOutlined)"
            @click="onDelete(f.id)"
          />
        </a-space>
      </template>
      <p style="white-space: pre-wrap; margin: 0 0 12px">{{ f.content }}</p>
      <a-button
        v-if="jumpToAsk"
        type="link"
        size="small"
        :icon="h(MessageOutlined)"
        @click="jumpToAsk(`关于我沉淀的知识片段「${f.title}」，请展开详细讲讲`)"
      >
        展开讲讲
      </a-button>
    </a-card>
  </a-space>
</template>
