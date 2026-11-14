<script setup lang="ts">
import { computed } from 'vue'
import { useData } from 'vitepress'
import { laneNames, routes } from './routes'

const { frontmatter, lang } = useData()

const lanes = computed(() => {
  const lanes = routes[frontmatter.value.route as string]
  if (!lanes) return []
  const key = lang.value.startsWith('ja') ? 'ja' : 'en'
  return lanes.map((lane) => ({
    side: lane.side,
    name: laneNames[lane.side][key],
    nodes: lane.nodes.map((node) => ({ text: node[key], here: node.here === true })),
  }))
})
</script>

<template>
  <div v-if="lanes.length" class="route-strip">
    <div v-for="lane in lanes" :key="lane.side" class="lane" :class="lane.side" role="group" :aria-label="lane.name">
      <span class="lane-name" aria-hidden="true">{{ lane.name }}</span>
      <ol>
        <li v-for="(node, index) in lane.nodes" :key="index" :aria-current="node.here ? 'step' : undefined">
          <span v-if="index > 0" class="wire" aria-hidden="true"></span>
          <span class="node" :class="{ here: node.here }">{{ node.text }}</span>
        </li>
      </ol>
    </div>
  </div>
</template>

<style scoped>
/* A running head for feature pages: the signal route this page sets up, with this page's
   step lit. Blue lanes carry what you send, purple lanes what comes back (how-it-works). */
.route-strip {
  display: grid;
  gap: 8px;
  margin-bottom: 24px;
  padding: 12px 16px;
  border: 1px solid var(--vox-hairline);
  border-radius: 8px;
  background: var(--vp-c-bg-alt);
}

.lane {
  --lane: var(--vox-mine);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 12px;
}

.lane.theirs {
  --lane: var(--vox-theirs);
}

.lane-name {
  min-width: 8em;
  font-size: 12px;
  font-weight: 600;
  line-height: 28px;
  color: var(--lane);
}

ol {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

li {
  display: flex;
  align-items: center;
}

/* The wire between two steps, ending in the lane's arrowhead. */
.wire {
  position: relative;
  width: 24px;
  height: 1.5px;
  margin: 0 8px;
  background: var(--lane);
  opacity: 0.7;
}

.wire::after {
  content: '';
  position: absolute;
  top: -3px;
  right: -1px;
  border-top: 3.75px solid transparent;
  border-bottom: 3.75px solid transparent;
  border-left: 6px solid var(--lane);
}

.node {
  font-size: 13px;
  line-height: 26px;
  color: var(--vp-c-text-2);
  white-space: nowrap;
}

.node.here {
  padding: 0 8px;
  border: 1px solid var(--lane);
  border-radius: 6px;
  background: rgba(110, 168, 255, 0.14);
  color: var(--vp-c-text-1);
  font-weight: 600;
}

.theirs .node.here {
  background: rgba(180, 140, 255, 0.14);
}

/* Phones: the lane name above, shorter wires so a 4-step route fits on one line. */
@media (max-width: 639px) {
  .route-strip {
    padding: 10px 12px;
  }

  .lane {
    gap: 0 12px;
  }

  .wire {
    width: 12px;
    margin: 0 6px 0 4px;
  }
}
</style>
