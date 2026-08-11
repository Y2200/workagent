<template>
  <div>
    <!-- 运营统计 -->
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card shadow="never">
          <template #header>知识库</template>
          <div class="stat-line">
            总数 <b>{{ stats.documents?.total ?? 0 }}</b>
            <span class="ok">就绪 {{ stats.documents?.ready ?? 0 }}</span>
            <span class="warn">处理中 {{ stats.documents?.processing ?? 0 }}</span>
            <span class="err">失败 {{ stats.documents?.failed ?? 0 }}</span>
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never">
          <template #header>今日问答</template>
          <div class="stat-line">
            次数 <b>{{ stats.qa?.today_count ?? 0 }}</b>
            <span>成功率 {{ pct(stats.qa?.success_rate) }}</span>
          </div>
          <div class="stat-line muted">
            平均耗时 {{ stats.qa?.avg_latency_ms ?? 0 }}ms ·
            平均 {{ stats.qa?.avg_tokens ?? 0 }} tokens
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never">
          <template #header>安全与用量</template>
          <div class="stat-line">
            拒绝 <b class="warn">{{ stats.security?.denied_count ?? 0 }}</b>
            <span>失败 <b class="err">{{ stats.security?.failed_count ?? 0 }}</b></span>
          </div>
          <div class="stat-line muted">
            今日 {{ stats.usage?.tokens_today ?? 0 }} tokens ·
            费用 ¥{{ stats.usage?.estimated_cost ?? 0 }}
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="row-gap">
      <el-col :span="14">
        <el-card shadow="never">
          <template #header>最近文档</template>
          <el-table :data="recentDocs" size="small" stripe>
            <el-table-column prop="filename" label="文件名" show-overflow-tooltip />
            <el-table-column prop="category" label="分类" width="100" />
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.status === 'ready' ? 'success' : 'warning'" size="small">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card shadow="never">
          <template #header>知识库检索</template>
          <el-input
            v-model="keyword"
            placeholder="输入关键词检索知识库"
            @keyup.enter="doSearch"
          >
            <template #append>
              <el-button @click="doSearch">检索</el-button>
            </template>
          </el-input>
          <div v-if="hits.length" class="hits">
            <div v-for="(hit, i) in hits" :key="i" class="hit-item">
              <div class="hit-title">
                {{ hit.document_filename || hit.source }}
                <el-tag size="small" type="info">{{ hit.score.toFixed(3) }}</el-tag>
              </div>
              <div class="hit-text">{{ hit.text }}</div>
            </div>
          </div>
          <el-empty
            v-else-if="searched"
            description="无检索结果"
            :image-size="60"
          />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import api from '../api'

const stats = ref({})
const documents = ref([])
const keyword = ref('')
const hits = ref([])
const searched = ref(false)

const recentDocs = computed(() =>
  [...documents.value].sort((a, b) => b.id - a.id).slice(0, 8),
)

function pct(v) {
  return v == null ? '-' : `${(v * 100).toFixed(1)}%`
}

async function loadStats() {
  const resp = await api.get('/admin/dashboard/stats')
  stats.value = resp.data
}

async function loadDocuments() {
  const resp = await api.get('/admin/documents')
  documents.value = resp.data
}

async function doSearch() {
  const q = keyword.value.trim()
  if (!q) return
  const resp = await api.get('/admin/knowledge/search', { params: { q, top_k: 8 } })
  hits.value = resp.data
  searched.value = true
}

onMounted(() => {
  loadStats()
  loadDocuments()
})
</script>

<style scoped>
.stat-line {
  font-size: 14px;
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.stat-line b {
  font-size: 22px;
  color: #409eff;
}
.muted {
  color: #999;
  font-size: 13px;
  margin-top: 6px;
}
.ok { color: #67c23a; }
.warn { color: #e6a23c; }
.err { color: #f56c6c; }
.row-gap {
  margin-top: 16px;
}
.hits {
  margin-top: 12px;
}
.hit-item {
  border: 1px solid #eee;
  border-radius: 6px;
  padding: 8px;
  margin-bottom: 8px;
}
.hit-title {
  font-size: 13px;
  color: #409eff;
  margin-bottom: 4px;
}
.hit-text {
  font-size: 13px;
  color: #555;
}
</style>
