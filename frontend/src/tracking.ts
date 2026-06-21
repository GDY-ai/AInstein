// 用户行为埋点 SDK：本地批量缓冲 → 定时/卸载前 flush 到 /ainstein/api/tracking
import { getToken } from './api';

interface TrackEvent {
  type: string;
  brain_id?: number;
  metadata?: Record<string, unknown>;
}

const QUEUE: TrackEvent[] = [];
const MAX_BATCH = 50;
const FLUSH_DELAY_MS = 3000;

let timer: ReturnType<typeof setTimeout> | null = null;

export function track(
  type: string,
  metadata?: Record<string, unknown> & { brain_id?: number },
): void {
  if (!type) return;
  let brain_id: number | undefined;
  let rest: Record<string, unknown> | undefined;
  if (metadata) {
    const { brain_id: bid, ...others } = metadata;
    if (typeof bid === 'number' && Number.isFinite(bid)) brain_id = bid;
    rest = Object.keys(others).length > 0 ? others : undefined;
  }
  QUEUE.push({ type, brain_id, metadata: rest });

  if (!timer) {
    timer = setTimeout(flush, FLUSH_DELAY_MS);
  }
}

async function flush(): Promise<void> {
  timer = null;
  if (QUEUE.length === 0) return;
  const events = QUEUE.splice(0, MAX_BATCH);
  const token = getToken();
  if (!token) return; // 未登录则丢弃，无需上报
  try {
    await fetch('/ainstein/api/tracking', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ events }),
      keepalive: true,
    });
  } catch {
    // 静默失败，不影响用户体验
  }
}

// 页面卸载前强制 flush，避免数据丢失
if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', () => {
    void flush();
  });
  window.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      void flush();
    }
  });
}
