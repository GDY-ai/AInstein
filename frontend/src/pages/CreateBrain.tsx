import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, getToken } from '../api'

const ALL_SAMPLES = [
  '如果宇宙是一个模拟程序，我们能找到什么证据？',
  '为什么所有文明最终都走向官僚化？',
  '量子纠缠能否解释意识的非局域性？',
  '人类语言的起源是否与音乐同源？',
  '暗物质会不会是另一个维度的普通物质？',
  '为什么生物演化会收敛到相似的形态？',
  '数学是被发现的还是被发明的？',
  '文明的平均寿命是多少年？费米悖论的最佳解释是什么？',
  '如果时间是离散的而非连续的，物理学需要怎样重写？',
  '社交媒体是否正在改变人类大脑的结构？',
  'mRNA 技术能否让人类实现器官再生？',
  '城市为什么会遵循齐普夫定律？这背后是什么机制？',
  '为什么睡眠中的大脑比清醒时更活跃？',
  '通货膨胀的本质是货币现象还是权力现象？',
  '如果 AI 能自主做科研，科学家的角色会变成什么？',
  '人类能否在100年内实现可控核聚变商业化？',
]
const SAMPLE_QUESTIONS = ALL_SAMPLES.sort(() => Math.random() - 0.5).slice(0, 4)

export default function CreateBrain() {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [seed, setSeed] = useState('')
  const [mode, setMode] = useState<'fast' | 'deep'>('fast')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [stage, setStage] = useState<'compose' | 'launching'>('compose')
  const textRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!getToken()) navigate('/login', { replace: true })
  }, [navigate])

  useEffect(() => {
    textRef.current?.focus()
  }, [])

  async function submit() {
    if (busy) return
    const seedText = seed.trim()
    if (seedText.length < 4) {
      setError('种子问题至少 4 个字符')
      return
    }
    const finalName = name.trim() || seedText.slice(0, 24)
    setError('')
    setBusy(true)
    setStage('launching')
    try {
      const r = await api.createBrain({
        name: finalName,
        seed_question: seedText,
        config: { mode },
      })
      // 短暂展示「点燃」动画后跳转
      setTimeout(() => {
        navigate(`/brain/${r.brain.id}`, { replace: true })
      }, 900)
    } catch (e: any) {
      setError(e?.message || '创建失败')
      setBusy(false)
      setStage('compose')
    }
  }

  function pickSample(q: string) {
    setSeed(q)
    textRef.current?.focus()
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      submit()
    }
  }

  if (stage === 'launching') return <Launching name={name.trim() || seed.trim().slice(0, 24)} />

  return (
    <div style={pageStyle}>
      <div style={gridBg} />
      <div style={glow1} />
      <div style={glow2} />

      <button onClick={() => navigate('/brains')} style={backBtnStyle}>← 返回大脑列表</button>

      <div style={shellStyle}>
        <div style={kickerStyle}>
          <span style={kickerDot} />
          诞生时刻
        </div>
        <h1 style={titleStyle}>
          向硅基大脑提出<br />
          <span style={titleAccent}>你的问题</span>
        </h1>
        <p style={subtitleStyle}>
          一个种子问题就是一个新生命的起点。
          提交之后，你将不再是它的指挥者——而是它思考过程的观察员。
        </p>

        <div style={composerStyle}>
          <div style={fieldLabel}>种子问题</div>
          <textarea
            ref={textRef}
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            onKeyDown={onKeyDown}
            rows={3}
            placeholder="例如：意识是大脑神经活动的副产品，还是某种更基础的存在？"
            style={textareaStyle}
            maxLength={1000}
          />

          <div style={charCounterStyle}>
            <span>{seed.length} / 1000</span>
            <span style={{ color: 'var(--text2)' }}>⌘ + Enter 提交</span>
          </div>

          <div style={modeSelectorStyle}>
            <div style={fieldLabel}>思考模式</div>
            <div style={modeOptionsRow}>
              <button
                type="button"
                onClick={() => setMode('fast')}
                style={modeChipStyle(mode === 'fast')}
              >
                <div style={modeChipTitleStyle(mode === 'fast')}>⚡ 快思考</div>
                <div style={modeChipDescStyle}>约 5 分钟内收敛，适合首次体验</div>
              </button>
              <button
                type="button"
                onClick={() => setMode('deep')}
                style={modeChipStyle(mode === 'deep')}
              >
                <div style={modeChipTitleStyle(mode === 'deep')}>🧠 深度思考</div>
                <div style={modeChipDescStyle}>5–60 分钟充分博弈，产出高置信度结论</div>
              </button>
            </div>
          </div>

          <details style={advancedStyle}>
            <summary style={advancedSummaryStyle}>高级 · 自定义大脑名称（可选）</summary>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="留空则自动从种子问题截取"
              style={inputStyle}
            />
          </details>

          {error && <div style={errorStyle}>⚠ {error}</div>}

          <button onClick={submit} disabled={busy} style={launchBtnStyle}>
            {busy ? '点燃中…' : '点燃这颗大脑 →'}
          </button>
        </div>

        <div style={samplesWrap}>
          <div style={samplesHint}>没有头绪？看看其他观察员问过什么：</div>
          <div style={samplesRow}>
            {SAMPLE_QUESTIONS.map((q) => (
              <button key={q} onClick={() => pickSample(q)} style={sampleChipStyle}>
                {q}
              </button>
            ))}
          </div>
        </div>

        <div style={contractStyle}>
          <div style={contractTitle}>观察者契约</div>
          <ul style={contractList}>
            <li>提交后，大脑将自主选择探索路径，不可在中途追加问题。</li>
            <li>多个角色 Agent（探索者 / 调研者 / 推理者 / 批评者 / 综合者）将在你的注视下进行平等博弈。</li>
            <li>你可以随时回来观察思考轨迹，但只有管理员能暂停或恢复一颗大脑。</li>
          </ul>
        </div>
      </div>
    </div>
  )
}

function Launching({ name }: { name: string }) {
  return (
    <div style={launchingStyle}>
      <div style={pulseRingOuter}>
        <div style={pulseRingMid}>
          <div style={pulseCore} />
        </div>
      </div>
      <div style={{ marginTop: 36, fontSize: 13, color: 'var(--text2)', letterSpacing: 4 }}>
        BRAIN.IGNITE
      </div>
      <div style={{ marginTop: 12, fontSize: 22, color: 'var(--accent2)', fontWeight: 600 }}>
        正在点燃 · {name}
      </div>
      <div style={{ marginTop: 14, color: 'var(--text2)', fontSize: 13, letterSpacing: 1 }}>
        召集探索者 · 调研者 · 推理者 · 批评者 · 综合者…
      </div>
    </div>
  )
}

const pageStyle: CSSProperties = {
  minHeight: '100vh', position: 'relative', overflow: 'hidden',
  padding: '40px 20px',
}

const gridBg: CSSProperties = {
  position: 'absolute', inset: 0, pointerEvents: 'none',
  backgroundImage:
    'linear-gradient(rgba(129,140,248,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(129,140,248,0.05) 1px, transparent 1px)',
  backgroundSize: '40px 40px',
  maskImage: 'radial-gradient(ellipse at center, #000 25%, transparent 80%)',
  WebkitMaskImage: 'radial-gradient(ellipse at center, #000 25%, transparent 80%)',
}
const glow1: CSSProperties = {
  position: 'absolute', top: '-10%', right: '-5%', width: 480, height: 480,
  background: 'radial-gradient(circle, rgba(99,102,241,0.45), transparent 70%)',
  filter: 'blur(60px)', pointerEvents: 'none',
}
const glow2: CSSProperties = {
  position: 'absolute', bottom: '-15%', left: '-10%', width: 540, height: 540,
  background: 'radial-gradient(circle, rgba(236,72,153,0.30), transparent 70%)',
  filter: 'blur(70px)', pointerEvents: 'none',
}

const backBtnStyle: CSSProperties = {
  position: 'relative', zIndex: 2,
  background: 'transparent', border: 'none', color: 'var(--text2)',
  cursor: 'pointer', fontSize: 13, padding: '8px 4px',
}

const shellStyle: CSSProperties = {
  position: 'relative', zIndex: 1,
  maxWidth: 720, margin: '24px auto 0',
}

const kickerStyle: CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 8,
  fontSize: 11, color: 'var(--accent2)', letterSpacing: 4,
  padding: '4px 12px', borderRadius: 999,
  border: '1px solid rgba(129,140,248,0.4)',
  background: 'rgba(129,140,248,0.08)',
  marginBottom: 20,
}
const kickerDot: CSSProperties = {
  width: 6, height: 6, borderRadius: '50%',
  background: 'var(--accent2)',
  boxShadow: '0 0 8px var(--accent2)',
}

const titleStyle: CSSProperties = {
  fontSize: 44, lineHeight: 1.15, fontWeight: 700,
  color: 'var(--text)', letterSpacing: -1,
}
const titleAccent: CSSProperties = {
  background: 'linear-gradient(90deg, var(--accent), #ec4899)',
  WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
  backgroundClip: 'text', color: 'transparent',
}

const subtitleStyle: CSSProperties = {
  marginTop: 18, color: 'var(--text2)', fontSize: 15,
  lineHeight: 1.7, maxWidth: 600,
}

const composerStyle: CSSProperties = {
  marginTop: 36,
  background: 'rgba(26,29,39,0.85)',
  border: '1px solid var(--border)',
  borderRadius: 16, padding: 24,
  backdropFilter: 'blur(20px)',
  boxShadow: '0 30px 60px rgba(0,0,0,0.4)',
}
const fieldLabel: CSSProperties = {
  fontSize: 11, color: 'var(--text2)', letterSpacing: 2, marginBottom: 8,
}
const textareaStyle: CSSProperties = {
  width: '100%', background: 'var(--bg)',
  border: '1px solid var(--border)', borderRadius: 10,
  padding: '14px 16px',
  color: 'var(--text)', fontSize: 16, lineHeight: 1.6,
  outline: 'none', resize: 'vertical', minHeight: 96,
  fontFamily: 'inherit',
}
const charCounterStyle: CSSProperties = {
  display: 'flex', justifyContent: 'space-between',
  fontSize: 11, color: 'var(--text2)', marginTop: 6, letterSpacing: 1,
}

const advancedStyle: CSSProperties = { marginTop: 18 }
const advancedSummaryStyle: CSSProperties = {
  cursor: 'pointer', color: 'var(--text2)', fontSize: 12,
  letterSpacing: 1, marginBottom: 8,
}
const inputStyle: CSSProperties = {
  marginTop: 8,
  width: '100%', background: 'var(--bg)',
  border: '1px solid var(--border)', borderRadius: 8,
  padding: '10px 12px', color: 'var(--text)', fontSize: 14, outline: 'none',
}

const errorStyle: CSSProperties = {
  marginTop: 14,
  background: 'rgba(239,68,68,0.12)', color: 'var(--red)',
  border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8,
  padding: '8px 12px', fontSize: 13,
}
const launchBtnStyle: CSSProperties = {
  marginTop: 22, width: '100%',
  background: 'linear-gradient(90deg, var(--accent), #ec4899)',
  color: '#fff', border: 'none', borderRadius: 10,
  padding: '14px', fontSize: 15, fontWeight: 600, letterSpacing: 1,
  cursor: 'pointer', boxShadow: '0 14px 30px rgba(99,102,241,0.4)',
}

const samplesWrap: CSSProperties = { marginTop: 32 }
const samplesHint: CSSProperties = {
  fontSize: 12, color: 'var(--text2)', letterSpacing: 1, marginBottom: 10,
}
const samplesRow: CSSProperties = {
  display: 'flex', gap: 8, flexWrap: 'wrap',
}
const sampleChipStyle: CSSProperties = {
  background: 'var(--bg2)', color: 'var(--text2)',
  border: '1px solid var(--border)', borderRadius: 999,
  padding: '6px 14px', fontSize: 12, cursor: 'pointer',
  transition: 'all .2s',
}

const contractStyle: CSSProperties = {
  marginTop: 32, padding: 18,
  background: 'rgba(15,17,23,0.5)',
  border: '1px dashed var(--border)', borderRadius: 10,
}
const contractTitle: CSSProperties = {
  fontSize: 11, color: 'var(--accent2)', letterSpacing: 3, marginBottom: 10,
}
const contractList: CSSProperties = {
  margin: 0, paddingLeft: 18,
  color: 'var(--text2)', fontSize: 13, lineHeight: 1.9,
}

const modeSelectorStyle: CSSProperties = { marginTop: 18 }
const modeOptionsRow: CSSProperties = {
  display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 8,
}
const modeChipStyle = (active: boolean): CSSProperties => ({
  textAlign: 'left',
  padding: '12px 14px',
  borderRadius: 10,
  border: active
    ? '1px solid rgba(129,140,248,0.85)'
    : '1px solid var(--border)',
  background: active
    ? 'linear-gradient(135deg, rgba(99,102,241,0.20), rgba(236,72,153,0.16))'
    : 'var(--bg)',
  color: 'var(--text)',
  cursor: 'pointer',
  transition: 'all .2s',
  boxShadow: active ? '0 8px 22px rgba(99,102,241,0.25)' : 'none',
})
const modeChipTitleStyle = (active: boolean): CSSProperties => ({
  fontSize: 14,
  fontWeight: 600,
  color: active ? 'var(--accent2)' : 'var(--text)',
  marginBottom: 4,
})
const modeChipDescStyle: CSSProperties = {
  fontSize: 11, color: 'var(--text2)', lineHeight: 1.5,
}

// === Launching screen ===
const launchingStyle: CSSProperties = {
  minHeight: '100vh', display: 'flex',
  alignItems: 'center', justifyContent: 'center',
  flexDirection: 'column', textAlign: 'center', padding: 40,
  position: 'relative',
}
const ringBase: CSSProperties = {
  borderRadius: '50%', display: 'flex',
  alignItems: 'center', justifyContent: 'center',
}
const pulseRingOuter: CSSProperties = {
  ...ringBase, width: 220, height: 220,
  border: '1px solid rgba(99,102,241,0.3)',
  animation: 'ainstein-pulse 2s ease-out infinite',
  boxShadow: '0 0 60px rgba(99,102,241,0.4)',
}
const pulseRingMid: CSSProperties = {
  ...ringBase, width: 140, height: 140,
  border: '1px solid rgba(236,72,153,0.4)',
  animation: 'ainstein-pulse 2s ease-out infinite 0.4s',
}
const pulseCore: CSSProperties = {
  width: 70, height: 70, borderRadius: '50%',
  background: 'radial-gradient(circle, rgba(99,102,241,1), rgba(236,72,153,0.6) 70%, transparent)',
  boxShadow: '0 0 60px rgba(99,102,241,0.8)',
}
