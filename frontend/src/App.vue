<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter, RouterView } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'

const router = useRouter()
const route = useRoute()

const menuItems = [
  { label: '智能数据仪表盘', path: '/dashboard', desc: '实时经营全景' },
  { label: '商品智能分析', path: '/products', desc: '销量利润洞察' },
  { label: 'AI运营助手', path: '/assistant', desc: '营销文案与话术' },
  { label: '用户洞察分析', path: '/insights', desc: '分层与推荐策略' },
]

const searchKeyword = ref('')
const isChatFullscreen = computed(() => route.path === '/assistant/chat')

const handleSelect = (key: string) => {
  // console.log('菜单点击:', key, '当前路由:', route.path)
  if (key !== route.path) {
    router.push(key)
  }
}

const handleSearch = () => {
  const keyword = searchKeyword.value.trim()
  if (!keyword) {
    ElMessage.info('请输入要搜索的数据/商品/用户关键词')
    return
  }
  ElMessage.success(`已提交搜索：${keyword}`)
}

const handleCreateTask = () => {
  ElMessage.success('已创建运营任务（示例），可接入实际接口')
}
</script>

<template>
  <div class="app-shell" :class="{ 'chat-fullscreen': isChatFullscreen }">
    <header v-if="!isChatFullscreen" class="app-header panel">
      <div class="branding">
        <div class="logo-dot">SMH</div>
        <div>
          <div class="brand-title">智能电商助手</div>
          <div class="brand-desc">Smart Mall Helper · 运营效率提升台</div>
        </div>
      </div>
      <div class="header-actions">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索数据/商品/用户"
          clearable
          class="search-input"
          @keyup.enter="handleSearch"
        >
          <template #prefix>
            <el-icon>
              <Search />
            </el-icon>
          </template>
        </el-input>
        <el-button type="primary" @click="handleCreateTask">创建运营任务</el-button>
      </div>
    </header>

    <nav v-if="!isChatFullscreen" class="app-nav panel">
      <el-menu
        :default-active="route.path"
        mode="horizontal"
        background-color="transparent"
        text-color="#7a869a"
        active-text-color="#3f8cff"
        @select="handleSelect"
      >
        <el-menu-item v-for="item in menuItems" :key="item.path" :index="item.path">
          <div class="menu-item">
            <div class="menu-label">{{ item.label }}</div>
            <span class="menu-desc">{{ item.desc }}</span>
          </div>
        </el-menu-item>
      </el-menu>
    </nav>

    <main class="app-main">
      <RouterView :key="route.fullPath" />
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.app-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
}

.branding {
  display: flex;
  align-items: center;
  gap: 16px;
}

.logo-dot {
  width: 52px;
  height: 52px;
  border-radius: 18px;
  background: linear-gradient(135deg, #60a5ff, #3f8cff);
  color: #fff;
  font-size: 20px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.brand-title {
  font-size: 20px;
  font-weight: 600;
  color: #1f2d3d;
}

.brand-desc {
  color: var(--text-muted);
  font-size: 14px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 50%;
}

.search-input {
  flex: 1;
}

.app-nav :deep(.el-menu) {
  border-bottom: none;
  display: flex;
  justify-content: space-between;
  background-color: transparent;
  gap: 12px;
  padding: 8px;
}

.app-nav :deep(.el-menu-item) {
  border-radius: 16px;
  padding: 20px 24px;
  height: 58px;
  transition: all 0.3s ease;
  border-bottom: 2px solid transparent;
}

.app-nav :deep(.el-menu-item:hover) {
  background: rgba(63, 140, 255, 0.08);
}

.app-nav :deep(.el-menu-item.is-active) {
  background: linear-gradient(120deg, rgba(63, 140, 255, 0.16), rgba(96, 165, 255, 0.2));
  /* border-bottom: 3px solid #3f8cff; */
  /* box-shadow: 0 8px 18px rgba(63, 140, 255, 0.2); */
  padding-bottom: 17px;
}

.menu-item {
  display: flex;
  flex-direction: column;
  font-size: 16px;
  gap: 6px;
  line-height: 1.2;
}

.menu-label {
  font-weight: 600;
  color: #1f2d3d;
}

.menu-desc {
  font-size: 12px;
  color: var(--text-muted);
  letter-spacing: 0.2px;
}

.app-main {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.chat-fullscreen {
  gap: 0;
  height: calc(100vh - 32px);
}

.chat-fullscreen .app-main {
  flex: 1;
  min-height: 0;
}

@media (max-width: 1024px) {
  #app {
    padding: 15px;
  }

  .app-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .header-actions {
    width: 100%;
  }

  .app-nav :deep(.el-menu) {
    flex-direction: column;
    gap: 8px;
  }
}
</style>
