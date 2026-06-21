import { useEffect, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, getStoredUser } from '../api'
import AdminNav from '../components/AdminNav'

/* ============================================================
 * 「指挥舱 · OPERATIONS DECK」
 *  KPI 运营仪表盘 — 北极星指标 / 一级指标趋势 / 用户漏斗 / 排行榜
 *  美学方向：航天指挥屏 × 编辑式信息图，深空底色 + 单点琥珀强调
 * ============================================================ */

// ---------- 字体注入 ----------
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
const FONT_DISPLAY = '"JetBrains Mono", ui-monospace, monospace'
const FONT_BODY = '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif'
const FONT_MONO = '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace'

// ---------- 配色 ----------
const COLORS = {
  bg0: '#05070f',
  bg1: '#0a0e1a',
  panel: 'rgba(15, 22, 38, 0.72)',
  panelAlt: 'rgba(20, 28, 46, 0.5)',
  border: 'rgba(120, 160, 220, 0.15)',
  borderHot: 'rgba(79, 209, 197, 0.35)',
  text: '#dce6f5',
  textDim: '#7a8da8',
  textFaint: '#475569',
  cyan: '#4fd1c5',
  amber: '#f6c179',
  pink: '#f687b3',
  blue: '#63b3ed',
  violet: '#a78bfa',
  rose: '#fb7185',
}

// ---------- 类型 ----------
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
  const [now, setNow] = useState(new Date())

  useEffect(() => {
    injectFonts()
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
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
        if (/admin/i.test(msg) || /403/.test(msg)) {
          // 非 admin → 提示并返回
        } else if (/401|auth/i.test(msg)) {
          navigate('/login')
        }
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
      <div style={scanlines} />

      {/* 顶部统一导航 */}
      <AdminNav
        active="dashboard"
        rightSlot={
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 12 }}>
            <span style={{ color: COLORS.cyan, letterSpacing: 1.5 }}>{formatClock(now)}</span>
            <span style={{ color: COLORS.textDim }}>·</span>
            <span style={{ letterSpacing: 1 }}>
              <span style={{ color: COLORS.textFaint }}>操作员 </span>
              <span style={{ color: COLORS.text }}>{user?.username || '未知'}</span>{' '}
              <span style={{ color: COLORS.amber }}>[{(user?.role || 'user').toUpperCase()}]</span>
            </span>
          </span>
        }
      />

      {/* 错误条 */}
      {error && (
        <div style={errorBarStyle}>
          <span style={{ color: COLORS.rose, marginRight: 12 }}>◆ 错误</span>
          {error}
        </div>
      )}

      {/* === 北极星指标 === */}
      <NorthStarBlock overview={overview} loading={loading} />

      {/* === 一级指标矩阵 === */}
      <PrimaryMetrics overview={overview} loading={loading} />

      {/* === 趋势图 === */}
      <TrendsBlock trends={trends} loading={loading} />

      {/* === 漏斗 + 排行榜 === */}
      <div style={twoColStyle}>
        <FunnelBlock overview={overview} />
        <LeaderboardBlock board={board} navigate={navigate} />
      </div>

      <footer style={footerStyle}>
        <span style={{ color: COLORS.textFaint }}>—— 数据流结束 ——</span>
        <span style={{ color: COLORS.textFaint, fontFamily: FONT_MONO, fontSize: 11 }}>
          AInstein · 运营仪表盘 · {now.toISOString().slice(0, 10)}
        </span>
      </footer>
    </div>
  )
}

// ============================================================
// 北极星指标
// ============================================================
function NorthStarBlock({ overview, loading }: { overview: OverviewData | null; loading: boolean }) {
  const wabcr = overview?.north_star.wabcr ?? 0
  const wau = overview?.north_star.week_active_users ?? 0
  const wcu = overview?.north_star.week_completing_users ?? 0

  return (
    <section style={northStarStyle}>
      <div style={northStarLeftStyle}>
        <div style={sectionLabelStyle}>
          <span style={sectionLabelDot} />
          北极星指标 · NORTH STAR
        </div>
        <div style={{ marginTop: 22 }}>
          <div style={northStarKickerStyle}>
            周活跃思考完成率
            <span style={{ color: COLORS.textFaint, margin: '0 10px' }}>·</span>
            <span style={{ color: COLORS.amber, fontFamily: FONT_MONO }}>WABCR</span>
          </div>
          <div style={northStarValueWrapStyle}>
            <span style={northStarValueStyle}>
              {loading ? '——' : (wabcr * 100).toFixed(1)}
            </span>
            <span style={northStarUnitStyle}>%</span>
          </div>
          <div style={northStarMetaStyle}>
            本周完成思考 <strong style={{ color: COLORS.cyan }}>{wcu}</strong> 人
            <span style={{ color: COLORS.textFaint, margin: '0 8px' }}>/</span>
            活跃用户 <strong style={{ color: COLORS.cyan }}>{wau}</strong> 人
          </div>
        </div>
      </div>
      <div style={northStarRightStyle}>
        <NorthStarRing value={wabcr} />
      </div>
    </section>
  )
}

function NorthStarRing({ value }: { value: number }) {
  const r = 78
  const c = 2 * Math.PI * r
  const filled = Math.max(0, Math.min(1, value))
  return (
    <svg width={200} height={200} viewBox="0 0 200 200">
      <defs>
        <linearGradient id="nsRing" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={COLORS.amber} />
          <stop offset="60%" stopColor={COLORS.pink} />
          <stop offset="100%" stopColor={COLORS.violet} />
        </linearGradient>
        <filter id="nsGlow">
          <feGaussianBlur stdDeviation="3" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {/* 外刻度 */}
      {Array.from({ length: 60 }).map((_, i) => {
        const a = (i / 60) * Math.PI * 2 - Math.PI / 2
        const r1 = 92
        const r2 = i % 5 === 0 ? 86 : 89
        return (
          <line
            key={i}
            x1={100 + Math.cos(a) * r1}
            y1={100 + Math.sin(a) * r1}
            x2={100 + Math.cos(a) * r2}
            y2={100 + Math.sin(a) * r2}
            stroke={i % 5 === 0 ? COLORS.cyan : 'rgba(123,227,211,0.25)'}
            strokeWidth={1}
            opacity={i % 5 === 0 ? 0.7 : 0.3}
          />
        )
      })}
      <circle cx={100} cy={100} r={r} fill="none" stroke="rgba(123,227,211,0.12)" strokeWidth={6} />
      <circle
        cx={100}
        cy={100}
        r={r}
        fill="none"
        stroke="url(#nsRing)"
        strokeWidth={6}
        strokeDasharray={`${c * filled} ${c}`}
        strokeDashoffset={c * 0.25}
        strokeLinecap="round"
        filter="url(#nsGlow)"
        transform="rotate(-90 100 100)"
      />
      <text
        x={100}
        y={104}
        textAnchor="middle"
        fontFamily={FONT_DISPLAY}
        fontSize={14}
        fill={COLORS.textDim}
        letterSpacing={2}
      >
        WABCR
      </text>
    </svg>
  )
}

// ============================================================
// 一级指标矩阵
// ============================================================
function PrimaryMetrics({ overview, loading }: { overview: OverviewData | null; loading: boolean }) {
  const cards: Array<{ label: string; sub: string; value: string; tone: string; foot?: string }> = [
    {
      label: 'DAU',
      sub: '日活用户',
      value: loading ? '——' : String(overview?.active_users.dau ?? 0),
      tone: COLORS.cyan,
      foot: `WAU ${overview?.active_users.wau ?? 0} · MAU ${overview?.active_users.mau ?? 0}`,
    },
    {
      label: 'WEEK BRAINS',
      sub: '本周新增大脑',
      value: loading ? '——' : String(overview?.brains.week_new ?? 0),
      tone: COLORS.amber,
      foot: `完成 ${overview?.brains.week_completed ?? 0} · 收敛率 ${overview ? (overview.brains.convergence_rate * 100).toFixed(1) : '0.0'}%`,
    },
    {
      label: 'AVG CE',
      sub: '平均认知深度',
      value: loading ? '——' : (overview?.brains.avg_ce_depth ?? 0).toFixed(1),
      tone: COLORS.pink,
      foot: '单大脑平均认知元素数',
    },
    {
      label: 'PAPERS',
      sub: '论文产出',
      value: loading ? '——' : String(overview?.papers.generated ?? 0),
      tone: COLORS.violet,
      foot: `分享 ${overview?.papers.shared ?? 0} · 公开浏览 ${overview?.papers.public_views ?? 0}`,
    },
    {
      label: 'MASTER CE',
      sub: '主脑吸收量',
      value: loading ? '——' : String(overview?.master_brain.ce_absorbed ?? 0),
      tone: COLORS.blue,
      foot: '主脑已吸收认知元素',
    },
  ]
  return (
    <section style={metricsRowStyle}>
      {cards.map((c, i) => (
        <div key={i} style={metricCardStyle(c.tone)}>
          <div style={metricCornerTL(c.tone)} />
          <div style={metricCornerBR(c.tone)} />
          <div style={metricLabelStyle}>
            <span style={{ color: c.tone }}>● </span>
            {c.label}
            <span style={{ color: COLORS.textFaint, margin: '0 8px' }}>·</span>
            <span style={{ color: COLORS.textDim }}>{c.sub}</span>
          </div>
          <div style={metricValueStyle(c.tone)}>{c.value}</div>
          {c.foot && <div style={metricFootStyle}>{c.foot}</div>}
        </div>
      ))}
    </section>
  )
}

// ============================================================
// 趋势图
// ============================================================
const TREND_SERIES: Array<{ key: keyof TrendsData; label: string; sub: string; color: string }> = [
  { key: 'new_users', label: '新用户', sub: 'NEW USERS', color: COLORS.cyan },
  { key: 'new_brains', label: '新大脑', sub: 'NEW BRAINS', color: COLORS.amber },
  { key: 'new_ces', label: 'CE 产出', sub: 'CE DELTA', color: COLORS.pink },
  { key: 'new_shares', label: '论文分享', sub: 'SHARES', color: COLORS.violet },
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
    <section style={trendsSectionStyle}>
      <div style={trendsHeaderStyle}>
        <div style={sectionLabelStyle}>
          <span style={sectionLabelDot} />
          30 天趋势 · TIMELINE
        </div>
        <div style={trendsTabsStyle}>
          {TREND_SERIES.map((s) => (
            <button
              key={String(s.key)}
              onClick={() => setActive(String(s.key))}
              style={trendsTabStyle(active === String(s.key), s.color)}
            >
              <span style={{ color: s.color, marginRight: 8 }}>●</span>
              {s.label}
              <span style={{ color: COLORS.textFaint, marginLeft: 8, fontSize: 10 }}>{s.sub}</span>
            </button>
          ))}
        </div>
      </div>

      <div style={trendsBodyStyle}>
        <div style={trendsLeftStyle}>
          <div style={{ color: COLORS.textDim, fontFamily: FONT_MONO, fontSize: 11 }}>
            30 天合计 · 30 DAY TOTAL
          </div>
          <div style={{ ...northStarValueStyle, fontSize: 64, color: cur.color, marginTop: 8 }}>
            {loading ? '——' : total.toLocaleString()}
          </div>
          <div style={{ color: COLORS.textDim, fontSize: 12, fontFamily: FONT_MONO, marginTop: 6 }}>
            峰值 · {days[peakIdx] || '—'}{' '}
            <span style={{ color: cur.color }}>{series[peakIdx] ?? 0}</span>
          </div>
          <div style={trendsLegendStyle}>
            <div>
              <span style={{ color: COLORS.textFaint, marginRight: 6 }}>起期</span>
              <span style={{ color: COLORS.text, fontFamily: FONT_MONO }}>{days[0] || '—'}</span>
            </div>
            <div>
              <span style={{ color: COLORS.textFaint, marginRight: 6 }}>止期</span>
              <span style={{ color: COLORS.text, fontFamily: FONT_MONO }}>
                {days[days.length - 1] || '—'}
              </span>
            </div>
          </div>
        </div>
        <div style={trendsRightStyle}>
          <SparkChart series={series} days={days} color={cur.color} max={max} />
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
          <stop offset="0%" stopColor={color} stopOpacity={0.35} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
        <filter id="sparkGlow">
          <feGaussianBlur stdDeviation="2.5" />
        </filter>
      </defs>
      {/* 横向网格 */}
      {[0.25, 0.5, 0.75].map((g) => (
        <line
          key={g}
          x1={padX}
          x2={W - padX}
          y1={padY + (H - padY * 2) * g}
          y2={padY + (H - padY * 2) * g}
          stroke="rgba(123,227,211,0.07)"
          strokeDasharray="2 4"
        />
      ))}
      {/* 区域 */}
      <path d={areaD} fill="url(#sparkArea)" />
      {/* 发光主线 */}
      <path d={pathD} stroke={color} strokeWidth={2.5} fill="none" filter="url(#sparkGlow)" opacity={0.55} />
      <path d={pathD} stroke={color} strokeWidth={1.5} fill="none" />
      {/* 数据点 */}
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
            r={hover === i ? 4 : 1.8}
            fill={color}
            stroke={COLORS.bg0}
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
                fill="rgba(5,7,13,0.92)"
                stroke={color}
                rx={2}
              />
              <text
                x={Math.min(W - 100, Math.max(0, p.x + 8)) + 8}
                y={Math.max(8, p.y - 32) + 12}
                fontFamily={FONT_MONO}
                fontSize={10}
                fill={COLORS.textDim}
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
// 漏斗
// ============================================================
const FUNNEL_STAGES = [
  { key: 'registered', label: '注册用户', sub: 'REGISTER', color: COLORS.cyan },
  { key: 'created_brain', label: '创建大脑', sub: 'CREATE', color: COLORS.blue },
  { key: 'completed_thinking', label: '完成思考', sub: 'THINK', color: COLORS.amber },
  { key: 'generated_paper', label: '生成论文', sub: 'PAPER', color: COLORS.pink },
  { key: 'shared_paper', label: '分享传播', sub: 'SHARE', color: COLORS.violet },
] as const

function FunnelBlock({ overview }: { overview: OverviewData | null }) {
  const f = overview?.funnel
  const top = f?.registered || 0
  return (
    <section style={panelStyle}>
      <div style={panelHeaderStyle}>
        <div style={sectionLabelStyle}>
          <span style={sectionLabelDot} />
          用户转化漏斗 · FUNNEL
        </div>
        <div style={{ color: COLORS.textFaint, fontFamily: FONT_MONO, fontSize: 11 }}>
          注册 → 分享
        </div>
      </div>
      <div style={{ marginTop: 22 }}>
        {FUNNEL_STAGES.map((s, i) => {
          const v = f ? (f as any)[s.key] || 0 : 0
          const ratio = top > 0 ? v / top : 0
          const stepRatio =
            i > 0 && f
              ? (f as any)[s.key] / Math.max((f as any)[FUNNEL_STAGES[i - 1].key] || 1, 1)
              : 1
          return (
            <div key={s.key} style={funnelRowStyle}>
              <div style={funnelLabelStyle}>
                <span style={{ color: s.color, fontFamily: FONT_MONO, marginRight: 8 }}>
                  {String(i + 1).padStart(2, '0')}
                </span>
                <span style={{ color: COLORS.text, fontWeight: 500 }}>{s.label}</span>
                <span style={{ color: COLORS.textFaint, marginLeft: 8, fontSize: 10, fontFamily: FONT_MONO }}>
                  {s.sub}
                </span>
              </div>
              <div style={funnelBarBoxStyle}>
                <div
                  style={{
                    ...funnelBarStyle,
                    width: `${Math.max(ratio * 100, 1.5)}%`,
                    background: `linear-gradient(90deg, ${s.color}cc, ${s.color}66)`,
                    boxShadow: `0 0 16px ${s.color}55`,
                  }}
                />
                <div style={funnelBarLabelStyle}>
                  <span style={{ color: s.color, fontFamily: FONT_MONO, fontSize: 14 }}>{v}</span>
                  <span style={{ color: COLORS.textFaint, fontFamily: FONT_MONO, fontSize: 10, marginLeft: 8 }}>
                    {(ratio * 100).toFixed(1)}%
                  </span>
                  {i > 0 && (
                    <span
                      style={{
                        color: stepRatio < 0.3 ? COLORS.rose : COLORS.textDim,
                        fontFamily: FONT_MONO,
                        fontSize: 10,
                        marginLeft: 10,
                      }}
                    >
                      ↳ {(stepRatio * 100).toFixed(1)}%
                    </span>
                  )}
                </div>
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
    { key: 'users' as const, label: '最活跃用户', sub: 'TOP CONTRIBUTORS' },
    { key: 'brains' as const, label: '最深大脑', sub: 'DEEPEST BRAINS' },
    { key: 'papers' as const, label: '最多分享', sub: 'MOST READ' },
  ]

  return (
    <section style={panelStyle}>
      <div style={panelHeaderStyle}>
        <div style={sectionLabelStyle}>
          <span style={sectionLabelDot} />
          贡献排行 · LEADERBOARD
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
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
      </div>

      <div style={{ marginTop: 14 }}>
        {tab === 'users' && (
          <BoardList
            rows={(board?.top_users || []).map((u, i) => ({
              rank: i + 1,
              primary: u.username,
              secondary: `用户 · #${u.id}`,
              metric: u.brain_count,
              metricLabel: '个大脑',
              tone: COLORS.cyan,
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
              metricLabel: 'CE',
              tone: COLORS.amber,
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
              tone: COLORS.violet,
              onClick: () => window.open(`/ainstein/api/public/papers/${p.share_token}/pdf`, '_blank'),
            }))}
          />
        )}
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
      <div style={{ padding: '40px 0', textAlign: 'center', color: COLORS.textFaint, fontFamily: FONT_MONO }}>
        — 暂无数据 —
      </div>
    )
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {rows.map((r) => (
        <div
          key={r.rank}
          onClick={r.onClick}
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

// ============================================================
// 工具
// ============================================================
function formatClock(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getUTCFullYear()}.${pad(d.getUTCMonth() + 1)}.${pad(d.getUTCDate())} · ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`
}

function StyleTag() {
  return (
    <style>{`
      @keyframes ainstein-pulse {
        0%, 100% { opacity: 0.5; }
        50% { opacity: 1; }
      }
      @keyframes ainstein-scan {
        0% { transform: translateY(-100%); }
        100% { transform: translateY(100%); }
      }
      .ad-fade-in {
        animation: ainstein-fade 0.6s ease-out both;
      }
      @keyframes ainstein-fade {
        from { opacity: 0; transform: translateY(8px); }
        to { opacity: 1; transform: translateY(0); }
      }
    `}</style>
  )
}

// ============================================================
// 样式（CSSProperties）
// ============================================================
const pageStyle: CSSProperties = {
  minHeight: '100vh',
  background: `radial-gradient(ellipse at 20% 0%, ${COLORS.bg1} 0%, ${COLORS.bg0} 60%)`,
  color: COLORS.text,
  fontFamily: FONT_BODY,
  position: 'relative',
  overflow: 'hidden',
  padding: '0 36px 64px',
}

const gridBg: CSSProperties = {
  position: 'fixed',
  inset: 0,
  backgroundImage:
    'linear-gradient(rgba(123,227,211,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(123,227,211,0.05) 1px, transparent 1px)',
  backgroundSize: '64px 64px',
  pointerEvents: 'none',
  zIndex: 0,
}

const vignette: CSSProperties = {
  position: 'fixed',
  inset: 0,
  background:
    'radial-gradient(ellipse at center, transparent 30%, rgba(0,0,0,0.55) 100%)',
  pointerEvents: 'none',
  zIndex: 1,
}

const scanlines: CSSProperties = {
  position: 'fixed',
  inset: 0,
  backgroundImage:
    'repeating-linear-gradient(0deg, rgba(255,255,255,0.015) 0px, rgba(255,255,255,0.015) 1px, transparent 1px, transparent 3px)',
  pointerEvents: 'none',
  mixBlendMode: 'overlay',
  zIndex: 2,
}

const topBarStyle: CSSProperties = {
  position: 'relative',
  zIndex: 5,
  height: 56,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  borderBottom: `1px solid ${COLORS.border}`,
  marginBottom: 28,
  fontFamily: FONT_MONO,
  fontSize: 12,
}

const crumbBtnStyle: CSSProperties = {
  background: 'transparent',
  border: `1px solid ${COLORS.border}`,
  color: COLORS.textDim,
  padding: '6px 12px',
  fontFamily: FONT_MONO,
  fontSize: 11,
  letterSpacing: 1.5,
  cursor: 'pointer',
  borderRadius: 0,
}

const topDividerStyle: CSSProperties = {
  display: 'inline-block',
  width: 1,
  height: 14,
  background: COLORS.border,
}

const topTagStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  color: COLORS.textDim,
  letterSpacing: 2,
}

const topDotStyle: CSSProperties = {
  width: 8,
  height: 8,
  borderRadius: '50%',
  background: COLORS.cyan,
  boxShadow: `0 0 8px ${COLORS.cyan}`,
  animation: 'ainstein-pulse 2s ease-in-out infinite',
}

const topClockStyle: CSSProperties = {
  color: COLORS.cyan,
  fontFamily: FONT_MONO,
  letterSpacing: 1.5,
  fontSize: 11,
}

const topUserStyle: CSSProperties = {
  fontFamily: FONT_MONO,
  letterSpacing: 1,
  fontSize: 11,
}

const errorBarStyle: CSSProperties = {
  position: 'relative',
  zIndex: 5,
  padding: '10px 14px',
  marginBottom: 18,
  background: 'rgba(251,113,133,0.08)',
  border: '1px solid rgba(251,113,133,0.4)',
  color: COLORS.text,
  fontFamily: FONT_MONO,
  fontSize: 12,
}

const sectionLabelStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 10,
  color: COLORS.textDim,
  fontFamily: FONT_MONO,
  fontSize: 11,
  letterSpacing: 2.5,
  textTransform: 'uppercase',
}

const sectionLabelDot: CSSProperties = {
  width: 6,
  height: 6,
  background: COLORS.amber,
  display: 'inline-block',
  boxShadow: `0 0 8px ${COLORS.amber}`,
}

const northStarStyle: CSSProperties = {
  position: 'relative',
  zIndex: 5,
  display: 'grid',
  gridTemplateColumns: '1fr auto',
  alignItems: 'center',
  gap: 32,
  padding: '36px 40px',
  background:
    'linear-gradient(135deg, rgba(246,193,121,0.06) 0%, rgba(123,227,211,0.04) 100%)',
  border: `1px solid ${COLORS.borderHot}`,
  marginBottom: 28,
}

const northStarLeftStyle: CSSProperties = { minWidth: 0 }
const northStarRightStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
}

const northStarKickerStyle: CSSProperties = {
  color: COLORS.textDim,
  fontSize: 13,
  letterSpacing: 1.5,
}

const northStarValueWrapStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'baseline',
  gap: 8,
  marginTop: 8,
}

const northStarValueStyle: CSSProperties = {
  fontFamily: FONT_DISPLAY,
  fontSize: 110,
  lineHeight: 0.9,
  fontWeight: 400,
  letterSpacing: -2,
  color: COLORS.amber,
  textShadow: `0 0 28px ${COLORS.amber}55`,
}

const northStarUnitStyle: CSSProperties = {
  fontFamily: FONT_DISPLAY,
  fontSize: 32,
  color: COLORS.textDim,
  letterSpacing: 4,
}

const northStarMetaStyle: CSSProperties = {
  marginTop: 16,
  color: COLORS.textDim,
  fontSize: 13,
  fontFamily: FONT_MONO,
}

const metricsRowStyle: CSSProperties = {
  position: 'relative',
  zIndex: 5,
  display: 'grid',
  gridTemplateColumns: 'repeat(5, 1fr)',
  gap: 14,
  marginBottom: 28,
}

function metricCardStyle(tone: string): CSSProperties {
  return {
    position: 'relative',
    padding: '20px 18px 22px',
    background: COLORS.panel,
    border: `1px solid ${COLORS.border}`,
    overflow: 'hidden',
    transition: 'border-color 0.3s, transform 0.3s',
  }
}

function metricCornerTL(tone: string): CSSProperties {
  return {
    position: 'absolute',
    top: 0,
    left: 0,
    width: 14,
    height: 14,
    borderTop: `1px solid ${tone}`,
    borderLeft: `1px solid ${tone}`,
  }
}

function metricCornerBR(tone: string): CSSProperties {
  return {
    position: 'absolute',
    bottom: 0,
    right: 0,
    width: 14,
    height: 14,
    borderBottom: `1px solid ${tone}`,
    borderRight: `1px solid ${tone}`,
  }
}

const metricLabelStyle: CSSProperties = {
  fontFamily: FONT_MONO,
  fontSize: 10,
  letterSpacing: 1.6,
  color: COLORS.textDim,
}

function metricValueStyle(tone: string): CSSProperties {
  return {
    fontFamily: FONT_DISPLAY,
    fontSize: 46,
    fontWeight: 400,
    color: tone,
    margin: '14px 0 6px',
    letterSpacing: -1,
    textShadow: `0 0 18px ${tone}33`,
  }
}

const metricFootStyle: CSSProperties = {
  fontFamily: FONT_MONO,
  fontSize: 10,
  color: COLORS.textFaint,
  letterSpacing: 1,
}

const trendsSectionStyle: CSSProperties = {
  position: 'relative',
  zIndex: 5,
  padding: 24,
  background: COLORS.panel,
  border: `1px solid ${COLORS.border}`,
  marginBottom: 28,
}

const trendsHeaderStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  flexWrap: 'wrap',
  gap: 14,
}

const trendsTabsStyle: CSSProperties = {
  display: 'flex',
  gap: 6,
  flexWrap: 'wrap',
}

function trendsTabStyle(active: boolean, color: string): CSSProperties {
  return {
    background: active ? `${color}15` : 'transparent',
    border: `1px solid ${active ? color : COLORS.border}`,
    color: active ? COLORS.text : COLORS.textDim,
    padding: '6px 12px',
    fontFamily: FONT_MONO,
    fontSize: 11,
    letterSpacing: 1,
    cursor: 'pointer',
  }
}

const trendsBodyStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'minmax(220px, 280px) 1fr',
  gap: 24,
  marginTop: 22,
  alignItems: 'center',
}

const trendsLeftStyle: CSSProperties = {
  paddingRight: 24,
  borderRight: `1px solid ${COLORS.border}`,
}

const trendsLegendStyle: CSSProperties = {
  marginTop: 14,
  display: 'flex',
  gap: 16,
  fontFamily: FONT_MONO,
  fontSize: 11,
  color: COLORS.textDim,
}

const trendsRightStyle: CSSProperties = { minWidth: 0 }

const twoColStyle: CSSProperties = {
  position: 'relative',
  zIndex: 5,
  display: 'grid',
  gridTemplateColumns: '1fr 1fr',
  gap: 18,
}

const panelStyle: CSSProperties = {
  padding: 22,
  background: COLORS.panel,
  border: `1px solid ${COLORS.border}`,
  minHeight: 360,
}

const panelHeaderStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  flexWrap: 'wrap',
  gap: 10,
}

const funnelRowStyle: CSSProperties = {
  marginBottom: 14,
}

const funnelLabelStyle: CSSProperties = {
  fontSize: 12,
  marginBottom: 6,
  display: 'flex',
  alignItems: 'baseline',
}

const funnelBarBoxStyle: CSSProperties = {
  position: 'relative',
  height: 30,
  background: COLORS.panelAlt,
  border: `1px solid ${COLORS.border}`,
  overflow: 'hidden',
}

const funnelBarStyle: CSSProperties = {
  position: 'absolute',
  inset: 0,
  height: '100%',
  transition: 'width 0.6s ease-out',
}

const funnelBarLabelStyle: CSSProperties = {
  position: 'absolute',
  inset: 0,
  display: 'flex',
  alignItems: 'center',
  paddingLeft: 12,
}

function leaderTabStyle(active: boolean): CSSProperties {
  return {
    background: active ? 'rgba(123,227,211,0.08)' : 'transparent',
    border: `1px solid ${active ? COLORS.cyan : COLORS.border}`,
    color: active ? COLORS.text : COLORS.textDim,
    padding: '6px 10px',
    fontFamily: FONT_MONO,
    fontSize: 11,
    letterSpacing: 0.5,
    cursor: 'pointer',
  }
}

const boardRowStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 14,
  padding: '10px 12px',
  background: COLORS.panelAlt,
  border: `1px solid ${COLORS.border}`,
  transition: 'border-color 0.2s, transform 0.2s',
}

function boardRankStyle(rank: number, tone: string): CSSProperties {
  return {
    width: 36,
    height: 36,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontFamily: FONT_DISPLAY,
    fontSize: 16,
    color: rank <= 3 ? tone : COLORS.textFaint,
    border: `1px solid ${rank <= 3 ? tone : COLORS.border}`,
    background: rank <= 3 ? `${tone}11` : 'transparent',
  }
}

const boardPrimaryStyle: CSSProperties = {
  color: COLORS.text,
  fontSize: 13,
  fontWeight: 500,
  whiteSpace: 'nowrap',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
}

const boardSecondaryStyle: CSSProperties = {
  color: COLORS.textFaint,
  fontSize: 11,
  fontFamily: FONT_MONO,
  marginTop: 2,
  whiteSpace: 'nowrap',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
}

const boardMetricStyle: CSSProperties = {
  fontFamily: FONT_DISPLAY,
  fontSize: 22,
  letterSpacing: -0.5,
  lineHeight: 1,
}

const boardMetricLabelStyle: CSSProperties = {
  color: COLORS.textFaint,
  fontFamily: FONT_MONO,
  fontSize: 10,
  letterSpacing: 1,
  marginTop: 2,
}

const footerStyle: CSSProperties = {
  position: 'relative',
  zIndex: 5,
  marginTop: 36,
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  padding: '14px 0',
  borderTop: `1px solid ${COLORS.border}`,
  fontSize: 11,
  letterSpacing: 2,
  fontFamily: FONT_MONO,
}
