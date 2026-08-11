<template>
  <div>
    <el-card shadow="never">
      <!-- 过滤 -->
      <div class="filters">
        <el-select v-model="filters.action" placeholder="操作类型" clearable class="filter-item">
          <el-option label="登录" value="auth.login" />
          <el-option label="登录失败" value="auth.login_failed" />
          <el-option label="上传文档" value="document.create" />
          <el-option label="删除文档" value="document.delete" />
          <el-option label="修改权限" value="document.permission_update" />
          <el-option label="导出数据" value="data.export" />
        </el-select>
        <el-input v-model="filters.user_id" placeholder="用户ID" class="filter-item" clearable />
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

      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column prop="created_at" label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="用户" width="110">
          <template #default="{ row }">
            {{ row.username || row.user_id || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="action" label="操作" min-width="160" />
        <el-table-column prop="target_type" label="对象类型" width="100">
          <template #default="{ row }">{{ row.target_type || '-' }}</template>
        </el-table-column>
        <el-table-column prop="target_id" label="对象ID" width="80">
          <template #default="{ row }">{{ row.target_id || '-' }}</template>
        </el-table-column>
        <el-table-column prop="ip" label="IP" width="130">
          <template #default="{ row }">{{ row.ip || '-' }}</template>
        </el-table-column>
      </el-table>

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
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import api from '../api'

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)

const filters = reactive({
  action: '',
  user_id: '',
  range: null,
})

function formatTime(iso) {
  return iso ? iso.replace('T', ' ').slice(0, 19) : ''
}

async function load(p = page.value) {
  loading.value = true
  try {
    const params = { page: p, page_size: pageSize }
    if (filters.action) params.action = filters.action
    if (filters.user_id) params.user_id = filters.user_id
    if (filters.range && filters.range.length === 2) {
      params.start_time = filters.range[0]
      params.end_time = filters.range[1]
    }
    const resp = await api.get('/admin/operations', { params })
    items.value = resp.data.items
    total.value = resp.data.total
    page.value = resp.data.page
  } finally {
    loading.value = false
  }
}

function reset() {
  filters.action = ''
  filters.user_id = ''
  filters.range = null
  load(1)
}

onMounted(() => load(1))
</script>

<style scoped>
.filters {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.filter-item {
  width: 180px;
}
.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
