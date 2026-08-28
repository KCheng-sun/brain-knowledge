<script setup>
import { ref, h, onMounted } from "vue";
import { message as antMessage, Modal } from "ant-design-vue";
import { ReloadOutlined, PlusOutlined, DeleteOutlined, ThunderboltOutlined } from "@ant-design/icons-vue";
import axios from "axios";

const feeds = ref([]);
const newUrl = ref("");
const loading = ref(false);

async function refresh() {
  try {
    const { data } = await axios.get("/api/rss");
    feeds.value = data;
  } catch (e) {
    console.error(e);
  }
}

async function addFeed() {
  const url = newUrl.value.trim();
  if (!url) return;
  loading.value = true;
  try {
    const { data } = await axios.post("/api/rss", { url });
    antMessage.success(`已添加，新增摄入 ${data.new_entries} 条`);
    newUrl.value = "";
    await refresh();
  } catch (e) {
    antMessage.error(`添加失败: ${e.response?.data?.detail || e.message}`);
  } finally {
    loading.value = false;
  }
}

async function fetchAll() {
  loading.value = true;
  try {
    const { data } = await axios.post("/api/rss/fetch");
    antMessage.success(`检查 ${data.feeds_checked} 个源，新增 ${data.new_entries} 条`);
    await refresh();
  } catch (e) {
    antMessage.error("拉取失败");
  } finally {
    loading.value = false;
  }
}

async function fetchOne(id) {
  loading.value = true;
  try {
    const { data } = await axios.post(`/api/rss/${id}/fetch`);
    antMessage.success(`拉取完成，新增 ${data.new_entries} 条`);
    await refresh();
  } catch (e) {
    antMessage.error(`拉取失败: ${e.response?.data?.detail || e.message}`);
  } finally {
    loading.value = false;
  }
}

function onRemove(id) {
  Modal.confirm({
    title: "删除订阅源",
    content: "确定删除这个订阅源？",
    okText: "删除",
    okType: "danger",
    cancelText: "取消",
    onOk: async () => {
      await axios.delete(`/api/rss/${id}`);
      antMessage.success("已删除");
      await refresh();
    },
  });
}

onMounted(refresh);

const columns = [
  { title: "订阅源", key: "title", ellipsis: true },
  { title: "文章数", dataIndex: "entry_count", key: "entry_count", width: 100 },
  { title: "上次拉取", key: "last_fetched", width: 130 },
  { title: "操作", key: "action", width: 120 },
];
</script>

<template>
  <a-space direction="vertical" :size="16" style="width: 100%">
    <div style="display: flex; justify-content: space-between; align-items: center">
      <a-typography-text type="secondary">
        订阅 RSS 源，新文章自动摄入知识库（打标签、建关联）
      </a-typography-text>
      <a-button type="primary" :icon="h(ThunderboltOutlined)" :loading="loading" @click="fetchAll">
        立即拉取
      </a-button>
    </div>

    <a-input-search
      v-model:value="newUrl"
      placeholder="输入 RSS/Atom 订阅源 URL"
      enter-button="添加"
      size="large"
      :loading="loading"
      @search="addFeed"
    >
      <template #enterButton>
        <a-button type="primary" :icon="h(PlusOutlined)">添加</a-button>
      </template>
    </a-input-search>

    <a-table
      :columns="columns"
      :data-source="feeds.map((f) => ({ ...f, key: f.id }))"
      :pagination="false"
      :loading="loading"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'title'">
          <div style="font-weight: 600">{{ record.title || record.url }}</div>
          <div style="font-size: 12px; color: #8c8c8c; font-family: monospace">
            {{ record.url }}
          </div>
        </template>
        <template v-else-if="column.key === 'last_fetched'">
          {{ record.last_fetched_at ? record.last_fetched_at.slice(0, 10) : "从未" }}
        </template>
        <template v-else-if="column.key === 'action'">
          <a-space size="small">
            <a-button type="text" size="small" :icon="h(ReloadOutlined)" :loading="loading" @click="fetchOne(record.id)" />
            <a-button type="text" danger size="small" :icon="h(DeleteOutlined)" @click="onRemove(record.id)" />
          </a-space>
        </template>
      </template>
    </a-table>

    <a-empty v-if="!feeds.length && !loading" description="还没有订阅源" />
  </a-space>
</template>
