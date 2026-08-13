<template>
  <div>
    <el-card shadow="never">
      <!-- 过滤 + 新建 -->
      <div class="filters">
        <el-select v-model="filters.status" placeholder="状态" clearable class="filter-item" @change="load(1)">
          <el-option v-for="(label, key) in STATUS" :key="key" :label="label" :value="key" />
        </el-select>
        <el-button type="primary" @click="openCreate">新建任务</el-button>
      </div>

      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column prop="title" label="任务" min-width="160" />
        <el-table-column prop="employee_username" label="负责人" width="110">
          <template #default="{ row }">{{ row.employee_username || '-' }}</template>
        </el-table-column>
        <el-table-column prop="department" label="部门" width="100">
          <template #default="{ row }">{{ row.department || '-' }}</template>
        </el-table-column>
        <el-table-column label="截止" width="110">
          <template #default="{ row }">{{ formatDate(row.deadline) }}</template>
        </el-table-column>
        <el-table-column label="进度" width="140">
          <template #default="{ row }">
            <el-progress :percentage="row.progress" :stroke-width="8" />
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ STATUS[row.status] || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="优先级" width="80">
          <template #default="{ row }">
            <el-tag :type="priorityType(row.priority)" size="small">{{ PRIORITY[row.priority] || row.priority }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination layout="total, prev, pager, next" :total="items.length" :page-size="100" />
      </div>
    </el-card>

    <!-- 新建任务 -->
    <el-dialog v-model="createVisible" title="新建任务" width="480px">
      <el-form label-width="90px">
        <el-form-item label="任务名称" required>
          <el-input v-model="form.title" placeholder="如：开发财务模块" />
        </el-form-item>
        <el-form-item label="负责人" required>
          <el-select v-model="form.employee_id" filterable placeholder="选择员工" class="full">
            <el-option
              v-for="u in employees"
              :key="u.id"
              :label="`${u.username}（${u.department || '无部门'}）`"
              :value="u.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="部门">
          <el-input v-model="form.department" placeholder="自动或手动填写" />
        </el-form-item>
        <el-form-item label="截止时间">
          <el-date-picker v-model="form.deadline" type="datetime" placeholder="选择截止时间" class="full"
            value-format="YYYY-MM-DDTHH:mm:ss" />
        </el-form-item>
        <el-form-item label="优先级">
          <el-select v-model="form.priority" class="full">
            <el-option label="低" value="low" />
            <el-option label="普通" value="normal" />
            <el-option label="高" value="high" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="任务说明" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 任务详情 -->
    <el-dialog v-model="detailVisible" title="任务详情" width="520px">
      <template v-if="detail">
        <div class="detail-title">{{ detail.title }}</div>
        <div class="detail-meta">
          负责人：{{ detail.employee_username }} · 部门：{{ detail.department || '-' }}
          · 截止：{{ formatDate(detail.deadline) }} · 进度：{{ detail.progress }}%
        </div>
        <p class="detail-desc">{{ detail.description || '（无描述）' }}</p>
        <el-divider>提交记录</el-divider>
        <el-timeline v-if="detail.updates?.length">
          <el-timeline-item v-for="u in detail.updates" :key="u.id" :timestamp="formatDate(u.created_at)">
            <div>{{ u.content }}</div>
            <div class="update-meta">进度 {{ u.progress }}% · {{ u.ai_summary || '' }}</div>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="暂无提交记录" :image-size="60" />
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const STATUS = { pending: '待处理', processing: '进行中', completed: '已完成', overdue: '已逾期' }
const PRIORITY = { low: '低', normal: '普通', high: '高' }

const items = ref([])
const loading = ref(false)
const saving = ref(false)
const employees = ref([])
const filters = reactive({ status: '' })

const createVisible = ref(false)
const form = reactive({
  title: '',
  employee_id: null,
  department: '',
  deadline: null,
  priority: 'normal',
  description: '',
})

const detailVisible = ref(false)
const detail = ref(null)

function formatDate(iso) {
  return iso ? iso.replace('T', ' ').slice(0, 16) : '-'
}
function statusType(s) {
  return { pending: 'info', processing: 'primary', completed: 'success', overdue: 'danger' }[s] || 'info'
}
function priorityType(p) {
  return { low: 'info', normal: '', high: 'danger' }[p] || ''
}

async function load(p = 1) {
  loading.value = true
  try {
    const params = {}
    if (filters.status) params.status = filters.status
    const resp = await api.get('/admin/tasks', { params })
    items.value = resp.data
  } finally {
    loading.value = false
  }
}

async function loadEmployees() {
  try {
    const resp = await api.get('/admin/task/employees')
    employees.value = resp.data
  } catch {
    employees.value = []
  }
}

function openCreate() {
  Object.assign(form, { title: '', employee_id: null, department: '', deadline: null, priority: 'normal', description: '' })
  createVisible.value = true
}

async function saveCreate() {
  if (!form.title) {
    ElMessage.warning('请填写任务名称')
    return
  }
  if (!form.employee_id) {
    ElMessage.warning('请选择负责人')
    return
  }
  saving.value = true
  try {
    await api.post('/admin/tasks', {
      title: form.title,
      description: form.description,
      employee_id: form.employee_id,
      department: form.department,
      deadline: form.deadline,
      priority: form.priority,
    })
    ElMessage.success('任务已创建')
    createVisible.value = false
    load(1)
  } finally {
    saving.value = false
  }
}

async function openDetail(row) {
  const resp = await api.get(`/admin/tasks/${row.id}`)
  detail.value = resp.data
  detailVisible.value = true
}

onMounted(() => {
  load(1)
  loadEmployees()
})
</script>

<style scoped>
.filters {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  align-items: center;
}
.filter-item {
  width: 160px;
}
.full {
  width: 100%;
}
.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
.detail-title {
  font-size: 18px;
  font-weight: 600;
}
.detail-meta {
  color: #666;
  margin: 8px 0;
  font-size: 13px;
}
.detail-desc {
  background: #f5f7fa;
  padding: 10px;
  border-radius: 6px;
}
.update-meta {
  color: #909399;
  font-size: 12px;
}
</style>
