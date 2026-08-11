<template>
  <div>
    <!-- 工具栏 -->
    <el-card shadow="never">
      <div class="toolbar">
        <el-input
          v-model="keyword"
          placeholder="检索知识库内容"
          class="search-input"
          clearable
          @keyup.enter="doSearch"
        >
          <template #append>
            <el-button @click="doSearch">检索</el-button>
          </template>
        </el-input>
        <el-button type="primary" @click="openUpload">上传文档</el-button>
      </div>

      <!-- 检索结果提示 -->
      <div v-if="searchMode" class="search-tip">
        检索结果：共 {{ searchHits.length }} 条（关键词：{{ lastKeyword }}）
        <el-button link type="primary" @click="resetSearch">返回列表</el-button>
      </div>

      <!-- 文档列表 -->
      <el-table :data="documents" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="filename" label="文件名" min-width="180" show-overflow-tooltip />
        <el-table-column prop="category" label="分类" width="110" />
        <el-table-column label="可见性" width="90">
          <template #default="{ row }">
            <el-tag :type="row.visibility === 'public' ? 'success' : 'warning'" size="small">
              {{ row.visibility === 'public' ? '公开' : '受限' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">
              {{ statusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="切片数" width="80" />
        <el-table-column prop="uploader" label="上传者" width="100" />
        <el-table-column prop="created_at" label="上传时间" width="170">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 上传对话框 -->
    <el-dialog v-model="uploadVisible" title="上传文档" width="520px">
      <el-form :model="uploadForm" label-width="90px">
        <el-form-item label="文件">
          <input type="file" class="file-input" @change="onFileChange" />
        </el-form-item>
        <el-form-item label="分类">
          <el-input v-model="uploadForm.category" placeholder="如：财务管理" />
        </el-form-item>
        <el-form-item label="可见性">
          <el-radio-group v-model="uploadForm.visibility">
            <el-radio value="public">公开</el-radio>
            <el-radio value="restricted">受限</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="可见部门">
          <el-input
            v-model="uploadForm.departments"
            placeholder="多个用逗号分隔，如：财务部,研发部"
          />
        </el-form-item>
        <el-form-item label="可见角色">
          <el-input
            v-model="uploadForm.roles"
            placeholder="多个用逗号分隔，如：财务人员,管理人员"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="submitUpload">
          上传
        </el-button>
      </template>
    </el-dialog>

    <!-- 详情对话框 -->
    <el-dialog v-model="detailVisible" title="文档详情" width="640px">
      <template v-if="detail">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="文件名">{{ detail.filename }}</el-descriptions-item>
          <el-descriptions-item label="分类">{{ detail.category }}</el-descriptions-item>
          <el-descriptions-item label="可见性">
            {{ detail.visibility === 'public' ? '公开' : '受限' }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">{{ statusText(detail.status) }}</el-descriptions-item>
          <el-descriptions-item label="切片数">{{ detail.chunks?.length || 0 }}</el-descriptions-item>
          <el-descriptions-item label="上传者">{{ detail.uploader }}</el-descriptions-item>
          <el-descriptions-item label="错误信息" :span="2">
            {{ detail.error_message || '无' }}
          </el-descriptions-item>
        </el-descriptions>

        <h4 class="section-title">权限</h4>
        <el-table :data="detail.permissions || []" size="small" border>
          <el-table-column prop="department" label="部门" />
          <el-table-column prop="role" label="角色" />
        </el-table>

        <h4 class="section-title">知识切片（{{ detail.chunks?.length || 0 }}）</h4>
        <div v-if="detail.chunks && detail.chunks.length" class="chunk-list">
          <div v-for="chunk in detail.chunks" :key="chunk.id" class="chunk-item">
            <span class="chunk-index">#{{ chunk.chunk_index }}</span>
            {{ chunk.content }}
          </div>
        </div>
        <el-empty v-else description="暂无切片" :image-size="60" />
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

const documents = ref([])
const loading = ref(false)
const keyword = ref('')
const searchMode = ref(false)
const searchHits = ref([])
const lastKeyword = ref('')

// 上传
const uploadVisible = ref(false)
const uploading = ref(false)
const selectedFile = ref(null)
const uploadForm = reactive({
  category: '',
  visibility: 'public',
  departments: '',
  roles: '',
})

// 详情
const detailVisible = ref(false)
const detail = ref(null)

// 状态轮询
let pollTimer = null

const statusMap = {
  processing: ['warning', '处理中'],
  ready: ['success', '就绪'],
  failed: ['danger', '失败'],
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

async function loadDocuments() {
  loading.value = true
  try {
    const resp = await api.get('/admin/documents')
    documents.value = resp.data
    // 有处理中的文档则轮询
    schedulePoll()
  } finally {
    loading.value = false
  }
}

function schedulePoll() {
  const hasProcessing = documents.value.some((d) => d.status === 'processing')
  clearInterval(pollTimer)
  if (hasProcessing) {
    pollTimer = setInterval(loadDocuments, 3000)
  }
}

function openUpload() {
  selectedFile.value = null
  uploadForm.category = ''
  uploadForm.visibility = 'public'
  uploadForm.departments = ''
  uploadForm.roles = ''
  uploadVisible.value = true
}

function onFileChange(e) {
  selectedFile.value = e.target.files?.[0] || null
}

async function submitUpload() {
  if (!selectedFile.value) {
    ElMessage.warning('请选择文件')
    return
  }
  const form = new FormData()
  form.append('file', selectedFile.value)
  form.append('category', uploadForm.category)
  form.append('visibility', uploadForm.visibility)
  form.append('departments', uploadForm.departments)
  form.append('roles', uploadForm.roles)
  uploading.value = true
  try {
    await api.post('/admin/documents/upload', form)
    ElMessage.success('上传成功，正在异步处理...')
    uploadVisible.value = false
    await loadDocuments()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '上传失败')
  } finally {
    uploading.value = false
  }
}

async function openDetail(row) {
  const resp = await api.get(`/admin/documents/${row.id}`)
  detail.value = resp.data
  detailVisible.value = true
}

async function remove(row) {
  await ElMessageBox.confirm(
    `确定删除文档「${row.filename}」吗？相关向量与存储将一并删除。`,
    '删除确认',
    { type: 'warning' },
  )
  try {
    await api.delete(`/admin/documents/${row.id}`)
    ElMessage.success('已删除')
    await loadDocuments()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '删除失败')
  }
}

async function doSearch() {
  const q = keyword.value.trim()
  if (!q) {
    resetSearch()
    return
  }
  try {
    const resp = await api.get('/admin/knowledge/search', { params: { q, top_k: 10 } })
    searchHits.value = resp.data
    lastKeyword.value = q
    searchMode.value = true
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '检索失败')
  }
}

function resetSearch() {
  searchMode.value = false
  searchHits.value = []
  keyword.value = ''
}

onMounted(loadDocuments)
onBeforeUnmount(() => clearInterval(pollTimer))
</script>

<style scoped>
.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.search-input {
  max-width: 360px;
}
.search-tip {
  margin-bottom: 12px;
  color: #666;
  font-size: 13px;
}
.file-input {
  width: 100%;
}
.section-title {
  margin: 16px 0 8px;
}
.chunk-list {
  max-height: 240px;
  overflow-y: auto;
  border: 1px solid #eee;
  border-radius: 6px;
  padding: 8px;
}
.chunk-item {
  padding: 6px 4px;
  border-bottom: 1px dashed #eee;
  font-size: 13px;
  color: #333;
}
.chunk-index {
  color: #409eff;
  margin-right: 8px;
}
</style>
