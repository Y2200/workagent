<template>
  <div>
    <el-card shadow="never">
      <div class="actions">
        <el-button type="primary" @click="loadStats">刷新</el-button>
        <el-button @click="download('/admin/task/stats/export?format=xlsx', 'task_stats.xlsx')">
          导出 Excel
        </el-button>
        <el-button @click="download('/admin/task/stats/export?format=docx', 'task_stats.docx')">
          导出 Word
        </el-button>
        <el-button @click="download('/admin/task/report/weekly/export?format=docx', 'weekly_report.docx')">
          下载周报
        </el-button>
      </div>

      <!-- 总览 -->
      <el-row :gutter="16" class="cards">
        <el-col :span="4" v-for="item in overviewCards" :key="item.key">
          <el-card shadow="never">
            <div class="stat-label">{{ item.label }}</div>
            <div class="stat-num">{{ stats.overview?.[item.key] ?? 0 }}</div>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="16">
        <el-col :span="12">
          <el-card shadow="never">
            <template #header>按部门</template>
            <el-table :data="stats.by_department" size="small" stripe v-loading="loading">
              <el-table-column prop="department" label="部门" />
              <el-table-column prop="total" label="任务数" width="80" />
              <el-table-column prop="completed" label="已完成" width="80" />
              <el-table-column prop="completion_rate" label="完成率%" width="90" />
              <el-table-column prop="high_risk" label="高风险" width="80" />
              <el-table-column prop="medium_risk" label="中风险" width="80" />
            </el-table>
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card shadow="never">
            <template #header>按员工</template>
            <el-table :data="stats.by_employee" size="small" stripe>
              <el-table-column label="姓名">
                <template #default="{ row }">{{ row.real_name || row.username || '-' }}</template>
              </el-table-column>
              <el-table-column prop="department" label="部门" width="90" />
              <el-table-column prop="total" label="任务数" width="80" />
              <el-table-column prop="completion_rate" label="完成率%" width="90" />
              <el-table-column prop="high_risk" label="高风险" width="80" />
            </el-table>
          </el-card>
        </el-col>
      </el-row>

      <el-card shadow="never" class="risk-card">
        <template #header>风险任务</template>
        <el-table :data="stats.risky_tasks" size="small" stripe>
          <el-table-column prop="title" label="任务" show-overflow-tooltip />
          <el-table-column label="负责人" width="110">
            <template #default="{ row }">{{ row.real_name || row.username || '-' }}</template>
          </el-table-column>
          <el-table-column prop="department" label="部门" width="100" />
          <el-table-column label="进度%" width="80">
            <template #default="{ row }">{{ row.progress }}%</template>
          </el-table-column>
          <el-table-column label="风险" width="90">
            <template #default="{ row }">
              <el-tag
                :type="row.risk_level === 'high' ? 'danger' : 'warning'"
                size="small"
              >
                {{ row.risk_level }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="risk_reason" label="原因" show-overflow-tooltip />
        </el-table>
      </el-card>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const loading = ref(false)
const stats = ref({
  overview: {},
  by_department: [],
  by_employee: [],
  risky_tasks: [],
})

const overviewCards = [
  { key: 'total', label: '任务总数' },
  { key: 'pending', label: '待处理' },
  { key: 'processing', label: '进行中' },
  { key: 'completed', label: '已完成' },
  { key: 'overdue', label: '已逾期' },
]

async function loadStats() {
  loading.value = true
  try {
    const resp = await api.get('/admin/task/stats')
    stats.value = resp.data
  } finally {
    loading.value = false
  }
}

async function download(url, filename) {
  try {
    const resp = await api.get(url, { responseType: 'blob' })
    const blobUrl = URL.createObjectURL(resp.data)
    const a = document.createElement('a')
    a.href = blobUrl
    a.download = filename
    a.click()
    URL.revokeObjectURL(blobUrl)
    ElMessage.success(`已下载 ${filename}`)
  } catch (e) {
    ElMessage.error('下载失败')
  }
}

onMounted(loadStats)
</script>

<style scoped>
.actions {
  margin-bottom: 16px;
}
.cards {
  margin-bottom: 16px;
}
.stat-label {
  color: #909399;
  font-size: 13px;
}
.stat-num {
  font-size: 24px;
  font-weight: 600;
  margin-top: 4px;
}
.risk-card {
  margin-top: 16px;
}
</style>
