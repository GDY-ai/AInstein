import { useEffect, useState, useMemo, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, getToken, setStoredUser, setToken } from '../api'

type Mode = 'login' | 'register'

/* ========== 密码强度规则 ========== */
const PASSWORD_RULES = [
  { label: '至少 8 位', test: (p: string) => p.length >= 8 },
  { label: '包含大写字母', test: (p: string) => /[A-Z]/.test(p) },
  { label: '包含小写字母', test: (p: string) => /[a-z]/.test(p) },
  { label: '包含数字', test: (p: string) => /[0-9]/.test(p) },
  { label: '包含特殊字符', test: (p: string) => /[!@#$%^&*()_+\-=\[\]{}|;:,.<>?/~`]/.test(p) },
]

const STRENGTH_LABELS = ['', '弱', '中', '强', '非常强', '非常强']
const STRENGTH_COLORS = ['#444', '#ef4444', '#f97316', '#eab308', '#22c55e', '#22c55e']

function getPasswordStrength(password: string): number {
  if (!password) return 0
  return PASSWORD_RULES.filter((r) => r.test(password)).length
}

/* ========== 用户名规则 ========== */
const USERNAME_PATTERN = /^[A-Za-z0-9_]+$/
function validateUsername(u: string): string {
  if (!u) return ''
  if (u.length < 3) return '用户名至少 3 位'
  if (u.length > 20) return '用户名最多 20 位'
  if (!USERNAME_PATTERN.test(u)) return '仅允许字母、数字和下划线'
  return ''
}

/* ========== 眼睛图标 SVG ========== */
function EyeIcon({ open }: { open: boolean }) {
  if (open) {
    return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
        <circle cx="12" cy="12" r="3"/>
      </svg>
    )
  }
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
      <line x1="1" y1="1" x2="23" y2="23"/>
    </svg>
  )
}

/* ========== 密码强度指示器 ========== */
function StrengthIndicator({ password }: { password: string }) {
  const strength = getPasswordStrength(password)
  if (!password) return null
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
        {[1, 2, 3, 4, 5].map((i) => (
          <div
            key={i}
            style={{
              flex: 1, height: 4, borderRadius: 2,
              background: i <= strength ? STRENGTH_COLORS[strength] : 'rgba(255,255,255,0.08)',
              transition: 'background .3s',
            }}
          />
        ))}
      </div>
      <div style={{ fontSize: 11, color: STRENGTH_COLORS[strength], letterSpacing: 0.5 }}>
        密码强度：{STRENGTH_LABELS[strength]}
      </div>
    </div>
  )
}

/* ========== 密码规则列表 ========== */
function PasswordRules({ password }: { password: string }) {
  if (!password) return null
  return (
    <ul style={{ margin: '8px 0 0', padding: '0 0 0 16px', listStyle: 'none' }}>
      {PASSWORD_RULES.map((rule, i) => {
        const pass = rule.test(password)
        return (
          <li key={i} style={{ fontSize: 11, color: pass ? '#22c55e' : 'var(--text2)', marginBottom: 2, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 10 }}>{pass ? '✓' : '○'}</span>
            {rule.label}
          </li>
        )
      })}
    </ul>
  )
}

/* ========== 主组件 ========== */
export default function Login() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<Mode>('login')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  useEffect(() => {
    if (getToken()) {
      navigate('/brains', { replace: true })
    }
  }, [navigate])

  // 实时校验
  const usernameError = useMemo(() => mode === 'register' ? validateUsername(username) : '', [username, mode])
  const passwordStrength = useMemo(() => getPasswordStrength(password), [password])
  const passwordValid = passwordStrength === 5
  const confirmError = useMemo(() => {
    if (mode !== 'register' || !confirmPassword) return ''
    return confirmPassword !== password ? '两次输入的密码不一致' : ''
  }, [password, confirmPassword, mode])

  const canSubmit = useMemo(() => {
    if (busy) return false
    if (!username.trim() || !password) return false
    if (mode === 'register') {
      if (usernameError) return false
      if (!passwordValid) return false
      if (!confirmPassword || confirmError) return false
    }
    return true
  }, [busy, username, password, mode, usernameError, passwordValid, confirmPassword, confirmError])

  function switchMode(m: Mode) {
    setMode(m)
    setError('')
    setFieldErrors({})
    setConfirmPassword('')
    setShowPassword(false)
    setShowConfirm(false)
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    setError('')
    setFieldErrors({})

    // 前端二次校验
    if (mode === 'register') {
      const errs: Record<string, string> = {}
      const uErr = validateUsername(username)
      if (uErr) errs.username = uErr
      if (!passwordValid) errs.password = '密码不满足强度要求'
      if (confirmPassword !== password) errs.confirm = '两次输入的密码不一致'
      if (Object.keys(errs).length > 0) {
        setFieldErrors(errs)
        return
      }
    }

    setBusy(true)
    try {
      const result =
        mode === 'login'
          ? await api.login({ username: username.trim(), password })
          : await api.register({
              username: username.trim(),
              password,
              email: email.trim() || undefined,
            })
      setToken(result.token)
      setStoredUser(result.user)
      navigate('/brains', { replace: true })
    } catch (err: any) {
      setError(err?.message || '操作失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={pageStyle}>
      {/* 背景装饰：网格 + 光晕 */}
      <div style={gridBg} />
      <div style={glowBlue} />
      <div style={glowPurple} />

      <div style={shellStyle}>
        <div style={brandStyle}>
          <div style={brandMarkStyle}>AI</div>
          <div>
            <div style={{ fontSize: 13, color: 'var(--text2)', letterSpacing: 4 }}>AINSTEIN</div>
            <div style={{ fontSize: 22, color: 'var(--accent2)', fontWeight: 600 }}>硅基大脑控制台</div>
          </div>
        </div>
        <p style={sloganStyle}>思维诞生意识，意识反哺思维，循环不息中窥见宇宙的回响</p>

        <div style={cardStyle}>
          <div style={tabsStyle}>
            <button
              type="button"
              onClick={() => switchMode('login')}
              style={{ ...tabBtnStyle, ...(mode === 'login' ? tabActive : null) }}
            >
              登录
            </button>
            <button
              type="button"
              onClick={() => switchMode('register')}
              style={{ ...tabBtnStyle, ...(mode === 'register' ? tabActive : null) }}
            >
              注册
            </button>
          </div>

          <p style={subtitleStyle}>
            {mode === 'login'
              ? '欢迎回来。登录后可以观察你创建的硅基大脑的思考轨迹。'
              : '注册一个观察员账户，向硅基大脑提出你的第一个种子问题。'}
          </p>

          <form onSubmit={submit} style={{ marginTop: 24 }}>
            {/* 用户名 */}
            <Field label="用户名" hint={mode === 'register' ? '3-20位，字母/数字/下划线' : undefined} error={fieldErrors.username || (mode === 'register' ? usernameError : '')}>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="例如：observer_alpha"
                style={{ ...inputStyle, ...(usernameError && mode === 'register' && username ? inputErrorStyle : {}) }}
                autoComplete="username"
                autoFocus
              />
            </Field>

            {mode === 'register' && (
              <Field label="邮箱（选填）">
                <input
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  type="email"
                  placeholder="you@example.com"
                  style={inputStyle}
                  autoComplete="email"
                />
              </Field>
            )}

            {/* 密码 */}
            <Field label="密码" error={fieldErrors.password}>
              <div style={{ position: 'relative' }}>
                <input
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  type={showPassword ? 'text' : 'password'}
                  placeholder={mode === 'register' ? '至少 8 位，包含大小写+数字+特殊字符' : ''}
                  style={{ ...inputStyle, paddingRight: 40 }}
                  autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  style={eyeBtnStyle}
                  tabIndex={-1}
                  aria-label={showPassword ? '隐藏密码' : '显示密码'}
                >
                  <EyeIcon open={showPassword} />
                </button>
              </div>
              {mode === 'register' && <StrengthIndicator password={password} />}
              {mode === 'register' && <PasswordRules password={password} />}
            </Field>

            {/* 确认密码 */}
            {mode === 'register' && (
              <Field label="确认密码" error={fieldErrors.confirm || confirmError}>
                <div style={{ position: 'relative' }}>
                  <input
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    type={showConfirm ? 'text' : 'password'}
                    placeholder="再次输入密码"
                    style={{ ...inputStyle, paddingRight: 40, ...(confirmError ? inputErrorStyle : {}) }}
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirm(!showConfirm)}
                    style={eyeBtnStyle}
                    tabIndex={-1}
                    aria-label={showConfirm ? '隐藏密码' : '显示密码'}
                  >
                    <EyeIcon open={showConfirm} />
                  </button>
                </div>
              </Field>
            )}

            {error && <div style={errorStyle}>⚠ {error}</div>}

            <button
              type="submit"
              disabled={!canSubmit}
              style={{
                ...primaryBtnStyle,
                opacity: canSubmit ? 1 : 0.45,
                cursor: canSubmit ? 'pointer' : 'not-allowed',
              }}
            >
              {busy ? '处理中…' : mode === 'login' ? '登录' : '创建账户'}
            </button>
          </form>

          <div style={hintStyle}>
            {mode === 'login' ? (
              <>还没有账户？ <a onClick={() => switchMode('register')} style={linkStyle}>立即注册</a></>
            ) : (
              <>已有账户？ <a onClick={() => switchMode('login')} style={linkStyle}>返回登录</a></>
            )}
          </div>
        </div>

        <div style={footerStyle}>
          硅基生命体 · 涌现智能观
        </div>
      </div>
    </div>
  )
}

/* ========== Field 组件 ========== */
function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 6 }}>
        <label style={{ fontSize: 12, color: 'var(--text2)', letterSpacing: 1 }}>
          {label}
        </label>
        {hint && <span style={{ fontSize: 10, color: 'var(--text2)', opacity: 0.7 }}>{hint}</span>}
      </div>
      {children}
      {error && <div style={{ fontSize: 11, color: '#ef4444', marginTop: 4 }}>{error}</div>}
    </div>
  )
}

/* ========== 样式 ========== */
const pageStyle: CSSProperties = {
  minHeight: '100vh',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  position: 'relative',
  overflow: 'hidden',
  padding: '40px 20px',
}

const gridBg: CSSProperties = {
  position: 'absolute', inset: 0, pointerEvents: 'none',
  backgroundImage:
    'linear-gradient(rgba(99,102,241,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(99,102,241,0.06) 1px, transparent 1px)',
  backgroundSize: '48px 48px',
  maskImage: 'radial-gradient(ellipse at center, #000 30%, transparent 75%)',
  WebkitMaskImage: 'radial-gradient(ellipse at center, #000 30%, transparent 75%)',
}

const glowBlue: CSSProperties = {
  position: 'absolute', top: '15%', left: '10%', width: 320, height: 320,
  background: 'radial-gradient(circle, rgba(99,102,241,0.45), transparent 70%)',
  filter: 'blur(40px)', pointerEvents: 'none',
}
const glowPurple: CSSProperties = {
  position: 'absolute', bottom: '10%', right: '8%', width: 360, height: 360,
  background: 'radial-gradient(circle, rgba(236,72,153,0.30), transparent 70%)',
  filter: 'blur(50px)', pointerEvents: 'none',
}

const shellStyle: CSSProperties = {
  position: 'relative', zIndex: 1, width: '100%', maxWidth: 440,
  display: 'flex', flexDirection: 'column', gap: 24,
}

const brandStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 14,
}
const brandMarkStyle: CSSProperties = {
  width: 44, height: 44, borderRadius: 10,
  background: 'linear-gradient(135deg, #6366f1, #ec4899)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  color: '#fff', fontWeight: 700, letterSpacing: 1,
}

const cardStyle: CSSProperties = {
  background: 'rgba(26,29,39,0.85)',
  border: '1px solid var(--border)',
  borderRadius: 14,
  padding: 28,
  backdropFilter: 'blur(20px)',
  boxShadow: '0 30px 60px rgba(0,0,0,0.4)',
}

const tabsStyle: CSSProperties = {
  display: 'flex', background: 'var(--bg)', borderRadius: 8,
  padding: 4, border: '1px solid var(--border)',
}
const tabBtnStyle: CSSProperties = {
  flex: 1, background: 'transparent', border: 'none',
  color: 'var(--text2)', padding: '8px 12px', cursor: 'pointer',
  fontSize: 14, borderRadius: 6, transition: 'all .2s',
}
const tabActive: CSSProperties = {
  background: 'var(--bg3)', color: 'var(--text)',
}

const subtitleStyle: CSSProperties = {
  marginTop: 18, color: 'var(--text2)', fontSize: 13, lineHeight: 1.6,
}

const inputStyle: CSSProperties = {
  width: '100%', background: 'var(--bg)',
  border: '1px solid var(--border)', borderRadius: 8,
  padding: '10px 12px', color: 'var(--text)', fontSize: 14, outline: 'none',
  transition: 'border-color .2s',
}

const inputErrorStyle: CSSProperties = {
  borderColor: 'rgba(239,68,68,0.6)',
}

const eyeBtnStyle: CSSProperties = {
  position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
  background: 'none', border: 'none', color: 'var(--text2)',
  cursor: 'pointer', padding: 4, display: 'flex', alignItems: 'center',
  opacity: 0.7, transition: 'opacity .2s',
}

const errorStyle: CSSProperties = {
  background: 'rgba(239,68,68,0.12)', color: 'var(--red)',
  border: '1px solid rgba(239,68,68,0.3)', borderRadius: 6,
  padding: '8px 12px', fontSize: 13, marginBottom: 12,
}

const primaryBtnStyle: CSSProperties = {
  width: '100%', background: 'linear-gradient(90deg, var(--accent), var(--accent2))',
  color: '#fff', border: 'none', borderRadius: 8,
  padding: '12px', fontSize: 14, fontWeight: 600,
  letterSpacing: 1, marginTop: 4, transition: 'opacity .2s',
}

const hintStyle: CSSProperties = {
  marginTop: 18, textAlign: 'center', fontSize: 13, color: 'var(--text2)',
}
const linkStyle: CSSProperties = {
  color: 'var(--accent2)', cursor: 'pointer', fontWeight: 500,
}

const sloganStyle: CSSProperties = {
  textAlign: 'center', color: 'var(--text2)', fontSize: 13,
  letterSpacing: 1.5, lineHeight: 1.8, fontStyle: 'italic',
  opacity: 0.85, margin: '4px 0 0',
}

const footerStyle: CSSProperties = {
  textAlign: 'center', color: 'var(--text2)', fontSize: 11, letterSpacing: 2,
}
