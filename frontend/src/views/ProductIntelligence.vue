<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { fetchCategories, fetchProducts, type ProductItem } from '@/utils/backendApi'

type Status = '热销' | '平稳' | '需关注'

const filterForm = reactive({ keyword: '', status: '全部', category: '' })
const loading = ref(false)
const products = ref<ProductItem[]>([])
const categories = ref<{ category: string; count: number }[]>([])
const total = ref(0)

const statusOf = (item: ProductItem, index: number): Status => {
  if (index < 5 && item.sales > 0) return '热销'
  if (item.sales === 0 || /缺货|紧张|低|out|low/i.test(item.stock_status || '')) return '需关注'
  return '平稳'
}

const rows = computed(() =>
  products.value.map((item, index) => {
    const avgPrice = item.sales > 0 ? item.revenue / item.sales : 0
    return {
      ...item,
      sku: item.global_product_id,
      avgPrice,
      status: statusOf(item, index),
    }
  })
)

const filteredProducts = computed(() =>
  rows.value.filter((item) => filterForm.status === '全部' || item.status === filterForm.status)
)

const supplyRecommendations = computed(() =>
  [...rows.value]
    .filter((item) => item.status === '需关注')
    .sort((a, b) => a.sales - b.sales)
    .slice(0, 3)
)

const promotionCandidates = computed(() =>
  [...rows.value].sort((a, b) => b.revenue - a.revenue).slice(0, 3)
)

const statusType = (status: Status) => (status === '热销' ? 'success' : status === '需关注' ? 'danger' : 'info')

async function loadProducts() {
  loading.value = true
  try {
    const data = await fetchProducts({
      keyword: filterForm.keyword || undefined,
      category: filterForm.category || undefined,
      page: 1,
      page_size: 100,
    })
    products.value = data.items
    total.value = data.total
  } catch {
    products.value = []
  } finally {
    loading.value = false
  }
}

const resetFilter = () => {
  filterForm.keyword = ''
  filterForm.status = '全部'
  filterForm.category = ''
}

onMounted(async () => {
  await loadProducts()
  try {
    categories.value = await fetchCategories()
  } catch {
    categories.value = []
  }
})

watch(() => [filterForm.keyword, filterForm.category], () => void loadProducts())
</script>

<template>
  <div class="product-page">
    <section class="panel">
      <div class="page-title">商品智能分析</div>
      <div class="page-subtitle">销量与销售额来自 order_item 真实聚合，共 {{ total }} 个商品</div>
      <el-form :model="filterForm" inline class="filter-form">
        <el-form-item>
          <el-input v-model="filterForm.keyword" placeholder="输入商品名称 / 商品ID / 品牌" clearable />
        </el-form-item>
        <el-form-item label="品类">
          <el-select v-model="filterForm.category" clearable placeholder="全部品类" style="width: 180px">
            <el-option v-for="c in categories" :key="c.category" :label="`${c.category} (${c.count})`" :value="c.category" />
          </el-select>
        </el-form-item>
        <el-form-item label="商品状态">
          <el-select v-model="filterForm.status" style="width: 160px">
            <el-option label="全部" value="全部" />
            <el-option label="热销" value="热销" />
            <el-option label="平稳" value="平稳" />
            <el-option label="需关注" value="需关注" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="loadProducts">刷新数据</el-button>
          <el-button @click="resetFilter">清空</el-button>
        </el-form-item>
      </el-form>
    </section>

    <section class="panel">
      <div class="section-header">
        <div>
          <div class="section-title">商品概览</div>
          <p class="tag-muted">成交均价 = 销售额 / 销量，标签来自 product.tags</p>
        </div>
        <el-button type="primary" link>导出分析报告</el-button>
      </div>
      <el-table :data="filteredProducts" border stripe v-loading="loading" max-height="520">
        <el-table-column prop="product_name" label="商品名称" min-width="200" show-overflow-tooltip />
        <el-table-column prop="sku" label="商品ID" width="140" show-overflow-tooltip />
        <el-table-column prop="brand" label="品牌" width="120" />
        <el-table-column prop="category" label="品类" width="110" />
        <el-table-column prop="sales" label="销量" width="100" sortable />
        <el-table-column prop="revenue" label="销售额" width="130" sortable>
          <template #default="{ row }">¥ {{ Math.round(row.revenue).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column label="标价/成交均价" width="170">
          <template #default="{ row }">
            ¥{{ row.price.toFixed(2) }} / ¥{{ row.avgPrice.toFixed(2) }}
          </template>
        </el-table-column>
        <el-table-column prop="stock_status" label="库存状态" width="120" />
        <el-table-column prop="status" label="智能评价" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="plain">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-row :gutter="20">
      <el-col :xs="24" :md="12">
        <section class="panel recommendation-panel">
          <div class="section-header">
            <div class="section-title">补货优先级</div>
            <el-tag type="danger" effect="plain">库存/销量预警</el-tag>
          </div>
          <el-empty v-if="supplyRecommendations.length === 0" description="暂无补货提醒" />
          <div v-else class="recommendation-list">
            <div v-for="item in supplyRecommendations" :key="item.sku" class="recommendation-item">
              <div>
                <div class="item-title">{{ item.product_name }}</div>
                <p class="tag-muted">ID {{ item.sku }} · {{ item.stock_status }} · 销量 {{ item.sales }}</p>
              </div>
              <el-button type="primary" text>去补货</el-button>
            </div>
          </div>
        </section>
      </el-col>
      <el-col :xs="24" :md="12">
        <section class="panel recommendation-panel">
          <div class="section-header">
            <div class="section-title">促销推荐</div>
            <el-tag type="success" effect="plain">销售额 TOP 3</el-tag>
          </div>
          <div class="recommendation-list">
            <div v-for="item in promotionCandidates" :key="item.sku" class="recommendation-item">
              <div>
                <div class="item-title">{{ item.product_name }}</div>
                <p class="tag-muted">销售额 ¥{{ Math.round(item.revenue).toLocaleString() }} · 销量 {{ item.sales }}</p>
              </div>
              <el-button type="primary" text>生成营销方案</el-button>
            </div>
          </div>
        </section>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.panel { margin-top: 0; }
.product-page { display: flex; flex-direction: column; gap: 20px; }
.filter-form { margin-top: 16px; display: flex; flex-wrap: wrap; gap: 8px 24px; }
.recommendation-panel { min-height: 260px; }
.recommendation-list { display: flex; flex-direction: column; gap: 16px; }
.recommendation-item { display: flex; align-items: center; justify-content: space-between; }
.item-title { font-size: 16px; font-weight: 600; color: #1f2d3d; }
</style>
