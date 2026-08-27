<script setup>
import { ref, watch } from "vue";
import { searchNotes } from "../api/index.js";
import { SearchOutlined } from "@ant-design/icons-vue";

const props = defineProps({
  seed: { type: Object, default: null },
});

const query = ref("");
const tag = ref("");
const topK = ref(5);
const results = ref([]);
const total = ref(0);
const loading = ref(false);

async function search() {
  if (!query.value.trim()) return;
  loading.value = true;
  try {
    const data = await searchNotes(query.value, tag.value, topK.value);
    results.value = data.results;
    total.value = data.total;
  } catch (e) {
    results.value = [];
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.seed,
  (newSeed) => {
    if (newSeed && newSeed.query) {
      query.value = newSeed.query;
      search();
    }
  },
  { immediate: true }
);
</script>

<template>
  <div>
    <a-space direction="vertical" :size="16" style="width: 100%">
      <a-input-group compact>
        <a-input
          v-model:value="query"
          placeholder="输入关键词..."
          style="width: calc(100% - 360px)"
          size="large"
          @press-enter="search"
        />
        <a-input
          v-model:value="tag"
          placeholder="标签（可选）"
          style="width: 150px"
          size="large"
          @press-enter="search"
        />
        <a-select
          v-model:value="topK"
          style="width: 90px"
          size="large"
        >
          <a-select-option :value="3">3 条</a-select-option>
          <a-select-option :value="5">5 条</a-select-option>
          <a-select-option :value="10">10 条</a-select-option>
          <a-select-option :value="20">20 条</a-select-option>
        </a-select>
        <a-button
          type="primary"
          size="large"
          :loading="loading"
          @click="search"
        >
          <template #icon><SearchOutlined /></template>
          搜索
        </a-button>
      </a-input-group>

      <a-alert
        v-if="total > 0"
        :message="`共 ${total} 条结果`"
        type="info"
        show-icon
      />

      <a-list
        v-if="results.length"
        :data-source="results"
        :split="true"
      >
        <template #renderItem="{ item }">
          <a-list-item>
            <a-list-item-meta>
              <template #title>
                <a-space>
                  <a-tag color="blue">{{ item.score }}</a-tag>
                  <span style="font-weight: 600">{{ item.title }}</span>
                </a-space>
              </template>
              <template #description>
                <div v-if="item.tags.length" style="margin-bottom: 4px">
                  <a-tag v-for="t in item.tags" :key="t" color="default">{{ t }}</a-tag>
                </div>
                <div>{{ item.content_preview }}...</div>
                <code style="font-size: 12px; color: #8c8c8c">{{ item.note_id }}</code>
              </template>
            </a-list-item-meta>
          </a-list-item>
        </template>
      </a-list>

      <a-empty
        v-if="!loading && results.length === 0 && query"
        description="没有找到相关笔记"
      />
    </a-space>
  </div>
</template>
