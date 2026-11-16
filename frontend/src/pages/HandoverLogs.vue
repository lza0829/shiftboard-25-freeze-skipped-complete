<script setup>
import { onMounted, ref } from 'vue'
import { getJson } from '../api'

const rows = ref([])
const err = ref('')

onMounted(async () => {
  try {
    rows.value = await getJson('/api/handovers')
  } catch (e) {
    err.value = String(e.message || e)
  }
})
</script>

<template>
  <div>
    <h1>交班记录</h1>
    <p class="lead">每单交班留档：双方班次、纳入清单批次数、发起时排除批次数、最终状态与失败原因。</p>
    <p v-if="err" class="msg">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>单号</th><th>交班方</th><th>接班方</th><th>清单</th>
            <th>排除</th><th>状态</th><th>开始</th><th>结束</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="h in rows" :key="h.id">
            <td>#{{ h.id }}</td>
            <td>{{ h.from_shift_name }}</td>
            <td>{{ h.to_shift_name }}</td>
            <td>{{ h.batch_count }}</td>
            <td>{{ h.excluded_count }}</td>
            <td><span class="tag" :class="{ on: h.status === '已完成', danger: h.status === '失败' }">{{ h.status }}</span></td>
            <td>{{ h.started_at }}</td>
            <td>{{ h.finished_at || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-for="h in rows.filter((x) => x.status === '失败')" :key="'r'+h.id" class="msg">
        #{{ h.id }} 失败原因：{{ h.reason || '—' }}
      </p>
    </div>
  </div>
</template>
