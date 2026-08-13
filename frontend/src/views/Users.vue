<template>
  <div>
    <el-card shadow="never">
      <!-- 过滤 -->
      <div class="filters">
        <el-input
          v-model="keyword"
          placeholder="搜索用户名 / 部门 / 企微账号"
          class="filter-item"
          clearable
          @keyup.enter="load(1)"
        />
        <el-button type="primary" @click="load(1)">查询</el-button>
        <el-button @click="reset">重置</el-button>
        <el-alert
          class="tip"
          title="绑定后，员工即可通过企业微信向 Work Agent 提问；解绑将立即失效。"
          type="info"
          :closable="false"
          show-icon
        />
      </div>

      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="username" label="用户名" width="120" />
        <el-table-column prop="department" label="部门" width="120">
          <template #default="{ row }">{{ row.department || '-' }}</template>
        </el-table-column>
        <el-table-column label="角色" width="130">
          <template #default="{ row }">
            <el-tag v-for="r in row.roles" :key="r" size="small" class="role-tag">
              {{ roleName(r) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="tenant_id" label="租户" width="90">
          <template #default="{ row }">{{ row.tenant_id || '平台' }}</template>
        </el-table-column>
        <el-table-column label="企微绑定" width="140">
          <template #default="{ row }">
            <el-tag v-if="row.wechat_user_id" type="success" size="small">
              {{ row.wechat_user_id }}
            </el-tag>
            <el-tag v-else type="info" size="small">未绑定</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button link type="primary" @click="openBind(row)">绑定/修改</el-button>
            <el-button
              link
              type="danger"
              :disabled="!row.wechat_user_id"
              @click="unbind(row)"
            >
              解绑
            </el-button>
          </template>
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

    <!-- 绑定对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="`绑定企微账号 · ${form.username}`"
      width="420px"
    >
      <el-form label-width="96px">
        <el-form-item label="企微 UserID">
          <el-input
            v-model="form.wechat_user_id"
            placeholder="企业微信中的 userid（如 zhangsan）"
            clearable
          />
        </el-form-item>
        <el-form-item label="租户">
          <span>{{ form.tenant_id || '平台' }}</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveBind">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const keyword = ref('')
const saving = ref(false)

const dialogVisible = ref(false)
const form = reactive({
  id: null,
  username: '',
  tenant_id: '',
  wechat_user_id: '',
})

const ROLE_NAMES = {
  SUPER_ADMIN: '超级管理员',
  TENANT_ADMIN: '租户管理员',
  DEPARTMENT_ADMIN: '部门管理员',
  USER: '普通用户',
}

function roleName(code) {
  return ROLE_NAMES[code] || code
}

async function load(p = page.value) {
  loading.value = true
  try {
    const params = { page: p, page_size: pageSize }
    if (keyword.value) params.keyword = keyword.value
    const resp = await api.get('/admin/users', { params })
    items.value = resp.data.items
    total.value = resp.data.total
    page.value = resp.data.page ?? 1
  } finally {
    loading.value = false
  }
}

function reset() {
  keyword.value = ''
  load(1)
}

function openBind(row) {
  form.id = row.id
  form.username = row.username
  form.tenant_id = row.tenant_id
  form.wechat_user_id = row.wechat_user_id || ''
  dialogVisible.value = true
}

async function saveBind() {
  if (!form.wechat_user_id) {
    ElMessage.warning('企微 UserID 不能为空；如需解绑请点「解绑」')
    return
  }
  saving.value = true
  try {
    const resp = await api.put(`/admin/users/${form.id}/wechat`, {
      wechat_user_id: form.wechat_user_id,
    })
    ElMessage.success('绑定成功')
    dialogVisible.value = false
    const idx = items.value.findIndex((it) => it.id === resp.data.id)
    if (idx >= 0) items.value[idx] = resp.data
  } finally {
    saving.value = false
  }
}

async function unbind(row) {
  await api.delete(`/admin/users/${row.id}/wechat`)
  ElMessage.success('已解绑')
  row.wechat_user_id = null
}

onMounted(() => load(1))
</script>

<style scoped>
.filters {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
  align-items: center;
}
.filter-item {
  width: 220px;
}
.tip {
  flex-basis: 100%;
}
.role-tag {
  margin-right: 4px;
}
.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
