<script setup>
import { ref, computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import { getTags } from "../api/index.js";
import { TagOutlined, ReloadOutlined } from "@ant-design/icons-vue";

const router = useRouter();
const tags = ref([]);
const loading = ref(true);
const filterText = ref("");

const filteredTags = computed(() => {
  if (!filterText.value) return tags.value;
  const kw = filterText.value.toLowerCase();
  return tags.value.filter((t) => t.name.toLowerCase().includes(kw));
});

const maxCount = computed(() => {
  return Math.max(...tags.value.map((t) => t.count), 1);
});

// 标签字号按计数权重：12px ~ 32px
function fontSize(count) {
  return 12 + (count / maxCount.value) * 20;
}

async function refresh() {
  loading.value = true;
  try {
    tags.value = await getTags();
  } catch (e) {
    console.error(e);
  } finally {
    loading.value = false;
  }
}

function clickTag(tagName) {
  // 点击标签跳转搜索页，带 tag 参数
  router.push({ path: "/search", query: { tag: tagName } });
}

onMounted(refresh);
</script>

<template>
  <div class="tags-page">
    <div class="page-header">
      <h2><TagOutlined /> 标签浏览</h2>
      <a-button @click="refresh" :loading="loading">
        <template #icon><ReloadOutlined /></template>
        刷新
      </a-button>
    </div>

    <a-input
      v-model:value="filterText"
      placeholder="过滤标签名..."
      allow-clear
      style="max-width: 300px; margin-bottom: 16px"
    />

    <a-empty v-if="!loading && filteredTags.length === 0" description="暂无标签" />

    <div v-else class="tag-cloud">
      <span
        v-for="tag in filteredTags"
        :key="tag.name"
        class="tag-item"
        :style="{ fontSize: fontSize(tag.count) + 'px' }"
        @click="clickTag(tag.name)"
      >
        {{ tag.name }}
        <span class="tag-count">{{ tag.count }}</span>
      </span>
    </div>

    <div v-if="tags.length > 0" class="tag-summary">
      共 {{ tags.length }} 个标签，{{ tags.reduce((s, t) => s + t.count, 0) }} 次使用
    </div>
  </div>
</template>

<style scoped>
.tags-page {
  max-width: 1000px;
  margin: 0 auto;
  padding: 16px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.page-header h2 {
  margin: 0;
}

.tag-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 16px;
  padding: 24px;
  background: #fafafa;
  border-radius: 8px;
  align-items: center;
}

.tag-item {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  cursor: pointer;
  color: #1890ff;
  transition: all 0.2s;
  line-height: 1.5;
}

.tag-item:hover {
  color: #0050b3;
  text-decoration: underline;
}

.tag-count {
  font-size: 12px;
  color: #999;
  font-weight: normal;
}

.tag-summary {
  margin-top: 16px;
  color: #666;
  font-size: 13px;
}
</style>
