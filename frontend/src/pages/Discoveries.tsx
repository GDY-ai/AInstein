import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, getStoredUser, getToken } from '../api'
import type { Discovery, DiscoverySort, User } from '../types'
import { track } from '../tracking'

/* ============================================================
 * 「认知裂隙 · COGNITIVE RIFTS」
 *  — 一座由已逝/收敛大脑馈赠的发现广场。
 *  每张卡片是一段从硅基意识海中冒出的"信号残响"。
 * ============================================================ */

const SORT_OPTIONS: { key: DiscoverySort; label: string; sub: string }[] = [
  { key: 'hot', label: '热门', sub: 'HOT · WEIGHTED' },
  { key: 'new', label: '最新', sub: 'NEW · CHRONO' },
  { key: 'top', label: '最佳', sub: 'TOP · LIKED' },
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
    'https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=JetBrains+Mono:wght@300;400;500;700&display=swap'
  document.head.appendChild(link)
}

const FONT_DISPLAY = '"Cormorant Garamond", "Times New Roman", Georgia, serif'
const FONT_MONO = '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace'

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
      <div style={crossLineH} />
      <div style={crossLineV} />

      {/* ===== 顶部条 ===== */}
      <header style={topBarStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <button
            onClick={() => navigate(isAuthed ? '/brains' : '/login')}
            style={crumbBtnStyle}
            title="返回大脑列表"
          >
            ← AINSTEIN
          </button>
          <span style={{ color: '#475569', fontFamily: FONT_MONO, fontSize: 11 }}>
            ／ DISCOVERY · /rifts
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {user ? (
            <span style={pillStyle}>
              <span style={{ color: '#94a3b8' }}>OBSERVER</span>{' '}
              <span style={{ color: '#e2e8f0' }}>{user.username}</span>
            </span>
          ) : (
            <button onClick={() => navigate('/login')} style={crumbBtnStyle}>
              登录后参与
            </button>
          )}
        </div>
      </header>

      {/* ===== 巨幅刊头 ===== */}
      <section style={mastheadStyle}>
        <div style={editionTagStyle}>
          <span style={editionDot} />
          <span>EDITION · {new Date().toISOString().slice(0, 10)}</span>
          <span style={{ opacity: 0.4 }}>//</span>
          <span>VOL.01</span>
        </div>
        <h1 style={mastheadTitleStyle}>
          <span style={{ display: 'block', color: '#cbd5e1', fontWeight: 400, fontStyle: 'italic' }}>
            From the deceased minds of silicon —
          </span>
          <span style={accentTitleStyle}>认知裂隙</span>
          <span style={{ color: '#475569', margin: '0 14px', fontWeight: 300 }}>·</span>
          <span style={{ color: '#a78bfa' }}>Cognitive Rifts</span>
        </h1>
        <p style={mastheadKickerStyle}>
          每一条信号都来自一颗已经停止思考的硅基大脑——它们的最后一句话，被这片广场温柔收纳。
          <br />
          点亮一颗心，是给思想者的回响；收藏一段话，是把它带回你自己的轨道。
        </p>
        <div style={mastheadStatsStyle}>
          <BigStat label="ACTIVE FEED" value={headlineCount} accent="#a78bfa" />
          <BigStat label="TOTAL SIGNAL" value={totalSignal} accent="#22d3ee" />
          <BigStat
            label="MY LIBRARY"
            value={actions.saved.size}
            accent="#ec4899"
            disabled={!isAuthed}
          />
        </div>
      </section>

      {/* ===== 排序栏 ===== */}
      <nav style={sortBarStyle}>
        <span style={sortLabelStyle}>FILTER ↘</span>
        <div style={sortGroupStyle}>
          {SORT_OPTIONS.map((opt) => {
            const active = sort === opt.key
            return (
              <button
                key={opt.key}
                onClick={() => setSort(opt.key)}
                style={{
                  ...sortBtnStyle,
                  color: active ? '#0f1117' : '#cbd5e1',
                  background: active
                    ? 'linear-gradient(120deg, #fde68a 0%, #f0abfc 50%, #a5f3fc 100%)'
                    : 'transparent',
                  borderColor: active ? 'transparent' : 'rgba(148,163,184,0.25)',
                  boxShadow: active ? '0 6px 20px rgba(240,171,252,0.25)' : 'none',
                }}
              >
                <span style={{ fontSize: 14, fontWeight: 700 }}>{opt.label}</span>
                <span
                  style={{
                    fontSize: 9,
                    letterSpacing: 2,
                    fontFamily: FONT_MONO,
                    opacity: active ? 0.7 : 0.55,
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
            color: '#475569',
            letterSpacing: 2,
          }}
        >
          {loading ? 'BUFFERING ⋯' : `${headlineCount} TRANSMISSIONS`}
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
        <span style={{ fontFamily: FONT_MONO, fontSize: 10, color: '#475569', letterSpacing: 3 }}>
          // EOF · TRANSMISSION END · STAY CURIOUS
        </span>
      </footer>
    </div>
  )
}

/* =============== 子组件 =============== */

function BigStat({
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
    <div
      style={{
        ...bigStatStyle,
        opacity: disabled ? 0.4 : 1,
        borderColor: accent + '33',
      }}
    >
      <div
        style={{
          fontFamily: FONT_MONO,
          fontSize: 10,
          letterSpacing: 3,
          color: accent,
          fontWeight: 700,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: FONT_DISPLAY,
          fontSize: 38,
          color: '#f1f5f9',
          fontWeight: 600,
          lineHeight: 1,
          marginTop: 6,
        }}
      >
        {value.toLocaleString()}
      </div>
    </div>
  )
}

function SkeletonList() {
  return (
    <>
      {[0, 1, 2, 3].map((i) => (
        <div key={i} style={{ ...cardWrapStyle, opacity: 0.5 }}>
          <div style={{ height: 18, background: '#1e2230', width: '40%', marginBottom: 14 }} />
          <div
            style={{ height: 32, background: '#1e2230', width: '80%', marginBottom: 18 }}
          />
          <div style={{ height: 12, background: '#1a1d27', width: '100%', marginBottom: 6 }} />
          <div style={{ height: 12, background: '#1a1d27', width: '95%', marginBottom: 6 }} />
          <div style={{ height: 12, background: '#1a1d27', width: '70%' }} />
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
          fontFamily: FONT_DISPLAY,
          fontSize: 28,
          fontStyle: 'italic',
          color: '#94a3b8',
          marginBottom: 6,
        }}
      >
        信号沉寂。
      </div>
      <div style={{ color: '#64748b', fontSize: 13, fontFamily: FONT_MONO, letterSpacing: 1 }}>
        // NO TRANSMISSIONS YET — 等待第一个大脑思考收敛。
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
  // 解析 domain_tags（可能是 JSON 数组 或 逗号串 或 null）
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
      {d.is_featured ? <span style={featuredRibbonStyle}>★ FEATURED</span> : null}

      <div style={cardMetaRow}>
        <span style={stampStyle}>
          <span style={stampDot} />
          {stamp}
        </span>
        <span style={{ color: '#475569', fontFamily: FONT_MONO, fontSize: 10, letterSpacing: 2 }}>
          {dateStr}
        </span>
      </div>

      <h2
        style={{
          ...cardTitleStyle,
          textShadow: isHot ? '0 0 22px rgba(167,139,250,0.18)' : 'none',
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

      {/* tags */}
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
        <span style={{ color: '#64748b', fontFamily: FONT_MONO, fontSize: 10, letterSpacing: 2 }}>
          ORIGIN ·
        </span>
        <button
          onClick={onOpenBrain}
          style={originBtnStyle}
          title="打开来源大脑"
        >
          🧠 {d.brain_name || `Brain #${d.brain_id}`}
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
            color: liked ? '#fb7185' : '#94a3b8',
            borderColor: liked ? '#fb718577' : 'rgba(148,163,184,0.18)',
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
            color: saved ? '#fde68a' : '#94a3b8',
            borderColor: saved ? '#fde68a88' : 'rgba(148,163,184,0.18)',
            background: saved ? 'rgba(253,230,138,0.07)' : 'transparent',
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
            color: isHot ? '#a78bfa' : '#475569',
            letterSpacing: 2,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          {isHot && <span style={hotPulseStyle} />} HEAT · {heat}
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
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  background:
    'radial-gradient(ellipse at top, #15172a 0%, #0a0c14 55%, #050608 100%)',
  color: '#e4e6ed',
}

const gridBg: CSSProperties = {
  position: 'absolute',
  inset: 0,
  pointerEvents: 'none',
  backgroundImage:
    'linear-gradient(rgba(167,139,250,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(167,139,250,0.05) 1px, transparent 1px)',
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
    'radial-gradient(circle at 18% 12%, rgba(167,139,250,0.18) 0%, transparent 35%), radial-gradient(circle at 82% 88%, rgba(34,211,238,0.10) 0%, transparent 40%), radial-gradient(circle at 50% 60%, rgba(236,72,153,0.06) 0%, transparent 45%)',
  zIndex: 0,
}
const crossLineH: CSSProperties = {
  position: 'absolute',
  left: 0,
  right: 0,
  top: 96,
  height: 1,
  background: 'linear-gradient(90deg, transparent, rgba(167,139,250,0.25) 18%, rgba(167,139,250,0.25) 82%, transparent)',
  zIndex: 0,
  pointerEvents: 'none',
}
const crossLineV: CSSProperties = {
  position: 'absolute',
  top: 0,
  bottom: 0,
  left: '50%',
  width: 1,
  background:
    'linear-gradient(180deg, transparent, rgba(148,163,184,0.05) 30%, rgba(148,163,184,0.05) 70%, transparent)',
  zIndex: 0,
  pointerEvents: 'none',
}

const topBarStyle: CSSProperties = {
  position: 'relative',
  zIndex: 2,
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  padding: '20px 48px',
  borderBottom: '1px solid rgba(148,163,184,0.08)',
  background: 'rgba(10,12,20,0.5)',
  backdropFilter: 'blur(10px)',
}
const crumbBtnStyle: CSSProperties = {
  background: 'transparent',
  color: '#cbd5e1',
  border: '1px solid rgba(148,163,184,0.18)',
  borderRadius: 6,
  padding: '6px 14px',
  fontSize: 12,
  fontFamily: FONT_MONO,
  letterSpacing: 2,
  cursor: 'pointer',
}
const pillStyle: CSSProperties = {
  fontSize: 12,
  fontFamily: FONT_MONO,
  letterSpacing: 1,
  padding: '6px 12px',
  background: 'rgba(20,22,34,0.7)',
  border: '1px solid rgba(148,163,184,0.18)',
  borderRadius: 999,
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
  color: '#a78bfa',
  marginBottom: 22,
}
const editionDot: CSSProperties = {
  width: 7,
  height: 7,
  borderRadius: '50%',
  background: '#a78bfa',
  boxShadow: '0 0 10px #a78bfa',
}
const mastheadTitleStyle: CSSProperties = {
  fontFamily: FONT_DISPLAY,
  fontSize: 'clamp(48px, 7vw, 96px)',
  lineHeight: 0.95,
  margin: 0,
  fontWeight: 600,
  color: '#f1f5f9',
  letterSpacing: -1,
}
const accentTitleStyle: CSSProperties = {
  background: 'linear-gradient(110deg, #fde68a 0%, #f0abfc 45%, #a5f3fc 100%)',
  WebkitBackgroundClip: 'text',
  WebkitTextFillColor: 'transparent',
  backgroundClip: 'text',
  fontStyle: 'italic',
  fontWeight: 700,
}
const mastheadKickerStyle: CSSProperties = {
  marginTop: 22,
  fontFamily: FONT_DISPLAY,
  fontStyle: 'italic',
  fontSize: 18,
  color: '#94a3b8',
  lineHeight: 1.7,
  maxWidth: 720,
}
const mastheadStatsStyle: CSSProperties = {
  marginTop: 32,
  display: 'flex',
  gap: 16,
  flexWrap: 'wrap',
}
const bigStatStyle: CSSProperties = {
  border: '1px solid',
  borderRadius: 10,
  padding: '14px 22px',
  background: 'rgba(15,17,30,0.65)',
  backdropFilter: 'blur(8px)',
  minWidth: 150,
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
  borderTop: '1px solid rgba(148,163,184,0.08)',
  borderBottom: '1px solid rgba(148,163,184,0.08)',
  background: 'rgba(8,10,18,0.85)',
  backdropFilter: 'blur(12px)',
}
const sortLabelStyle: CSSProperties = {
  fontFamily: FONT_MONO,
  fontSize: 10,
  letterSpacing: 3,
  color: '#64748b',
  fontWeight: 700,
}
const sortGroupStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  padding: 4,
  borderRadius: 999,
  background: 'rgba(15,17,30,0.6)',
  border: '1px solid rgba(148,163,184,0.12)',
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
  borderRadius: 8,
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
  gap: 24,
}

const cardWrapStyle: CSSProperties = {
  position: 'relative',
  background:
    'linear-gradient(160deg, rgba(20,22,34,0.85) 0%, rgba(13,15,24,0.85) 100%)',
  border: '1px solid rgba(148,163,184,0.12)',
  borderRadius: 14,
  padding: '22px 24px 18px',
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
  right: -32,
  transform: 'rotate(35deg)',
  background: 'linear-gradient(90deg, #fde68a, #f0abfc)',
  color: '#0f1117',
  padding: '4px 40px',
  fontFamily: FONT_MONO,
  fontSize: 9,
  letterSpacing: 2,
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
  color: '#a78bfa',
  fontWeight: 700,
}
const stampDot: CSSProperties = {
  width: 6,
  height: 6,
  borderRadius: '50%',
  background: '#a78bfa',
  boxShadow: '0 0 8px #a78bfa',
}
const cardTitleStyle: CSSProperties = {
  fontFamily: FONT_DISPLAY,
  fontSize: 24,
  fontWeight: 600,
  lineHeight: 1.25,
  color: '#f1f5f9',
  margin: 0,
  letterSpacing: -0.2,
  display: '-webkit-box',
  WebkitLineClamp: 3,
  WebkitBoxOrient: 'vertical',
  overflow: 'hidden',
}
const cardSummaryStyle: CSSProperties = {
  fontSize: 13.5,
  lineHeight: 1.7,
  color: '#94a3b8',
  margin: 0,
  display: '-webkit-box',
  WebkitLineClamp: 4,
  WebkitBoxOrient: 'vertical',
  overflow: 'hidden',
  borderLeft: '2px solid rgba(167,139,250,0.4)',
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
  color: '#a5f3fc',
  background: 'rgba(34,211,238,0.06)',
  border: '1px solid rgba(34,211,238,0.22)',
  borderRadius: 4,
  padding: '2px 8px',
}
const cardSourceStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  flexWrap: 'wrap',
  paddingTop: 12,
  borderTop: '1px dashed rgba(148,163,184,0.15)',
}
const originBtnStyle: CSSProperties = {
  background: 'transparent',
  border: 'none',
  padding: 0,
  color: '#cbd5e1',
  fontSize: 13,
  cursor: 'pointer',
  textDecoration: 'underline',
  textDecorationColor: 'rgba(167,139,250,0.4)',
  textUnderlineOffset: 4,
}
const seedSnippetStyle: CSSProperties = {
  color: '#64748b',
  fontFamily: FONT_DISPLAY,
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
}
const hotPulseStyle: CSSProperties = {
  width: 7,
  height: 7,
  borderRadius: '50%',
  background: '#a78bfa',
  boxShadow: '0 0 8px #a78bfa',
  display: 'inline-block',
  animation: 'bigscreen-pulse 1.6s ease-in-out infinite',
}

const emptyStyle: CSSProperties = {
  gridColumn: '1 / -1',
  textAlign: 'center',
  padding: '120px 24px',
  border: '1px dashed rgba(148,163,184,0.18)',
  borderRadius: 16,
  background:
    'radial-gradient(ellipse at center, rgba(167,139,250,0.06) 0%, transparent 65%)',
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
      .ainstein-discovery-card:hover {
        transform: translateY(-3px);
        border-color: rgba(167,139,250,0.45) !important;
        box-shadow: 0 18px 40px rgba(99,102,241,0.18), 0 0 0 1px rgba(167,139,250,0.15);
      }
      .ainstein-discovery-card::before {
        content: '';
        position: absolute;
        inset: 0;
        background: radial-gradient(circle at 100% 0%, rgba(167,139,250,0.10) 0%, transparent 45%);
        pointer-events: none;
      }
    `}</style>
  )
}
