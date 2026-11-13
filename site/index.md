---
layout: page
title: VRCT-VOX
sidebar: false
---

<script setup>
import { onMounted } from 'vue'
import { withBase } from 'vitepress'
import { preferredLocale } from './.vitepress/theme/locale'

// Only this page redirects, so deep links such as /ja/guide/install stay put.
onMounted(() => location.replace(withBase(`/${preferredLocale()}/`)))
</script>

<div class="language-picker">
  <h1>VRCT-VOX</h1>
  <p>
    <a href="./ja/" lang="ja">日本語のドキュメント</a>
    <span aria-hidden="true"> · </span>
    <a href="./en/" lang="en">English documentation</a>
  </p>
</div>

<style scoped>
.language-picker {
  max-width: 640px;
  margin: 96px auto;
  padding: 0 24px;
  text-align: center;
  color: var(--vp-c-text-1);
}
.language-picker h1 {
  font-size: 2rem;
  font-weight: 600;
  margin-bottom: 24px;
}
.language-picker a {
  color: var(--vp-c-brand-1);
  font-size: 1.125rem;
  text-decoration: underline;
  text-underline-offset: 4px;
}
</style>
