import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { ObserverLog, ObserverLogBody } from '../types'

// ============================================================
//  ObserverPanel — 观察员视角（可读优先版）
//  正常字体、自然换行、可见细滚动条；宁可滚动也要内容完整。
// ============================================================

interface Props {
  brainId: number
  /** 默认展开 */
  defaultOpen?: boolean
  /** 轮询间隔，单位 ms */
  pollIntervalMs?: number
  /** 当前大脑状态：'thinking' | 'paused' | 'completed' | ... */
  brainState?: string
}

const POLL_DEFAULT = 30_000

export default function ObserverPanel({ brainId, defaultOpen = true, pollIntervalMs = POLL_DEFAULT, brainState }: Props) {
  const [open, setOpen] = useState(defaultOpen)
  const [latest, setLatest] = useState<ObserverLog | null>(null)
  const [history, setHistory] = useState<ObserverLog[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string>('')
  const [lastSync, setLastSync] = useState<Date | null>(null)
  const aliveRef = useRef(true)

  // ---------- 拉取最新总结 ----------
  useEffect(() => {
    if (!brainId || Number.isNaN(brainId)) return
    aliveRef.current = true

    async function load() {
      try {
        const data = await api.getLatestObserverLog(brainId)
        if (!aliveRef.current) return
        setLatest(data || null)
        setLastSync(new Date())
        setError('')
      } catch (e: any) {
        if (aliveRef.current) setError(e?.message || '加载失败')
      }
    }

    load()
    const t = setInterval(load, pollIntervalMs)
    return () => {
      aliveRef.current = false
      clearInterval(t)
    }
  }, [brainId, pollIntervalMs])

  // ---------- 大脑暂停/完成时 → 自动展开 + 立即刷新 ----------
  useEffect(() => {
    if (brainState === 'paused' || brainState === 'completed') {
      setOpen(true)
      ;(async () => {
        try {
          const data = await api.getLatestObserverLog(brainId)
          setLatest(data || null)
          setLastSync(new Date())
          setError('')
        } catch (e: any) {
          setError(e?.message || '刷新失败')
        }
      })()
    }
  }, [brainState, brainId])

  // ---------- 历史展开时拉取列表 ----------
  useEffect(() => {
    if (!historyOpen || !brainId) return
    let alive = true
    setHistoryLoading(true)
    api
      .getObserverLogs(brainId, { kind: 'summary', limit: 10 })
      .then(res => {
        if (!alive) return
        setHistory(res.items || [])
      })
      .catch(e => {
        if (alive) setError(e?.message || '历史加载失败')
      })
      .finally(() => {
        if (alive) setHistoryLoading(false)
      })
    return () => {
      alive = false
    }
  }, [historyOpen, brainId])

  // ---------- 手动触发生成 ----------
  async function handleGenerate() {
    if (generating) return
    setGenerating(true)
    setError('')
    try {
      await api.generateObserverSummary(brainId, { reason: 'manual', force: true })
      const data = await api.getLatestObserverLog(brainId)
      setLatest(data || null)
      setLastSync(new Date())
      if (historyOpen) {
        const res = await api.getObserverLogs(brainId, { kind: 'summary', limit: 10 })
        setHistory(res.items || [])
      }
    } catch (e: any) {
      setError(e?.message || '生成失败')
    } finally {
      setGenerating(false)
    }
  }

  // ---------- 解析 body ----------
  const body: ObserverLogBody | null = useMemo(() => {
    if (!latest) return null
    if (latest.body_struct) return latest.body_struct
    try {
      return JSON.parse(latest.body) as ObserverLogBody
    } catch {
      return null
    }
  }, [latest])

  const isHighImportance = (body?.importance ?? 0) >= 0.7

  // ============================================================
  //  渲染
  // ============================================================
  return (
    <aside
      className={'observer-panel' + (isHighImportance ? ' is-elevated' : '')}
      style={{
        ...wrapperStyle,
        ...(isHighImportance ? elevatedStyle : {}),
      }}
    >
      {/* 顶部标题栏 */}
      <button
        onClick={() => setOpen(o => !o)}
        style={headerBtn}
        title={open ? '折叠' : '展开'}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
          <span style={titleEmoji} aria-hidden>🔭</span>
          <span style={titleText}>观察员视角</span>
          {(brainState === 'paused' || brainState === 'completed') && latest && (
            <span style={reviewBadge}>复盘报告</span>
          )}
          {body && (
            <span style={importanceMeter(body.importance)}>
              {(body.importance * 100).toFixed(0)}
            </span>
          )}
          {isHighImportance && <span style={importanceBadge}>HIGH</span>}
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {lastSync && (
            <span style={syncStamp}>{lastSync.toLocaleTimeString().slice(0, 5)}</span>
          )}
          <span style={chevron(open)} aria-hidden>▾</span>
        </span>
      </button>

      {open && (
        <div className="observer-body" style={bodyStyle}>
          {error && <div style={errorBox}>{error}</div>}

          {/* 占位 */}
          {!latest && !error && (
            <EmptyState />
          )}

          {/* 主内容 */}
          {latest && body && (
            <div style={contentStack}>
              {/* 标题行：编号 + 标题 + 时间 */}
              <div style={titleRow}>
                <span style={kicker}>#{latest.id}</span>
                <span style={summaryTitle} title={latest.title || ''}>
                  {latest.title || '尚未命名的观察'}
                </span>
                <span style={timeStamp}>{formatTime(latest.created_at)}</span>
              </div>

              {body.narrative && (
                <p style={narrativeStyle}>{body.narrative}</p>
              )}

              {/* 主要方向 */}
              {Array.isArray(body.main_directions) && body.main_directions.length > 0 && (
                <Row label="方向">
                  <div style={chipRow}>
                    {body.main_directions.map((d, i) => (
                      <span key={i} style={chipStyle}>{d}</span>
                    ))}
                  </div>
                </Row>
              )}

              {/* 关键发展 */}
              {Array.isArray(body.key_developments) && body.key_developments.length > 0 && (
                <Row label="发展">
                  <ul style={listStyle}>
                    {body.key_developments.map((d, i) => (
                      <li key={i} style={listItem}>
                        <span style={bullet} aria-hidden />
                        <span style={listText}>
                          {d.summary}
                          {d.cited_ce_ids && d.cited_ce_ids.length > 0 && (
                            <span style={citeStyle}>
                              {' '}{d.cited_ce_ids.map(id => `#${id}`).join(' · ')}
                            </span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                </Row>
              )}

              {/* 段落型字段（自然换行，全文显示） */}
              {body.deliberation_dynamics && (
                <Row label="博弈"><span style={paragraph}>{body.deliberation_dynamics}</span></Row>
              )}
              {body.frontier_movement && (
                <Row label="边界"><span style={paragraph}>{body.frontier_movement}</span></Row>
              )}
              {body.health_assessment && (
                <Row label="评价"><span style={paragraph}>{body.health_assessment}</span></Row>
              )}
            </div>
          )}

          {/* fallback — 拿到 log 但无法解析 body */}
          {latest && !body && (
            <div>
              <div style={summaryTitle}>{latest.title || '观察员日志'}</div>
              <pre style={rawBox}>{latest.body}</pre>
            </div>
          )}

          {/* 历史折叠 */}
          <div style={historyBlock}>
            <button onClick={() => setHistoryOpen(o => !o)} style={historyToggle}>
              <span>{historyOpen ? '收起历史' : '查看历史'}</span>
              <span style={{ opacity: 0.5, fontSize: 12 }}>{historyOpen ? '▴' : '▾'}</span>
            </button>

            {historyOpen && (
              <div style={{ marginTop: 8 }}>
                {historyLoading && <div style={paragraph}>加载中…</div>}
                {!historyLoading && history.length === 0 && (
                  <div style={paragraph}>暂无历史总结</div>
                )}
                {!historyLoading && history.length > 0 && (
                  <ol style={historyList}>
                    {history.map(h => (
                      <li key={h.id} style={historyItem}>
                        <span style={historyDot} />
                        <span style={historyTitleStyle}>
                          {h.title || `观察 #${h.id}`}
                        </span>
                        <span style={historyTime}>{formatTime(h.created_at)}</span>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            )}
          </div>

          {/* 操作行 */}
          <div style={footerRow}>
            <button onClick={handleGenerate} disabled={generating} style={generateBtn(generating)}>
              {generating ? '凝视中…' : '请求新观察'}
            </button>
            {body && (
              <span style={{ fontSize: 11, color: 'var(--text2)', letterSpacing: 1, opacity: 0.65 }}>
                IMPORTANCE · {(body.importance * 100).toFixed(0)}
              </span>
            )}
          </div>
        </div>
      )}

      {/* 局部样式：动画 + 美化滚动条 */}
      <style>{`
        @keyframes observerScan {
          0% { background-position: 0% 50%; }
          50% { background-position: 100% 50%; }
          100% { background-position: 0% 50%; }
        }
        @keyframes observerEyeFloat {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-4px); }
        }
        .observer-panel::before {
          content: "";
          position: absolute;
          inset: -1px;
          border-radius: inherit;
          padding: 1px;
          background: linear-gradient(115deg, rgba(99,102,241,0.55), rgba(168,85,247,0.45) 38%, rgba(56,189,248,0.45) 72%, rgba(99,102,241,0.55));
          background-size: 200% 200%;
          animation: observerScan 9s ease-in-out infinite;
          -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
          -webkit-mask-composite: xor;
                  mask-composite: exclude;
          pointer-events: none;
          opacity: 0.85;
        }
        .observer-panel.is-elevated::before {
          background: linear-gradient(115deg, rgba(255,196,0,0.85), rgba(255,140,0,0.65) 50%, rgba(255,196,0,0.85));
          background-size: 200% 200%;
          opacity: 1;
        }
        .observer-eye {
          animation: observerEyeFloat 4.6s ease-in-out infinite;
          display: inline-block;
        }
        /* 美化的细滚动条（保持可见） */
        .observer-body {
          scrollbar-width: thin;
          scrollbar-color: rgba(168,85,247,0.45) transparent;
        }
        .observer-body::-webkit-scrollbar {
          width: 8px;
          height: 8px;
        }
        .observer-body::-webkit-scrollbar-track {
          background: transparent;
        }
        .observer-body::-webkit-scrollbar-thumb {
          background: linear-gradient(180deg, rgba(168,85,247,0.55), rgba(99,102,241,0.55));
          border-radius: 4px;
          border: 1px solid rgba(255,255,255,0.05);
        }
        .observer-body::-webkit-scrollbar-thumb:hover {
          background: linear-gradient(180deg, rgba(168,85,247,0.85), rgba(99,102,241,0.85));
        }
      `}</style>
    </aside>
  )
}

// ============================================================
//  子组件
// ============================================================

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={rowWrap}>
      <span style={rowLabel}>{label}</span>
      <div style={{ flex: 1, minWidth: 0 }}>{children}</div>
    </div>
  )
}

function EmptyState() {
  return (
    <div style={emptyWrap}>
      <span className="observer-eye" style={{ fontSize: 30, filter: 'drop-shadow(0 0 10px rgba(168,85,247,0.55))' }}>
        🔭
      </span>
      <div style={emptyTitle}>观察员正在凝视…</div>
      <div style={emptySub}>
        当涌现出值得讲述的演化时，<br />这里会浮现观察员的叙事。
      </div>
    </div>
  )
}

// ============================================================
//  工具
// ============================================================
function formatTime(s: string): string {
  if (!s) return ''
  const safe = s.includes('T') ? s : s.replace(' ', 'T') + 'Z'
  const d = new Date(safe)
  if (isNaN(d.getTime())) return s
  const now = Date.now()
  const diff = now - d.getTime()
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}分前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}时前`
  return d.toLocaleDateString()
}

// ============================================================
//  样式（可读优先）
// ============================================================

const wrapperStyle: React.CSSProperties = {
  position: 'relative',
  width: '100%',
  height: '100%',
  display: 'flex',
  flexDirection: 'column',
  background:
    'linear-gradient(180deg, rgba(15,20,30,0.92) 0%, rgba(11,13,22,0.94) 100%)',
  borderRadius: 12,
  border: '1px solid rgba(99,102,241,0.18)',
  boxShadow: '0 12px 40px rgba(0,0,0,0.45), inset 0 0 24px rgba(99,102,241,0.05)',
  backdropFilter: 'blur(14px)',
  WebkitBackdropFilter: 'blur(14px)',
  overflow: 'hidden',
  isolation: 'isolate',
  minHeight: 0,
}

const elevatedStyle: React.CSSProperties = {
  borderColor: 'rgba(255,196,0,0.55)',
  boxShadow:
    '0 0 0 1px rgba(255,196,0,0.25), 0 18px 50px rgba(255,140,0,0.18), inset 0 0 30px rgba(255,196,0,0.08)',
}

const headerBtn: React.CSSProperties = {
  appearance: 'none',
  background: 'transparent',
  border: 'none',
  color: 'var(--text)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  width: '100%',
  padding: '10px 14px',
  cursor: 'pointer',
  borderBottom: '1px solid rgba(99,102,241,0.12)',
  flexShrink: 0,
  minHeight: 40,
}

const titleEmoji: React.CSSProperties = {
  fontSize: 16,
  filter: 'drop-shadow(0 0 6px rgba(168,85,247,0.5))',
}

const titleText: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 600,
  letterSpacing: 1.5,
  background: 'linear-gradient(90deg, #c4b5fd, #93c5fd)',
  WebkitBackgroundClip: 'text',
  WebkitTextFillColor: 'transparent',
  backgroundClip: 'text',
  textTransform: 'uppercase' as const,
  whiteSpace: 'nowrap',
}

const importanceBadge: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: 1.2,
  padding: '2px 7px',
  borderRadius: 4,
  background: 'rgba(255,196,0,0.18)',
  color: '#FFD27F',
  border: '1px solid rgba(255,196,0,0.35)',
  whiteSpace: 'nowrap',
  fontWeight: 600,
}

const reviewBadge: React.CSSProperties = {
  fontSize: 10,
  padding: '2px 6px',
  borderRadius: 4,
  background: 'rgba(168, 85, 247, 0.2)',
  color: '#c084fc',
  border: '1px solid rgba(168, 85, 247, 0.3)',
  fontWeight: 500,
  marginLeft: 6,
}

const syncStamp: React.CSSProperties = {
  fontSize: 11,
  letterSpacing: 0.8,
  color: 'var(--text2)',
  opacity: 0.6,
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
}

const chevron = (open: boolean): React.CSSProperties => ({
  fontSize: 13,
  color: 'var(--text2)',
  transform: open ? 'rotate(0deg)' : 'rotate(-90deg)',
  transition: 'transform .2s ease',
  opacity: 0.7,
})

// body 区允许滚动；显示美化的细滚动条（在 <style> 中实现）
const bodyStyle: React.CSSProperties = {
  padding: '14px 16px 16px',
  overflowY: 'auto',
  flex: 1,
  minHeight: 0,
  fontSize: 13,
  lineHeight: 1.6,
  color: 'var(--text2)',
}

const errorBox: React.CSSProperties = {
  background: 'rgba(239,68,68,0.12)',
  border: '1px solid rgba(239,68,68,0.35)',
  color: '#fca5a5',
  padding: '8px 10px',
  borderRadius: 6,
  fontSize: 13,
  marginBottom: 10,
  lineHeight: 1.5,
}

const contentStack: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 10,
}

const titleRow: React.CSSProperties = {
  display: 'flex',
  alignItems: 'baseline',
  gap: 8,
  flexWrap: 'wrap',
  minWidth: 0,
}

const kicker: React.CSSProperties = {
  fontSize: 11,
  letterSpacing: 1,
  color: 'rgba(196,181,253,0.75)',
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
  flexShrink: 0,
}

const summaryTitle: React.CSSProperties = {
  fontSize: 16,
  fontWeight: 600,
  color: 'var(--text)',
  lineHeight: 1.4,
  flex: 1,
  minWidth: 0,
  wordBreak: 'break-word',
}

const timeStamp: React.CSSProperties = {
  fontSize: 11,
  color: 'var(--text2)',
  flexShrink: 0,
  opacity: 0.7,
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
}

const importanceMeter = (v: number): React.CSSProperties => ({
  fontSize: 11,
  letterSpacing: 0.6,
  color: v >= 0.7 ? '#FFD27F' : v >= 0.4 ? '#93c5fd' : 'var(--text2)',
  border: `1px solid ${v >= 0.7 ? 'rgba(255,196,0,0.4)' : 'rgba(99,102,241,0.25)'}`,
  borderRadius: 999,
  padding: '1px 8px',
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
})

// 叙事段落：全文展示，自然换行
const narrativeStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 14,
  lineHeight: 1.7,
  color: 'var(--text)',
  background:
    'linear-gradient(180deg, rgba(99,102,241,0.07), rgba(168,85,247,0.04))',
  border: '1px solid rgba(99,102,241,0.18)',
  borderRadius: 8,
  padding: '12px 14px',
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
}

// 行式区块：标签 + 内容
const rowWrap: React.CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  gap: 10,
  minWidth: 0,
}

const rowLabel: React.CSSProperties = {
  fontSize: 11,
  letterSpacing: 1,
  color: 'rgba(196,181,253,0.75)',
  textTransform: 'uppercase' as const,
  flexShrink: 0,
  width: 38,
  paddingTop: 3,
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
}

const chipRow: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 6,
}

const chipStyle: React.CSSProperties = {
  fontSize: 12,
  padding: '3px 10px',
  borderRadius: 999,
  background: 'rgba(99,102,241,0.14)',
  color: '#c4b5fd',
  border: '1px solid rgba(99,102,241,0.32)',
  whiteSpace: 'normal',
  wordBreak: 'break-word',
  lineHeight: 1.4,
}

const listStyle: React.CSSProperties = {
  margin: 0,
  padding: 0,
  listStyle: 'none',
  display: 'flex',
  flexDirection: 'column',
  gap: 6,
  minWidth: 0,
}

const listItem: React.CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  gap: 8,
  fontSize: 13,
  color: 'var(--text)',
  lineHeight: 1.55,
  minWidth: 0,
}

const listText: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  color: 'var(--text)',
  wordBreak: 'break-word',
}

const bullet: React.CSSProperties = {
  width: 5,
  height: 5,
  borderRadius: 3,
  background: 'linear-gradient(135deg, #a855f7, #6366f1)',
  flexShrink: 0,
  marginTop: 8,
  boxShadow: '0 0 4px rgba(168,85,247,0.4)',
}

const citeStyle: React.CSSProperties = {
  fontSize: 11,
  letterSpacing: 0.3,
  color: 'rgba(147,197,253,0.75)',
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
}

// 段落：自然换行，全文展示
const paragraph: React.CSSProperties = {
  display: 'block',
  fontSize: 13,
  color: 'var(--text)',
  lineHeight: 1.6,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
}

const rawBox: React.CSSProperties = {
  background: 'rgba(0,0,0,0.3)',
  border: '1px solid rgba(99,102,241,0.18)',
  borderRadius: 6,
  padding: 10,
  fontSize: 12,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  marginTop: 8,
}

const historyBlock: React.CSSProperties = {
  marginTop: 14,
  paddingTop: 10,
  borderTop: '1px dashed rgba(140,150,200,0.18)',
}

const historyToggle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  width: '100%',
  background: 'transparent',
  border: 'none',
  color: 'rgba(196,181,253,0.9)',
  fontSize: 12,
  letterSpacing: 1,
  cursor: 'pointer',
  padding: 0,
  textTransform: 'uppercase' as const,
}

const historyList: React.CSSProperties = {
  margin: 0,
  padding: 0,
  listStyle: 'none',
  display: 'flex',
  flexDirection: 'column',
  borderLeft: '1px solid rgba(99,102,241,0.22)',
  paddingLeft: 14,
  gap: 6,
  marginLeft: 4,
}

const historyItem: React.CSSProperties = {
  display: 'flex',
  alignItems: 'baseline',
  gap: 8,
  position: 'relative',
  minWidth: 0,
  fontSize: 13,
  flexWrap: 'wrap',
}

const historyDot: React.CSSProperties = {
  position: 'absolute',
  left: -17,
  top: 7,
  width: 6,
  height: 6,
  borderRadius: 3,
  background: '#6366f1',
  boxShadow: '0 0 6px rgba(99,102,241,0.7)',
}

const historyTitleStyle: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  fontSize: 13,
  color: 'var(--text)',
  lineHeight: 1.5,
  wordBreak: 'break-word',
}

const historyTime: React.CSSProperties = {
  fontSize: 11,
  color: 'var(--text2)',
  letterSpacing: 0.3,
  flexShrink: 0,
  opacity: 0.7,
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
}

const footerRow: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 10,
  marginTop: 14,
  paddingTop: 10,
  borderTop: '1px solid rgba(99,102,241,0.12)',
  flexShrink: 0,
}

const generateBtn = (loading: boolean): React.CSSProperties => ({
  appearance: 'none',
  border: '1px solid rgba(99,102,241,0.4)',
  background:
    'linear-gradient(135deg, rgba(99,102,241,0.22), rgba(168,85,247,0.16))',
  color: '#c4b5fd',
  fontSize: 13,
  letterSpacing: 1,
  padding: '6px 14px',
  borderRadius: 6,
  cursor: loading ? 'wait' : 'pointer',
  opacity: loading ? 0.6 : 1,
  fontWeight: 500,
})

const emptyWrap: React.CSSProperties = {
  textAlign: 'center',
  padding: '28px 14px',
  color: 'var(--text2)',
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  gap: 10,
}

const emptyTitle: React.CSSProperties = {
  fontSize: 14,
  color: 'var(--text)',
  letterSpacing: 1,
}

const emptySub: React.CSSProperties = {
  fontSize: 12,
  color: 'var(--text2)',
  lineHeight: 1.6,
  opacity: 0.75,
}
