<script setup>
</script>
<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand-block">
        <div class="brand">交班台</div>
        <div class="brand-sub">班次责任与在途批次交接</div>
      </div>
      <nav class="topnav">
        <router-link to="/">总览</router-link>
        <router-link to="/shifts">班次</router-link>
        <router-link to="/batches">在途批次</router-link>
        <router-link to="/handover">交班办理</router-link>
        <router-link to="/logs">交班记录</router-link>
        <router-link to="/reconcile">交班对账</router-link>
      </nav>
    </header>
    <div class="ribbon" aria-hidden="true">
      <span>值班中</span>
      <span class="dot">→</span>
      <span>交班中</span>
      <span class="dot">→</span>
      <span>接班确认</span>
      <span class="dot">→</span>
      <span>对账落档</span>
    </div>
    <main class="content">
      <router-view />
    </main>
  </div>
</template>
