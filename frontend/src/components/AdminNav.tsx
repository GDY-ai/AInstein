import { type CSSProperties } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'

/* ============================================================
 * AdminNav · 统一深空风导航
 *  在 态势大屏 / 发现广场 / 运营仪表盘 三页顶部使用。
 *  美学：深色毛玻璃 + 青蓝强调 + 等宽编号
 * ============================================================ */

export type AdminNavKey = 'bigscreen' | 'discoveries' | 'dashboard'

interface Props {
  active: AdminNavKey
  /** 是否使用绝对定位浮在画布上（用于 BigScreen 这种全屏 canvas 页） */
  floating?: boolean
  /** 右侧附加内容（如时钟、用户信息） */
  rightSlot?: React.ReactNode
}

const NAV_ITEMS: Array<{ key: AdminNavKey; label: string; sub: string; path: string; idx: string }> = [
  { key: 'bigscreen', label: '态势大屏', sub: 'TOPOLOGY', path: '/admin/bigscreen', idx: '01' },
  { key: 'discoveries', label: '发现广场', sub: 'DISCOVERY', path: '/discoveries', idx: '02' },
  { key: 'dashboard', label: '运营仪表盘', sub: 'OPERATIONS', path: '/admin/dashboard', idx: '03' },
]

const FONT_MONO = '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace'
const FONT_BODY =
  '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif'

const ACCENT = '#4fd1c5'
const ACCENT_2 = '#63b3ed'
const TEXT = '#dce6f5'
const DIM = '#7a8da8'
const FAINT = '#475569'

export default function AdminNav({ active, floating = false, rightSlot }: Props) {
  const navigate = useNavigate()
  const location = useLocation()

  return (
    <nav style={floating ? floatingWrapStyle : staticWrapStyle}>
      <style>{`
        .ainstein-nav-link { transition: color .2s ease, background .2s ease, border-color .2s ease; }
        .ainstein-nav-link:hover { color: ${TEXT} !important; border-color: rgba(99,179,237,.45) !important; }
        .ainstein-nav-link[data-active="true"]::after {
          content: '';
          position: absolute;
          left: 14px; right: 14px; bottom: -1px;
          height: 1px;
          background: linear-gradient(90deg, transparent, ${ACCENT} 30%, ${ACCENT_2} 70%, transparent);
          box-shadow: 0 0 12px ${ACCENT}aa;
        }
        .ainstein-nav-back:hover { border-color: rgba(99,179,237,.45) !important; color: ${TEXT} !important; }
      `}</style>

      <div style={leftClusterStyle}>
        <button
          className="ainstein-nav-back"
          onClick={() => navigate('/brains')}
          style={backBtnStyle}
          title="返回大脑列表"
        >
          <span style={{ fontSize: 14, lineHeight: 1 }}>‹</span>
          <span>返回大脑列表</span>
        </button>

        <span style={dividerStyle} />

        <span style={brandStyle}>
          <span style={brandDotStyle} />
          <span style={{ color: TEXT, letterSpacing: 4, fontWeight: 500 }}>AInstein</span>
          <span style={{ color: FAINT, margin: '0 8px' }}>·</span>
          <span style={{ color: DIM, letterSpacing: 2 }}>控制台</span>
        </span>
      </div>

      <div style={navGroupStyle}>
        {NAV_ITEMS.map((it) => {
          const isActive = it.key === active
          return (
            <button
              key={it.key}
              className="ainstein-nav-link"
              data-active={isActive}
              onClick={() => {
                if (location.pathname !== it.path) navigate(it.path)
              }}
              style={navItemStyle(isActive)}
            >
              <span style={{ fontFamily: FONT_MONO, fontSize: 10, color: isActive ? ACCENT : FAINT, letterSpacing: 1 }}>
                {it.idx}
              </span>
              <span style={{ fontSize: 13, fontWeight: 500, letterSpacing: 1.5 }}>{it.label}</span>
              <span style={{ fontFamily: FONT_MONO, fontSize: 9, color: isActive ? ACCENT_2 : FAINT, letterSpacing: 2 }}>
                {it.sub}
              </span>
            </button>
          )
        })}
      </div>

      <div style={rightClusterStyle}>{rightSlot}</div>
    </nav>
  )
}

/* ============== styles ============== */

const baseWrapStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 18,
  padding: '12px 28px',
  background: 'rgba(10, 14, 26, 0.72)',
  borderBottom: '1px solid rgba(120, 160, 220, 0.15)',
  backdropFilter: 'blur(14px) saturate(140%)',
  WebkitBackdropFilter: 'blur(14px) saturate(140%)',
  fontFamily: FONT_BODY,
  color: TEXT,
  boxShadow: '0 4px 20px rgba(0,0,0,0.35)',
}

const staticWrapStyle: CSSProperties = {
  ...baseWrapStyle,
  position: 'relative',
  zIndex: 50,
}

const floatingWrapStyle: CSSProperties = {
  ...baseWrapStyle,
  position: 'fixed',
  top: 0,
  left: 0,
  right: 0,
  zIndex: 50,
}

const leftClusterStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 14,
  flex: '0 0 auto',
}

const backBtnStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  background: 'transparent',
  color: DIM,
  border: '1px solid rgba(120, 160, 220, 0.2)',
  borderRadius: 4,
  padding: '6px 12px',
  fontSize: 12,
  letterSpacing: 1,
  fontFamily: FONT_BODY,
  cursor: 'pointer',
}

const dividerStyle: CSSProperties = {
  width: 1,
  height: 16,
  background: 'rgba(120,160,220,0.18)',
}

const brandStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  fontSize: 13,
  letterSpacing: 0.5,
}

const brandDotStyle: CSSProperties = {
  width: 7,
  height: 7,
  borderRadius: '50%',
  background: ACCENT,
  boxShadow: `0 0 10px ${ACCENT}`,
}

const navGroupStyle: CSSProperties = {
  flex: '1 1 auto',
  display: 'flex',
  justifyContent: 'center',
  gap: 6,
}

function navItemStyle(active: boolean): CSSProperties {
  return {
    position: 'relative',
    display: 'inline-flex',
    alignItems: 'center',
    gap: 10,
    background: active ? 'rgba(79, 209, 197, 0.06)' : 'transparent',
    color: active ? TEXT : DIM,
    border: '1px solid',
    borderColor: active ? 'rgba(79, 209, 197, 0.35)' : 'rgba(120, 160, 220, 0.12)',
    borderRadius: 4,
    padding: '8px 14px',
    cursor: 'pointer',
    fontFamily: FONT_BODY,
  }
}

const rightClusterStyle: CSSProperties = {
  flex: '0 0 auto',
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  fontFamily: FONT_MONO,
  fontSize: 11,
  color: DIM,
  letterSpacing: 1.5,
  minWidth: 140,
  justifyContent: 'flex-end',
}
