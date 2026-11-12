<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getJSON } from '../api'

const route = useRoute()
const router = useRouter()
const key = ref(route.query.key || '')
const chain = ref(null)
const summary = ref(null)
const err = ref('')

async function loadSummary() {
  try {
    summary.value = await getJSON('/api/lineage/summary')
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function loadChain() {
  err.value = ''
  chain.value = null
  const target = String(key.value || '').trim()
  if (!target) return
  try {
    chain.value = await getJSON(`/api/lineage/${encodeURIComponent(target)}`)
    router.replace({ path: '/lineage', query: { key: target } })
  } catch (e) {
    err.value = String(e.message || e)
  }
}

const sortNote = computed(() => (chain.value ? `${chain.value.applied_count} 次实际写入 · ${chain.value.quarantined_count} 次隔离尝试` : ''))

watch(() => route.query.key, (k) => {
  if (k && k !== key.value) {
    key.value = k
    loadChain()
  }
})

loadSummary()
if (key.value) loadChain()
</script>
<template>
  <div class="page">
    <h1>行级血缘</h1>
    <p class="muted">按业务键追溯每一次实际写入的来源、Run、revision 与事件时间；隔离尝试以虚线标记，不计入写入数。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel" v-if="summary">
      <p>
        血缘事件 <strong>{{ summary.lineage_event_count }}</strong> ·
        Canonical <strong>{{ summary.canonical_count }}</strong> ·
        已挂血缘 <strong>{{ summary.canonical_with_lineage }}</strong> ·
        隔离 <strong>{{ summary.quarantined_count }}</strong>
      </p>
    </div>
    <div class="panel">
      <label>
        业务键
        <input v-model="key" placeholder="如 SKU-1001" @keyup.enter="loadChain" />
      </label>
      <button style="margin-left:0.75rem" @click="loadChain">查看血缘</button>
    </div>
    <div class="panel" v-if="chain">
      <h3>{{ chain.business_key }}</h3>
      <p v-if="sortNote" class="muted">{{ sortNote }}</p>
      <p v-if="chain.canonical">
        当前 Canonical：
        <span class="mono">{{ chain.canonical.title }}</span> ·
        price <span class="mono">{{ chain.canonical.price }}</span> ·
        source {{ chain.canonical.source_name || chain.canonical.source_id }} ·
        run {{ chain.canonical.run_id }} ·
        lineage #{{ chain.canonical.lineage_id }} ·
        <span class="tag" :class="chain.canonical_points_to_latest ? 'ok' : 'warn'">
          {{ chain.canonical_points_to_latest ? '指向最新成功血缘' : '未指向最新成功血缘' }}
        </span>
      </p>
      <p v-else class="muted">当前无 Canonical 行（仅存在隔离尝试）。</p>
      <table>
        <thead>
          <tr>
            <th>时间</th><th>事件</th><th>源</th><th>run</th><th>revision</th><th>event_ts</th><th>写入</th><th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="n in chain.chain" :key="`${n.kind}-${n.id}`" :class="{ 'row-quarantine': !n.applied }">
            <td class="mono">{{ n.written_at }}</td>
            <td>{{ n.applied ? n.action : 'quarantine' }}</td>
            <td>{{ n.source_name || n.source_id }}</td>
            <td>
              <router-link :to="`/workbench?run=${n.run_id}`">#{{ n.run_id }}</router-link>
            </td>
            <td>{{ n.source_revision }}</td>
            <td class="mono">{{ n.event_ts }}</td>
            <td>{{ n.applied ? 'yes' : 'no' }}</td>
            <td>
              <span class="tag" :class="n.applied ? 'ok' : 'danger'">
                {{ n.applied ? (n.is_canonical_current ? '当前有效' : (n.is_latest ? '最新成功' : '历史')) : '隔离·未写入' }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="chain.attempts.length" class="muted" style="margin-top:0.5rem">
        隔离尝试来自冲突记录，可见其来源 run/源，但不作为已成功写入血缘。
      </p>
      <div class="panel" v-for="a in chain.attempts" :key="`attempt-${a.id}`">
        <p>
          冲突 #{{ a.id }} · run {{ a.run_id }} · 源 {{ a.source_name || a.source_id }} ·
          原因 {{ a.reason }} ·
          <span class="muted">{{ a.created_at }}</span>
        </p>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem">
          <div>
            <div class="muted">existing（来自 source {{ a.existing_source_name || a.existing_source_id }} · run {{ a.existing_run_id }}）</div>
            <pre class="mono">{{ JSON.stringify(a.existing_payload, null, 2) }}</pre>
          </div>
          <div>
            <div class="muted">incoming（未写入）</div>
            <pre class="mono">{{ JSON.stringify(a.payload, null, 2) }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
<style scoped>
pre {
  background: #0a1422;
  padding: 0.75rem;
  border-radius: 8px;
  overflow: auto;
  max-height: 220px;
}
.row-quarantine { opacity: 0.75; font-style: italic; }
</style>
