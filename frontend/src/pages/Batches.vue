<script setup>
import { onMounted, ref } from 'vue'
import { getJson, postJson } from '../api'

const rows = ref([])
const err = ref('')
const msg = ref('')

async function load() {
  rows.value = await getJson('/api/batches')
}

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    err.value = String(e.message || e)
  }
})

async function runChecks() {
  msg.value = ''
  try {
    const r = await postJson('/api/batches/checks/run')
    msg.value = `检查任务完成，本次新冻结 ${r.本次新冻结} 批`
    await load()
  } catch (e) {
    msg.value = String(e.message || e)
  }
}

async function act(b, action, label, body) {
  msg.value = ''
  try {
    await postJson(`/api/batches/${b.id}/${action}`, body)
    msg.value = `批次 ${b.biz_key} 已${label}`
    await load()
  } catch (e) {
    msg.value = String(e.message || e)
  }
}

async function setOverdue(b) {
  const raw = window.prompt(`设置 ${b.biz_key} 的逾期时限（小时）`, String(b.overdue_hours ?? 24))
  if (raw === null) return
  const hours = Number(raw)
  if (!Number.isFinite(hours) || hours < 0) {
    msg.value = '逾期时限必须是非负数字'
    return
  }
  const due = window.prompt('检查任务到期时间（ISO8601，留空表示不按时限自动冻结）', b.check_due_at || '')
  if (due === null) return
  await act(b, 'overdue', '配置逾期时限', { overdue_hours: hours, check_due_at: due || null })
}
</script>

<template>
  <div>
    <h1>在途批次</h1>
    <p class="lead">
      批次归属当前值班班次；检查任务到期后标「冻结」，冻结批不进入交班清单、不得普通结清，只能解冻（转待确认）或报废。
    </p>
    <p v-if="err" class="msg">{{ err }}</p>
    <div class="panel">
      <div class="row">
        <button class="btn ghost" @click="runChecks">运行检查任务</button>
        <span class="hint">按逾期时限比对，到期批次标冻结</span>
      </div>
      <p v-if="msg" class="msg">{{ msg }}</p>
      <table>
        <thead>
          <tr>
            <th>业务键</th><th>标题</th><th>归属班次</th><th>状态</th>
            <th>检查截止</th><th>逾期限时</th><th>备注</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in rows" :key="b.id" :class="{ frozen: b.已冻结 }">
            <td>{{ b.biz_key }}</td>
            <td>{{ b.title }}</td>
            <td>{{ b.owner_shift_name || '—' }}</td>
            <td>
              <span class="tag" :class="{ on: b.status === '在途', danger: b.已冻结 }">{{ b.status }}</span>
              <span v-if="b.逾期 && !b.已冻结" class="tag danger">逾期</span>
            </td>
            <td>{{ b.检查截止 || '—' }}</td>
            <td>{{ b.overdue_hours }} 小时</td>
            <td>{{ b.freeze_reason || b.note || '—' }}</td>
            <td class="ops">
              <button v-if="!b.已冻结" class="btn tiny ghost" @click="setOverdue(b)">配置时限</button>
              <button
                v-if="b.status === '在途'"
                class="btn tiny ghost"
                @click="act(b, 'settle', '结清')"
              >结清</button>
              <button
                v-if="b.status === '冻结'"
                class="btn tiny ghost"
                @click="act(b, 'unfreeze', '解冻（转待确认）')"
              >解冻</button>
              <button
                v-if="b.status === '待确认'"
                class="btn tiny ghost"
                @click="act(b, 'confirm', '确认转在途')"
              >确认</button>
              <button
                v-if="!['已结清', '报废'].includes(b.status)"
                class="btn tiny ghost"
                @click="act(b, 'scrap', '报废')"
              >报废</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
tr.frozen td { background: rgba(196, 92, 92, 0.08); }
.hint { color: var(--muted); font-size: 12px; }
.ops { display: flex; flex-wrap: wrap; gap: 6px; }
.btn.tiny { padding: 4px 8px; font-size: 12px; }
</style>
