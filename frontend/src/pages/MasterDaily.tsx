import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'

/* ============================================================
 *「主脑日报」公开阅读页
 *  统一深空风：青蓝主调 + 毛玻璃 + Tab 切换 + 全中文
 *  Task #17 — 公开访问，无需登录
 * ============================================================ */

const FONT_INJECT_ID = 'ainstein-master-daily-fonts'
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

interface Digest {
  id: number
  master_id: number | null
  title: string
  summary: string
  highlights: string[]
  stats: Record<string, number | string>
  status: string
  created_at: string
  date_str: string
}

const RSS_URL = '/ainstein/master-daily.rss'
const API_LIST = '/ainstein/api/public/master-daily'

export default function MasterDaily() {
  const nav = useNavigate()
  const [items, setItems] = useState<Digest[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeId, setActiveId] = useState<number | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => { injectFonts() }, [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetch(`${API_LIST}?limit=30`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then((data: { items: Digest[] }) => {
        if (cancelled) return
        const list = data.items || []
        setItems(list)
        setActiveId(list[0]?.id ?? null)
        setLoading(false)
      })
      .catch(err => {
        if (cancelled) return
        setError(err?.message || '加载失败')
        setLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  const active = useMemo(
    () => items.find(d => d.id === activeId) || items[0] || null,
    [items, activeId],
  )

  const rssFullUrl = useMemo(() => {
    if (typeof window === 'undefined') return RSS_URL
    return `${window.location.origin}${RSS_URL}`
  }, [])

  function copyRss() {
    if (typeof navigator === 'undefined' || !navigator.clipboard) return
    navigator.clipboard.writeText(rssFullUrl).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    }).catch(() => { /* ignore */ })
  }

  return (
    <div style={pageStyle}>
      <BgGrid />

      <header style={navStyle}>
        <div style={brandStyle} onClick={() => nav('/')}>
          <span style={{ color: ACCENT }}>AI</span>
          <span style={{ color: TEXT }}>nstein</span>
          <span style={{ color: DIM, marginLeft: 10, fontSize: 13 }}>· 主脑日报</span>
        </div>
        <nav style={navLinksStyle}>
          <a style={navLinkStyle} onClick={() => nav('/discoveries')}>发现广场</a>
          <a style={navLinkStyle} onClick={() => nav('/admin/bigscreen')}>态势大屏</a>
          <a style={{ ...navLinkStyle, color: ACCENT }}>日报</a>
        </nav>
      </header>

      <main style={mainStyle}>
        <section style={heroStyle}>
          <div>
            <h1 style={heroTitleStyle}>主脑日报</h1>
            <p style={heroDescStyle}>
              创世主脑每日 08:00 UTC 自动生成，凝练过去 24 小时全网认知活动。
            </p>
          </div>
          <div style={subscribeBoxStyle}>
            <div style={{ fontSize: 11, letterSpacing: 1, color: DIM, marginBottom: 8 }}>
              RSS 订阅
            </div>
            <div style={rssRowStyle}>
              <code style={rssCodeStyle}>{rssFullUrl}</code>
              <button style={pillBtnStyle} onClick={copyRss}>
                {copied ? '已复制' : '复制'}
              </button>
              <a style={{ ...pillBtnStyle, textDecoration: 'none' }} href={RSS_URL} target="_blank" rel="noreferrer">
                打开
              </a>
            </div>
          </div>
        </section>

        {loading && <SkeletonBlock />}
        {error && <ErrorBanner message={error} />}

        {!loading && !error && items.length === 0 && (
          <EmptyHint />
        )}

        {!loading && !error && items.length > 0 && (
          <div style={layoutStyle}>
            <aside style={sideStyle}>
              <div style={sideHeaderStyle}>近 30 日</div>
              <ul style={listStyle}>
                {items.map(d => (
                  <li
                    key={d.id}
                    onClick={() => setActiveId(d.id)}
                    style={{
                      ...listItemStyle,
                      borderLeftColor: d.id === activeId ? ACCENT : 'transparent',
                      background: d.id === activeId ? 'rgba(79,209,197,0.06)' : 'transparent',
                    }}
                  >
                    <div style={dateStyle}>{d.date_str}</div>
                    <div style={titleSmStyle}>{d.title}</div>
                    <div style={excerptStyle}>{(d.summary || '').slice(0, 38)}</div>
                  </li>
                ))}
              </ul>
            </aside>

            <article style={detailStyle}>
              {active ? <DigestDetail digest={active} /> : <EmptyHint />}
            </article>
          </div>
        )}

        <footer style={footerStyle}>
          <span style={{ color: FAINT }}>由 AInstein 创世主脑自主生成 · 内容由模型撰写，请审慎参考</span>
        </footer>
      </main>
    </div>
  )
}

/* ----------------------------- 子组件 ----------------------------- */

function DigestDetail({ digest }: { digest: Digest }) {
  const stats = digest.stats || {}
  const statEntries = Object.entries(stats)

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4 }}>
        <span style={{ fontFamily: FONT_MONO, color: ACCENT, fontSize: 13 }}>
          {digest.date_str}
        </span>
        <span style={{ color: FAINT, fontSize: 12 }}>· {digest.status}</span>
      </div>
      <h2 style={{
        fontSize: 26, fontWeight: 600, color: TEXT, margin: '4px 0 18px',
        letterSpacing: 0.4,
      }}>
        {digest.title}
      </h2>

      <p style={{
        color: TEXT, fontSize: 15.5, lineHeight: 1.85,
        whiteSpace: 'pre-wrap', margin: 0,
      }}>
        {digest.summary}
      </p>

      {digest.highlights && digest.highlights.length > 0 && (
        <div style={{ marginTop: 28 }}>
          <div style={sectionLabelStyle}>今日亮点</div>
          <ul style={{ margin: 0, padding: 0, listStyle: 'none' }}>
            {digest.highlights.map((h, i) => (
              <li key={i} style={highlightItemStyle}>
                <span style={{ color: AMBER, marginRight: 10, fontFamily: FONT_MONO }}>0{i + 1}</span>
                <span style={{ color: TEXT, fontSize: 14.5, lineHeight: 1.7 }}>{h}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {statEntries.length > 0 && (
        <div style={{ marginTop: 28 }}>
          <div style={sectionLabelStyle}>过去 24 小时数据</div>
          <div style={statsGridStyle}>
            {statEntries.map(([k, v]) => (
              <div key={k} style={statCardStyle}>
                <div style={statLabelStyle}>{statLabel(k)}</div>
                <div style={statValStyle}>{String(v)}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function statLabel(k: string): string {
  const map: Record<string, string> = {
    new_brains: '新增大脑',
    new_ces: '新增认知元素',
    master_ces: '主脑产出',
    deliberations: '博弈触发',
    converged_brains: '收敛大脑',
    active_brains: '活跃大脑',
    contradictions: '矛盾发现',
  }
  return map[k] || k
}

function SkeletonBlock() {
  return (
    <div style={{
      marginTop: 32, padding: 28, borderRadius: 16,
      background: 'rgba(15,23,42,0.55)', border: `1px solid ${BORDER}`,
      backdropFilter: 'blur(12px)', color: DIM, fontSize: 14,
    }}>
      正在加载主脑日报…
    </div>
  )
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div style={{
      marginTop: 32, padding: 18, borderRadius: 12,
      background: 'rgba(220,80,80,0.08)', border: '1px solid rgba(220,80,80,0.3)',
      color: '#f0b3b3', fontSize: 14,
    }}>
      加载失败：{message}
    </div>
  )
}

function EmptyHint() {
  return (
    <div style={{
      marginTop: 40, padding: '60px 30px', borderRadius: 16, textAlign: 'center',
      background: 'rgba(15,23,42,0.55)', border: `1px dashed ${BORDER}`,
      color: DIM,
    }}>
      <div style={{ fontSize: 38, marginBottom: 16, color: FAINT }}>⌬</div>
      <div style={{ fontSize: 14 }}>主脑暂未输出日报</div>
      <div style={{ fontSize: 12, color: FAINT, marginTop: 6 }}>
        当过去 24 小时无活跃认知活动时跳过当日生成
      </div>
    </div>
  )
}

function BgGrid() {
  return (
    <div aria-hidden style={{
      position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 0,
      background:
        'radial-gradient(1200px 600px at 80% -10%, rgba(99,179,237,0.10), transparent 60%),' +
        'radial-gradient(900px 500px at 0% 110%, rgba(79,209,197,0.08), transparent 60%),' +
        '#070b14',
    }} />
  )
}

/* ----------------------------- 样式 ----------------------------- */

const pageStyle: CSSProperties = {
  minHeight: '100vh', color: TEXT, fontFamily: FONT_BODY,
  position: 'relative', isolation: 'isolate',
}
const navStyle: CSSProperties = {
  position: 'sticky', top: 0, zIndex: 10,
  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  padding: '16px 32px', backdropFilter: 'blur(14px)',
  background: 'rgba(7,11,20,0.72)', borderBottom: `1px solid ${BORDER}`,
}
const brandStyle: CSSProperties = {
  cursor: 'pointer', fontSize: 19, fontWeight: 700, letterSpacing: 0.6,
}
const navLinksStyle: CSSProperties = { display: 'flex', gap: 22, fontSize: 13.5 }
const navLinkStyle: CSSProperties = { color: DIM, cursor: 'pointer', letterSpacing: 0.4 }

const mainStyle: CSSProperties = {
  position: 'relative', zIndex: 1,
  maxWidth: 1180, margin: '0 auto', padding: '36px 28px 60px',
}

const heroStyle: CSSProperties = {
  display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between',
  gap: 24, flexWrap: 'wrap', marginBottom: 28,
}
const heroTitleStyle: CSSProperties = {
  fontSize: 32, fontWeight: 700, margin: 0, letterSpacing: 1,
  background: `linear-gradient(120deg, ${TEXT} 30%, ${ACCENT} 100%)`,
  WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
}
const heroDescStyle: CSSProperties = {
  margin: '10px 0 0', color: DIM, fontSize: 14, lineHeight: 1.7,
}
const subscribeBoxStyle: CSSProperties = {
  padding: '14px 16px', borderRadius: 12,
  background: 'rgba(15,23,42,0.55)', border: `1px solid ${BORDER}`,
  backdropFilter: 'blur(10px)',
}
const rssRowStyle: CSSProperties = { display: 'flex', alignItems: 'center', gap: 8 }
const rssCodeStyle: CSSProperties = {
  fontFamily: FONT_MONO, fontSize: 12, color: ACCENT_2,
  padding: '6px 10px', borderRadius: 6, background: 'rgba(99,179,237,0.06)',
  border: `1px solid ${BORDER}`, maxWidth: 320,
  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
}
const pillBtnStyle: CSSProperties = {
  padding: '6px 12px', borderRadius: 999, fontSize: 12,
  background: 'transparent', color: TEXT, border: `1px solid ${BORDER}`,
  cursor: 'pointer', letterSpacing: 0.4,
}

const layoutStyle: CSSProperties = {
  display: 'grid', gridTemplateColumns: '280px 1fr', gap: 24,
}
const sideStyle: CSSProperties = {
  borderRadius: 14, padding: '8px 0',
  background: 'rgba(15,23,42,0.55)', border: `1px solid ${BORDER}`,
  backdropFilter: 'blur(10px)', maxHeight: 'calc(100vh - 200px)', overflowY: 'auto',
}
const sideHeaderStyle: CSSProperties = {
  fontSize: 11, letterSpacing: 1, color: DIM, padding: '8px 18px 12px',
  borderBottom: `1px solid ${BORDER}`,
}
const listStyle: CSSProperties = { listStyle: 'none', margin: 0, padding: 0 }
const listItemStyle: CSSProperties = {
  padding: '14px 18px', cursor: 'pointer', borderLeft: '3px solid transparent',
  transition: 'background 0.18s ease',
}
const dateStyle: CSSProperties = { fontFamily: FONT_MONO, color: ACCENT, fontSize: 12 }
const titleSmStyle: CSSProperties = {
  color: TEXT, fontSize: 14, marginTop: 4, fontWeight: 500,
  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
}
const excerptStyle: CSSProperties = {
  color: DIM, fontSize: 12, marginTop: 4,
  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
}
const detailStyle: CSSProperties = {
  borderRadius: 16, padding: '32px 36px',
  background: 'rgba(15,23,42,0.55)', border: `1px solid ${BORDER}`,
  backdropFilter: 'blur(10px)',
}

const sectionLabelStyle: CSSProperties = {
  fontSize: 11, letterSpacing: 1.5, color: DIM,
  textTransform: 'uppercase', marginBottom: 12, fontFamily: FONT_MONO,
}
const highlightItemStyle: CSSProperties = {
  display: 'flex', alignItems: 'flex-start', padding: '10px 0',
  borderTop: `1px solid ${BORDER}`,
}
const statsGridStyle: CSSProperties = {
  display: 'grid', gap: 12,
  gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
}
const statCardStyle: CSSProperties = {
  padding: '14px 16px', borderRadius: 10,
  background: 'rgba(99,179,237,0.04)', border: `1px solid ${BORDER}`,
}
const statLabelStyle: CSSProperties = { fontSize: 12, color: DIM, marginBottom: 6 }
const statValStyle: CSSProperties = {
  fontFamily: FONT_MONO, fontSize: 22, color: TEXT, fontWeight: 600,
}

const footerStyle: CSSProperties = {
  marginTop: 36, paddingTop: 18, fontSize: 12,
  borderTop: `1px solid ${BORDER}`, textAlign: 'center',
}
