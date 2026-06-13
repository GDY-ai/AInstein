import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { ObserverLog, ObserverLogBody } from '../types'

// ============================================================
//  ObserverPanel — 观察员视角
//  上帝视角的"望远镜"，以叙事方式呈现整颗大脑的演化
// ============================================================

interface Props {
  brainId: number
  /** 默认展开 */
  defaultOpen?: boolean
  /** 轮询间隔，单位 ms */
  pollIntervalMs?: number
}

const POLL_DEFAULT = 30_000

export default function ObserverPanel({ brainId, defaultOpen = true, pollIntervalMs = POLL_DEFAULT }: Props) {
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
      // 刷新最新
      const data = await api.getLatestObserverLog(brainId)
      setLatest(data || null)
      setLastSync(new Date())
      // 同时刷新历史（如已展开）
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
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={titleEmoji} aria-hidden>🔭</span>
          <span style={titleText}>观察员视角</span>
          {isHighImportance && <span style={importanceBadge}>HIGH&nbsp;SIGNAL</span>}
        </span>
        <span style={chevron(open)} aria-hidden>▾</span>
      </button>

      {open && (
        <div style={bodyStyle}>
          {error && <div style={errorBox}>{error}</div>}

          {/* 占位 */}
          {!latest && !error && (
            <EmptyState />
          )}

          {/* 主内容 */}
          {latest && body && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div>
                <div style={kicker}>OBSERVER · LOG #{latest.id}</div>
                <h3 style={summaryTitle}>{latest.title || '尚未命名的观察'}</h3>
                <div style={metaRow}>
                  <span>{formatTime(latest.created_at)}</span>
                  <span style={importanceMeter(body.importance)}>
                    importance {(body.importance * 100).toFixed(0)}
                  </span>
                </div>
              </div>

              {body.narrative && (
                <p style={narrativeStyle}>{body.narrative}</p>
              )}

              {/* 主要方向 */}
              {Array.isArray(body.main_directions) && body.main_directions.length > 0 && (
                <Section label="主要方向">
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {body.main_directions.map((d, i) => (
                      <span key={i} style={chipStyle}>{d}</span>
                    ))}
                  </div>
                </Section>
              )}

              {/* 关键发展 */}
              {Array.isArray(body.key_developments) && body.key_developments.length > 0 && (
                <Section label="关键发展">
                  <ul style={listStyle}>
                    {body.key_developments.map((d, i) => (
                      <li key={i} style={listItem}>
                        <span style={bullet} aria-hidden />
                        <span>
                          <span style={{ color: 'var(--text)' }}>{d.summary}</span>
                          {d.cited_ce_ids && d.cited_ce_ids.length > 0 && (
                            <span style={citeStyle}>
                              {d.cited_ce_ids.map(id => `#${id}`).join(' · ')}
                            </span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                </Section>
              )}

              {/* 次要字段 */}
              {body.deliberation_dynamics && (
                <Section label="博弈动态">
                  <p style={subText}>{body.deliberation_dynamics}</p>
                </Section>
              )}
              {body.frontier_movement && (
                <Section label="认知边界">
                  <p style={subText}>{body.frontier_movement}</p>
                </Section>
              )}
              {body.health_assessment && (
                <Section label="整体评价">
                  <p style={subText}>{body.health_assessment}</p>
                </Section>
              )}
            </div>
          )}

          {/* fallback — 拿到 log 但无法解析 body */}
          {latest && !body && (
            <div>
              <h3 style={summaryTitle}>{latest.title || '观察员日志'}</h3>
              <pre style={rawBox}>{latest.body}</pre>
            </div>
          )}

          {/* 历史折叠 */}
          <div style={{ marginTop: 10, borderTop: '1px dashed rgba(140,150,200,0.18)', paddingTop: 8 }}>
            <button onClick={() => setHistoryOpen(o => !o)} style={historyToggle}>
              <span>{historyOpen ? '收起历史' : '查看历史'}</span>
              <span style={{ opacity: 0.5, fontSize: 11 }}>{historyOpen ? '▴' : '▾'}</span>
            </button>

            {historyOpen && (
              <div style={{ marginTop: 8 }}>
                {historyLoading && <div style={subText}>加载中…</div>}
                {!historyLoading && history.length === 0 && (
                  <div style={subText}>暂无历史总结</div>
                )}
                {!historyLoading && history.length > 0 && (
                  <ol style={historyList}>
                    {history.map(h => (
                      <li key={h.id} style={historyItem}>
                        <span style={historyDot} />
                        <span style={{ flex: 1, minWidth: 0 }}>
                          <div style={historyTitle}>{h.title || `观察 #${h.id}`}</div>
                          <div style={historyTime}>{formatTime(h.created_at)}</div>
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            )}
          </div>

          {/* 操作区 */}
          <div style={footerRow}>
            <button onClick={handleGenerate} disabled={generating} style={generateBtn(generating)}>
              {generating ? '凝视中…' : '请求新观察'}
            </button>
            {lastSync && (
              <span style={{ fontSize: 10, color: 'var(--text2)', letterSpacing: 1 }}>
                SYNC · {lastSync.toLocaleTimeString()}
              </span>
            )}
          </div>
        </div>
      )}

      {/* 局部样式 */}
      <style>{`
        @keyframes observerScan {
          0% { background-position: 0% 50%; }
          50% { background-position: 100% 50%; }
          100% { background-position: 0% 50%; }
        }
        @keyframes observerEyeBlink {
          0%, 92%, 100% { opacity: 1; transform: scaleY(1); }
          95% { opacity: 0.85; transform: scaleY(0.05); }
        }
        @keyframes observerEyeFloat {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-4px); }
        }
        @keyframes observerOrbit {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
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
      `}</style>
    </aside>
  )
}

// ============================================================
//  子组件
// ============================================================

function Section({ label, mutedTitle, children }: { label: string; mutedTitle?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ ...sectionLabel, ...(mutedTitle ? { opacity: 0.6 } : {}) }}>{label}</div>
      {children}
    </div>
  )
}

function EmptyState() {
  return (
    <div style={emptyWrap}>
      <div style={emptyOrb}>
        <span className="observer-eye" style={{ fontSize: 38, filter: 'drop-shadow(0 0 14px rgba(168,85,247,0.55))' }}>
          🔭
        </span>
      </div>
      <div style={emptyTitle}>观察员正在凝视这颗大脑…</div>
      <div style={emptySub}>
        当涌现出第一缕值得讲述的演化时，<br />
        这里会自动浮现观察员的叙事。
      </div>
    </div>
  )
}

// ============================================================
//  工具
// ============================================================
function formatTime(s: string): string {
  if (!s) return ''
  // 后端格式 "YYYY-MM-DD HH:MM:SS"，可能是 UTC
  const safe = s.includes('T') ? s : s.replace(' ', 'T') + 'Z'
  const d = new Date(safe)
  if (isNaN(d.getTime())) return s
  const now = Date.now()
  const diff = now - d.getTime()
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  return d.toLocaleString()
}

// ============================================================
//  样式
// ============================================================

const wrapperStyle: React.CSSProperties = {
  position: 'relative',
  width: '100%',
  height: '100%',
  display: 'flex',
  flexDirection: 'column',
  background:
    'linear-gradient(180deg, rgba(15,20,30,0.92) 0%, rgba(11,13,22,0.94) 100%)',
  borderRadius: 14,
  border: '1px solid rgba(99,102,241,0.18)',
  boxShadow: '0 12px 40px rgba(0,0,0,0.45), inset 0 0 24px rgba(99,102,241,0.05)',
  backdropFilter: 'blur(14px)',
  WebkitBackdropFilter: 'blur(14px)',
  overflow: 'hidden',
  isolation: 'isolate',
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
}

const titleEmoji: React.CSSProperties = {
  fontSize: 18,
  filter: 'drop-shadow(0 0 6px rgba(168,85,247,0.5))',
}

const titleText: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 600,
  letterSpacing: 2,
  background: 'linear-gradient(90deg, #c4b5fd, #93c5fd)',
  WebkitBackgroundClip: 'text',
  WebkitTextFillColor: 'transparent',
  backgroundClip: 'text',
  textTransform: 'uppercase' as const,
}

const importanceBadge: React.CSSProperties = {
  marginLeft: 8,
  fontSize: 9,
  letterSpacing: 1.5,
  padding: '2px 6px',
  borderRadius: 3,
  background: 'rgba(255,196,0,0.18)',
  color: '#FFD27F',
  border: '1px solid rgba(255,196,0,0.35)',
}

const chevron = (open: boolean): React.CSSProperties => ({
  fontSize: 12,
  color: 'var(--text2)',
  transform: open ? 'rotate(0deg)' : 'rotate(-90deg)',
  transition: 'transform .2s ease',
  opacity: 0.6,
})

const bodyStyle: React.CSSProperties = {
  padding: '10px 14px 12px',
  overflow: 'hidden',
  flex: 1,
  fontSize: 12,
  lineHeight: 1.5,
  color: 'var(--text2)',
}

const errorBox: React.CSSProperties = {
  background: 'rgba(239,68,68,0.12)',
  border: '1px solid rgba(239,68,68,0.35)',
  color: '#fca5a5',
  padding: '6px 10px',
  borderRadius: 6,
  fontSize: 12,
  marginBottom: 10,
}

const kicker: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: 2,
  color: 'rgba(196,181,253,0.7)',
  marginBottom: 4,
}

const summaryTitle: React.CSSProperties = {
  margin: 0,
  fontSize: 14,
  fontWeight: 600,
  color: 'var(--text)',
  lineHeight: 1.3,
}

const metaRow: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  gap: 12,
  marginTop: 4,
  fontSize: 11,
  color: 'var(--text2)',
}

const importanceMeter = (v: number): React.CSSProperties => ({
  fontSize: 10,
  letterSpacing: 1,
  color: v >= 0.7 ? '#FFD27F' : v >= 0.4 ? '#93c5fd' : 'var(--text2)',
  border: `1px solid ${v >= 0.7 ? 'rgba(255,196,0,0.4)' : 'rgba(99,102,241,0.25)'}`,
  borderRadius: 999,
  padding: '1px 8px',
  textTransform: 'uppercase' as const,
})

const narrativeStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 13,
  lineHeight: 1.55,
  color: 'var(--text)',
  background:
    'linear-gradient(180deg, rgba(99,102,241,0.07), rgba(168,85,247,0.04))',
  border: '1px solid rgba(99,102,241,0.18)',
  borderRadius: 6,
  padding: '8px 10px',
  whiteSpace: 'pre-wrap',
}

const sectionLabel: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: 1.5,
  color: 'rgba(196,181,253,0.7)',
  marginBottom: 4,
  textTransform: 'uppercase' as const,
}

const chipStyle: React.CSSProperties = {
  fontSize: 11,
  padding: '2px 8px',
  borderRadius: 999,
  background: 'rgba(99,102,241,0.12)',
  color: '#c4b5fd',
  border: '1px solid rgba(99,102,241,0.32)',
}

const listStyle: React.CSSProperties = {
  margin: 0,
  padding: 0,
  listStyle: 'none',
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
}

const listItem: React.CSSProperties = {
  display: 'flex',
  gap: 8,
  fontSize: 12,
  color: 'var(--text2)',
  lineHeight: 1.45,
}

const bullet: React.CSSProperties = {
  marginTop: 5,
  width: 5,
  height: 5,
  borderRadius: 3,
  background: 'linear-gradient(135deg, #a855f7, #6366f1)',
  flexShrink: 0,
  boxShadow: '0 0 6px rgba(168,85,247,0.4)',
}

const citeStyle: React.CSSProperties = {
  marginLeft: 6,
  fontSize: 10,
  letterSpacing: 0.5,
  color: 'rgba(147,197,253,0.7)',
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
}

const subText: React.CSSProperties = {
  margin: 0,
  fontSize: 12,
  color: 'var(--text2)',
  lineHeight: 1.45,
  whiteSpace: 'pre-wrap',
}

const rawBox: React.CSSProperties = {
  background: 'rgba(0,0,0,0.3)',
  border: '1px solid rgba(99,102,241,0.18)',
  borderRadius: 6,
  padding: 10,
  fontSize: 11,
  whiteSpace: 'pre-wrap',
  maxHeight: 240,
  overflow: 'auto',
}

const historyToggle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  width: '100%',
  background: 'transparent',
  border: 'none',
  color: 'rgba(196,181,253,0.85)',
  fontSize: 12,
  letterSpacing: 1,
  cursor: 'pointer',
  padding: 0,
}

const historyList: React.CSSProperties = {
  margin: 0,
  padding: 0,
  listStyle: 'none',
  display: 'flex',
  flexDirection: 'column',
  borderLeft: '1px solid rgba(99,102,241,0.2)',
  paddingLeft: 12,
  gap: 8,
}

const historyItem: React.CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  gap: 10,
  position: 'relative',
}

const historyDot: React.CSSProperties = {
  position: 'absolute',
  left: -16,
  top: 6,
  width: 6,
  height: 6,
  borderRadius: 3,
  background: '#6366f1',
  boxShadow: '0 0 6px rgba(99,102,241,0.7)',
}

const historyTitle: React.CSSProperties = {
  fontSize: 12,
  color: 'var(--text)',
  lineHeight: 1.4,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
}

const historyTime: React.CSSProperties = {
  fontSize: 10,
  color: 'var(--text2)',
  marginTop: 2,
  letterSpacing: 0.5,
}

const footerRow: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 8,
  marginTop: 10,
  paddingTop: 8,
  borderTop: '1px solid rgba(99,102,241,0.12)',
  flexShrink: 0,
}

const generateBtn = (loading: boolean): React.CSSProperties => ({
  appearance: 'none',
  border: '1px solid rgba(99,102,241,0.35)',
  background:
    'linear-gradient(135deg, rgba(99,102,241,0.18), rgba(168,85,247,0.12))',
  color: '#c4b5fd',
  fontSize: 12,
  letterSpacing: 1,
  padding: '6px 12px',
  borderRadius: 6,
  cursor: loading ? 'wait' : 'pointer',
  opacity: loading ? 0.6 : 1,
})

const emptyWrap: React.CSSProperties = {
  textAlign: 'center',
  padding: '36px 12px 28px',
  color: 'var(--text2)',
}

const emptyOrb: React.CSSProperties = {
  width: 76,
  height: 76,
  margin: '0 auto 14px',
  borderRadius: '50%',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  background:
    'radial-gradient(circle at 30% 30%, rgba(168,85,247,0.35), rgba(99,102,241,0.05) 70%)',
  border: '1px solid rgba(168,85,247,0.3)',
  boxShadow:
    'inset 0 0 24px rgba(168,85,247,0.18), 0 0 30px rgba(99,102,241,0.18)',
}

const emptyTitle: React.CSSProperties = {
  fontSize: 13,
  color: 'var(--text)',
  marginBottom: 6,
  letterSpacing: 1,
}

const emptySub: React.CSSProperties = {
  fontSize: 11,
  color: 'var(--text2)',
  lineHeight: 1.7,
  opacity: 0.8,
}
