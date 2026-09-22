<template>
  <div class="char-card" :class="{victim: character.role.toLowerCase()==='victim'}" @click="handleClick">
    <div class="name">{{ character.name }}</div>
    <div class="role-tag">{{ character.role }}</div>
    <div class="desc">{{ character.backstory }}</div>
  </div>
</template>

<script setup lang="ts">
import type {Character} from "@/types/game"
const props = defineProps<{character:Character}>()
const emit = defineEmits<{select:[]}>()
const handleClick = ()=>emit("select")
</script>

<style scoped lang="scss">
.char-card{
  border:1px solid #ccc;
  border-radius:8px;
  padding:12px;
  cursor:pointer;
  transition:0.2s;
  &:hover{
    background:#f0f4ff;
  }
  &.victim{
    border-color:#ef4444;
    background:#fef2f2;
  }
  .name{
    font-size:16px;
    font-weight:bold;
  }
  .role-tag{
    font-size:12px;
    color:#666;
  }
  .desc{
    margin-top:6px;
    font-size:13px;
    color:#444;
  }
}
</style>
