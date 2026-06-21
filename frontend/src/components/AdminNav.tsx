import { type CSSProperties } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'

/* ============================================================
 * AdminNav · 统一深空风导航
 *  在 我的大脑 / 态势大屏 / 发现广场 / 运营仪表盘 四页顶部使用。
 *  全中文标签，简洁的毛玻璃 + 青蓝强调。
 * ============================================================ */

export type AdminNavKey = 'home' | 'bigscreen' | 'discoveries' | 'dashboard'

interface Props {
  active: AdminNavKey
  /** 是否使用绝对定位浮在画布上（用于 BigScreen 这种全屏 canvas 页） */
  floating?: boolean
  /** 右侧附加内容（如时钟、用户信息） */
  rightSlot?: React.ReactNode
  /** 左侧是否显示「返回大脑列表」按钮，默认 true。在 BrainList 主页应传 false */
  showBack?: boolean
}

const NAV_ITEMS: Array<{ key: AdminNavKey; label: string; path: string; idx: string }> = [
  { key: 'home', label: '我的大脑', path: '/brains', idx: '01' },
  { key: 'bigscreen', label: '态势大屏', path: '/admin/bigscreen', idx: '02' },
  { key: 'discoveries', label: '发现广场', path: '/discoveries', idx: '03' },
  { key: 'dashboard', label: '运营仪表盘', path: '/admin/dashboard', idx: '04' },
]

const FONT_MONO = '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace'
const FONT_BODY =
  '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif'

const ACCENT = '#4fd1c5'
const ACCENT_2 = '#63b3ed'
const TEXT = '#dce6f5'
const DIM = '#7a8da8'
const FAINT = '#475569'

export default function AdminNav({ active, floating = false, rightSlot, showBack = true }: Props) {
  const navigate = useNavigate()
  const location = useLocation()

  return (
    <nav style={floating ? floatingWrapStyle : staticWrapStyle}>
      <style>{`
        .ainstein-nav-link { transition: color .2s ease, background .2s ease, border-color .2s ease; }
        .ainstein-nav-link:hover { color: ${TEXT} !important; border-color: rgba(79,209,197,.35) !important; }
        .ainstein-nav-link[data-active="true"]::after {
          content: '';
          position: absolute;
          left: 12px; right: 12px; bottom: -1px;
          height: 1px;
          background: linear-gradient(90deg, transparent, ${ACCENT} 30%, ${ACCENT_2} 70%, transparent);
          box-shadow: 0 0 12px ${ACCENT}aa;
        }
        .ainstein-nav-back:hover { border-color: rgba(79,209,197,.35) !important; color: ${TEXT} !important; }
      `}</style>

      <div style={leftClusterStyle}>
        {showBack && (
          <>
            <button
              className="ainstein-nav-back"
              onClick={() => navigate('/brains')}
              style={backBtnStyle}
              title="返回大脑列表"
            >
              <span style={{ fontSize: 14, lineHeight: 1 }}>‹</span>
              <span>返回</span>
            </button>
            <span style={dividerStyle} />
          </>
        )}

        <span style={brandStyle}>
          <span style={brandDotStyle} />
          <span style={{ color: TEXT, letterSpacing: 3, fontWeight: 500 }}>AInstein</span>
          <span style={{ color: FAINT, margin: '0 8px' }}>·</span>
          <span style={{ color: DIM, letterSpacing: 1.5 }}>控制台</span>
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
              <span
                style={{
                  fontFamily: FONT_MONO,
                  fontSize: 10,
                  color: isActive ? ACCENT : FAINT,
                  letterSpacing: 1,
                }}
              >
                {it.idx}
              </span>
              <span style={{ fontSize: 13, fontWeight: 500, letterSpacing: 1.5 }}>{it.label}</span>
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
  height: 56,
  padding: '0 28px',
  background: 'rgba(10, 14, 26, 0.85)',
  borderBottom: '1px solid rgba(120, 160, 220, 0.15)',
  backdropFilter: 'blur(14px) saturate(140%)',
  WebkitBackdropFilter: 'blur(14px) saturate(140%)',
  fontFamily: FONT_BODY,
  color: TEXT,
  boxShadow: '0 4px 20px rgba(0,0,0,0.35)',
}

const staticWrapStyle: CSSProperties = {
  ...baseWrapStyle,
  position: 'sticky',
  top: 0,
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
  gap: 6,
  background: 'transparent',
  color: DIM,
  border: '1px solid rgba(120, 160, 220, 0.2)',
  borderRadius: 4,
  padding: '5px 10px',
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
  gap: 4,
}

function navItemStyle(active: boolean): CSSProperties {
  return {
    position: 'relative',
    display: 'inline-flex',
    alignItems: 'center',
    gap: 8,
    background: active ? 'rgba(79, 209, 197, 0.08)' : 'transparent',
    color: active ? TEXT : DIM,
    border: '1px solid',
    borderColor: active ? 'rgba(79, 209, 197, 0.35)' : 'rgba(120, 160, 220, 0.10)',
    borderRadius: 4,
    padding: '7px 14px',
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
