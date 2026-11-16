<script setup>
import { onMounted, ref } from 'vue'
import { getJson } from '../api'

const rows = ref([])
const err = ref('')

onMounted(async () => {
  try {
    rows.value = await getJson('/api/reconcile')
  } catch (e) {
    err.value = String(e.message || e)
  }
})
</script>

<template>
  <div>
    <h1>交班对账</h1>
    <p class="lead">交班前后：交班方在途应变 0，接班方在途应接住清单批次数；数字与交班单同源。</p>
    <p v-if="err" class="msg">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>报告</th><th>交班单</th><th>交班前清单</th>
            <th>交后交班方</th><th>交后接班方</th><th>一致</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td>#{{ r.id }}</td>
            <td>#{{ r.handover_id }}</td>
            <td>{{ r.before_count }}</td>
            <td>{{ r.after_from_count }}</td>
            <td>{{ r.after_to_count }}</td>
            <td>
              <span class="tag" :class="{ on: r.一致 }">{{ r.一致 ? '一致' : '不一致' }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
