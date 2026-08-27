<script setup>
import { ref, onMounted } from "vue";
import { message, Modal } from "ant-design-vue";
import { uploadFiles } from "../api/index.js";
import { InboxOutlined, EyeOutlined, EyeInvisibleOutlined } from "@ant-design/icons-vue";
import axios from "axios";

const loading = ref(false);
const watch = ref({ running: false, watch_dir: "", recent_events: [] });
const watchLoading = ref(false);

const fileList = ref([]);

async function handleUpload({ fileList: files }) {
  const mdFiles = files.filter((f) => f.name?.endsWith(".md"));
  if (!mdFiles.length) return;
  loading.value = true;
  const formData = new FormData();
  for (const f of mdFiles) {
    formData.append("file", f.originFileObj || f);
  }
  try {
    const res = await uploadFiles(formData);
    message.success(res.message);
    fileList.value = [];
  } catch (e) {
    message.error(`导入失败: ${e.message}`);
  } finally {
    loading.value = false;
  }
}

async function refreshWatch() {
  try {
    const { data } = await axios.get("/api/watch");
    watch.value = data;
  } catch (e) {
    console.error(e);
  }
}

async function toggleWatch() {
  watchLoading.value = true;
  try {
    const url = watch.value.running ? "/api/watch/stop" : "/api/watch/start";
    const { data } = await axios.post(url);
    watch.value = data;
  } catch (e) {
    console.error(e);
  } finally {
    watchLoading.value = false;
  }
}

onMounted(refreshWatch);

const columns = [
  { title: "时间", dataIndex: "time", key: "time", width: 100 },
  { title: "文件", dataIndex: "file", key: "file", ellipsis: true },
  { title: "笔记 ID", dataIndex: "note_id", key: "note_id", width: 120 },
];
</script>

<template>
  <a-space direction="vertical" :size="24" style="width: 100%">
    <div>
      <p style="color: #8c8c8c; margin-bottom: 16px">支持选择多个 .md 文件批量导入</p>
      <a-upload-dragger
        :file-list="fileList"
        :multiple="true"
        accept=".md"
        :before-upload="() => false"
        @change="handleUpload"
        :disabled="loading"
      >
        <p class="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p class="ant-upload-text">点击或拖拽文件到此区域上传</p>
        <p class="ant-upload-hint">仅支持 .md 格式文件</p>
      </a-upload-dragger>
    </div>

    <!-- 文件监听 -->
    <a-card size="small">
      <template #title>
        <a-space>
          <EyeOutlined v-if="watch.running" />
          <EyeInvisibleOutlined v-else />
          <span>自动监听</span>
        </a-space>
      </template>
      <template #extra>
        <a-space>
          <a-tag :color="watch.running ? 'success' : 'default'">
            {{ watch.running ? "监听中" : "已停止" }}
          </a-tag>
          <a-button
            :type="watch.running ? 'default' : 'primary'"
            size="small"
            :loading="watchLoading"
            @click="toggleWatch"
          >
            {{ watch.running ? "停止" : "启动" }}
          </a-button>
        </a-space>
      </template>

      <a-typography-paragraph type="secondary" style="margin: 0 0 12px">
        监听目录：<code>{{ watch.watch_dir }}</code>
        <br />把 .md 文件放入该目录，系统会自动摄入
      </a-typography-paragraph>

      <a-table
        v-if="watch.recent_events && watch.recent_events.length"
        :columns="columns"
        :data-source="watch.recent_events.map((e, i) => ({ ...e, key: i }))"
        :pagination="false"
        size="small"
        :scroll="{ y: 180 }"
      />
      <a-empty v-else description="暂无监听事件" />
    </a-card>
  </a-space>
</template>
