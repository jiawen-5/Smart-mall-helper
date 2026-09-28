// 有限状态机：thinking(意图解析) / tool_calling(skill 调用) / answering(流式生成)
// 普通对话退化为 thinking -> answering，只有 skill 命中时才进入 tool_calling。
export type ChatStatus = 'idle' | 'thinking' | 'tool_calling' | 'answering' | 'error'

const STATUS_LABEL: Record<ChatStatus, string> = {
  idle: '',
  thinking: '正在理解需求…',
  tool_calling: '正在查询业务数据…',
  answering: '正在生成…',
  error: '生成失败，请重试',
}

export function statusLabel(s: ChatStatus): string {
  return STATUS_LABEL[s]
}

// 非法转移直接忽略，保证 UI 不会跳变（如 answering 时又收到 thinking）
const TRANSITIONS: Record<ChatStatus, ChatStatus[]> = {
  idle: ['thinking'],
  thinking: ['tool_calling', 'answering', 'error', 'idle'],
  tool_calling: ['answering', 'error', 'idle'],
  answering: ['idle', 'error'],
  error: ['thinking', 'idle'],
}

export function canTransit(from: ChatStatus, to: ChatStatus): boolean {
  return TRANSITIONS[from]?.includes(to) ?? false
}
