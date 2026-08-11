<template>
  <div>
    <el-card shadow="never">
      <template #header>文档权限总览</template>

      <el-table :data="rows" v-loading="loading" stripe>
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
        <el-table-column label="可见部门" min-width="140">
          <template #default="{ row }">
            <el-tag v-for="dept in row.departments" :key="dept" size="small" class="perm-tag">
              {{ dept }}
            </el-tag>
            <span v-if="!row.departments.length" class="muted">全员</span>
          </template>
        </el-table-column>
        <el-table-column label="可见角色" min-width="140">
          <template #default="{ row }">
            <el-tag v-for="role in row.roles" :key="role" size="small" type="warning" class="perm-tag">
              {{ role }}
            </el-tag>
            <span v-if="!row.roles.length" class="muted">不限</span>
          </template>
        </el-table-column>
        <el-table-column label="指定用户" min-width="100">
          <template #default="{ row }">
            <el-tag v-for="uid in row.user_ids" :key="uid" size="small" type="success" class="perm-tag">
              #{{ uid }}
            </el-tag>
            <span v-if="!row.user_ids.length" class="muted">无</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑权限</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 编辑权限对话框 -->
    <el-dialog v-model="editVisible" title="编辑文档权限" width="520px">
      <el-form v-if="form" label-width="90px">
        <el-form-item label="可见性">
          <el-radio-group v-model="form.visibility">
            <el-radio value="public">公开</el-radio>
            <el-radio value="restricted">受限</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="可见部门">
          <el-input
            v-model="form.departmentsText"
            placeholder="多个用逗号分隔，如：财务部,研发部"
          />
        </el-form-item>
        <el-form-item label="可见角色">
          <el-input
            v-model="form.rolesText"
            placeholder="多个用逗号分隔，如：财务人员,管理人员"
          />
        </el-form-item>
        <el-form-item label="指定用户ID">
          <el-input
            v-model="form.userIdsText"
            placeholder="多个用逗号分隔，如：3,5,7"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const rows = ref([])
const loading = ref(false)
const editVisible = ref(false)
const saving = ref(false)
const form = ref(null)

async function load() {
  loading.value = true
  try {
    const listResp = await api.get('/admin/documents')
    const list = listResp.data
    const detailPromises = list.map(async (doc) => {
      try {
        const resp = await api.get(`/admin/documents/${doc.id}`)
        const detail = resp.data
        const permissions = detail.permissions || []
        return {
          ...doc,
          departments: [...new Set(permissions.filter((p) => p.department).map((p) => p.department))],
          roles: [...new Set(permissions.filter((p) => p.role).map((p) => p.role))],
          user_ids: [...new Set(permissions.filter((p) => p.user_id).map((p) => p.user_id))],
        }
      } catch {
        return { ...doc, departments: [], roles: [], user_ids: [] }
      }
    })
    rows.value = await Promise.all(detailPromises)
  } finally {
    loading.value = false
  }
}

async function openEdit(row) {
  const resp = await api.get(`/admin/documents/${row.id}/permissions`)
  const p = resp.data
  form.value = {
    id: row.id,
    visibility: p.visibility,
    departmentsText: (p.departments || []).join(','),
    rolesText: (p.roles || []).join(','),
    userIdsText: (p.user_ids || []).join(','),
  }
  editVisible.value = true
}

async function save() {
  saving.value = true
  try {
    const payload = {
      visibility: form.value.visibility,
      departments: form.value.departmentsText.split(',').map((s) => s.trim()).filter(Boolean),
      roles: form.value.rolesText.split(',').map((s) => s.trim()).filter(Boolean),
      user_ids: form.value.userIdsText.split(',').map((s) => Number(s.trim())).filter((n) => !Number.isNaN(n)),
    }
    await api.put(`/admin/documents/${form.value.id}/permissions`, payload)
    ElMessage.success('权限已更新，RAG 过滤已同步')
    editVisible.value = false
    load()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.perm-tag {
  margin-right: 6px;
}
.muted {
  color: #999;
}
</style>
