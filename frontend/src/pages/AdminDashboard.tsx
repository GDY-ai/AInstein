import { useEffect, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, getStoredUser } from '../api'
import AdminNav from '../components/AdminNav'

/* ============================================================
 * 「运营仪表盘」
 *  统一深空风：青蓝主调 + 320px 卡片 + 18px 间距
 *  保留趋势图、漏斗、排行榜功能，但简化外观。
 * ============================================================ */

const FONT_INJECT_ID = 'ainstein-admin-dashboard-fonts'
function injectFonts() {
  if (typeof document === 'undefined') return
  if (document.getElementById(FONT_INJECT_ID)) return
  const link = document.createElement('link')
  link.id = FONT_INJECT_ID
  link.rel = 'stylesheet'
  link.href =
    'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600&display=swap'
  document.head.appendChild(link)
}
const FONT_BODY =
  '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif'
const FONT_MONO = '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace'

const C = {
  bg0: '#05070f',
  bg1: '#0a0e1a',
  panel: 'rgba(10, 14, 26, 0.75)',
  panelAlt: 'rgba(15, 22, 38, 0.55)',
  border: 'rgba(120, 160, 220, 0.15)',
  borderHot: 'rgba(79, 209, 197, 0.30)',
  text: '#dce6f5',
  dim: '#7a8da8',
  faint: '#475569',
  accent: '#4fd1c5',
  accent2: '#63b3ed',
  amber: '#f6c179',
  rose: '#fb7185',
}

interface OverviewData {
  active_users: { dau: number; wau: number; mau: number }
  brains: { week_new: number; week_completed: number; convergence_rate: number; avg_ce_depth: number }
  papers: { generated: number; shared: number; public_views: number }
  master_brain: { ce_absorbed: number }
  north_star: { wabcr: number; week_active_users: number; week_completing_users: number }
  funnel: {
    registered: number
    created_brain: number
    completed_thinking: number
    generated_paper: number
    shared_paper: number
  }
}
interface TrendsData {
  days: string[]
  new_users: number[]
  new_brains: number[]
  new_ces: number[]
  new_shares: number[]
}
interface LeaderboardData {
  top_users: Array<{ id: number; username: string; brain_count: number }>
  top_brains: Array<{ id: number; name: string; seed_question: string; state: string; owner_name: string; ce_count: number }>
  top_papers: Array<{ id: number; share_token: string; title: string; view_count: number; brain_id: number; owner_name: string }>
}

export default function AdminDashboard() {
  const navigate = useNavigate()
  const user = getStoredUser()
  const [overview, setOverview] = useState<OverviewData | null>(null)
  const [trends, setTrends] = useState<TrendsData | null>(null)
  const [board, setBoard] = useState<LeaderboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    injectFonts()
  }, [])

  useEffect(() => {
    let alive = true
    async function load() {
      setLoading(true)
      setError('')
      try {
        const [ov, tr, lb] = await Promise.all([
          api.adminStatsOverview(),
          api.adminStatsTrends(),
          api.adminStatsLeaderboard(),
        ])
        if (!alive) return
        setOverview(ov)
        setTrends(tr)
        setBoard(lb)
      } catch (e: any) {
        if (!alive) return
        const msg = e?.message || '加载失败'
        setError(msg)
        if (/401|auth/i.test(msg)) navigate('/login')
      } finally {
        if (alive) setLoading(false)
      }
    }
    load()
    return () => {
      alive = false
    }
  }, [navigate])

  return (
    <div style={pageStyle}>
      <StyleTag />
      <div style={gridBg} />
      <div style={vignette} />

      <AdminNav
        active="dashboard"
        rightSlot={
          <span style={{ letterSpacing: 1 }}>
            <span style={{ color: C.faint }}>操作员 </span>
            <span style={{ color: C.text }}>{user?.username || '未知'}</span>
          </span>
        }
      />

      <main style={contentStyle}>
        {error && (
          <div style={errorBarStyle}>
            <span style={{ color: C.rose, marginRight: 12 }}>◆ 错误</span>
            {error}
          </div>
        )}

        <Hero />

        <NorthStarBlock overview={overview} loading={loading} />
        <PrimaryMetrics overview={overview} loading={loading} />
        <TrendsBlock trends={trends} loading={loading} />

        <div style={twoColStyle}>
          <FunnelBlock overview={overview} />
          <LeaderboardBlock board={board} navigate={navigate} />
        </div>
      </main>
    </div>
  )
}

function Hero() {
  return (
    <header style={heroStyle}>
      <div style={{ flex: 1, minWidth: 280 }}>
        <h1 style={heroTitleStyle}>运营仪表盘</h1>
        <p style={heroSubStyle}>
          俯瞰用户、大脑、论文与传播的整体走势。每一个数字背后，都是一段思考的轨迹。
        </p>
      </div>
    </header>
  )
}

function SectionTitle({ label, sub }: { label: string; sub?: string }) {
  return (
    <div style={sectionTitleStyle}>
      <span style={sectionTitleDot} />
      <span style={{ color: C.text, fontSize: 14, fontWeight: 600, letterSpacing: 1 }}>{label}</span>
      {sub && (
        <span style={{ color: C.faint, fontSize: 11, fontFamily: FONT_MONO, letterSpacing: 1 }}>
          {sub}
        </span>
      )}
      <span style={sectionTitleLine} />
    </div>
  )
}

// ============================================================
// 北极星指标 — 简洁大数字卡片
// ============================================================
function NorthStarBlock({ overview, loading }: { overview: OverviewData | null; loading: boolean }) {
  const wabcr = overview?.north_star.wabcr ?? 0
  const wau = overview?.north_star.week_active_users ?? 0
  const wcu = overview?.north_star.week_completing_users ?? 0

  return (
    <section style={{ marginBottom: 28 }}>
      <SectionTitle label="北极星指标" sub="周活跃思考完成率" />
      <div style={northStarCardStyle}>
        <div style={{ flex: 1, minWidth: 240 }}>
          <div style={{ color: C.dim, fontSize: 13, letterSpacing: 0.5 }}>
            本周活跃用户中，完成至少一次思考收敛的比例
          </div>
          <div style={northStarValueWrapStyle}>
            <span style={northStarValueStyle}>
              {loading ? '——' : (wabcr * 100).toFixed(1)}
            </span>
            <span style={northStarUnitStyle}>%</span>
          </div>
          <div style={northStarMetaStyle}>
            完成思考 <strong style={{ color: C.accent }}>{wcu}</strong> 人
            <span style={{ color: C.faint, margin: '0 8px' }}>/</span>
            活跃 <strong style={{ color: C.accent }}>{wau}</strong> 人
          </div>
        </div>
        <div style={northStarBarWrapStyle}>
          <div style={northStarBarTrackStyle}>
            <div
              style={{
                ...northStarBarFillStyle,
                width: `${Math.min(100, wabcr * 100)}%`,
              }}
            />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontFamily: FONT_MONO, fontSize: 10, color: C.faint, letterSpacing: 1 }}>
            <span>0%</span>
            <span>50%</span>
            <span>100%</span>
          </div>
        </div>
      </div>
    </section>
  )
}

// ============================================================
// 一级指标矩阵
// ============================================================
function PrimaryMetrics({ overview, loading }: { overview: OverviewData | null; loading: boolean }) {
  const cards: Array<{ label: string; value: string; tone: string; foot?: string }> = [
    {
      label: '日活用户',
      value: loading ? '——' : String(overview?.active_users.dau ?? 0),
      tone: C.accent,
      foot: `周活 ${overview?.active_users.wau ?? 0} · 月活 ${overview?.active_users.mau ?? 0}`,
    },
    {
      label: '本周新增大脑',
      value: loading ? '——' : String(overview?.brains.week_new ?? 0),
      tone: C.accent2,
      foot: `完成 ${overview?.brains.week_completed ?? 0} · 收敛率 ${overview ? (overview.brains.convergence_rate * 100).toFixed(1) : '0.0'}%`,
    },
    {
      label: '平均认知深度',
      value: loading ? '——' : (overview?.brains.avg_ce_depth ?? 0).toFixed(1),
      tone: C.amber,
      foot: '单大脑平均认知元素数',
    },
    {
      label: '论文产出',
      value: loading ? '——' : String(overview?.papers.generated ?? 0),
      tone: C.accent,
      foot: `分享 ${overview?.papers.shared ?? 0} · 公开浏览 ${overview?.papers.public_views ?? 0}`,
    },
    {
      label: '主脑吸收量',
      value: loading ? '——' : String(overview?.master_brain.ce_absorbed ?? 0),
      tone: C.accent2,
      foot: '主脑已吸收认知元素',
    },
  ]
  return (
    <section style={{ marginBottom: 28 }}>
      <SectionTitle label="一级指标" sub="核心运营数据" />
      <div style={metricsGridStyle}>
        {cards.map((c, i) => (
          <div key={i} className="ainstein-metric-card" style={metricCardStyle}>
            <div style={metricLabelStyle}>{c.label}</div>
            <div style={{ ...metricValueStyle, color: c.tone, textShadow: `0 0 18px ${c.tone}33` }}>
              {c.value}
            </div>
            {c.foot && <div style={metricFootStyle}>{c.foot}</div>}
          </div>
        ))}
      </div>
    </section>
  )
}

// ============================================================
// 趋势图
// ============================================================
const TREND_SERIES: Array<{ key: keyof TrendsData; label: string; color: string }> = [
  { key: 'new_users', label: '新用户', color: C.accent },
  { key: 'new_brains', label: '新大脑', color: C.accent2 },
  { key: 'new_ces', label: '认知节点', color: C.amber },
  { key: 'new_shares', label: '论文分享', color: '#a78bfa' },
]

function TrendsBlock({ trends, loading }: { trends: TrendsData | null; loading: boolean }) {
  const [active, setActive] = useState<string>('new_users')
  const cur = TREND_SERIES.find((s) => s.key === active) || TREND_SERIES[0]
  const series = (trends ? (trends[cur.key] as number[]) : []) || []
  const days = trends?.days || []
  const total = series.reduce((a, b) => a + b, 0)
  const max = Math.max(...series, 1)
  const peakIdx = series.indexOf(Math.max(...series, 0))

  return (
    <section style={{ marginBottom: 28 }}>
      <SectionTitle label="30 天趋势" sub="时间线" />
      <div style={panelStyle}>
        <div style={trendsTabsStyle}>
          {TREND_SERIES.map((s) => (
            <button
              key={String(s.key)}
              onClick={() => setActive(String(s.key))}
              style={trendsTabStyle(active === String(s.key), s.color)}
            >
              <span style={{ color: s.color, marginRight: 6 }}>●</span>
              {s.label}
            </button>
          ))}
        </div>

        <div style={trendsBodyStyle}>
          <div style={trendsLeftStyle}>
            <div style={{ color: C.dim, fontSize: 11, fontFamily: FONT_MONO, letterSpacing: 1 }}>
              30 天合计
            </div>
            <div
              style={{
                fontFamily: FONT_MONO,
                fontSize: 48,
                color: cur.color,
                marginTop: 6,
                letterSpacing: -1,
                lineHeight: 1,
                textShadow: `0 0 18px ${cur.color}33`,
              }}
            >
              {loading ? '——' : total.toLocaleString()}
            </div>
            <div style={{ color: C.dim, fontSize: 12, fontFamily: FONT_MONO, marginTop: 8 }}>
              峰值 {days[peakIdx] || '—'}{' '}
              <span style={{ color: cur.color }}>{series[peakIdx] ?? 0}</span>
            </div>
            <div style={{ marginTop: 12, fontSize: 11, color: C.faint, fontFamily: FONT_MONO, letterSpacing: 1 }}>
              {days[0] || '—'} → {days[days.length - 1] || '—'}
            </div>
          </div>
          <div style={trendsRightStyle}>
            <SparkChart series={series} days={days} color={cur.color} max={max} />
          </div>
        </div>
      </div>
    </section>
  )
}

function SparkChart({
  series,
  days,
  color,
  max,
}: {
  series: number[]
  days: string[]
  color: string
  max: number
}) {
  const W = 760
  const H = 220
  const padX = 20
  const padY = 26
  const N = Math.max(series.length, 1)
  const stepX = (W - padX * 2) / Math.max(N - 1, 1)
  const points = series.map((v, i) => {
    const x = padX + stepX * i
    const y = padY + (H - padY * 2) * (1 - v / max)
    return { x, y, v }
  })
  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
  const areaD = `${pathD} L${(padX + stepX * (N - 1)).toFixed(1)},${(H - padY).toFixed(1)} L${padX},${H - padY} Z`
  const [hover, setHover] = useState<number | null>(null)

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ display: 'block' }}>
      <defs>
        <linearGradient id="sparkArea" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.30} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((g) => (
        <line
          key={g}
          x1={padX}
          x2={W - padX}
          y1={padY + (H - padY * 2) * g}
          y2={padY + (H - padY * 2) * g}
          stroke="rgba(120,160,220,0.08)"
          strokeDasharray="2 4"
        />
      ))}
      <path d={areaD} fill="url(#sparkArea)" />
      <path d={pathD} stroke={color} strokeWidth={1.6} fill="none" />
      {points.map((p, i) => (
        <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
          <rect
            x={p.x - stepX / 2}
            y={padY}
            width={stepX}
            height={H - padY * 2}
            fill="transparent"
          />
          <circle
            cx={p.x}
            cy={p.y}
            r={hover === i ? 4 : 1.6}
            fill={color}
            stroke={C.bg0}
            strokeWidth={hover === i ? 2 : 0}
          />
          {hover === i && (
            <g>
              <line
                x1={p.x}
                x2={p.x}
                y1={padY}
                y2={H - padY}
                stroke={color}
                strokeDasharray="2 3"
                opacity={0.5}
              />
              <rect
                x={Math.min(W - 100, Math.max(0, p.x + 8))}
                y={Math.max(8, p.y - 32)}
                width={92}
                height={28}
                fill="rgba(5,7,13,0.95)"
                stroke={color}
                rx={4}
              />
              <text
                x={Math.min(W - 100, Math.max(0, p.x + 8)) + 8}
                y={Math.max(8, p.y - 32) + 12}
                fontFamily={FONT_MONO}
                fontSize={10}
                fill={C.dim}
              >
                {days[i]}
              </text>
              <text
                x={Math.min(W - 100, Math.max(0, p.x + 8)) + 8}
                y={Math.max(8, p.y - 32) + 24}
                fontFamily={FONT_MONO}
                fontSize={11}
                fill={color}
              >
                {p.v}
              </text>
            </g>
          )}
        </g>
      ))}
    </svg>
  )
}

// ============================================================
// 漏斗 — 简化为水平进度条列表
// ============================================================
const FUNNEL_STAGES = [
  { key: 'registered', label: '注册用户' },
  { key: 'created_brain', label: '创建大脑' },
  { key: 'completed_thinking', label: '完成思考' },
  { key: 'generated_paper', label: '生成论文' },
  { key: 'shared_paper', label: '分享传播' },
] as const

function FunnelBlock({ overview }: { overview: OverviewData | null }) {
  const f = overview?.funnel
  const top = f?.registered || 0
  return (
    <section>
      <SectionTitle label="用户转化漏斗" sub="注册 → 分享" />
      <div style={panelStyle}>
        {FUNNEL_STAGES.map((s, i) => {
          const v = f ? (f as any)[s.key] || 0 : 0
          const ratio = top > 0 ? v / top : 0
          const stepRatio =
            i > 0 && f
              ? (f as any)[s.key] / Math.max((f as any)[FUNNEL_STAGES[i - 1].key] || 1, 1)
              : 1
          const tone = i === 0 ? C.accent : C.accent2
          return (
            <div key={s.key} style={funnelRowStyle}>
              <div style={funnelLabelStyle}>
                <span style={{ color: C.faint, fontFamily: FONT_MONO, marginRight: 8, fontSize: 10 }}>
                  {String(i + 1).padStart(2, '0')}
                </span>
                <span style={{ color: C.text, fontWeight: 500 }}>{s.label}</span>
                <span style={{ flex: 1 }} />
                <span style={{ color: tone, fontFamily: FONT_MONO, fontSize: 14 }}>{v}</span>
                <span style={{ color: C.faint, fontFamily: FONT_MONO, fontSize: 10, marginLeft: 8 }}>
                  {(ratio * 100).toFixed(1)}%
                </span>
                {i > 0 && (
                  <span
                    style={{
                      color: stepRatio < 0.3 ? C.rose : C.dim,
                      fontFamily: FONT_MONO,
                      fontSize: 10,
                      marginLeft: 8,
                    }}
                  >
                    ↳ {(stepRatio * 100).toFixed(1)}%
                  </span>
                )}
              </div>
              <div style={funnelBarBoxStyle}>
                <div
                  style={{
                    ...funnelBarStyle,
                    width: `${Math.max(ratio * 100, 1.5)}%`,
                    background: `linear-gradient(90deg, ${tone}, ${tone}66)`,
                  }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

// ============================================================
// 排行榜
// ============================================================
function LeaderboardBlock({
  board,
  navigate,
}: {
  board: LeaderboardData | null
  navigate: (p: string) => void
}) {
  const [tab, setTab] = useState<'users' | 'brains' | 'papers'>('users')
  const tabs = [
    { key: 'users' as const, label: '最活跃用户' },
    { key: 'brains' as const, label: '最深大脑' },
    { key: 'papers' as const, label: '最多分享' },
  ]

  return (
    <section>
      <SectionTitle label="贡献排行" sub="活跃 · 深度 · 影响" />
      <div style={panelStyle}>
        <div style={{ display: 'flex', gap: 6, marginBottom: 14, flexWrap: 'wrap' }}>
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              style={leaderTabStyle(tab === t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div>
          {tab === 'users' && (
            <BoardList
              rows={(board?.top_users || []).map((u, i) => ({
                rank: i + 1,
                primary: u.username,
                secondary: `用户 #${u.id}`,
                metric: u.brain_count,
                metricLabel: '个大脑',
                tone: C.accent,
              }))}
            />
          )}
          {tab === 'brains' && (
            <BoardList
              rows={(board?.top_brains || []).map((b, i) => ({
                rank: i + 1,
                primary: b.name || `大脑 #${b.id}`,
                secondary: `${b.owner_name} · ${b.state}`,
                metric: b.ce_count,
                metricLabel: '认知节点',
                tone: C.accent2,
                onClick: () => navigate(`/brain/${b.id}`),
              }))}
            />
          )}
          {tab === 'papers' && (
            <BoardList
              rows={(board?.top_papers || []).map((p, i) => ({
                rank: i + 1,
                primary: p.title || `论文 #${p.id}`,
                secondary: `${p.owner_name} · 大脑 #${p.brain_id}`,
                metric: p.view_count,
                metricLabel: '浏览',
                tone: C.amber,
                onClick: () => window.open(`/ainstein/api/public/papers/${p.share_token}/pdf`, '_blank'),
              }))}
            />
          )}
        </div>
      </div>
    </section>
  )
}

interface BoardRow {
  rank: number
  primary: string
  secondary: string
  metric: number
  metricLabel: string
  tone: string
  onClick?: () => void
}
function BoardList({ rows }: { rows: BoardRow[] }) {
  if (!rows.length) {
    return (
      <div style={{ padding: '40px 0', textAlign: 'center', color: C.faint, fontFamily: FONT_MONO }}>
        暂无数据
      </div>
    )
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {rows.map((r) => (
        <div
          key={r.rank}
          onClick={r.onClick}
          className="ainstein-board-row"
          style={{
            ...boardRowStyle,
            cursor: r.onClick ? 'pointer' : 'default',
          }}
        >
          <div style={boardRankStyle(r.rank, r.tone)}>{String(r.rank).padStart(2, '0')}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={boardPrimaryStyle}>{r.primary}</div>
            <div style={boardSecondaryStyle}>{r.secondary}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ ...boardMetricStyle, color: r.tone }}>{r.metric}</div>
            <div style={boardMetricLabelStyle}>{r.metricLabel}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

function StyleTag() {
  return (
    <style>{`
      .ainstein-metric-card { transition: border-color .2s ease, transform .2s ease, box-shadow .25s ease; }
      .ainstein-metric-card:hover {
        transform: translateY(-2px);
        border-color: ${C.borderHot};
        box-shadow: 0 12px 32px rgba(0,0,0,0.4), 0 0 0 1px rgba(79,209,197,0.10);
      }
      .ainstein-board-row { transition: border-color .2s ease, background .2s ease; }
      .ainstein-board-row:hover {
        border-color: ${C.borderHot};
        background: rgba(79, 209, 197, 0.04);
      }
    `}</style>
  )
}

// ============================================================
// 样式
// ============================================================
const pageStyle: CSSProperties = {
  minHeight: '100vh',
  background: 'radial-gradient(ellipse at top, #0f1729 0%, #0a0e1a 55%, #05070f 100%)',
  color: C.text,
  fontFamily: FONT_BODY,
  position: 'relative',
  overflow: 'hidden',
}

const gridBg: CSSProperties = {
  position: 'fixed',
  inset: 0,
  backgroundImage:
    'linear-gradient(rgba(79,209,197,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(79,209,197,0.04) 1px, transparent 1px)',
  backgroundSize: '64px 64px',
  pointerEvents: 'none',
  maskImage: 'radial-gradient(ellipse at top, #000 5%, transparent 75%)',
  WebkitMaskImage: 'radial-gradient(ellipse at top, #000 5%, transparent 75%)',
  zIndex: 0,
}

const vignette: CSSProperties = {
  position: 'fixed',
  inset: 0,
  background:
    'radial-gradient(circle at 18% 12%, rgba(79,209,197,0.05) 0%, transparent 40%), radial-gradient(circle at 82% 88%, rgba(99,179,237,0.04) 0%, transparent 45%)',
  pointerEvents: 'none',
  zIndex: 0,
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
  color: C.text,
  letterSpacing: 1,
  lineHeight: 1.2,
}
const heroSubStyle: CSSProperties = {
  marginTop: 10,
  color: C.dim,
  fontSize: 14,
  lineHeight: 1.7,
  maxWidth: 620,
}

const errorBarStyle: CSSProperties = {
  padding: '10px 14px',
  marginBottom: 18,
  background: 'rgba(251,113,133,0.08)',
  border: '1px solid rgba(251,113,133,0.4)',
  color: C.text,
  fontSize: 13,
  borderRadius: 6,
}

const sectionTitleStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  marginBottom: 16,
}
const sectionTitleDot: CSSProperties = {
  width: 6,
  height: 6,
  background: C.accent,
  boxShadow: `0 0 8px ${C.accent}`,
  borderRadius: '50%',
}
const sectionTitleLine: CSSProperties = {
  flex: 1,
  height: 1,
  background:
    'linear-gradient(90deg, rgba(79,209,197,0.25), rgba(79,209,197,0.04) 70%, transparent)',
}

// 北极星
const northStarCardStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 32,
  padding: '28px 28px',
  background: C.panel,
  border: `1px solid ${C.borderHot}`,
  borderRadius: 10,
  flexWrap: 'wrap',
}
const northStarValueWrapStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'baseline',
  gap: 6,
  marginTop: 12,
}
const northStarValueStyle: CSSProperties = {
  fontFamily: FONT_MONO,
  fontSize: 64,
  lineHeight: 0.9,
  fontWeight: 500,
  letterSpacing: -1,
  color: C.accent,
  textShadow: `0 0 28px ${C.accent}33`,
}
const northStarUnitStyle: CSSProperties = {
  fontFamily: FONT_MONO,
  fontSize: 24,
  color: C.dim,
  letterSpacing: 2,
}
const northStarMetaStyle: CSSProperties = {
  marginTop: 14,
  color: C.dim,
  fontSize: 13,
  fontFamily: FONT_MONO,
}
const northStarBarWrapStyle: CSSProperties = {
  flex: 1,
  minWidth: 240,
}
const northStarBarTrackStyle: CSSProperties = {
  height: 8,
  background: 'rgba(120, 160, 220, 0.10)',
  borderRadius: 4,
  overflow: 'hidden',
  border: `1px solid ${C.border}`,
}
const northStarBarFillStyle: CSSProperties = {
  height: '100%',
  background: `linear-gradient(90deg, ${C.accent}, ${C.accent2})`,
  boxShadow: `0 0 12px ${C.accent}66`,
  transition: 'width 0.6s ease-out',
}

// 一级指标
const metricsGridStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
  gap: 18,
}
const metricCardStyle: CSSProperties = {
  padding: 20,
  background: C.panel,
  border: `1px solid ${C.border}`,
  borderRadius: 10,
}
const metricLabelStyle: CSSProperties = {
  fontSize: 12,
  letterSpacing: 1,
  color: C.dim,
  fontWeight: 500,
}
const metricValueStyle: CSSProperties = {
  fontFamily: FONT_MONO,
  fontSize: 38,
  fontWeight: 500,
  margin: '12px 0 6px',
  letterSpacing: -1,
  lineHeight: 1.05,
}
const metricFootStyle: CSSProperties = {
  fontFamily: FONT_MONO,
  fontSize: 10,
  color: C.faint,
  letterSpacing: 0.5,
}

// 趋势 / 通用面板
const panelStyle: CSSProperties = {
  padding: 20,
  background: C.panel,
  border: `1px solid ${C.border}`,
  borderRadius: 10,
}
const trendsTabsStyle: CSSProperties = {
  display: 'flex',
  gap: 6,
  flexWrap: 'wrap',
  marginBottom: 18,
}
function trendsTabStyle(active: boolean, color: string): CSSProperties {
  return {
    background: active ? `${color}15` : 'transparent',
    border: `1px solid ${active ? color + '88' : C.border}`,
    color: active ? C.text : C.dim,
    padding: '6px 12px',
    fontFamily: FONT_BODY,
    fontSize: 12,
    letterSpacing: 1,
    cursor: 'pointer',
    borderRadius: 4,
  }
}
const trendsBodyStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'minmax(200px, 240px) 1fr',
  gap: 24,
  alignItems: 'center',
}
const trendsLeftStyle: CSSProperties = {
  paddingRight: 24,
  borderRight: `1px solid ${C.border}`,
}
const trendsRightStyle: CSSProperties = { minWidth: 0 }

const twoColStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))',
  gap: 18,
}

// 漏斗
const funnelRowStyle: CSSProperties = {
  marginBottom: 14,
}
const funnelLabelStyle: CSSProperties = {
  fontSize: 13,
  marginBottom: 6,
  display: 'flex',
  alignItems: 'baseline',
}
const funnelBarBoxStyle: CSSProperties = {
  position: 'relative',
  height: 8,
  background: C.panelAlt,
  border: `1px solid ${C.border}`,
  borderRadius: 4,
  overflow: 'hidden',
}
const funnelBarStyle: CSSProperties = {
  height: '100%',
  transition: 'width 0.6s ease-out',
  borderRadius: 4,
}

// 排行榜
function leaderTabStyle(active: boolean): CSSProperties {
  return {
    background: active ? 'rgba(79,209,197,0.10)' : 'transparent',
    border: `1px solid ${active ? C.borderHot : C.border}`,
    color: active ? C.text : C.dim,
    padding: '6px 12px',
    fontFamily: FONT_BODY,
    fontSize: 12,
    letterSpacing: 0.5,
    cursor: 'pointer',
    borderRadius: 4,
  }
}
const boardRowStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 14,
  padding: '10px 12px',
  background: C.panelAlt,
  border: `1px solid ${C.border}`,
  borderRadius: 6,
}
function boardRankStyle(rank: number, tone: string): CSSProperties {
  return {
    width: 32,
    height: 32,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontFamily: FONT_MONO,
    fontSize: 14,
    color: rank <= 3 ? tone : C.faint,
    border: `1px solid ${rank <= 3 ? tone + '88' : C.border}`,
    background: rank <= 3 ? `${tone}11` : 'transparent',
    borderRadius: 4,
  }
}
const boardPrimaryStyle: CSSProperties = {
  color: C.text,
  fontSize: 13,
  fontWeight: 500,
  whiteSpace: 'nowrap',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
}
const boardSecondaryStyle: CSSProperties = {
  color: C.faint,
  fontSize: 11,
  fontFamily: FONT_MONO,
  marginTop: 2,
  whiteSpace: 'nowrap',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
}
const boardMetricStyle: CSSProperties = {
  fontFamily: FONT_MONO,
  fontSize: 20,
  letterSpacing: -0.5,
  lineHeight: 1,
}
const boardMetricLabelStyle: CSSProperties = {
  color: C.faint,
  fontFamily: FONT_MONO,
  fontSize: 10,
  letterSpacing: 1,
  marginTop: 2,
}
