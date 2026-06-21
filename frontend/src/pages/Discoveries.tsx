import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, getStoredUser, getToken } from '../api'
import type { Discovery, DiscoverySort, User } from '../types'
import { track } from '../tracking'
import AdminNav from '../components/AdminNav'

/* ============================================================
 * 「发现广场」
 *  统一深空风：青蓝主调 + 320px 卡片 + 18px 间距
 * ============================================================ */

const SORT_OPTIONS: { key: DiscoverySort; label: string }[] = [
  { key: 'hot', label: '热门' },
  { key: 'new', label: '最新' },
  { key: 'top', label: '最佳' },
]

interface ActionMap {
  liked: Set<number>
  saved: Set<number>
}

const FONT_INJECT_ID = 'ainstein-discoveries-fonts'

function injectFonts() {
  if (typeof document === 'undefined') return
  if (document.getElementById(FONT_INJECT_ID)) return
  const link = document.createElement('link')
  link.id = FONT_INJECT_ID
  link.rel = 'stylesheet'
  link.href =
    'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&display=swap'
  document.head.appendChild(link)
}

const FONT_BODY =
  '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif'
const FONT_MONO = '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace'

const ACCENT = '#4fd1c5'
const ACCENT_2 = '#63b3ed'
const AMBER = '#f6c179'
const TEXT = '#dce6f5'
const DIM = '#7a8da8'
const FAINT = '#475569'
const BORDER = 'rgba(120, 160, 220, 0.15)'
const BORDER_HOT = 'rgba(79, 209, 197, 0.30)'

export default function Discoveries() {
  const navigate = useNavigate()
  const [user, setUser] = useState<User | null>(getStoredUser())
  const [items, setItems] = useState<Discovery[]>([])
  const [sort, setSort] = useState<DiscoverySort>('hot')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState<number | null>(null)
  const [actions, setActions] = useState<ActionMap>({ liked: new Set(), saved: new Set() })

  const isAuthed = Boolean(getToken())

  useEffect(() => {
    injectFonts()
    track('page.view', { page: 'discoveries' })
    if (isAuthed) {
      api.me().then((r) => setUser(r.user)).catch(() => undefined)
      loadActions()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    load(sort)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sort])

  async function load(s: DiscoverySort) {
    setLoading(true)
    setError('')
    try {
      const r = await api.listDiscoveries(s, 60, 0)
      setItems(r.items || [])
    } catch (e: any) {
      setError(e?.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  async function loadActions() {
    try {
      const r = await api.myDiscoveryActions()
      const liked = new Set<number>()
      const saved = new Set<number>()
      for (const a of r.actions || []) {
        if (a.action_type === 'like') liked.add(a.discovery_id)
        else if (a.action_type === 'save') saved.add(a.discovery_id)
      }
      setActions({ liked, saved })
    } catch {
      /* ignore */
    }
  }

  async function handleLike(d: Discovery) {
    if (!isAuthed) {
      navigate('/login')
      return
    }
    setBusyId(d.id)
    try {
      const r = await api.likeDiscovery(d.id)
      setActions((prev) => {
        const next = new Set(prev.liked)
        if (r.liked) next.add(d.id)
        else next.delete(d.id)
        return { ...prev, liked: next }
      })
      setItems((prev) =>
        prev.map((it) =>
          it.id === d.id ? { ...it, likes_count: it.likes_count + (r.liked ? 1 : -1) } : it
        )
      )
    } catch (e: any) {
      setError(e?.message || '操作失败')
    } finally {
      setBusyId(null)
    }
  }

  async function handleSave(d: Discovery) {
    if (!isAuthed) {
      navigate('/login')
      return
    }
    setBusyId(d.id)
    try {
      const r = await api.saveDiscovery(d.id)
      setActions((prev) => {
        const next = new Set(prev.saved)
        if (r.saved) next.add(d.id)
        else next.delete(d.id)
        return { ...prev, saved: next }
      })
      setItems((prev) =>
        prev.map((it) =>
          it.id === d.id ? { ...it, saves_count: it.saves_count + (r.saved ? 1 : -1) } : it
        )
      )
    } catch (e: any) {
      setError(e?.message || '操作失败')
    } finally {
      setBusyId(null)
    }
  }

  const headlineCount = items.length
  const totalSignal = useMemo(
    () => items.reduce((acc, it) => acc + it.likes_count + it.saves_count, 0),
    [items]
  )

  return (
    <div style={pageStyle}>
      <StyleTag />
      <div style={gridBg} />
      <div style={vignetteStyle} />

      <AdminNav
        active="discoveries"
        rightSlot={
          user ? (
            <span style={{ letterSpacing: 1 }}>
              <span style={{ color: FAINT }}>观察员 </span>
              <span style={{ color: TEXT }}>{user.username}</span>
            </span>
          ) : (
            <button onClick={() => navigate('/login')} style={loginBtnStyle}>
              登录后参与
            </button>
          )
        }
      />

      <main style={contentStyle}>
        {/* 页面标题区 */}
        <header style={heroStyle}>
          <div style={{ flex: 1, minWidth: 280 }}>
            <h1 style={heroTitleStyle}>发现广场</h1>
            <p style={heroSubStyle}>
              每一条信号都来自一颗已经收敛思考的硅基大脑——它们的最后一句话，被这片广场温柔收纳。
            </p>
          </div>
          <div style={statsRowStyle}>
            <Stat label="活跃信号" value={headlineCount} accent={ACCENT} />
            <Stat label="累计回响" value={totalSignal} accent={ACCENT_2} />
            <Stat
              label="我的收藏"
              value={actions.saved.size}
              accent={AMBER}
              disabled={!isAuthed}
            />
          </div>
        </header>

        {/* 排序栏 */}
        <div style={sortBarStyle}>
          <span style={{ color: FAINT, fontSize: 11, fontFamily: FONT_MONO, letterSpacing: 1.5 }}>
            筛选
          </span>
          <div style={sortGroupStyle}>
            {SORT_OPTIONS.map((opt) => {
              const active = sort === opt.key
              return (
                <button
                  key={opt.key}
                  onClick={() => setSort(opt.key)}
                  style={{
                    ...sortBtnStyle,
                    color: active ? '#0a0e1a' : DIM,
                    background: active
                      ? `linear-gradient(120deg, ${ACCENT} 0%, ${ACCENT_2} 100%)`
                      : 'transparent',
                    borderColor: active ? 'transparent' : BORDER,
                    fontWeight: active ? 700 : 500,
                  }}
                >
                  {opt.label}
                </button>
              )
            })}
          </div>
          <span style={{ flex: 1 }} />
          <span style={{ color: FAINT, fontSize: 11, fontFamily: FONT_MONO, letterSpacing: 1.5 }}>
            {loading ? '加载中…' : `共 ${headlineCount} 条`}
          </span>
        </div>

        {error && <div style={errorBoxStyle}>⚠ {error}</div>}

        {/* 列表 */}
        <div style={feedStyle}>
          {loading ? (
            <SkeletonList />
          ) : items.length === 0 ? (
            <EmptyState />
          ) : (
            items.map((d, idx) => (
              <DiscoveryCard
                key={d.id}
                d={d}
                index={idx}
                liked={actions.liked.has(d.id)}
                saved={actions.saved.has(d.id)}
                busy={busyId === d.id}
                onLike={() => handleLike(d)}
                onSave={() => handleSave(d)}
                onOpenBrain={() => navigate(`/brain/${d.brain_id}`)}
              />
            ))
          )}
        </div>
      </main>
    </div>
  )
}

/* =============== 子组件 =============== */

function Stat({
  label,
  value,
  accent,
  disabled,
}: {
  label: string
  value: number
  accent: string
  disabled?: boolean
}) {
  return (
    <div style={{ ...statStyle, opacity: disabled ? 0.45 : 1, borderColor: accent + '40' }}>
      <div
        style={{
          fontFamily: FONT_MONO,
          fontSize: 24,
          color: TEXT,
          fontWeight: 500,
          lineHeight: 1,
          letterSpacing: -0.5,
          textShadow: `0 0 18px ${accent}33`,
        }}
      >
        {value.toLocaleString()}
      </div>
      <div style={{ fontSize: 11, color: DIM, marginTop: 6, letterSpacing: 1 }}>{label}</div>
    </div>
  )
}

function SkeletonList() {
  return (
    <>
      {[0, 1, 2, 3].map((i) => (
        <div key={i} style={{ ...cardWrapStyle, opacity: 0.5 }}>
          <div style={{ height: 14, background: 'rgba(120,160,220,0.08)', width: '40%', marginBottom: 14 }} />
          <div style={{ height: 24, background: 'rgba(120,160,220,0.08)', width: '85%', marginBottom: 14 }} />
          <div style={{ height: 12, background: 'rgba(120,160,220,0.05)', width: '100%', marginBottom: 6 }} />
          <div style={{ height: 12, background: 'rgba(120,160,220,0.05)', width: '70%' }} />
        </div>
      ))}
    </>
  )
}

function EmptyState() {
  return (
    <div style={emptyStyle}>
      <div style={{ fontSize: 16, color: DIM, marginBottom: 6, letterSpacing: 2 }}>
        信号沉寂
      </div>
      <div style={{ color: FAINT, fontSize: 12, letterSpacing: 1 }}>
        暂无信号，等待第一颗大脑思考收敛…
      </div>
    </div>
  )
}

function DiscoveryCard({
  d,
  index,
  liked,
  saved,
  busy,
  onLike,
  onSave,
  onOpenBrain,
}: {
  d: Discovery
  index: number
  liked: boolean
  saved: boolean
  busy: boolean
  onLike: () => void
  onSave: () => void
  onOpenBrain: () => void
}) {
  const tags = useMemo(() => parseTags(d.domain_tags), [d.domain_tags])
  const heat = d.likes_count + d.saves_count
  const isHot = heat >= 5
  const dateStr = (d.created_at || '').slice(0, 10)

  return (
    <article
      style={{
        ...cardWrapStyle,
        animationDelay: `${Math.min(index * 40, 320)}ms`,
      }}
      className="ainstein-discovery-card"
    >
      {d.is_featured ? <span style={featuredRibbonStyle}>★ 精选</span> : null}

      <div style={cardMetaRow}>
        <span style={dateStyle}>{dateStr}</span>
        {isHot && (
          <span style={hotPillStyle}>
            <span style={hotPulseStyle} /> 热度 {heat}
          </span>
        )}
      </div>

      <h2 style={cardTitleStyle}>{d.title}</h2>

      {d.summary ? (
        <p style={cardSummaryStyle}>{d.summary}</p>
      ) : (
        <p style={{ ...cardSummaryStyle, opacity: 0.4, fontStyle: 'italic' }}>
          ——（无补充注脚）
        </p>
      )}

      {tags.length > 0 && (
        <div style={tagRowStyle}>
          {tags.slice(0, 5).map((t) => (
            <span key={t} style={tagChipStyle}>
              #{t}
            </span>
          ))}
        </div>
      )}

      <div style={cardSourceStyle}>
        <span style={{ color: FAINT, fontSize: 11, letterSpacing: 1 }}>来自</span>
        <button onClick={onOpenBrain} style={originBtnStyle} title="打开来源大脑">
          🧠 {d.brain_name || `大脑 #${d.brain_id}`}
        </button>
        {d.seed_question && (
          <span style={seedSnippetStyle} title={d.seed_question}>
            「{d.seed_question}」
          </span>
        )}
      </div>

      <div style={cardActionsStyle}>
        <button
          onClick={onLike}
          disabled={busy}
          style={{
            ...actionBtnStyle,
            color: liked ? '#fb7185' : DIM,
            borderColor: liked ? '#fb718577' : BORDER,
            background: liked ? 'rgba(251,113,133,0.07)' : 'transparent',
          }}
        >
          <span style={{ fontSize: 14 }}>{liked ? '❤' : '♡'}</span>
          <span style={{ fontFamily: FONT_MONO, fontWeight: 500 }}>{d.likes_count}</span>
        </button>
        <button
          onClick={onSave}
          disabled={busy}
          style={{
            ...actionBtnStyle,
            color: saved ? AMBER : DIM,
            borderColor: saved ? AMBER + '88' : BORDER,
            background: saved ? 'rgba(246,193,121,0.07)' : 'transparent',
          }}
        >
          <span style={{ fontSize: 14 }}>{saved ? '★' : '☆'}</span>
          <span style={{ fontFamily: FONT_MONO, fontWeight: 500 }}>{d.saves_count}</span>
        </button>
      </div>
    </article>
  )
}

/* =============== utils =============== */

function parseTags(raw: string | null | undefined): string[] {
  if (!raw) return []
  const s = String(raw).trim()
  if (!s) return []
  if (s.startsWith('[')) {
    try {
      const arr = JSON.parse(s)
      if (Array.isArray(arr)) return arr.map((x) => String(x)).filter(Boolean)
    } catch {
      /* fallthrough */
    }
  }
  return s
    .split(/[,，;；]/)
    .map((x) => x.trim())
    .filter(Boolean)
}

/* =============== styles =============== */

const pageStyle: CSSProperties = {
  minHeight: '100vh',
  position: 'relative',
  overflow: 'hidden',
  fontFamily: FONT_BODY,
  background: 'radial-gradient(ellipse at top, #0f1729 0%, #0a0e1a 55%, #05070f 100%)',
  color: TEXT,
}

const gridBg: CSSProperties = {
  position: 'fixed',
  inset: 0,
  pointerEvents: 'none',
  backgroundImage:
    `linear-gradient(rgba(79,209,197,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(79,209,197,0.04) 1px, transparent 1px)`,
  backgroundSize: '64px 64px',
  maskImage: 'radial-gradient(ellipse at top, #000 5%, transparent 75%)',
  WebkitMaskImage: 'radial-gradient(ellipse at top, #000 5%, transparent 75%)',
  zIndex: 0,
}
const vignetteStyle: CSSProperties = {
  position: 'fixed',
  inset: 0,
  pointerEvents: 'none',
  background:
    'radial-gradient(circle at 18% 12%, rgba(79,209,197,0.05) 0%, transparent 40%), radial-gradient(circle at 82% 88%, rgba(99,179,237,0.04) 0%, transparent 45%)',
  zIndex: 0,
}

const loginBtnStyle: CSSProperties = {
  background: 'transparent',
  color: TEXT,
  border: `1px solid ${BORDER_HOT}`,
  borderRadius: 4,
  padding: '5px 12px',
  fontSize: 12,
  fontFamily: FONT_BODY,
  letterSpacing: 1,
  cursor: 'pointer',
}

const contentStyle: CSSProperties = {
  position: 'relative',
  zIndex: 1,
  maxWidth: 1280,
  margin: '0 auto',
  padding: '32px 40px 80px',
}

const heroStyle: CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'flex-end',
  gap: 24,
  marginBottom: 28,
  flexWrap: 'wrap',
}
const heroTitleStyle: CSSProperties = {
  fontSize: 38,
  margin: 0,
  fontWeight: 700,
  color: TEXT,
  letterSpacing: 1,
  lineHeight: 1.2,
}
const heroSubStyle: CSSProperties = {
  marginTop: 10,
  color: DIM,
  fontSize: 14,
  lineHeight: 1.7,
  maxWidth: 620,
}
const statsRowStyle: CSSProperties = {
  display: 'flex',
  gap: 12,
  flexWrap: 'wrap',
}
const statStyle: CSSProperties = {
  border: '1px solid',
  borderRadius: 8,
  padding: '12px 18px',
  background: 'rgba(10, 14, 26, 0.65)',
  minWidth: 110,
  backdropFilter: 'blur(8px)',
}

const sortBarStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 14,
  padding: '14px 18px',
  marginBottom: 20,
  background: 'rgba(10, 14, 26, 0.65)',
  border: `1px solid ${BORDER}`,
  borderRadius: 8,
  backdropFilter: 'blur(8px)',
}
const sortGroupStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
}
const sortBtnStyle: CSSProperties = {
  border: '1px solid',
  borderRadius: 999,
  padding: '6px 16px',
  fontSize: 13,
  cursor: 'pointer',
  fontFamily: FONT_BODY,
  letterSpacing: 1,
  transition: 'all .2s ease',
}

const errorBoxStyle: CSSProperties = {
  padding: '10px 14px',
  marginBottom: 16,
  background: 'rgba(251,113,133,0.08)',
  border: '1px solid rgba(251,113,133,0.3)',
  color: '#fb7185',
  borderRadius: 6,
  fontSize: 13,
}

const feedStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
  gap: 18,
}

const cardWrapStyle: CSSProperties = {
  position: 'relative',
  background: 'rgba(10, 14, 26, 0.75)',
  border: `1px solid ${BORDER}`,
  borderRadius: 10,
  padding: 20,
  display: 'flex',
  flexDirection: 'column',
  gap: 10,
  overflow: 'hidden',
  animation: 'ainstein-fade-in .5s ease both',
  transition: 'transform .2s ease, border-color .2s ease, box-shadow .25s ease',
}
const featuredRibbonStyle: CSSProperties = {
  position: 'absolute',
  top: 14,
  right: -36,
  transform: 'rotate(35deg)',
  background: `linear-gradient(90deg, ${ACCENT}, ${ACCENT_2})`,
  color: '#0a0e1a',
  padding: '3px 44px',
  fontSize: 10,
  letterSpacing: 2,
  fontWeight: 700,
  fontFamily: FONT_BODY,
}
const cardMetaRow: CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
}
const dateStyle: CSSProperties = {
  fontFamily: FONT_MONO,
  fontSize: 10,
  letterSpacing: 1.5,
  color: FAINT,
}
const hotPillStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 5,
  fontSize: 10,
  fontFamily: FONT_MONO,
  letterSpacing: 1,
  color: ACCENT,
  background: 'rgba(79, 209, 197, 0.08)',
  border: `1px solid ${BORDER_HOT}`,
  borderRadius: 999,
  padding: '2px 8px',
}
const cardTitleStyle: CSSProperties = {
  fontSize: 17,
  fontWeight: 600,
  lineHeight: 1.4,
  color: TEXT,
  margin: '4px 0 2px',
  letterSpacing: 0.3,
  display: '-webkit-box',
  WebkitLineClamp: 2,
  WebkitBoxOrient: 'vertical',
  overflow: 'hidden',
}
const cardSummaryStyle: CSSProperties = {
  fontSize: 13,
  lineHeight: 1.7,
  color: DIM,
  margin: 0,
  display: '-webkit-box',
  WebkitLineClamp: 3,
  WebkitBoxOrient: 'vertical',
  overflow: 'hidden',
  borderLeft: `2px solid ${ACCENT}66`,
  paddingLeft: 10,
}
const tagRowStyle: CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 5,
  marginTop: 2,
}
const tagChipStyle: CSSProperties = {
  fontFamily: FONT_MONO,
  fontSize: 10,
  letterSpacing: 0.5,
  color: ACCENT,
  background: 'rgba(79, 209, 197, 0.06)',
  border: `1px solid ${BORDER_HOT}`,
  borderRadius: 3,
  padding: '2px 7px',
}
const cardSourceStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  flexWrap: 'wrap',
  paddingTop: 12,
  borderTop: `1px dashed ${BORDER}`,
}
const originBtnStyle: CSSProperties = {
  background: 'transparent',
  border: 'none',
  padding: 0,
  color: TEXT,
  fontSize: 13,
  cursor: 'pointer',
  textDecoration: 'underline',
  textDecorationColor: `${ACCENT}66`,
  textUnderlineOffset: 4,
  fontFamily: FONT_BODY,
}
const seedSnippetStyle: CSSProperties = {
  color: FAINT,
  fontStyle: 'italic',
  fontSize: 12,
  flex: 1,
  minWidth: 0,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
}
const cardActionsStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  marginTop: 4,
}
const actionBtnStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  border: '1px solid',
  borderRadius: 999,
  padding: '5px 12px',
  fontSize: 13,
  cursor: 'pointer',
  transition: 'all .2s ease',
  fontFamily: FONT_BODY,
}
const hotPulseStyle: CSSProperties = {
  width: 6,
  height: 6,
  borderRadius: '50%',
  background: ACCENT,
  boxShadow: `0 0 6px ${ACCENT}`,
  display: 'inline-block',
  animation: 'ainstein-pulse 1.6s ease-in-out infinite',
}

const emptyStyle: CSSProperties = {
  gridColumn: '1 / -1',
  textAlign: 'center',
  padding: '80px 24px',
  border: `1px dashed ${BORDER}`,
  borderRadius: 10,
  background: 'rgba(10, 14, 26, 0.5)',
}

function StyleTag() {
  return (
    <style>{`
      @keyframes ainstein-fade-in {
        from { opacity: 0; transform: translateY(6px); }
        to { opacity: 1; transform: translateY(0); }
      }
      @keyframes ainstein-pulse {
        0%, 100% { opacity: 0.5; }
        50% { opacity: 1; }
      }
      .ainstein-discovery-card:hover {
        transform: translateY(-2px);
        border-color: ${BORDER_HOT} !important;
        box-shadow: 0 12px 32px rgba(0,0,0,0.4), 0 0 0 1px rgba(79,209,197,0.10);
      }
    `}</style>
  )
}
