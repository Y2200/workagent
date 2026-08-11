# Work Agent 管理后台（Vue3 + Element Plus）

## 启动

```bash
# 依赖安装（首次）
npm install

# 开发模式（端口 5173，/api 代理到 http://127.0.0.1:8000）
npm run dev

# 生产构建
npm run build
```

## 页面

| 路由 | 页面 | 功能 |
|------|------|------|
| /login | 登录 | JWT 登录 |
| /knowledge | 知识库管理 | 上传文档（分类/可见性/部门/角色）、列表、检索、详情、删除、状态轮询 |
| /permission | 权限管理 | 文档权限总览（可见性/部门/角色） |
| /dashboard | 督导看板 | 文档统计卡片、最近文档、知识库检索 |

## 对接后端

- 开发环境：Vite 代理 `/api` → `http://127.0.0.1:8000`（见 `vite.config.js`）
- 生产环境：由 nginx 将 `/` 与 `/api` 反代到前端与后端（部署阶段配置）
- JWT 存于 `localStorage`，axios 请求拦截自动附加 `Authorization: Bearer <token>`
- 401 自动跳转登录页
