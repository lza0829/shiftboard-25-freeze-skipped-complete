<script setup>
import { computed, onMounted, ref } from 'vue'
import { getJson, postJson } from '../api'

const shifts = ref([])
const fromId = ref(1)
const toId = ref(2)
const current = ref(null)
const msg = ref('')
const ok = ref(false)

async function refresh() {
  shifts.value = await getJson('/api/shifts')
  const logs = await getJson('/api/handovers')
  const active = logs.find((h) => h.status === '进行中') || null
  if (active) {
    current.value = await getJson(`/api/handovers/${active.id}`)
  } else if (!current.value || current.value.status === '进行中') {
    // 保留刚完成/失败的单据用于展示结果，不覆盖为 null
    current.value = null
  }
}

const processing = computed(() => current.value?.status === '进行中')

onMounted(async () => {
  try {
    await refresh()
  } catch (e) {
    msg.value = String(e.message || e)
  }
})

async function start() {
  msg.value = ''
  ok.value = false
  try {
    current.value = await postJson('/api/handovers/start', {
      from_shift_id: Number(fromId.value),
      to_shift_id: Number(toId.value),
    })
    ok.value = true
    msg.value = `已开交班单 #${current.value.id}，清单 ${current.value.batch_count} 批`
    await refresh()
  } catch (e) {
    msg.value = String(e.message || e)
  }
}

async function complete() {
  if (!current.value) return
  msg.value = ''
  ok.value = false
  try {
    current.value = await postJson(`/api/handovers/${current.value.id}/complete`)
    ok.value = current.value.status === '已完成'
    msg.value = current.value.status === '已完成'
      ? `交班单 #${current.value.id} 已完成，批次已过户`
      : `交班单 #${current.value.id} 失败：${current.value.reason || '归属不一致'}`
    await refresh()
  } catch (e) {
    msg.value = String(e.message || e)
  }
}
</script>

<template>
  <div>
    <h1>交班办理</h1>
    <p class="lead">同一时刻只允许一单进行中的交班；清单内在途批次必须整批过户，禁止只改单据不改归属。</p>

    <div class="panel">
      <div class="row">
        <label>交班方
          <select v-model.number="fromId">
            <option v-for="s in shifts" :key="s.id" :value="s.id">{{ s.name }} · {{ s.keeper }}</option>
          </select>
        </label>
        <label>接班方
          <select v-model.number="toId">
            <option v-for="s in shifts" :key="'t'+s.id" :value="s.id">{{ s.name }} · {{ s.keeper }}</option>
          </select>
        </label>
        <button class="btn" :disabled="processing" @click="start">发起交班</button>
        <button class="btn ghost" :disabled="!processing" @click="complete">完成交班</button>
      </div>
      <p class="msg" :class="{ ok }">{{ msg }}</p>
    </div>

    <div class="panel" v-if="current">
      <h2>
        当前交班单 #{{ current.id }} ·
        <span class="tag" :class="{ on: current.status === '进行中', danger: current.status === '失败' }">{{ current.status }}</span>
      </h2>
      <p v-if="current.reason" class="msg">{{ current.reason }}</p>
      <p class="lead" style="margin-bottom:12px">
        {{ current.from_shift_name }} → {{ current.to_shift_name }} ·
        清单 {{ current.batch_count }} 批 · 排除 {{ current.excluded_count }} 批
        <span v-if="current.冻结数"> · 清单内冻结 {{ current.冻结数 }} 批（完成将整单失败）</span>
      </p>
      <table>
        <thead><tr><th>业务键</th><th>标题</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="b in current.items || []" :key="b.id">
            <td>{{ b.biz_key }}</td>
            <td>{{ b.title }}</td>
            <td><span class="tag" :class="{ danger: b.已冻结 }">{{ b.status }}</span></td>
          </tr>
        </tbody>
      </table>
      <template v-if="(current.snapshot || []).some((s) => s.outcome === '排除')">
        <h2 style="margin-top:18px">发起时排除明细（已固化）</h2>
        <table>
          <thead><tr><th>业务键</th><th>排除原因</th><th>详情</th></tr></thead>
          <tbody>
            <tr v-for="s in current.snapshot.filter((x) => x.outcome === '排除')" :key="s.batch_id">
              <td>{{ s.biz_key }}</td>
              <td>{{ s.reason }}</td>
              <td>{{ s.detail || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </template>
    </div>
  </div>
</template>
