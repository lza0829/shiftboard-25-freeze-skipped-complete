<script setup>
import { onMounted, ref } from 'vue'
import { getJson } from '../api'

const data = ref(null)
const err = ref('')

onMounted(async () => {
  try {
    data.value = await getJson('/api/dashboard')
  } catch (e) {
    err.value = String(e.message || e)
  }
})
</script>

<template>
  <div>
    <h1>总览</h1>
    <p class="lead">看清谁在值班、有多少在途批次、有没有交班卡在半路。</p>
    <p v-if="err" class="msg">{{ err }}</p>
    <template v-if="data">
      <div class="stats">
        <div class="stat"><div class="k">班次数</div><div class="v">{{ data.班次数 }}</div></div>
        <div class="stat"><div class="k">在途批次</div><div class="v">{{ data.在途批次数 }}</div></div>
        <div class="stat"><div class="k">冻结批次</div><div class="v">{{ data.冻结批次数 }}</div></div>
        <div class="stat"><div class="k">进行中交班</div><div class="v">{{ data.进行中交班 }}</div></div>
      </div>
      <div class="panel">
        <h2>班次状态</h2>
        <table>
          <thead><tr><th>班次</th><th>值班人</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="s in data.班次" :key="s.id">
              <td>{{ s.name }}</td>
              <td>{{ s.keeper }}</td>
              <td><span class="tag" :class="{ on: s.status === '值班中' }">{{ s.status }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>
