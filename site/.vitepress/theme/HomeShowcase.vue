<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useData, withBase } from 'vitepress'

// The home page's features, each beside a short loop of what it does (site/motion renders
// the loops into public/motion/<lang>/). A loop plays only while it is on screen; readers who
// prefer less motion see the finished scene as a still.
interface Item {
  id: string
  title: string
  details: string
  link: string
  linkText: string
}

const { frontmatter, lang } = useData()
const items = computed<Item[]>(() => frontmatter.value.showcase ?? [])
const note = computed<{ text: string; link: string; linkText: string } | undefined>(() => frontmatter.value.showcaseNote)
const folder = computed(() => (lang.value.startsWith('ja') ? 'ja' : 'en'))
const media = (id: string, ext: string) => withBase(`/motion/${folder.value}/${id}.${ext}`)

const videos = ref<HTMLVideoElement[]>([])
const visible = new Set<HTMLVideoElement>()
let observer: IntersectionObserver | undefined
let reduce: MediaQueryList | undefined

function sync() {
  for (const video of videos.value) {
    if (!reduce?.matches && visible.has(video)) video.play().catch(() => {})
    else video.pause()
  }
}

onMounted(() => {
  reduce = window.matchMedia('(prefers-reduced-motion: reduce)')
  reduce.addEventListener('change', sync)
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const video = entry.target as HTMLVideoElement
        if (entry.isIntersecting) visible.add(video)
        else visible.delete(video)
      }
      sync()
    },
    { threshold: 0.35 },
  )
  for (const video of videos.value) observer.observe(video)
})

onBeforeUnmount(() => {
  observer?.disconnect()
  reduce?.removeEventListener('change', sync)
})
</script>

<template>
  <section v-if="items.length" class="showcase">
    <article v-for="(item, index) in items" :key="item.id" class="row" :class="{ flip: index % 2 === 1 }">
      <div class="media">
        <video
          :ref="(el) => el && !videos.includes(el as HTMLVideoElement) && videos.push(el as HTMLVideoElement)"
          :src="media(item.id, 'mp4')"
          :poster="media(item.id, 'webp')"
          width="1280"
          height="500"
          muted
          loop
          playsinline
          preload="none"
          disablepictureinpicture
          aria-hidden="true"
          tabindex="-1"
        />
      </div>
      <div class="text">
        <h2>{{ item.title }}</h2>
        <p>{{ item.details }}</p>
        <a class="more" :href="withBase(item.link)">{{ item.linkText }}</a>
      </div>
    </article>
    <p v-if="note" class="note">
      {{ note.text }}
      <a :href="withBase(note.link)">{{ note.linkText }}</a>
    </p>
  </section>
</template>

<style scoped>
.showcase {
  max-width: 1152px;
  margin: 0 auto;
  padding: 16px 24px 72px;
}

.row {
  display: grid;
  grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
  align-items: center;
  gap: 48px;
  padding: 40px 0;
  border-top: 1px solid var(--vox-hairline);
}

.row.flip {
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
}

.row.flip .media {
  order: 2;
}

video {
  display: block;
  width: 100%;
  height: auto;
  aspect-ratio: 1280 / 500;
  border: 1px solid var(--vox-hairline);
  border-radius: 12px;
  background: var(--vp-c-bg);
}

h2 {
  margin: 0 0 12px;
  font-size: 24px;
  font-weight: 600;
  line-height: 1.4;
  word-break: auto-phrase;
}

p {
  margin: 0 0 16px;
  font-size: 16px;
  line-height: 1.8;
  color: var(--vp-c-text-2);
}

.more {
  font-weight: 500;
  color: var(--vp-c-brand-1);
  text-decoration: underline;
  text-decoration-color: rgba(128, 172, 255, 0.45);
  text-underline-offset: 4px;
}

.more::after {
  content: ' →';
}

.more:hover {
  text-decoration-color: currentColor;
}

.note {
  margin: 0;
  padding-top: 32px;
  border-top: 1px solid var(--vox-hairline);
  font-size: 15px;
  color: var(--vp-c-text-2);
}

.note a {
  color: var(--vp-c-brand-1);
  text-decoration: underline;
  text-underline-offset: 4px;
}

@media (max-width: 767px) {
  .row,
  .row.flip {
    grid-template-columns: 1fr;
    gap: 20px;
    padding: 28px 0;
  }

  .row.flip .media {
    order: 0;
  }
}
</style>
