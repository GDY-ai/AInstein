import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  api,
  getStoredUser,
  getToken,
  setStoredUser,
  setToken,
} from '../api'
import type { Brain, User } from '../types'
import { track } from '../tracking'
import AdminNav from '../components/AdminNav'

/* ============================================================
 * BrainList · 我的大脑
 *  统一深空风：青蓝主调 + 320px 卡片 + 18px 间距
 * ============================================================ */

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

const STATE_LABEL: Record<string, string> = {
  gestating: '孕育中',
  active: '思考中',
  paused: '已暂停',
  completed: '已完成',
  archived: '已归档',
  dormant: '休眠中',
}

const STATE_COLOR: Record<string, string> = {
  gestating: '#94a3b8',
  active: '#4fd1c5',
  paused: AMBER,
  completed: ACCENT_2,
  archived: '#64748b',
  dormant: '#7aa3d6',
}

interface GroupedBrains {
  username: string
  brains: Brain[]
  earliestCreated: string
}

export default function BrainList() {
  const navigate = useNavigate()
  const [user, setUser] = useState<User | null>(getStoredUser())
  const [brains, setBrains] = useState<Brain[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionBusy, setActionBusy] = useState<number | null>(null)
  const [achievementCount, setAchievementCount] = useState<{ unlocked: number; total: number } | null>(null)

  const isAdmin = (user?.role || '').toLowerCase() === 'admin'

  useEffect(() => {
    if (!getToken()) {
      navigate('/login', { replace: true })
      return
    }
    track('page.view', { page: 'brain_list' })
    refreshUser()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!getToken()) return
    load()
    api.getMyAchievements()
      .then((r) => setAchievementCount({ unlocked: r.unlocked_count, total: r.total }))
      .catch(() => { /* 静默 */ })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin])

  async function refreshUser() {
    try {
      const r = await api.me()
      setUser(r.user)
      setStoredUser(r.user)
    } catch {
      navigate('/login', { replace: true })
    }
  }

  async function load() {
    setLoading(true)
    setError('')
    try {
      const r = await api.listBrains(isAdmin ? { all: true } : {})
      setBrains(r.items || [])
    } catch (e: any) {
      setError(e?.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  async function togglePause(brain: Brain) {
    if (!isAdmin) return
    setActionBusy(brain.id)
    try {
      if (brain.state === 'paused') {
        await api.resumeBrain(brain.id)
      } else {
        await api.pauseBrain(brain.id)
      }
      load()
    } catch (e: any) {
      setError(e?.message || '操作失败')
    } finally {
      setActionBusy(null)
    }
  }

  async function handleStop(brain: Brain) {
    if (!isAdmin) return
    if (!window.confirm('停止后不可恢复，确认终止该大脑的思考？')) return
    setActionBusy(brain.id)
    try {
      await api.stopBrain(brain.id)
      load()
    } catch (e: any) {
      setError(e?.message || '停止失败')
    } finally {
      setActionBusy(null)
    }
  }

  function logout() {
    setToken(null)
    setStoredUser(null)
    navigate('/login', { replace: true })
  }

  const masterBrain = brains.find((b) => b.brain_type === 'master')
  const normalBrains = brains.filter((b) => b.brain_type !== 'master')

  const grouped: GroupedBrains[] = useMemo(() => {
    if (!isAdmin) return []
    const map = new Map<string, Brain[]>()
    for (const b of normalBrains) {
      const key = b.owner_username || '未知用户'
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(b)
    }
    const list: GroupedBrains[] = []
    map.forEach((arr, username) => {
      const earliest = arr
        .map((x) => x.created_at)
        .filter(Boolean)
        .sort()[0] || ''
      list.push({ username, brains: arr, earliestCreated: earliest })
    })
    const myName = user?.username
    list.sort((a, b) => {
      if (a.username === myName && b.username !== myName) return -1
      if (b.username === myName && a.username !== myName) return 1
      return a.earliestCreated.localeCompare(b.earliestCreated)
    })
    return list
  }, [normalBrains, isAdmin, user?.username])

  return (
    <div style={pageStyle}>
      <StyleTag />
      <div style={gridBg} />
      <div style={vignetteStyle} />

      <AdminNav
        active="home"
        showBack={false}
        rightSlot={
          user ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
              <span style={{ letterSpacing: 1 }}>
                <span style={{ color: FAINT }}>{isAdmin ? '管理员' : '观察员'} </span>
                <span style={{ color: TEXT }}>{user.username}</span>
              </span>
              {achievementCount && (
                <span
                  title={`已解锁 ${achievementCount.unlocked} / ${achievementCount.total} 个成就`}
                  style={achievementBadgeStyle}
                >
                  🏆 {achievementCount.unlocked}/{achievementCount.total}
                </span>
              )}
              <button onClick={logout} style={ghostBtnStyle}>退出</button>
            </span>
          ) : null
        }
      />

      <div style={contentStyle}>
        <Hero
          isAdmin={isAdmin}
          username={user?.username}
          onCreate={() => navigate('/brains/new')}
        />

        {error && <div style={errorBoxStyle}>⚠ {error}</div>}

        {loading ? (
          <div style={emptyStyle}>加载中…</div>
        ) : brains.length === 0 ? (
          <div style={emptyStyle}>
            <div style={{ fontSize: 18, marginBottom: 8, color: TEXT }}>这里还没有大脑。</div>
            <div style={{ color: DIM, fontSize: 13, marginBottom: 20 }}>
              提出你的第一个种子问题，开启一段涌现智能的旅程。
            </div>
            <button onClick={() => navigate('/brains/new')} style={primaryBtnStyle}>
              ＋ 创建第一个大脑
            </button>
          </div>
        ) : isAdmin ? (
          <AdminGodView
            masterBrain={masterBrain}
            groups={grouped}
            currentUsername={user?.username}
            actionBusy={actionBusy}
            onOpen={(b) => navigate(`/brain/${b.id}`)}
            onTogglePause={togglePause}
            onStop={handleStop}
          />
        ) : (
          <UserView
            brains={normalBrains}
            user={user}
            actionBusy={actionBusy}
            onOpen={(b) => navigate(`/brain/${b.id}`)}
            onTogglePause={togglePause}
            onStop={handleStop}
          />
        )}
      </div>
    </div>
  )
}

/* ---------------- Hero ---------------- */

function Hero({
  isAdmin,
  username,
  onCreate,
}: {
  isAdmin: boolean
  username?: string
  onCreate: () => void
}) {
  return (
    <header style={heroStyle}>
      <div style={{ flex: 1, minWidth: 280 }}>
        <h1 style={heroTitleStyle}>
          {isAdmin ? '硅基大脑全景' : `你好，${username || '观察员'}`}
        </h1>
        <p style={heroSubStyle}>
          {isAdmin
            ? '俯瞰整片硅基意识海。每一颗大脑由一个种子问题诞生，一念为一脑，一脑为一域。'
            : '你的大脑正在思考。在这里，看见多 Agent 的协商、博弈与涌现。'}
        </p>
      </div>
      <button onClick={onCreate} style={primaryBtnStyle}>
        <span style={{ marginRight: 6 }}>＋</span>创建新大脑
      </button>
    </header>
  )
}

/* ---------------- Admin God View ---------------- */

function AdminGodView({
  masterBrain,
  groups,
  currentUsername,
  actionBusy,
  onOpen,
  onTogglePause,
  onStop,
}: {
  masterBrain: Brain | undefined
  groups: GroupedBrains[]
  currentUsername: string | undefined
  actionBusy: number | null
  onOpen: (b: Brain) => void
  onTogglePause: (b: Brain) => void
  onStop: (b: Brain) => void
}) {
  return (
    <>
      {masterBrain && (
        <section style={sectionStyle}>
          <SectionTitle label="创世主脑" sub={`#${masterBrain.id}`} />
          <MasterBrainCard brain={masterBrain} onOpen={() => onOpen(masterBrain)} />
        </section>
      )}

      <section style={sectionStyle}>
        <SectionTitle
          label="分支大脑矩阵"
          sub={`${groups.length} 位观察员 · ${groups.reduce((acc, g) => acc + g.brains.length, 0)} 个大脑`}
        />

        {groups.length === 0 ? (
          <div style={emptyStyle}>
            <div style={{ fontSize: 14, color: DIM }}>
              还没有分支大脑。等待第一个种子被播下…
            </div>
          </div>
        ) : (
          <div style={groupsStackStyle}>
            {groups.map((g) => (
              <UserGroup
                key={g.username}
                group={g}
                isSelf={g.username === currentUsername}
                actionBusy={actionBusy}
                onOpen={onOpen}
                onTogglePause={onTogglePause}
                onStop={onStop}
              />
            ))}
          </div>
        )}
      </section>
    </>
  )
}

function UserGroup({
  group,
  isSelf,
  actionBusy,
  onOpen,
  onTogglePause,
  onStop,
}: {
  group: GroupedBrains
  isSelf: boolean
  actionBusy: number | null
  onOpen: (b: Brain) => void
  onTogglePause: (b: Brain) => void
  onStop: (b: Brain) => void
}) {
  const activeCount = group.brains.filter((b) => b.state === 'active').length
  return (
    <div style={groupSectionStyle}>
      <div style={groupHeaderStyle}>
        <span style={groupBadgeStyle}>{group.username.charAt(0).toUpperCase()}</span>
        <span style={{ color: TEXT, fontSize: 14, fontWeight: 500, letterSpacing: 0.5 }}>
          {group.username}
        </span>
        {isSelf && <span style={selfTagStyle}>本人</span>}
        <span style={{ color: FAINT, margin: '0 4px' }}>·</span>
        <span style={{ color: DIM, fontSize: 12, fontFamily: FONT_MONO }}>
          {group.brains.length} 个大脑 · {activeCount} 个思考中
        </span>
      </div>

      <div style={gridStyle}>
        {group.brains.map((b) => (
          <BrainCard
            key={b.id}
            brain={b}
            isAdmin={true}
            isOwner={false}
            actionBusy={actionBusy === b.id}
            onOpen={() => onOpen(b)}
            onTogglePause={() => onTogglePause(b)}
            onStop={() => onStop(b)}
          />
        ))}
      </div>
    </div>
  )
}

/* ---------------- Plain User View ---------------- */

function UserView({
  brains,
  user,
  actionBusy,
  onOpen,
  onTogglePause,
  onStop,
}: {
  brains: Brain[]
  user: User | null
  actionBusy: number | null
  onOpen: (b: Brain) => void
  onTogglePause: (b: Brain) => void
  onStop: (b: Brain) => void
}) {
  if (brains.length === 0) {
    return (
      <div style={emptyStyle}>
        <div style={{ fontSize: 14, color: DIM }}>
          还没有分支大脑，创建一个去探索一个具体问题吧。
        </div>
      </div>
    )
  }
  return (
    <div style={gridStyle}>
      {brains.map((b) => (
        <BrainCard
          key={b.id}
          brain={b}
          isAdmin={false}
          isOwner={!!user && b.owner_user_id === user.id}
          actionBusy={actionBusy === b.id}
          onOpen={() => onOpen(b)}
          onTogglePause={() => onTogglePause(b)}
          onStop={() => onStop(b)}
        />
      ))}
    </div>
  )
}

/* ---------------- BrainCard ---------------- */

function SectionTitle({ label, sub }: { label: string; sub?: string }) {
  return (
    <div style={sectionTitleStyle}>
      <span style={sectionTitleDot} />
      <span style={{ color: TEXT, fontSize: 14, fontWeight: 600, letterSpacing: 1 }}>{label}</span>
      {sub && (
        <span style={{ color: FAINT, fontSize: 11, fontFamily: FONT_MONO, letterSpacing: 1.5 }}>
          {sub}
        </span>
      )}
      <span style={sectionTitleLine} />
    </div>
  )
}

function BrainCard({
  brain,
  isAdmin,
  isOwner,
  actionBusy,
  onOpen,
  onTogglePause,
  onStop,
}: {
  brain: Brain
  isAdmin: boolean
  isOwner: boolean
  actionBusy: boolean
  onOpen: () => void
  onTogglePause: () => void
  onStop: () => void
}) {
  const stateColor = STATE_COLOR[brain.state] || '#64748b'
  const reportedToMaster = (() => {
    const cfg = brain.config as any
    if (cfg && typeof cfg === 'object' && 'reported_to_master' in cfg) {
      return Boolean(cfg.reported_to_master)
    }
    if (brain.config_json) {
      try {
        const parsed = JSON.parse(brain.config_json)
        return Boolean(parsed?.reported_to_master)
      } catch {
        return false
      }
    }
    return false
  })()
  return (
    <div className="ainstein-brain-card" style={cardStyle} onClick={onOpen}>
      <div style={cardTopStyle}>
        <span
          style={{
            ...statePillStyle,
            color: stateColor,
            borderColor: stateColor + '66',
            background: stateColor + '14',
          }}
        >
          <span style={{ ...stateDot, background: stateColor }} />{' '}
          {STATE_LABEL[brain.state] || brain.state}
        </span>
        <span style={{ color: FAINT, fontSize: 11, fontFamily: FONT_MONO }}>#{brain.id}</span>
      </div>
      <h3 style={cardTitleStyle}>{brain.name}</h3>
      <p style={seedQuestionStyle}>「{brain.seed_question}」</p>
      <div style={metricsRow}>
        <Metric label="智能体" value={brain.agent_count ?? '-'} />
        <Metric label="认知节点" value={brain.ce_count ?? '-'} />
        <Metric label="博弈" value={brain.deliberation_count ?? 0} />
      </div>
      {brain.state === 'completed' && reportedToMaster && (
        <div style={{ marginTop: 10, fontSize: 11, color: ACCENT, display: 'flex', alignItems: 'center', gap: 4 }}>
          已上报主脑 ✓
        </div>
      )}
      {(isAdmin || isOwner) && (
        <div style={cardActions} onClick={(e) => e.stopPropagation()}>
          <button onClick={onOpen} style={smallBtnStyle}>查看图谱</button>
          {isAdmin && brain.state !== 'completed' && brain.state !== 'archived' && (
            <button
              onClick={onTogglePause}
              disabled={actionBusy}
              style={{
                ...smallBtnStyle,
                color: brain.state === 'paused' ? ACCENT : AMBER,
                borderColor: (brain.state === 'paused' ? ACCENT : AMBER) + '55',
              }}
            >
              {actionBusy ? '…' : brain.state === 'paused' ? '▶ 恢复' : '⏸ 暂停'}
            </button>
          )}
          {isAdmin &&
            (brain.state === 'active' || brain.state === 'paused') &&
            brain.brain_type !== 'master' && (
              <button
                onClick={onStop}
                disabled={actionBusy}
                style={{ ...smallBtnStyle, color: '#fb7185', borderColor: '#fb718555' }}
              >
                {actionBusy ? '…' : '⏹ 停止'}
              </button>
            )}
        </div>
      )}
    </div>
  )
}

function MasterBrainCard({ brain, onOpen }: { brain: Brain; onOpen: () => void }) {
  const stateColor = STATE_COLOR[brain.state] || ACCENT
  return (
    <div className="ainstein-master-card" style={masterCardStyle} onClick={onOpen}>
      <div style={masterGlowStyle} />
      <div style={{ position: 'relative', zIndex: 1 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            marginBottom: 10,
            flexWrap: 'wrap',
          }}
        >
          <span style={{ fontSize: 24, filter: `drop-shadow(0 0 10px ${ACCENT}aa)` }}>🧠</span>
          <h2 style={{ margin: 0, color: TEXT, fontSize: 20, letterSpacing: 1, fontWeight: 600 }}>
            创世主脑
          </h2>
          <span
            style={{
              fontSize: 11,
              padding: '2px 8px',
              borderRadius: 4,
              background: stateColor + '22',
              color: stateColor,
              border: `1px solid ${stateColor}44`,
              letterSpacing: 1,
            }}
          >
            {STATE_LABEL[brain.state] || brain.state}
          </span>
          <span style={{ marginLeft: 'auto', fontSize: 11, color: FAINT, fontFamily: FONT_MONO }}>
            #{brain.id}
          </span>
        </div>
        <p style={{ margin: '4px 0 16px', color: '#cbd5e1', fontSize: 14, lineHeight: 1.6 }}>
          「{brain.seed_question}」
        </p>
        <div style={{ display: 'flex', gap: 12, color: '#cbd5e1', fontSize: 13, flexWrap: 'wrap' }}>
          <span style={masterMetricStyle}>
            📚 已积累 <strong style={{ color: ACCENT }}>{brain.ce_count ?? 0}</strong> 条记忆
          </span>
          <span style={masterMetricStyle}>
            💭 已思考 <strong style={{ color: ACCENT }}>{brain.think_count ?? 0}</strong>/100 次
          </span>
        </div>
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: 17, color: TEXT, fontWeight: 600 }}>{value}</div>
      <div style={{ fontSize: 10, color: FAINT, letterSpacing: 1.5, fontFamily: FONT_MONO, marginTop: 2 }}>
        {label}
      </div>
    </div>
  )
}

/* ---------------- Styles ---------------- */

const pageStyle: CSSProperties = {
  minHeight: '100vh',
  position: 'relative',
  overflow: 'hidden',
  fontFamily: FONT_BODY,
  color: TEXT,
  background: 'radial-gradient(ellipse at top, #0f1729 0%, #0a0e1a 55%, #05070f 100%)',
}
const gridBg: CSSProperties = {
  position: 'fixed',
  inset: 0,
  pointerEvents: 'none',
  backgroundImage:
    'linear-gradient(rgba(79,209,197,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(79,209,197,0.04) 1px, transparent 1px)',
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

const achievementBadgeStyle: CSSProperties = {
  fontSize: 11,
  fontWeight: 600,
  color: AMBER,
  background: 'rgba(246, 193, 121, 0.10)',
  border: `1px solid ${AMBER}55`,
  padding: '2px 8px',
  borderRadius: 4,
  letterSpacing: 0.5,
  whiteSpace: 'nowrap',
  fontFamily: FONT_BODY,
}

const ghostBtnStyle: CSSProperties = {
  background: 'transparent',
  color: DIM,
  border: `1px solid ${BORDER}`,
  borderRadius: 4,
  padding: '5px 12px',
  fontSize: 12,
  cursor: 'pointer',
  fontFamily: FONT_BODY,
  letterSpacing: 1,
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

const sectionStyle: CSSProperties = { marginBottom: 28 }

const sectionTitleStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  marginBottom: 16,
}
const sectionTitleDot: CSSProperties = {
  width: 6,
  height: 6,
  background: ACCENT,
  boxShadow: `0 0 8px ${ACCENT}`,
  borderRadius: '50%',
}
const sectionTitleLine: CSSProperties = {
  flex: 1,
  height: 1,
  background:
    'linear-gradient(90deg, rgba(79,209,197,0.25), rgba(79,209,197,0.04) 70%, transparent)',
}

const groupsStackStyle: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 26,
}
const groupSectionStyle: CSSProperties = {
  position: 'relative',
}
const groupHeaderStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  marginBottom: 14,
  flexWrap: 'wrap',
}
const groupBadgeStyle: CSSProperties = {
  width: 26,
  height: 26,
  borderRadius: 4,
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: 'rgba(79, 209, 197, 0.10)',
  border: `1px solid ${BORDER_HOT}`,
  color: ACCENT,
  fontSize: 12,
  fontWeight: 700,
  fontFamily: FONT_MONO,
}
const selfTagStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: 1,
  color: '#0a0e1a',
  background: ACCENT,
  borderRadius: 3,
  padding: '2px 6px',
  fontWeight: 700,
}

const primaryBtnStyle: CSSProperties = {
  background: `linear-gradient(120deg, ${ACCENT}, ${ACCENT_2})`,
  color: '#0a0e1a',
  border: 'none',
  borderRadius: 6,
  padding: '11px 22px',
  fontSize: 13,
  fontWeight: 700,
  letterSpacing: 1,
  cursor: 'pointer',
  boxShadow: `0 8px 24px ${ACCENT}33`,
  fontFamily: FONT_BODY,
}
const errorBoxStyle: CSSProperties = {
  background: 'rgba(251,113,133,0.08)',
  color: '#fb7185',
  border: '1px solid rgba(251,113,133,0.3)',
  borderRadius: 6,
  padding: '10px 14px',
  fontSize: 13,
  marginBottom: 16,
}
const emptyStyle: CSSProperties = {
  background: 'rgba(10, 14, 26, 0.6)',
  border: `1px dashed ${BORDER}`,
  borderRadius: 10,
  padding: '60px 24px',
  textAlign: 'center',
  color: TEXT,
}
const gridStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
  gap: 18,
}
const cardStyle: CSSProperties = {
  background: 'rgba(10, 14, 26, 0.75)',
  border: `1px solid ${BORDER}`,
  borderRadius: 10,
  padding: 20,
  cursor: 'pointer',
  transition: 'transform .2s ease, border-color .2s ease, box-shadow .25s ease',
  position: 'relative',
  overflow: 'hidden',
}
const masterCardStyle: CSSProperties = {
  background:
    'linear-gradient(135deg, rgba(15, 22, 38, 0.90) 0%, rgba(10, 14, 26, 0.90) 50%, rgba(15, 26, 38, 0.90) 100%)',
  border: `1px solid ${BORDER_HOT}`,
  borderRadius: 12,
  padding: '24px 28px',
  position: 'relative',
  overflow: 'hidden',
  cursor: 'pointer',
  boxShadow: `0 16px 48px rgba(79, 209, 197, 0.15), inset 0 1px 0 rgba(255,255,255,0.04)`,
  transition: 'border-color .2s ease, transform .2s ease',
}
const masterGlowStyle: CSSProperties = {
  position: 'absolute',
  top: -120,
  right: -100,
  width: 320,
  height: 320,
  background: `radial-gradient(circle, ${ACCENT}26 0%, transparent 70%)`,
  pointerEvents: 'none',
  zIndex: 0,
}
const masterMetricStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  padding: '6px 12px',
  background: 'rgba(79, 209, 197, 0.08)',
  border: `1px solid ${BORDER_HOT}`,
  borderRadius: 4,
  fontFamily: FONT_BODY,
}
const cardTopStyle: CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
}
const cardTitleStyle: CSSProperties = {
  fontSize: 17,
  color: TEXT,
  fontWeight: 600,
  margin: '14px 0 8px',
  letterSpacing: 0.3,
  lineHeight: 1.35,
  display: '-webkit-box',
  WebkitLineClamp: 2,
  WebkitBoxOrient: 'vertical',
  overflow: 'hidden',
}
const statePillStyle: CSSProperties = {
  fontSize: 11,
  padding: '3px 10px',
  borderRadius: 4,
  border: '1px solid',
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  letterSpacing: 1,
  fontWeight: 500,
  fontFamily: FONT_BODY,
}
const stateDot: CSSProperties = {
  width: 6,
  height: 6,
  borderRadius: '50%',
  boxShadow: '0 0 8px currentColor',
}
const seedQuestionStyle: CSSProperties = {
  color: DIM,
  fontSize: 13,
  lineHeight: 1.6,
  borderLeft: `2px solid ${ACCENT}66`,
  paddingLeft: 10,
  margin: 0,
  display: '-webkit-box',
  WebkitLineClamp: 3,
  WebkitBoxOrient: 'vertical',
  overflow: 'hidden',
}
const metricsRow: CSSProperties = {
  display: 'flex',
  gap: 8,
  marginTop: 18,
  paddingTop: 14,
  borderTop: `1px dashed ${BORDER}`,
}
const cardActions: CSSProperties = {
  display: 'flex',
  gap: 8,
  marginTop: 14,
  flexWrap: 'wrap',
}
const smallBtnStyle: CSSProperties = {
  background: 'transparent',
  color: DIM,
  border: `1px solid ${BORDER}`,
  borderRadius: 4,
  padding: '5px 12px',
  fontSize: 12,
  cursor: 'pointer',
  fontFamily: FONT_BODY,
  letterSpacing: 0.5,
}

function StyleTag() {
  return (
    <style>{`
      .ainstein-brain-card:hover {
        transform: translateY(-2px);
        border-color: ${BORDER_HOT} !important;
        box-shadow: 0 12px 32px rgba(0,0,0,0.4), 0 0 0 1px rgba(79,209,197,0.10);
      }
      .ainstein-master-card:hover {
        transform: translateY(-2px);
        border-color: rgba(79, 209, 197, 0.45) !important;
      }
    `}</style>
  )
}
