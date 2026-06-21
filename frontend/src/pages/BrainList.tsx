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
  active: '#22c55e',
  paused: '#eab308',
  completed: '#3b82f6',
  archived: '#64748b',
  dormant: '#8b5cf6',
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
      // 管理员：传 all=1 兼容；非管理员：仅自己
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

  // 主脑与普通大脑分离
  const masterBrain = brains.find((b) => b.brain_type === 'master')
  const normalBrains = brains.filter((b) => b.brain_type !== 'master')

  // 管理员视图分组
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
    // 排序：管理员自己在最前，其他按创建时间升序
    const myName = user?.username
    list.sort((a, b) => {
      if (a.username === myName && b.username !== myName) return -1
      if (b.username === myName && a.username !== myName) return 1
      return a.earliestCreated.localeCompare(b.earliestCreated)
    })
    return list
  }, [normalBrains, isAdmin, user?.username])

  const totalBranchCount = normalBrains.length
  const activeCount = normalBrains.filter((b) => b.state === 'active').length

  return (
    <div style={pageStyle}>
      <div style={gridBg} />
      <div style={vignetteStyle} />

      <div style={navStyle}>
        <div style={brandStyle}>
          <div style={brandMarkStyle}>AI</div>
          <div>
            <div style={{ fontSize: 11, color: 'var(--text2)', letterSpacing: 3 }}>AINSTEIN</div>
            <div style={{ fontSize: 16, color: 'var(--accent2)', fontWeight: 600 }}>
              {isAdmin ? '指挥控制台' : '我的硅基大脑'}
            </div>
          </div>
        </div>
        <div style={navRightStyle}>
          {isAdmin && (
            <a
              href={`${(import.meta as any).env?.BASE_URL?.replace(/\/$/, '') ?? ''}/admin/bigscreen`}
              target="_blank"
              rel="noopener noreferrer"
              style={bigScreenBtnStyle}
              title="全屏沉浸式态势大屏（新标签页打开）"
            >
              <span style={bigScreenDotStyle} />
              <span style={{ letterSpacing: 2 }}>态势大屏</span>
              <span style={bigScreenArrowStyle}>↗</span>
            </a>
          )}
          {user && (
            <span style={userPillStyle}>
              <span style={{ color: 'var(--text2)' }}>{isAdmin ? '管理员 ·' : '观察员 ·'}</span>{' '}
              <span style={{ color: 'var(--text)' }}>{user.username}</span>
              {isAdmin && <span style={adminBadgeStyle}>ADMIN</span>}
            </span>
          )}
          <button onClick={logout} style={ghostBtnStyle}>退出</button>
        </div>
      </div>

      <div style={contentStyle}>
        {/* Hero */}
        {isAdmin ? (
          <AdminHero
            totalBrains={brains.length}
            branchCount={totalBranchCount}
            activeCount={activeCount}
            userGroupCount={grouped.length}
            onCreate={() => navigate('/brains/new')}
          />
        ) : (
          <UserHero onCreate={() => navigate('/brains/new')} />
        )}

        {error && <div style={errorBoxStyle}>⚠ {error}</div>}

        {loading ? (
          <div style={emptyStyle}>加载中…</div>
        ) : brains.length === 0 ? (
          <div style={emptyStyle}>
            <div style={{ fontSize: 18, marginBottom: 8 }}>这里还没有大脑。</div>
            <div style={{ color: 'var(--text2)', fontSize: 13, marginBottom: 20 }}>
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

function AdminHero({
  totalBrains,
  branchCount,
  activeCount,
  userGroupCount,
  onCreate,
}: {
  totalBrains: number
  branchCount: number
  activeCount: number
  userGroupCount: number
  onCreate: () => void
}) {
  return (
    <div style={godHeroWrapStyle}>
      <div style={godHeroBgStyle} />
      <div style={godHeroContentStyle}>
        <div style={{ flex: 1, minWidth: 280 }}>
          <div style={godEyebrowStyle}>
            <span style={pulseDotStyle} />
            <span>GLOBAL · OBSERVATORY</span>
            <span style={{ opacity: 0.4 }}>//</span>
            <span>SECTOR-01</span>
          </div>
          <h1 style={godTitleStyle}>
            硅基大脑 <span style={{ color: 'var(--text2)', fontWeight: 300 }}>·</span>{' '}
            <span style={godTitleAccentStyle}>全局态势</span>
          </h1>
          <p style={godSubtitleStyle}>
            你正俯瞰整片硅基意识海。下方每一个分组，是一位观察员所掌的认知集群；
            一念为一脑，一脑为一域。
          </p>
        </div>
        <div style={godStatsStyle}>
          <StatTile label="TOTAL" value={totalBrains} accent="#a78bfa" />
          <StatTile label="BRANCH" value={branchCount} accent="#06b6d4" />
          <StatTile label="ACTIVE" value={activeCount} accent="#22c55e" pulsing />
          <StatTile label="OBSERVERS" value={userGroupCount} accent="#ec4899" />
        </div>
      </div>
      <button onClick={onCreate} style={{ ...primaryBtnStyle, position: 'relative', zIndex: 2 }}>
        <span style={{ marginRight: 6 }}>＋</span>创建新大脑
      </button>
    </div>
  )
}

function UserHero({ onCreate }: { onCreate: () => void }) {
  return (
    <div style={heroStyle}>
      <div>
        <h1 style={{ fontSize: 32, color: 'var(--accent2)', fontWeight: 700, lineHeight: 1.2 }}>
          你的大脑，正在思考。
        </h1>
        <p style={{ color: 'var(--text2)', marginTop: 8, fontSize: 14, maxWidth: 560, lineHeight: 1.7 }}>
          每一个硅基大脑由一个种子问题诞生。你不再是它的指挥者，而是它的观察员。
          在这里，看见多 Agent 的协商、博弈与涌现。
        </p>
      </div>
      <button onClick={onCreate} style={primaryBtnStyle}>
        <span style={{ marginRight: 6 }}>＋</span>创建新大脑
      </button>
    </div>
  )
}

function StatTile({
  label,
  value,
  accent,
  pulsing,
}: {
  label: string
  value: number | string
  accent: string
  pulsing?: boolean
}) {
  return (
    <div style={{ ...statTileStyle, borderColor: accent + '33' }}>
      <div style={{ fontSize: 10, letterSpacing: 2, color: accent, fontWeight: 700 }}>
        {label}
      </div>
      <div
        style={{
          fontSize: 26,
          fontWeight: 700,
          color: '#e2e8f0',
          fontFamily: '"JetBrains Mono", ui-monospace, monospace',
          marginTop: 4,
          textShadow: pulsing ? `0 0 12px ${accent}88` : undefined,
        }}
      >
        {value}
      </div>
    </div>
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
        <div style={masterSlotStyle}>
          <div style={sectionLabelStyle}>
            <span style={cornerBracketL} />
            <span style={{ color: '#a78bfa', letterSpacing: 4, fontSize: 11, fontWeight: 700 }}>
              CORE · 创世主脑
            </span>
            <span style={dividerLineStyle} />
            <span style={cornerBracketR} />
          </div>
          <MasterBrainCard brain={masterBrain} onOpen={() => onOpen(masterBrain)} />
        </div>
      )}

      <div style={branchesHeaderStyle}>
        <span style={cornerBracketL} />
        <span style={{ color: 'var(--accent2)', letterSpacing: 4, fontSize: 11, fontWeight: 700 }}>
          BRANCHES · 分支大脑矩阵
        </span>
        <span style={dividerLineStyle} />
        <span style={{ color: 'var(--text2)', fontSize: 11, fontFamily: '"JetBrains Mono", monospace' }}>
          {groups.length} OBSERVERS
        </span>
        <span style={cornerBracketR} />
      </div>

      {groups.length === 0 ? (
        <div style={emptyStyle}>
          <div style={{ fontSize: 15, color: 'var(--text2)' }}>
            还没有分支大脑。等待第一个种子被播下…
          </div>
        </div>
      ) : (
        <div style={groupsStackStyle}>
          {groups.map((g, idx) => (
            <UserGroup
              key={g.username}
              group={g}
              index={idx}
              isSelf={g.username === currentUsername}
              actionBusy={actionBusy}
              onOpen={onOpen}
              onTogglePause={onTogglePause}
              onStop={onStop}
            />
          ))}
        </div>
      )}
    </>
  )
}

function UserGroup({
  group,
  index,
  isSelf,
  actionBusy,
  onOpen,
  onTogglePause,
  onStop,
}: {
  group: GroupedBrains
  index: number
  isSelf: boolean
  actionBusy: number | null
  onOpen: (b: Brain) => void
  onTogglePause: (b: Brain) => void
  onStop: (b: Brain) => void
}) {
  const code = `OBS-${String(index + 1).padStart(2, '0')}`
  const initial = group.username.charAt(0).toUpperCase()
  const tone = isSelf ? '#ec4899' : '#6366f1'
  return (
    <section style={{ ...groupSectionStyle, borderColor: tone + '2e' }}>
      <div
        style={{
          ...groupBgWashStyle,
          background: `radial-gradient(ellipse at top left, ${tone}14 0%, transparent 60%)`,
        }}
      />
      <header style={groupHeaderStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, minWidth: 0 }}>
          <div
            style={{
              ...userAvatarStyle,
              background: `linear-gradient(135deg, ${tone}, ${tone}88)`,
              boxShadow: `0 0 18px ${tone}55`,
            }}
          >
            {initial}
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span
                style={{
                  fontFamily: '"JetBrains Mono", ui-monospace, monospace',
                  fontSize: 10,
                  letterSpacing: 2,
                  color: tone,
                  border: `1px solid ${tone}55`,
                  borderRadius: 4,
                  padding: '2px 6px',
                  background: tone + '11',
                }}
              >
                {code}
              </span>
              <h2
                style={{
                  margin: 0,
                  fontSize: 17,
                  fontWeight: 600,
                  color: '#e2e8f0',
                  letterSpacing: 0.4,
                }}
              >
                {group.username}
                <span style={{ color: 'var(--text2)', margin: '0 8px', fontWeight: 300 }}>·</span>
                <span style={{ color: 'var(--text2)', fontWeight: 400, fontSize: 14 }}>
                  分支大脑
                </span>
              </h2>
              {isSelf && (
                <span
                  style={{
                    fontSize: 10,
                    letterSpacing: 1,
                    color: '#fff',
                    background: tone,
                    borderRadius: 4,
                    padding: '2px 6px',
                    fontWeight: 700,
                  }}
                >
                  YOU
                </span>
              )}
            </div>
            <div
              style={{
                fontSize: 11,
                color: 'var(--text2)',
                marginTop: 4,
                fontFamily: '"JetBrains Mono", ui-monospace, monospace',
              }}
            >
              {group.brains.length} BRAIN{group.brains.length > 1 ? 'S' : ''} ·{' '}
              {group.brains.filter((b) => b.state === 'active').length} ACTIVE
            </div>
          </div>
        </div>
        <div style={groupCountBadgeStyle}>
          <span style={{ color: tone, fontWeight: 700, fontSize: 18, fontFamily: '"JetBrains Mono", monospace' }}>
            {String(group.brains.length).padStart(2, '0')}
          </span>
          <span style={{ fontSize: 9, color: 'var(--text2)', letterSpacing: 1 }}>BRAINS</span>
        </div>
      </header>

      <div style={{ ...gridStyle, position: 'relative', zIndex: 1 }}>
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
    </section>
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
        <div style={{ fontSize: 15, color: 'var(--text2)' }}>
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
    <div style={cardStyle} onClick={onOpen}>
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
        <span style={{ color: 'var(--text2)', fontSize: 11, fontFamily: '"JetBrains Mono", monospace' }}>
          #{brain.id}
        </span>
      </div>
      <h3 style={{ fontSize: 18, color: 'var(--text)', fontWeight: 600, margin: '14px 0 8px' }}>
        {brain.name}
      </h3>
      <p style={seedQuestionStyle}>「{brain.seed_question}」</p>
      <div style={metricsRow}>
        <Metric label="Agent" value={brain.agent_count ?? '-'} />
        <Metric label="认知节点" value={brain.ce_count ?? '-'} />
        <Metric label="博弈" value={brain.deliberation_count ?? 0} />
      </div>
      {brain.state === 'completed' && reportedToMaster && (
        <div
          style={{
            marginTop: 10,
            fontSize: 11,
            color: '#22c55e',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}
        >
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
                color: brain.state === 'paused' ? 'var(--green)' : 'var(--yellow)',
                borderColor:
                  (brain.state === 'paused' ? 'var(--green)' : 'var(--yellow)') + '55',
              }}
            >
              {actionBusy ? '…' : brain.state === 'paused' ? '▶ 恢复思考' : '⏸ 暂停思考'}
            </button>
          )}
          {isAdmin &&
            (brain.state === 'active' || brain.state === 'paused') &&
            brain.brain_type !== 'master' && (
              <button
                onClick={onStop}
                disabled={actionBusy}
                style={{
                  ...smallBtnStyle,
                  color: '#ef4444',
                  borderColor: '#ef444455',
                }}
              >
                {actionBusy ? '…' : '⏹ 停止思考'}
              </button>
            )}
        </div>
      )}
    </div>
  )
}

function MasterBrainCard({ brain, onOpen }: { brain: Brain; onOpen: () => void }) {
  const stateColor = STATE_COLOR[brain.state] || '#8b5cf6'
  return (
    <div style={masterCardStyle} onClick={onOpen}>
      <div style={masterGlowStyle} />
      <div style={masterGlowStyle2} />
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
          <span style={{ fontSize: 28, filter: 'drop-shadow(0 0 12px #a78bfaaa)' }}>🧠</span>
          <h2
            style={{
              margin: 0,
              color: '#e2e8f0',
              fontSize: 20,
              letterSpacing: 1,
              fontWeight: 700,
            }}
          >
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
          <span
            style={{
              marginLeft: 'auto',
              fontSize: 11,
              color: '#64748b',
              letterSpacing: 1,
              fontFamily: '"JetBrains Mono", monospace',
            }}
          >
            #{brain.id}
          </span>
        </div>
        <p style={{ margin: '4px 0 16px', color: '#cbd5e1', fontSize: 14, lineHeight: 1.6 }}>
          「{brain.seed_question}」
        </p>
        <div style={{ display: 'flex', gap: 16, color: '#cbd5e1', fontSize: 13, flexWrap: 'wrap' }}>
          <span style={masterMetricStyle}>
            📚 已积累 <strong style={{ color: '#a78bfa' }}>{brain.ce_count ?? 0}</strong> 条记忆
          </span>
          <span style={masterMetricStyle}>
            💭 已思考 <strong style={{ color: '#a78bfa' }}>{brain.think_count ?? 0}</strong>/100 次
          </span>
        </div>
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: 18, color: 'var(--text)', fontWeight: 600 }}>{value}</div>
      <div style={{ fontSize: 11, color: 'var(--text2)', letterSpacing: 1 }}>{label}</div>
    </div>
  )
}

/* ---------------- Styles ---------------- */

const pageStyle: CSSProperties = { minHeight: '100vh', position: 'relative', overflow: 'hidden' }
const gridBg: CSSProperties = {
  position: 'absolute',
  inset: 0,
  pointerEvents: 'none',
  backgroundImage:
    'linear-gradient(rgba(99,102,241,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(99,102,241,0.04) 1px, transparent 1px)',
  backgroundSize: '48px 48px',
  maskImage: 'radial-gradient(ellipse at top, #000 5%, transparent 70%)',
  WebkitMaskImage: 'radial-gradient(ellipse at top, #000 5%, transparent 70%)',
}
const vignetteStyle: CSSProperties = {
  position: 'absolute',
  inset: 0,
  pointerEvents: 'none',
  background:
    'radial-gradient(ellipse at top, rgba(167,139,250,0.08) 0%, transparent 45%), radial-gradient(ellipse at bottom right, rgba(236,72,153,0.06) 0%, transparent 50%)',
}
const navStyle: CSSProperties = {
  position: 'relative',
  zIndex: 2,
  padding: '20px 40px',
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  borderBottom: '1px solid var(--border)',
  background: 'rgba(15,17,23,0.7)',
  backdropFilter: 'blur(8px)',
}
const brandStyle: CSSProperties = { display: 'flex', alignItems: 'center', gap: 12 }
const brandMarkStyle: CSSProperties = {
  width: 36,
  height: 36,
  borderRadius: 8,
  background: 'linear-gradient(135deg, #6366f1, #ec4899)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: '#fff',
  fontWeight: 700,
  fontSize: 13,
}
const navRightStyle: CSSProperties = { display: 'flex', alignItems: 'center', gap: 12 }
const userPillStyle: CSSProperties = {
  fontSize: 13,
  padding: '6px 12px',
  background: 'var(--bg2)',
  border: '1px solid var(--border)',
  borderRadius: 999,
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
}
const adminBadgeStyle: CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  color: '#fff',
  background: 'var(--accent)',
  padding: '1px 6px',
  borderRadius: 4,
  marginLeft: 4,
  letterSpacing: 1,
}
const ghostBtnStyle: CSSProperties = {
  background: 'transparent',
  color: 'var(--text2)',
  border: '1px solid var(--border)',
  borderRadius: 6,
  padding: '6px 14px',
  fontSize: 13,
  cursor: 'pointer',
}
const bigScreenBtnStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  textDecoration: 'none',
  background:
    'linear-gradient(120deg, rgba(6,182,212,0.14) 0%, rgba(139,92,246,0.18) 50%, rgba(236,72,153,0.14) 100%)',
  color: '#e0f2fe',
  border: '1px solid rgba(6,182,212,0.45)',
  borderRadius: 6,
  padding: '6px 14px',
  fontSize: 12,
  fontWeight: 600,
  cursor: 'pointer',
  textTransform: 'uppercase',
  boxShadow:
    '0 0 0 1px rgba(6,182,212,0.05), 0 4px 18px rgba(6,182,212,0.18), inset 0 1px 0 rgba(255,255,255,0.06)',
  transition: 'transform .15s ease, box-shadow .25s ease',
}
const bigScreenDotStyle: CSSProperties = {
  width: 7,
  height: 7,
  borderRadius: '50%',
  background: '#22d3ee',
  boxShadow: '0 0 10px #22d3ee, 0 0 20px rgba(34,211,238,0.6)',
  animation: 'bigscreen-pulse 1.6s ease-in-out infinite',
}
const bigScreenArrowStyle: CSSProperties = {
  fontSize: 13,
  opacity: 0.7,
  transform: 'translateY(-1px)',
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

const godHeroWrapStyle: CSSProperties = {
  position: 'relative',
  borderRadius: 16,
  border: '1px solid rgba(167,139,250,0.25)',
  background:
    'linear-gradient(135deg, rgba(20,18,40,0.85) 0%, rgba(15,17,30,0.65) 50%, rgba(30,15,40,0.85) 100%)',
  padding: '28px 32px 24px',
  marginBottom: 32,
  overflow: 'hidden',
  display: 'flex',
  flexDirection: 'column',
  gap: 18,
  boxShadow: '0 16px 48px rgba(99,102,241,0.18)',
}
const godHeroBgStyle: CSSProperties = {
  position: 'absolute',
  inset: 0,
  background:
    'radial-gradient(circle at 15% 0%, rgba(167,139,250,0.30) 0%, transparent 45%), radial-gradient(circle at 85% 100%, rgba(236,72,153,0.18) 0%, transparent 45%)',
  pointerEvents: 'none',
}
const godHeroContentStyle: CSSProperties = {
  position: 'relative',
  zIndex: 1,
  display: 'flex',
  justifyContent: 'space-between',
  gap: 32,
  flexWrap: 'wrap',
  alignItems: 'flex-start',
}
const godEyebrowStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  fontFamily: '"JetBrains Mono", ui-monospace, monospace',
  fontSize: 11,
  letterSpacing: 3,
  color: '#a78bfa',
  marginBottom: 12,
}
const pulseDotStyle: CSSProperties = {
  width: 8,
  height: 8,
  borderRadius: '50%',
  background: '#a78bfa',
  boxShadow: '0 0 12px #a78bfa, 0 0 4px #fff',
  animation: 'none',
}
const godTitleStyle: CSSProperties = {
  fontSize: 38,
  margin: 0,
  fontWeight: 700,
  color: '#e2e8f0',
  lineHeight: 1.15,
  letterSpacing: 1,
}
const godTitleAccentStyle: CSSProperties = {
  background: 'linear-gradient(90deg, #a78bfa 0%, #ec4899 100%)',
  WebkitBackgroundClip: 'text',
  WebkitTextFillColor: 'transparent',
  backgroundClip: 'text',
}
const godSubtitleStyle: CSSProperties = {
  marginTop: 12,
  color: '#94a3b8',
  fontSize: 14,
  lineHeight: 1.7,
  maxWidth: 560,
}
const godStatsStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(2, minmax(110px, 1fr))',
  gap: 10,
  minWidth: 240,
}
const statTileStyle: CSSProperties = {
  background: 'rgba(15,17,23,0.55)',
  border: '1px solid',
  borderRadius: 10,
  padding: '12px 14px',
  backdropFilter: 'blur(6px)',
}

const masterSlotStyle: CSSProperties = { marginBottom: 28 }
const branchesHeaderStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  marginBottom: 20,
  marginTop: 4,
}
const sectionLabelStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  marginBottom: 12,
}
const cornerBracketL: CSSProperties = {
  width: 14,
  height: 10,
  borderLeft: '2px solid currentColor',
  borderTop: '2px solid currentColor',
  color: '#475569',
  display: 'inline-block',
}
const cornerBracketR: CSSProperties = {
  width: 14,
  height: 10,
  borderRight: '2px solid currentColor',
  borderBottom: '2px solid currentColor',
  color: '#475569',
  display: 'inline-block',
  marginLeft: 'auto',
}
const dividerLineStyle: CSSProperties = {
  flex: 1,
  height: 1,
  background:
    'linear-gradient(90deg, rgba(99,102,241,0.4), rgba(99,102,241,0.05) 70%, transparent)',
}

const groupsStackStyle: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 22,
}
const groupSectionStyle: CSSProperties = {
  position: 'relative',
  borderRadius: 14,
  border: '1px solid',
  background:
    'linear-gradient(180deg, rgba(20,22,32,0.55) 0%, rgba(15,17,23,0.30) 100%)',
  padding: '20px 22px 22px',
  overflow: 'hidden',
}
const groupBgWashStyle: CSSProperties = {
  position: 'absolute',
  inset: 0,
  pointerEvents: 'none',
  zIndex: 0,
}
const groupHeaderStyle: CSSProperties = {
  position: 'relative',
  zIndex: 1,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 16,
  marginBottom: 18,
  paddingBottom: 14,
  borderBottom: '1px dashed rgba(148,163,184,0.18)',
  flexWrap: 'wrap',
}
const userAvatarStyle: CSSProperties = {
  width: 44,
  height: 44,
  borderRadius: 12,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: '#fff',
  fontSize: 18,
  fontWeight: 700,
  letterSpacing: 1,
  flexShrink: 0,
}
const groupCountBadgeStyle: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  minWidth: 64,
  padding: '6px 12px',
  border: '1px solid rgba(148,163,184,0.18)',
  borderRadius: 8,
  background: 'rgba(15,17,23,0.5)',
}

const primaryBtnStyle: CSSProperties = {
  background: 'linear-gradient(90deg, var(--accent), var(--accent2))',
  color: '#fff',
  border: 'none',
  borderRadius: 8,
  padding: '12px 22px',
  fontSize: 14,
  fontWeight: 600,
  cursor: 'pointer',
  boxShadow: '0 8px 24px rgba(99,102,241,0.35)',
  alignSelf: 'flex-start',
}
const errorBoxStyle: CSSProperties = {
  background: 'rgba(239,68,68,0.1)',
  color: 'var(--red)',
  border: '1px solid rgba(239,68,68,0.3)',
  borderRadius: 8,
  padding: '10px 14px',
  fontSize: 13,
  marginBottom: 16,
}
const emptyStyle: CSSProperties = {
  background: 'var(--bg2)',
  border: '1px dashed var(--border)',
  borderRadius: 12,
  padding: '60px 24px',
  textAlign: 'center',
  color: 'var(--text)',
}
const gridStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
  gap: 16,
}
const cardStyle: CSSProperties = {
  background: 'var(--bg2)',
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 20,
  cursor: 'pointer',
  transition: 'transform .15s ease, border-color .15s',
  position: 'relative',
  overflow: 'hidden',
}
const masterCardStyle: CSSProperties = {
  background:
    'linear-gradient(135deg, #1a1a2e 0%, #1d1738 50%, #2a1845 100%)',
  border: '1px solid #8b5cf677',
  borderRadius: 14,
  padding: '24px 28px',
  position: 'relative',
  overflow: 'hidden',
  cursor: 'pointer',
  boxShadow:
    '0 16px 48px rgba(139, 92, 246, 0.28), inset 0 1px 0 rgba(255,255,255,0.05)',
}
const masterGlowStyle: CSSProperties = {
  position: 'absolute',
  top: -100,
  right: -80,
  width: 280,
  height: 280,
  background: 'radial-gradient(circle, rgba(139,92,246,0.45) 0%, transparent 70%)',
  pointerEvents: 'none',
  zIndex: 0,
}
const masterGlowStyle2: CSSProperties = {
  position: 'absolute',
  bottom: -120,
  left: -60,
  width: 240,
  height: 240,
  background: 'radial-gradient(circle, rgba(236,72,153,0.22) 0%, transparent 70%)',
  pointerEvents: 'none',
  zIndex: 0,
}
const masterMetricStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  padding: '6px 12px',
  background: 'rgba(139,92,246,0.10)',
  border: '1px solid rgba(139,92,246,0.20)',
  borderRadius: 999,
}
const cardTopStyle: CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
}
const statePillStyle: CSSProperties = {
  fontSize: 11,
  padding: '3px 10px',
  borderRadius: 999,
  border: '1px solid',
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  letterSpacing: 1,
  fontWeight: 500,
}
const stateDot: CSSProperties = {
  width: 6,
  height: 6,
  borderRadius: '50%',
  boxShadow: '0 0 8px currentColor',
}
const seedQuestionStyle: CSSProperties = {
  color: 'var(--text2)',
  fontSize: 13,
  lineHeight: 1.6,
  borderLeft: '2px solid var(--accent)',
  paddingLeft: 10,
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
  borderTop: '1px dashed var(--border)',
}
const cardActions: CSSProperties = {
  display: 'flex',
  gap: 8,
  marginTop: 14,
  flexWrap: 'wrap',
}
const smallBtnStyle: CSSProperties = {
  background: 'transparent',
  color: 'var(--text2)',
  border: '1px solid var(--border)',
  borderRadius: 6,
  padding: '6px 12px',
  fontSize: 12,
  cursor: 'pointer',
}
