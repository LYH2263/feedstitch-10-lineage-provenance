<script setup>
import { onMounted, ref } from 'vue'
import { getJSON } from '../api'
const rows = ref([])
const err = ref('')
onMounted(async () => {
  try {
    rows.value = await getJSON('/api/conflicts')
  } catch (e) {
    err.value = String(e.message || e)
  }
})
</script>
<template>
  <div class="page">
    <h1>冲突队列</h1>
    <p class="muted">同业务键、非键字段分歧 → quarantine；不得静默覆盖 Canonical。隔离尝试保留来源 run/源，但不是成功写入血缘。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel" v-for="c in rows" :key="c.id">
      <p>
        #{{ c.id }} · run {{ c.run_id }} ·
        <span class="mono">{{ c.business_key }}</span> ·
        <span class="tag danger">{{ c.reason }}</span>
        <span class="muted"> · {{ c.created_at }}</span>
      </p>
      <p class="muted">
        incoming 来自源 {{ c.source_name || c.source_id }} · rev {{ c.incoming_revision ?? c.incoming?.source_revision }} ·
        event_ts {{ c.incoming_event_ts ?? c.incoming?.event_ts }}
        <span style="margin-left:0.75rem">existing 来自源 {{ c.existing_source_name || c.existing_source_id }} ·
          rev {{ c.existing_revision ?? c.existing?.source_revision }} ·
          run {{ c.existing_run_id ?? '—' }}</span>
      </p>
      <p>
        <router-link :to="`/lineage?key=${encodeURIComponent(c.business_key)}`">查看该业务键血缘链 →</router-link>
      </p>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem">
        <div>
          <div class="muted">existing</div>
          <pre class="mono">{{ JSON.stringify(c.existing, null, 2) }}</pre>
        </div>
        <div>
          <div class="muted">incoming（未写入主数据）</div>
          <pre class="mono">{{ JSON.stringify(c.incoming, null, 2) }}</pre>
        </div>
      </div>
    </div>
    <p v-if="!rows.length" class="muted">暂无冲突。</p>
  </div>
</template>
<style scoped>
pre {
  background: #0a1422;
  padding: 0.75rem;
  border-radius: 8px;
  overflow: auto;
  max-height: 240px;
}
</style>
