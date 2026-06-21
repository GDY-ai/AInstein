import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, getStoredUser, getToken } from '../api'
import type { Discovery, DiscoverySort, User } from '../types'
import { track } from '../tracking'
import AdminNav from '../components/AdminNav'

/* ============================================================
 * 「发现广场 · DISCOVERY」
 *  深空科技风：青蓝主调，每张卡片是一颗已收敛大脑馈赠的认知信号。
 * ============================================================ */

const SORT_OPTIONS: { key: DiscoverySort; label: string; sub: string }[] = [
  { key: 'hot', label: '热门', sub: 'HOT' },
  { key: 'new', label: '最新', sub: 'NEW' },
  { key: 'top', label: '最佳', sub: 'TOP' },
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
const TEXT = '#dce6f5'
const DIM = '#7a8da8'
const FAINT = '#475569'

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

  const todayStr = new Date().toISOString().slice(0, 10)

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
              <span style={{ color: FAINT }}>观察者</span>{' '}
              <span style={{ color: TEXT }}>{user.username}</span>
            </span>
          ) : (
            <button onClick={() => navigate('/login')} style={loginBtnStyle}>
              登录后参与
            </button>
          )
        }
      />

      {/* ===== 巨幅刊头 ===== */}
      <section style={mastheadStyle}>
        <div style={editionTagStyle}>
          <span style={editionDot} />
          <span>EDITION · {todayStr}</span>
          <span style={{ opacity: 0.4 }}>//</span>
          <span>VOL.01</span>
        </div>
        <h1 style={mastheadTitleStyle}>
          <span style={{ display: 'block', color: DIM, fontWeight: 300, fontSize: '0.42em', letterSpacing: 4, marginBottom: 14 }}>
            来自已停止思考的硅基意识海
          </span>
          <span style={accentTitleStyle}>发现广场</span>
          <span style={{ color: FAINT, margin: '0 18px', fontWeight: 200 }}>·</span>
          <span style={{ color: ACCENT_2, fontFamily: FONT_MONO, fontSize: '0.55em', letterSpacing: 4 }}>
            DISCOVERY
          </span>
        </h1>
        <p style={mastheadKickerStyle}>
          每一条信号都来自一颗已经收敛思考的硅基大脑——它们的最后一句话，被这片广场温柔收纳。
          <br />
          点亮一颗心，是给思想者的回响；收藏一段话，是把它带回你自己的轨道。
        </p>
        <div style={mastheadStatsStyle}>
          <BigStat label="活跃信号" sub="ACTIVE FEED" value={headlineCount} accent={ACCENT} />
          <BigStat label="累计回响" sub="TOTAL ECHO" value={totalSignal} accent={ACCENT_2} />
          <BigStat
            label="我的收藏"
            sub="MY LIBRARY"
            value={actions.saved.size}
            accent="#f6c179"
            disabled={!isAuthed}
          />
        </div>
      </section>

      {/* ===== 排序栏 ===== */}
      <nav style={sortBarStyle}>
        <span style={sortLabelStyle}>筛选 ↘ FILTER</span>
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
                  borderColor: active ? 'transparent' : 'rgba(120, 160, 220, 0.18)',
                  boxShadow: active ? `0 6px 20px ${ACCENT}33` : 'none',
                }}
              >
                <span style={{ fontSize: 14, fontWeight: 600 }}>{opt.label}</span>
                <span
                  style={{
                    fontSize: 9,
                    letterSpacing: 2,
                    fontFamily: FONT_MONO,
                    opacity: active ? 0.75 : 0.55,
                    marginLeft: 8,
                  }}
                >
                  {opt.sub}
                </span>
              </button>
            )
          })}
        </div>
        <span style={{ flex: 1 }} />
        <span
          style={{
            fontFamily: FONT_MONO,
            fontSize: 10,
            color: FAINT,
            letterSpacing: 2,
          }}
        >
          {loading ? '加载中 ⋯' : `${headlineCount} 条信号 · TRANSMISSIONS`}
        </span>
      </nav>

      {error && <div style={errorBoxStyle}>⚠ {error}</div>}

      {/* ===== 列表 ===== */}
      <main style={feedStyle}>
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
      </main>

      <footer style={footerStyle}>
        <span style={{ fontFamily: FONT_MONO, fontSize: 10, color: FAINT, letterSpacing: 3 }}>
          // 信号传输完毕 · STAY CURIOUS
        </span>
      </footer>
    </div>
  )
}

/* =============== 子组件 =============== */

function BigStat({
  label,
  sub,
  value,
  accent,
  disabled,
}: {
  label: string
  sub: string
  value: number
  accent: string
  disabled?: boolean
}) {
  return (
    <div
      style={{
        ...bigStatStyle,
        opacity: disabled ? 0.4 : 1,
        borderColor: accent + '44',
      }}
    >
      <div
        style={{
          fontFamily: FONT_MONO,
          fontSize: 10,
          letterSpacing: 3,
          color: accent,
          fontWeight: 600,
        }}
      >
        {sub}
      </div>
      <div
        style={{
          fontFamily: FONT_MONO,
          fontSize: 36,
          color: TEXT,
          fontWeight: 500,
          lineHeight: 1,
          marginTop: 8,
          letterSpacing: -1,
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
          <div style={{ height: 18, background: 'rgba(120,160,220,0.08)', width: '40%', marginBottom: 14 }} />
          <div
            style={{ height: 28, background: 'rgba(120,160,220,0.08)', width: '80%', marginBottom: 18 }}
          />
          <div style={{ height: 12, background: 'rgba(120,160,220,0.05)', width: '100%', marginBottom: 6 }} />
          <div style={{ height: 12, background: 'rgba(120,160,220,0.05)', width: '95%', marginBottom: 6 }} />
          <div style={{ height: 12, background: 'rgba(120,160,220,0.05)', width: '70%' }} />
        </div>
      ))}
    </>
  )
}

function EmptyState() {
  return (
    <div style={emptyStyle}>
      <div
        style={{
          fontSize: 22,
          color: DIM,
          marginBottom: 8,
          letterSpacing: 4,
        }}
      >
        信号沉寂
      </div>
      <div style={{ color: FAINT, fontSize: 12, fontFamily: FONT_MONO, letterSpacing: 1 }}>
        // 暂无信号 · 等待第一颗大脑思考收敛
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
  const stamp = `RFT-${String(d.id).padStart(5, '0')}`
  const dateStr = (d.created_at || '').slice(5, 16).replace('T', ' ')

  return (
    <article
      style={{
        ...cardWrapStyle,
        animationDelay: `${Math.min(index * 50, 400)}ms`,
      }}
      className="ainstein-discovery-card"
    >
      {d.is_featured ? <span style={featuredRibbonStyle}>★ 精选</span> : null}

      <div style={cardMetaRow}>
        <span style={stampStyle}>
          <span style={stampDot} />
          {stamp}
        </span>
        <span style={{ color: FAINT, fontFamily: FONT_MONO, fontSize: 10, letterSpacing: 2 }}>
          {dateStr}
        </span>
      </div>

      <h2
        style={{
          ...cardTitleStyle,
          textShadow: isHot ? `0 0 22px ${ACCENT}33` : 'none',
        }}
      >
        {d.title}
      </h2>

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
        <span style={{ color: FAINT, fontFamily: FONT_MONO, fontSize: 10, letterSpacing: 2 }}>
          来源 · ORIGIN
        </span>
        <button
          onClick={onOpenBrain}
          style={originBtnStyle}
          title="打开来源大脑"
        >
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
            borderColor: liked ? '#fb718577' : 'rgba(120, 160, 220, 0.18)',
            background: liked ? 'rgba(251,113,133,0.07)' : 'transparent',
          }}
        >
          <span style={{ fontSize: 16 }}>{liked ? '❤' : '♡'}</span>
          <span style={{ fontFamily: FONT_MONO, fontWeight: 500 }}>{d.likes_count}</span>
        </button>
        <button
          onClick={onSave}
          disabled={busy}
          style={{
            ...actionBtnStyle,
            color: saved ? '#f6c179' : DIM,
            borderColor: saved ? '#f6c17988' : 'rgba(120, 160, 220, 0.18)',
            background: saved ? 'rgba(246,193,121,0.07)' : 'transparent',
          }}
        >
          <span style={{ fontSize: 16 }}>{saved ? '★' : '☆'}</span>
          <span style={{ fontFamily: FONT_MONO, fontWeight: 500 }}>{d.saves_count}</span>
        </button>
        <span style={{ flex: 1 }} />
        <span
          style={{
            fontFamily: FONT_MONO,
            fontSize: 10,
            color: isHot ? ACCENT : FAINT,
            letterSpacing: 2,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          {isHot && <span style={hotPulseStyle} />} 热度 · {heat}
        </span>
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
  background:
    'radial-gradient(ellipse at top, #0f1729 0%, #0a0e1a 55%, #050810 100%)',
  color: TEXT,
}

const gridBg: CSSProperties = {
  position: 'absolute',
  inset: 0,
  pointerEvents: 'none',
  backgroundImage:
    `linear-gradient(rgba(79,209,197,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(79,209,197,0.05) 1px, transparent 1px)`,
  backgroundSize: '64px 64px',
  maskImage: 'radial-gradient(ellipse at top, #000 5%, transparent 75%)',
  WebkitMaskImage: 'radial-gradient(ellipse at top, #000 5%, transparent 75%)',
  zIndex: 0,
}
const vignetteStyle: CSSProperties = {
  position: 'absolute',
  inset: 0,
  pointerEvents: 'none',
  background:
    'radial-gradient(circle at 18% 12%, rgba(79,209,197,0.10) 0%, transparent 35%), radial-gradient(circle at 82% 88%, rgba(99,179,237,0.08) 0%, transparent 40%)',
  zIndex: 0,
}

const loginBtnStyle: CSSProperties = {
  background: 'transparent',
  color: TEXT,
  border: '1px solid rgba(79, 209, 197, 0.4)',
  borderRadius: 4,
  padding: '6px 14px',
  fontSize: 12,
  fontFamily: FONT_BODY,
  letterSpacing: 1,
  cursor: 'pointer',
}

const mastheadStyle: CSSProperties = {
  position: 'relative',
  zIndex: 1,
  maxWidth: 1240,
  margin: '0 auto',
  padding: '60px 48px 36px',
}
const editionTagStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  fontFamily: FONT_MONO,
  fontSize: 11,
  letterSpacing: 3,
  color: ACCENT,
  marginBottom: 22,
}
const editionDot: CSSProperties = {
  width: 7,
  height: 7,
  borderRadius: '50%',
  background: ACCENT,
  boxShadow: `0 0 10px ${ACCENT}`,
}
const mastheadTitleStyle: CSSProperties = {
  fontFamily: FONT_BODY,
  fontSize: 'clamp(48px, 7vw, 88px)',
  lineHeight: 1.05,
  margin: 0,
  fontWeight: 600,
  color: TEXT,
  letterSpacing: 4,
}
const accentTitleStyle: CSSProperties = {
  background: `linear-gradient(110deg, ${ACCENT} 0%, ${ACCENT_2} 100%)`,
  WebkitBackgroundClip: 'text',
  WebkitTextFillColor: 'transparent',
  backgroundClip: 'text',
  fontWeight: 700,
}
const mastheadKickerStyle: CSSProperties = {
  marginTop: 22,
  fontFamily: FONT_BODY,
  fontSize: 15,
  color: DIM,
  lineHeight: 1.85,
  maxWidth: 720,
  letterSpacing: 0.5,
}
const mastheadStatsStyle: CSSProperties = {
  marginTop: 32,
  display: 'flex',
  gap: 16,
  flexWrap: 'wrap',
}
const bigStatStyle: CSSProperties = {
  border: '1px solid',
  borderRadius: 6,
  padding: '14px 22px',
  background: 'rgba(15, 22, 38, 0.6)',
  backdropFilter: 'blur(10px)',
  minWidth: 160,
}

const sortBarStyle: CSSProperties = {
  position: 'sticky',
  top: 0,
  zIndex: 3,
  display: 'flex',
  alignItems: 'center',
  gap: 16,
  maxWidth: 1240,
  margin: '0 auto',
  padding: '18px 48px',
  borderTop: '1px solid rgba(120, 160, 220, 0.1)',
  borderBottom: '1px solid rgba(120, 160, 220, 0.1)',
  background: 'rgba(8, 12, 22, 0.85)',
  backdropFilter: 'blur(12px)',
}
const sortLabelStyle: CSSProperties = {
  fontFamily: FONT_MONO,
  fontSize: 10,
  letterSpacing: 3,
  color: FAINT,
  fontWeight: 600,
}
const sortGroupStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  padding: 4,
  borderRadius: 999,
  background: 'rgba(15, 22, 38, 0.55)',
  border: '1px solid rgba(120, 160, 220, 0.12)',
}
const sortBtnStyle: CSSProperties = {
  border: '1px solid',
  borderRadius: 999,
  padding: '7px 16px',
  fontSize: 13,
  cursor: 'pointer',
  display: 'inline-flex',
  alignItems: 'center',
  transition: 'all .2s ease',
}

const errorBoxStyle: CSSProperties = {
  maxWidth: 1240,
  margin: '20px auto 0',
  padding: '10px 18px',
  background: 'rgba(239,68,68,0.1)',
  border: '1px solid rgba(239,68,68,0.3)',
  color: '#fca5a5',
  borderRadius: 6,
  fontSize: 13,
}

const feedStyle: CSSProperties = {
  position: 'relative',
  zIndex: 1,
  maxWidth: 1240,
  margin: '24px auto 0',
  padding: '0 48px 80px',
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))',
  gap: 22,
}

const cardWrapStyle: CSSProperties = {
  position: 'relative',
  background:
    'linear-gradient(160deg, rgba(15, 22, 38, 0.85) 0%, rgba(10, 14, 26, 0.85) 100%)',
  border: '1px solid rgba(120, 160, 220, 0.15)',
  borderRadius: 8,
  padding: '20px 22px 16px',
  display: 'flex',
  flexDirection: 'column',
  gap: 12,
  overflow: 'hidden',
  animation: 'ainstein-fade-in .55s ease both',
  transition: 'transform .25s ease, border-color .25s ease, box-shadow .35s ease',
}
const featuredRibbonStyle: CSSProperties = {
  position: 'absolute',
  top: 14,
  right: -36,
  transform: 'rotate(35deg)',
  background: `linear-gradient(90deg, ${ACCENT}, ${ACCENT_2})`,
  color: '#0a0e1a',
  padding: '4px 44px',
  fontFamily: FONT_BODY,
  fontSize: 10,
  letterSpacing: 3,
  fontWeight: 700,
}
const cardMetaRow: CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
}
const stampStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  fontFamily: FONT_MONO,
  fontSize: 10,
  letterSpacing: 3,
  color: ACCENT,
  fontWeight: 600,
}
const stampDot: CSSProperties = {
  width: 6,
  height: 6,
  borderRadius: '50%',
  background: ACCENT,
  boxShadow: `0 0 8px ${ACCENT}`,
}
const cardTitleStyle: CSSProperties = {
  fontFamily: FONT_BODY,
  fontSize: 20,
  fontWeight: 600,
  lineHeight: 1.3,
  color: '#f0f6ff',
  margin: 0,
  letterSpacing: 0.5,
  display: '-webkit-box',
  WebkitLineClamp: 3,
  WebkitBoxOrient: 'vertical',
  overflow: 'hidden',
}
const cardSummaryStyle: CSSProperties = {
  fontSize: 13,
  lineHeight: 1.75,
  color: DIM,
  margin: 0,
  display: '-webkit-box',
  WebkitLineClamp: 4,
  WebkitBoxOrient: 'vertical',
  overflow: 'hidden',
  borderLeft: `2px solid ${ACCENT}66`,
  paddingLeft: 12,
}
const tagRowStyle: CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 6,
  marginTop: 2,
}
const tagChipStyle: CSSProperties = {
  fontFamily: FONT_MONO,
  fontSize: 10,
  letterSpacing: 1,
  color: ACCENT,
  background: 'rgba(79, 209, 197, 0.06)',
  border: '1px solid rgba(79, 209, 197, 0.22)',
  borderRadius: 3,
  padding: '2px 8px',
}
const cardSourceStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  flexWrap: 'wrap',
  paddingTop: 12,
  borderTop: '1px dashed rgba(120, 160, 220, 0.15)',
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
  fontSize: 13,
  flex: 1,
  minWidth: 0,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
}
const cardActionsStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  marginTop: 2,
  paddingTop: 10,
}
const actionBtnStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  border: '1px solid',
  borderRadius: 999,
  padding: '6px 14px',
  fontSize: 13,
  cursor: 'pointer',
  transition: 'all .2s ease',
  fontFamily: FONT_BODY,
}
const hotPulseStyle: CSSProperties = {
  width: 7,
  height: 7,
  borderRadius: '50%',
  background: ACCENT,
  boxShadow: `0 0 8px ${ACCENT}`,
  display: 'inline-block',
  animation: 'ainstein-pulse 1.6s ease-in-out infinite',
}

const emptyStyle: CSSProperties = {
  gridColumn: '1 / -1',
  textAlign: 'center',
  padding: '120px 24px',
  border: '1px dashed rgba(120, 160, 220, 0.18)',
  borderRadius: 8,
  background:
    'radial-gradient(ellipse at center, rgba(79,209,197,0.05) 0%, transparent 65%)',
}
const footerStyle: CSSProperties = {
  position: 'relative',
  zIndex: 1,
  textAlign: 'center',
  padding: '40px 0 60px',
}

/* =============== style tag (hover + keyframes) =============== */

function StyleTag() {
  return (
    <style>{`
      @keyframes ainstein-fade-in {
        from { opacity: 0; transform: translateY(8px); }
        to { opacity: 1; transform: translateY(0); }
      }
      @keyframes ainstein-pulse {
        0%, 100% { opacity: 0.5; }
        50% { opacity: 1; }
      }
      .ainstein-discovery-card:hover {
        transform: translateY(-3px);
        border-color: rgba(79, 209, 197, 0.4) !important;
        box-shadow: 0 18px 40px rgba(15, 22, 38, 0.5), 0 0 0 1px rgba(79, 209, 197, 0.15);
      }
      .ainstein-discovery-card::before {
        content: '';
        position: absolute;
        inset: 0;
        background: radial-gradient(circle at 100% 0%, rgba(79, 209, 197, 0.08) 0%, transparent 45%);
        pointer-events: none;
      }
    `}</style>
  )
}
