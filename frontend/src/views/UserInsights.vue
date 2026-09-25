<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { fetchSegments, fetchPlatforms } from '@/utils/backendApi'

echarts.use([BarChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const behaviorChartRef = ref<HTMLDivElement>()
const segmentChartRef = ref<HTMLDivElement>()
let behaviorChart: echarts.ECharts | null = null
let segmentChart: echarts.ECharts | null = null

const platform = ref('')
const platforms = ref<{ code: string; name: string }[]>([])
const loading = ref(false)
const segments = ref<{ label: string; value: number; desc: string }[]>([])

async function loadSegments() {
  loading.value = true
  try {
    const [s, p] = await Promise.all([
      fetchSegments(platform.value),
      platforms.value.length ? Promise.resolve(platforms.value) : fetchPlatforms().catch(() => []),
    ])
    platforms.value = p as { code: string; name: string }[]
    const fq = s.frequency || {}
    const total = Object.values(fq).reduce((a, b) => a + (b as number), 0) || 1
    behaviorChart?.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['人数'], top: 0 },
      grid: { left: '4%', right: '4%', bottom: '8%', containLabel: true },
      xAxis: { type: 'category', data: Object.keys(fq) },
      yAxis: [{ type: 'value', name: '人数' }],
      series: [{ name: '人数', type: 'bar', data: Object.values(fq), barWidth: 36, itemStyle: { borderRadius: 12, color: '#3f8cff' } }],
    })
    const levelTotal = s.levels.reduce((a, b) => a + b.count, 0) || 1
    segments.value = s.levels.map((l) => ({
      label: l.user_level || '未知',
      value: Math.round((l.count / levelTotal) * 100),
      desc: `${l.count.toLocaleString()} 人 · 占比 ${Math.round((l.count / levelTotal) * 100)}%`,
    }))
    segmentChart?.setOption({
      tooltip: { trigger: 'item' },
      legend: { bottom: 0 },
      series: [{
        name: '用户分层', type: 'pie', radius: ['45%', '70%'],
        itemStyle: { borderRadius: 12, borderColor: '#fff', borderWidth: 2 },
        label: { formatter: '{b}: {d}%' },
        data: s.levels.map((l) => ({ value: l.count, name: l.user_level || '未知' })),
      }],
    })
  } catch {
    segments.value = []
  } finally {
    loading.value = false
  }
}

const handleResize = () => { behaviorChart?.resize(); segmentChart?.resize() }

onMounted(() => {
  if (behaviorChartRef.value) behaviorChart = echarts.init(behaviorChartRef.value)
  if (segmentChartRef.value) segmentChart = echarts.init(segmentChartRef.value)
  window.addEventListener('resize', handleResize)
  void loadSegments()
})
onBeforeUnmount(() => { window.removeEventListener('resize', handleResize); behaviorChart?.dispose(); segmentChart?.dispose() })
</script>

<template>
  <div class="insights-page">
    <section class="panel hero">
      <div>
        <div class="page-title">用户洞察分析</div>
        <div class="page-subtitle">分层来自 user.user_level，频次来自 user_behavior 人均行为数（真实数据）</div>
      </div>
      <el-select v-model="platform" placeholder="全部平台" clearable style="width: 160px" @change="loadSegments">
        <el-option label="全部平台" value="" />
        <el-option v-for="p in platforms" :key="p.code" :label="p.name" :value="p.code" />
      </el-select>
    </section>

    <el-row :gutter="20" v-loading="loading">
      <el-col :xs="24" :lg="14">
        <section class="panel chart-panel">
          <div class="section-header">
            <div>
              <div class="section-title">用户行为频次（高频≥20 / 中频5-20 / 低频&lt;5）</div>
              <p class="tag-muted">按人均行为数划分</p>
            </div>
            <el-button text type="primary" @click="loadSegments">刷新</el-button>
          </div>
          <div ref="behaviorChartRef" class="chart"></div>
        </section>
      </el-col>
      <el-col :xs="24" :lg="10">
        <section class="panel chart-panel">
          <div class="section-header">
            <div class="section-title">用户分层（user_level）</div>
            <el-tag type="info" effect="plain">真实会员等级</el-tag>
          </div>
          <div ref="segmentChartRef" class="chart small"></div>
          <el-divider />
          <ul class="segment-list">
            <li v-for="item in segments" :key="item.label">
              <strong>{{ item.label }}</strong>
              <span>{{ item.desc }}</span>
            </li>
          </ul>
        </section>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.insights-page { display: flex; flex-direction: column; gap: 10px; }
.hero { display: flex; justify-content: space-between; align-items: center; }
.chart { width: 100%; height: 320px; }
.chart.small { height: 260px; }
.segment-list { list-style: none; padding-left: 0; display: flex; flex-direction: column; gap: 12px; font-size: 14px; color: var(--text-muted); }
.segment-list strong { color: #1f2d3d; margin-right: 8px; }
</style>
