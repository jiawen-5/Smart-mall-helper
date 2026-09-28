// chunk 缓冲 + rAF 批量 flush：SSE 高频 onDelta 只入队，每帧最多 setState 一次。
// 后台 tab 下 rAF 暂停，自动降级为 setTimeout(50ms)。
export type FlushFn = (text: string) => void

export function createStreamBuffer(onFlush: FlushFn) {
  let queue = ''
  let acc = ''
  let rafId = 0
  let timer: ReturnType<typeof setTimeout> | null = null
  let scheduled = false

  const flush = () => {
    scheduled = false
    if (!queue) return
    acc += queue
    queue = ''
    onFlush(acc)
  }

  const schedule = () => {
    if (scheduled) return
    scheduled = true
    if (typeof requestAnimationFrame !== 'undefined' && !document.hidden) {
      rafId = requestAnimationFrame(() => {
        rafId = 0
        flush()
      })
    } else {
      timer = setTimeout(() => {
        timer = null
        flush()
      }, 50)
    }
  }

  return {
    push(chunk: string) {
      if (!chunk) return
      queue += chunk
      schedule()
    },
    setInitial(text: string) {
      acc = text
    },
    flushNow() {
      if (rafId) cancelAnimationFrame(rafId)
      if (timer) clearTimeout(timer)
      rafId = 0
      timer = null
      scheduled = false
      if (queue) {
        acc += queue
        queue = ''
        onFlush(acc)
      }
      return acc
    },
    getText() {
      return acc + queue
    },
  }
}

export type StreamBuffer = ReturnType<typeof createStreamBuffer>
