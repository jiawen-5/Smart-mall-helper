<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { fetchMetrics, fetchTrend, fetchOrderHealth, fetchPlatforms } from '@/utils/backendApi'

echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent, CanvasRenderer])

const trendChartRef = ref<HTMLDivElement>()
const orderChartRef = ref<HTMLDivElement>()
let trendChart: echarts.ECharts | null = null
let orderChart: echarts.ECharts | null = null

const trendRange = ref('7 天')
const rangeMap: Record<string, string> = { '7 天': '7d', '15 天': '15d', '30 天': '30d' }
const daysMap: Record<string, number> = { '7 天': 7, '15 天': 15, '30 天': 30 }
const platform = ref('')
const platforms = ref<{ code: string; name: string }[]>([])
const loading = ref(false)

const metrics = reactive([
  { label: '今日销售额', value: '—', trend: '', desc: '较昨日' },
  { label: '今日订单数', value: '—', trend: '', desc: '' },
  { label: '活跃用户', value: '—', trend: '', desc: '' },
  { label: '履约健康度', value: '—', trend: '', desc: '' },
])

const alerts = ref<{ title: string; level: string; time: string }[]>([])
const trendData = ref<{ dates: string[]; sales: number[]; orders: number[] }>({ dates: [], sales: [], orders: [] })
const orderStats = ref<{ categories: string[]; values: number[] }>({ categories: [], values: [] })

const fmt = (n: number) => n.toLocaleString('zh-CN')

async function loadAll() {
  loading.value = true
  try {
    const [m, t, h, p] = await Promise.all([
      fetchMetrics(platform.value),
      fetchTrend(rangeMap[trendRange.value] ?? '7d', platform.value),
      fetchOrderHealth(platform.value, daysMap[trendRange.value] ?? 7),
      platforms.value.length ? Promise.resolve(platforms.value) : fetchPlatforms().catch(() => []),
    ])
    platforms.value = p as { code: string; name: string }[]
    const m0 = metrics[0]!
    const m1 = metrics[1]!
    const m2 = metrics[2]!
    const m3 = metrics[3]!
    m0.value = `¥ ${fmt(Math.round(m.today_sales))}`
    m1.value = fmt(m.today_orders)
    m2.value = fmt(m.active_users)
    m2.desc = `转化率 ${m.conversion_rate}%`
    const total = h.reduce((s, x) => s + x.count, 0) || 1
    const done = h.find((x) => /完成|已完成|签收/.test(x.status))?.count ?? h[0]?.count ?? 0
    const pct = Math.round((done / total) * 100)
    m3.value = `${pct}%`
    m3.desc = `共 ${fmt(total)} 单`
    trendData.value = t
    orderStats.value = { categories: h.map((x) => x.status), values: h.map((x) => Math.round((x.count / total) * 100)) }
    alerts.value = h.slice(0, 5).map((x) => ({ title: `${x.status}：${fmt(x.count)} 单`, level: 'info', time: '实时' }))
    updateTrendChart()
    updateOrderChart()
  } catch {
    alerts.value = [{ title: '后端连接失败：请确认 FastAPI 已启动（:8000）且 MySQL 可连', level: 'danger', time: '刚刚' }]
  } finally {
    loading.value = false
  }
}

const updateTrendChart = () => {
  if (!trendChart) return
  trendChart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['销售额(万)', '订单数'], bottom: 0 },
    grid: { left: '3%', right: '4%', bottom: '12%', containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: trendData.value.dates },
    yAxis: [{ type: 'value', name: '销售额(万)' }, { type: 'value', name: '订单数' }],
    series: [
      {
        name: '销售额(万)', type: 'line', smooth: true, data: trendData.value.sales,
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(63,140,255,0.35)' }, { offset: 1, color: 'rgba(63,140,255,0)' }]) },
      },
      { name: '订单数', type: 'line', smooth: true, yAxisIndex: 1, data: trendData.value.orders, color: '#34d399' },
    ],
  })
}

const updateOrderChart = () => {
  if (!orderChart) return
  orderChart.setOption({
    title: { text: '订单健康度', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    grid: { left: '8%', right: '4%', bottom: '4%', top: '18%', containLabel: true },
    xAxis: { type: 'value', max: 100 },
    yAxis: { type: 'category', data: orderStats.value.categories },
    series: [{ type: 'bar', data: orderStats.value.values, barWidth: 20, label: { show: true, position: 'right', formatter: '{c}%' } }],
  })
}

const handleResize = () => { trendChart?.resize(); orderChart?.resize() }

onMounted(() => {
  if (trendChartRef.value) trendChart = echarts.init(trendChartRef.value)
  if (orderChartRef.value) orderChart = echarts.init(orderChartRef.value)
  window.addEventListener('resize', handleResize)
  void loadAll()
})

watch([trendRange, platform], () => { void loadAll() })
onBeforeUnmount(() => { window.removeEventListener('resize', handleResize); trendChart?.dispose(); orderChart?.dispose() })
</script>

<template>
  <div class="dashboard">
    <section class="panel hero">
      <div>
        <div class="page-title">智能数据仪表盘</div>
        <div class="page-subtitle">实时监控核心经营指标（数据来自 MySQL 真实订单）</div>
      </div>
      <div style="display: flex; gap: 8px; align-items: center">
        <el-select v-model="platform" placeholder="全部平台" clearable style="width: 160px" @change="loadAll">
          <el-option label="全部平台" value="" />
          <el-option v-for="p in platforms" :key="p.code" :label="p.name" :value="p.code" />
        </el-select>
        <el-tag size="large" effect="dark" type="success">已接真实数据</el-tag>
      </div>
    </section>

    <el-row :gutter="20" v-loading="loading">
      <el-col v-for="metric in metrics" :key="metric.label" :xs="24" :sm="12" :lg="6">
        <div class="panel metric-card">
          <div class="tag-muted">{{ metric.label }}</div>
          <div class="metric-value">{{ metric.value }}</div>
          <div class="metric-footer">
            <span class="metric-trend">{{ metric.trend }}</span>
            <span class="tag-muted">{{ metric.desc }}</span>
          </div>
        </div>
      </el-col>
    </el-row>

    <section class="panel trend-panel">
      <div class="section-header">
        <div>
          <div class="section-title">核心指标趋势</div>
          <p class="tag-muted">按 order_time 按天聚合销售额与订单数</p>
        </div>
        <el-radio-group v-model="trendRange" size="small" class="range-selector">
          <el-radio-button label="7 天" />
          <el-radio-button label="15 天" />
          <el-radio-button label="30 天" />
        </el-radio-group>
      </div>
      <div ref="trendChartRef" class="chart"></div>
    </section>

    <el-row :gutter="20">
      <el-col :xs="24" :lg="14">
        <section class="panel alerts-panel">
          <div class="section-header">
            <div class="section-title">订单状态分布（近 {{ trendRange }}）</div>
            <el-tag type="info" effect="plain">近{{ trendRange }}实时统计</el-tag>
          </div>
          <el-timeline>
            <el-timeline-item v-for="alert in alerts" :key="alert.title" :type="alert.level as never" :timestamp="alert.time">
              {{ alert.title }}
            </el-timeline-item>
          </el-timeline>
        </section>
      </el-col>
      <el-col :xs="24" :lg="10">
        <section class="panel order-panel">
          <div class="section-header">
            <div class="section-title">履约健康度</div>
            <el-tag type="success" effect="plain">自动监控</el-tag>
          </div>
          <div ref="orderChartRef" class="chart small"></div>
        </section>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.dashboard { display: flex; flex-direction: column; gap: 20px; }
.hero { display: flex; justify-content: space-between; align-items: center; }
.metric-card { min-height: 160px; display: flex; flex-direction: column; justify-content: space-between; }
.metric-value { font-size: 28px; font-weight: 700; }
.metric-footer { display: flex; justify-content: space-between; align-items: center; font-size: 13px; }
.chart { width: 100%; height: 320px; }
.chart.small { height: 260px; }
.range-selector :deep(.el-radio-button__inner) { border-radius: 999px !important; margin-left: 8px; }
</style>
