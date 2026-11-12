<script setup>
import { onMounted, ref } from 'vue'
import { getJSON, postJSON } from '../api'

const sources = ref([])
const sourceId = ref(null)
const mode = ref('incremental')
const last = ref(null)
const history = ref([])
const err = ref('')
const busy = ref(false)

async function refresh() {
  history.value = await getJSON('/api/runs')
}

async function runOnce() {
  err.value = ''
  busy.value = true
  try {
    last.value = await postJSON(`/api/sources/${sourceId.value}/runs`, { mode: mode.value })
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  sources.value = await getJSON('/api/sources')
  if (sources.value.length) sourceId.value = sources.value[0].id
  await refresh()
})
</script>
<template>
  <div class="page">
    <h1>运行台</h1>
    <p class="muted">选源触发增量或全量；报告中的成功写入数须与本 run 新增的成功血缘条数互相解释。</p>
    <div class="panel">
      <label>
        源
        <select v-model.number="sourceId">
          <option v-for="s in sources" :key="s.id" :value="s.id">{{ s.id }}. {{ s.name }}</option>
        </select>
      </label>
      <label style="margin-left:1rem">
        模式
        <select v-model="mode">
          <option value="incremental">incremental</option>
          <option value="full">full</option>
        </select>
      </label>
      <button style="margin-left:1rem" :disabled="busy || !sourceId" @click="runOnce">
        {{ busy ? '运行中…' : '执行 Run' }}
      </button>
    </div>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel" v-if="last">
      <h3>最近一次报告</h3>
      <p>
        Run #{{ last.id }} ·
        <span class="tag ok">{{ last.status }}</span> ·
        parsed {{ last.parsed_count }} /
        upserted {{ last.upserted_count }} /
        conflict {{ last.conflict_count }} /
        skipped {{ last.skipped_count }}
      </p>
      <p class="mono muted">canonical_count={{ last.report?.canonical_count }} watermark={{ last.report?.watermark_ts }}</p>
      <p>
        本 run 新增成功血缘
        <strong>{{ last.report?.lineage_event_count }}</strong> 条（覆盖
        {{ last.report?.lineage_distinct_keys }} 个业务键）·
        <span class="tag" :class="last.report?.lineage_reconciles ? 'ok' : 'danger'">
          {{ last.report?.lineage_reconciles ? '写入数 = 血缘条数' : '写入数与血缘条数不一致' }}
        </span>
        <span class="tag" :class="last.report?.canonical_lineage_pointers_ok ? 'ok' : 'warn'">
          {{ last.report?.canonical_lineage_pointers_ok ? 'Canonical 已指向最新血缘' : 'Canonical 指针待核对' }}
        </span>
      </p>
      <p v-if="last.report?.written_keys?.length" class="muted">
        本 run 写入的业务键：
        <router-link
          v-for="k in last.report.written_keys"
          :key="k"
          :to="`/lineage?key=${encodeURIComponent(k)}`"
          style="margin-right:0.5rem"
        >{{ k }} ↗</router-link>
      </p>
    </div>
    <div class="panel">
      <h3>历史 Runs</h3>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>源</th><th>模式</th><th>状态</th><th>parsed</th><th>upserted</th><th>血缘</th><th>conflict</th><th>skipped</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in history" :key="r.id">
            <td>{{ r.id }}</td>
            <td>{{ r.source_name }}</td>
            <td>{{ r.mode }}</td>
            <td><span class="tag" :class="r.status === 'ok' ? 'ok' : 'danger'">{{ r.status }}</span></td>
            <td>{{ r.parsed_count }}</td>
            <td>{{ r.upserted_count }}</td>
            <td>
              <span class="mono" :class="r.report?.lineage_event_count === r.upserted_count ? '' : 'warn'">
                {{ r.report?.lineage_event_count ?? '—' }}
              </span>
            </td>
            <td>{{ r.conflict_count }}</td>
            <td>{{ r.skipped_count }}</td>
            <td class="mono">{{ r.created_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
<style scoped>
.warn { color: var(--warn); }
</style>
