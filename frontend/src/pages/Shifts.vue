<script setup>
import { onMounted, ref } from 'vue'
import { getJson } from '../api'

const rows = ref([])
const err = ref('')

onMounted(async () => {
  try {
    rows.value = await getJson('/api/shifts')
  } catch (e) {
    err.value = String(e.message || e)
  }
})
</script>

<template>
  <div>
    <h1>班次</h1>
    <p class="lead">每个班次有固定值班人；交班中/接班中表示正在交接，不能并行再开一单。</p>
    <p v-if="err" class="msg">{{ err }}</p>
    <div class="panel">
      <table>
        <thead><tr><th>编号</th><th>班次</th><th>值班人</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="s in rows" :key="s.id">
            <td>{{ s.id }}</td>
            <td>{{ s.name }}</td>
            <td>{{ s.keeper }}</td>
            <td>{{ s.status }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
