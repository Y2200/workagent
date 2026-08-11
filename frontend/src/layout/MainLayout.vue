<template>
  <el-container class="layout">
    <el-aside width="210px" class="aside">
      <div class="logo">Work Agent</div>
      <el-menu
        :default-active="$route.path"
        router
        class="menu"
        background-color="#001529"
        text-color="rgba(255,255,255,0.68)"
        active-text-color="#ffffff"
      >
        <el-menu-item index="/knowledge">
          <span>知识库管理</span>
        </el-menu-item>
        <el-menu-item index="/permission">
          <span>权限管理</span>
        </el-menu-item>
        <el-menu-item index="/dashboard">
          <span>督导看板</span>
        </el-menu-item>
        <el-menu-item index="/logs">
          <span>问答审计</span>
        </el-menu-item>
        <el-menu-item index="/operations">
          <span>操作审计</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="header-title">企业智能督导 Agent</div>
        <div class="header-user">
          <el-tag size="small" type="info" v-if="user">
            {{ user.department }} · {{ user.role }}
          </el-tag>
          <span class="username">{{ user?.username || '管理员' }}</span>
          <el-button link type="danger" @click="logout">退出登录</el-button>
        </div>
      </el-header>

      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'

const router = useRouter()
const user = ref(null)

async function loadMe() {
  try {
    const resp = await api.get('/admin/auth/me')
    user.value = resp.data
  } catch {
    // 401 拦截器已处理
  }
}

function logout() {
  localStorage.removeItem('token')
  ElMessage.success('已退出登录')
  router.push('/login')
}

onMounted(loadMe)
</script>

<style scoped>
.layout {
  height: 100vh;
}
.aside {
  background-color: #001529;
}
.logo {
  height: 60px;
  line-height: 60px;
  text-align: center;
  color: #fff;
  font-size: 18px;
  font-weight: 600;
}
.menu {
  border-right: none;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #eee;
  background: #fff;
}
.header-title {
  font-weight: 600;
}
.header-user {
  display: flex;
  align-items: center;
  gap: 10px;
}
.username {
  font-size: 14px;
}
.main {
  background: #f5f7fa;
}
</style>
