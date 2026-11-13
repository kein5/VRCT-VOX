<script setup lang="ts">
import { computed } from 'vue'
import { useData, withBase } from 'vitepress'

// A home page may name one picture of the app in its frontmatter (`shot`); it goes under the hero.
const { frontmatter } = useData()
const shot = computed(() => frontmatter.value.shot as { src: string; alt: string } | undefined)
</script>

<template>
  <div v-if="shot" class="home-shot">
    <img :src="withBase(shot.src)" :alt="shot.alt" width="1200" height="850" />
  </div>
</template>
