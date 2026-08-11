<template>
  <div>
    <!-- 审计统计 -->
    <el-card shadow="never" class="stat-card">
      <div class="stats-row">
        <div class="stat-item">
          <div class="stat-num">{{ auditStats.total ?? 0 }}</div>
          <div class="stat-label">未归档日志</div>
        </div>
        <div class="stat-item">
          <div class="stat-num">{{ auditStats.today ?? 0 }}</div>
          <div class="stat-label">今日</div>
        </div>
        <div class="stat-item">
          <div class="stat-num">{{ auditStats.archived ?? 0 }}</div>
          <div class="stat-label">已归档</div>
        </div>
        <div class="stat-item">
          <div class="stat-num">{{ formatSize(auditStats.storage_size) }}</div>
          <div class="stat-label">存储占用</div>
        </div>
        <el-button type="warning" plain class="archive-btn" @click="doArchive">
          归档过期日志
        </el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <!-- 过滤条件 -->
      <div class="filters">
        <el-select v-model="filters.status" placeholder="状态" clearable class="filter-item">
          <el-option label="成功" value="success" />
          <el-option label="失败" value="failed" />
          <el-option label="拒绝" value="denied" />
          <el-option label="处理中" value="processing" />
        </el-select>
        <el-select v-model="filters.channel" placeholder="渠道" clearable class="filter-item">
          <el-option label="企业微信" value="wechat" />
          <el-option label="Web" value="web" />
          <el-option label="后台" value="admin" />
        </el-select>
        <el-input
          v-model="filters.user_id"
          placeholder="用户ID"
          class="filter-item"
          clearable
        />
        <el-date-picker
          v-model="filters.range"
          type="datetimerange"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          class="filter-item"
          value-format="YYYY-MM-DDTHH:mm:ss"
        />
        <el-button type="primary" @click="load(1)">查询</el-button>
        <el-button @click="reset">重置</el-button>
      </div>

      <!-- 日志表格 -->
      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column prop="created_at" label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="用户" width="110">
          <template #default="{ row }">
            {{ row.username || row.user_id || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="tenant_id" label="租户" width="70">
          <template #default="{ row }">
            {{ row.tenant_id === '' ? '默认' : row.tenant_id }}
          </template>
        </el-table-column>
        <el-table-column prop="channel" label="渠道" width="90" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">
              {{ statusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="question" label="问题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="intent" label="意图" width="90">
          <template #default="{ row }">{{ row.intent || '-' }}</template>
        </el-table-column>
        <el-table-column prop="latency_ms" label="耗时ms" width="90" />
        <el-table-column prop="token_usage" label="tokens" width="90" />
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pager">
        <el-pagination
          layout="total, prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page="page"
          @current-change="load"
        />
      </div>
    </el-card>

    <!-- 详情对话框 -->
    <el-dialog v-model="detailVisible" title="审计日志详情" width="720px">
      <template v-if="detail">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="request_id">{{ detail.request_id }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusType(detail.status)" size="small">
              {{ statusText(detail.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="用户">
            {{ detail.username || detail.user_id || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="部门/角色">
            {{ detail.department }} / {{ detail.role }}
          </el-descriptions-item>
          <el-descriptions-item label="渠道">{{ detail.channel }}</el-descriptions-item>
          <el-descriptions-item label="耗时/Token">
            {{ detail.latency_ms }}ms / {{ detail.token_usage }}
          </el-descriptions-item>
          <el-descriptions-item label="错误类型" :span="1">
            {{ detail.error_type || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="错误信息" :span="1">
            {{ detail.error_message || '-' }}
          </el-descriptions-item>
        </el-descriptions>

        <h4 class="section-title">问题</h4>
        <div class="content-box">{{ detail.question }}</div>

        <h4 class="section-title">回答</h4>
        <div class="content-box">{{ detail.answer || '（无）' }}</div>

        <h4 class="section-title">命中文档（{{ detail.retrieval_documents?.length || 0 }}）</h4>
        <div v-if="detail.retrieval_documents && detail.retrieval_documents.length">
          <el-tag
            v-for="(doc, i) in detail.retrieval_documents"
            :key="i"
            size="small"
            class="doc-tag"
          >
            {{ doc.source }} {{ doc.score?.toFixed ? '(' + doc.score.toFixed(3) + ')' : '' }}
          </el-tag>
        </div>
        <el-empty v-else description="无检索命中" :image-size="50" />
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const detailVisible = ref(false)
const detail = ref(null)
const auditStats = ref({})

const filters = reactive({
  status: '',
  channel: '',
  user_id: '',
  range: null,
})

const statusMap = {
  processing: ['warning', '处理中'],
  success: ['success', '成功'],
  failed: ['danger', '失败'],
  denied: ['info', '拒绝'],
}

function statusType(s) {
  return statusMap[s]?.[0] || 'info'
}
function statusText(s) {
  return statusMap[s]?.[1] || s
}
function formatTime(iso) {
  return iso ? iso.replace('T', ' ').slice(0, 19) : ''
}
function formatSize(bytes) {
  if (!bytes && bytes !== 0) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

async function loadStats() {
  const resp = await api.get('/admin/audit/statistics')
  auditStats.value = resp.data
}

async function doArchive() {
  await ElMessageBox.confirm(
    '将归档超过保留期（.env 中 AUDIT_LOG_RETENTION_DAYS）的问答日志，归档仅标记不删除。',
    '归档确认',
    { type: 'warning' },
  )
  try {
    const resp = await api.post('/admin/audit/archive')
    ElMessage.success(`已归档 ${resp.data.archived_count} 条`)
    loadStats()
    load(1)
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '归档失败')
  }
}

async function load(p = page.value) {
  loading.value = true
  try {
    const params = { page: p, page_size: pageSize }
    if (filters.status) params.status = filters.status
    if (filters.channel) params.channel = filters.channel
    if (filters.user_id) params.user_id = filters.user_id
    if (filters.range && filters.range.length === 2) {
      params.start_time = filters.range[0]
      params.end_time = filters.range[1]
    }
    const resp = await api.get('/admin/logs', { params })
    items.value = resp.data.items
    total.value = resp.data.total
    page.value = resp.data.page
  } finally {
    loading.value = false
  }
}

function reset() {
  filters.status = ''
  filters.channel = ''
  filters.user_id = ''
  filters.range = null
  load(1)
}

function openDetail(row) {
  detail.value = row
  detailVisible.value = true
}

onMounted(() => {
  load(1)
  loadStats()
})
</script>

<style scoped>
.stat-card {
  margin-bottom: 16px;
}
.stats-row {
  display: flex;
  align-items: center;
  gap: 40px;
  flex-wrap: wrap;
}
.stat-item {
  text-align: center;
}
.stat-num {
  font-size: 22px;
  font-weight: 700;
  color: #409eff;
}
.stat-label {
  color: #999;
  font-size: 12px;
  margin-top: 2px;
}
.archive-btn {
  margin-left: auto;
}
.table-card {
  margin-bottom: 16px;
}
.filters {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.filter-item {
  width: 160px;
}
.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
.section-title {
  margin: 14px 0 8px;
}
.content-box {
  border: 1px solid #eee;
  border-radius: 6px;
  padding: 10px;
  font-size: 13px;
  color: #333;
  max-height: 160px;
  overflow-y: auto;
  white-space: pre-wrap;
}
.doc-tag {
  margin-right: 6px;
  margin-bottom: 4px;
}
</style>
