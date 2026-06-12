import { useEffect, useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { Project, Finding, Session, QueueItem, Dataset, Directive, MemoryEntry } from '../types'

type Tab = 'findings' | 'sessions' | 'queue' | 'datasets' | 'team'

export default function ProjectDetail() {
  const { id } = useParams()
  const pid = Number(id)
  const navigate = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [tab, setTab] = useState<Tab>('findings')

  useEffect(() => {
    api.getProject(pid).then(setProject)
  }, [pid])

  if (!project) return <div style={{padding: 40, color: 'var(--text2)'}}>Loading...</div>

  return (
    <div style={{minHeight: '100vh', padding: '24px 40px'}}>
      <div style={{maxWidth: 1200, margin: '0 auto'}}>
        <div style={{marginBottom: 24}}>
          <button onClick={() => navigate('/')} style={{background: 'none', border: 'none', color: 'var(--text2)', cursor: 'pointer', fontSize: 14, marginBottom: 8}}>
            &larr; Back to Projects
          </button>
          <h1 style={{fontSize: 24, color: 'var(--accent2)'}}>{project.name}</h1>
          <p style={{color: 'var(--text2)', fontSize: 14}}>{project.mission}</p>
          {project.stats && (
            <div style={{display: 'flex', gap: 16, marginTop: 8}}>
              <span style={{color: 'var(--text2)', fontSize: 13}}>{project.stats.sessions_completed} sessions</span>
              <span style={{color: 'var(--text2)', fontSize: 13}}>{project.stats.findings_total} findings</span>
              <span style={{color: 'var(--text2)', fontSize: 13}}>{project.stats.findings_validated} validated</span>
              <span style={{color: 'var(--text2)', fontSize: 13}}>{project.stats.queue_pending} pending</span>
            </div>
          )}
        </div>

        <div style={{display: 'flex', gap: 0, borderBottom: '1px solid var(--border)', marginBottom: 24}}>
          {(['findings', 'sessions', 'queue', 'datasets', 'team'] as Tab[]).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              background: 'none', border: 'none', padding: '10px 20px', cursor: 'pointer',
              color: tab === t ? 'var(--accent2)' : 'var(--text2)',
              borderBottom: tab === t ? '2px solid var(--accent)' : '2px solid transparent',
              fontSize: 14,
            }}>
              {{findings: 'Findings', sessions: 'Research Log', queue: 'Queue', datasets: 'Datasets', team: 'AI Team'}[t]}
            </button>
          ))}
        </div>

        {tab === 'findings' && <FindingsTab pid={pid} />}
        {tab === 'sessions' && <SessionsTab pid={pid} />}
        {tab === 'queue' && <QueueTab pid={pid} />}
        {tab === 'datasets' && <DatasetsTab pid={pid} />}
        {tab === 'team' && <TeamTab pid={pid} />}
      </div>
    </div>
  )
}

function FindingsTab({pid}: {pid: number}) {
  const [findings, setFindings] = useState<Finding[]>([])
  const [filter, setFilter] = useState('')
  useEffect(() => { load() }, [pid])
  async function load() {
    const params: any = {limit: 50}
    if (filter) params.status = filter
    setFindings(await api.getFindings(pid, params))
  }
  return (
    <div>
      <div style={{marginBottom: 16, display: 'flex', gap: 8}}>
        {['', 'open', 'validated', 'rejected'].map(s => (
          <button key={s} onClick={() => {setFilter(s); setTimeout(load, 0)}} style={{
            background: filter === s ? 'var(--accent)' : 'var(--bg3)', color: '#fff',
            border: 'none', borderRadius: 4, padding: '4px 12px', cursor: 'pointer', fontSize: 13,
          }}>
            {s || 'All'}
          </button>
        ))}
      </div>
      <div style={{display: 'flex', flexDirection: 'column', gap: 12}}>
        {findings.map(f => (
          <div key={f.id} style={{background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 16}}>
            <div style={{display: 'flex', justifyContent: 'space-between', marginBottom: 8}}>
              <div style={{display: 'flex', gap: 8}}>
                <ConfBadge confidence={f.confidence} />
                <span style={{color: 'var(--text2)', fontSize: 12}}>{f.category}</span>
                <span style={{color: 'var(--text2)', fontSize: 12}}>{f.status}</span>
              </div>
              <span style={{color: 'var(--text2)', fontSize: 12}}>{f.session_topic}</span>
            </div>
            <p style={{color: 'var(--text)', fontSize: 14, lineHeight: 1.5}}>{f.finding}</p>
            {f.evidence && <p style={{color: 'var(--text2)', fontSize: 12, marginTop: 6}}>Evidence: {f.evidence}</p>}
            {f.actionable === 1 && f.action_suggestion && (
              <p style={{color: 'var(--green)', fontSize: 12, marginTop: 4}}>Action: {f.action_suggestion}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function ConfBadge({confidence}: {confidence: string}) {
  const colors: Record<string, string> = {high: 'var(--green)', medium: 'var(--yellow)', low: 'var(--text2)'}
  return <span style={{background: (colors[confidence]||colors.low)+'22', color: colors[confidence]||colors.low, fontSize: 11, padding: '1px 6px', borderRadius: 3}}>{confidence}</span>
}

function SessionsTab({pid}: {pid: number}) {
  const [sessions, setSessions] = useState<Session[]>([])
  const [selected, setSelected] = useState<Session | null>(null)
  const [running, setRunning] = useState(false)
  useEffect(() => { load() }, [pid])
  async function load() { setSessions(await api.getSessions(pid)) }
  async function runSession() {
    setRunning(true)
    await api.runSession(pid)
    setTimeout(() => { load(); setRunning(false) }, 2000)
  }
  return (
    <div>
      <button onClick={runSession} disabled={running} style={{
        background: running ? 'var(--bg3)' : 'var(--accent)', color: '#fff',
        border: 'none', borderRadius: 6, padding: '8px 20px', cursor: 'pointer', fontSize: 14, marginBottom: 16,
      }}>
        {running ? 'Running...' : 'Run Research Session'}
      </button>
      {selected ? (
        <div>
          <button onClick={() => setSelected(null)} style={{background: 'none', border: 'none', color: 'var(--text2)', cursor: 'pointer', marginBottom: 12}}>
            &larr; Back to list
          </button>
          <SessionDetail session={selected} />
        </div>
      ) : (
        <div style={{display: 'flex', flexDirection: 'column', gap: 8}}>
          {sessions.map(s => (
            <div key={s.id} onClick={() => setSelected(s)} style={{
              background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, cursor: 'pointer',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <div>
                <span style={{color: s.status === 'completed' ? 'var(--green)' : s.status === 'failed' ? 'var(--red)' : 'var(--yellow)', fontSize: 12}}>{s.status}</span>
                <span style={{color: 'var(--text)', marginLeft: 12}}>{s.topic}</span>
              </div>
              <span style={{color: 'var(--text2)', fontSize: 12}}>{s.duration_seconds}s | {s.created_at}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function SessionDetail({session}: {session: Session}) {
  let hypotheses: any[] = []
  let findings: any[] = []
  let nextDirs: string[] = []
  try { hypotheses = JSON.parse(session.hypotheses || '[]') } catch {}
  try { findings = JSON.parse(session.findings || '[]') } catch {}
  try { nextDirs = JSON.parse(session.next_directions || '[]') } catch {}

  return (
    <div>
      <h3 style={{color: 'var(--accent2)', marginBottom: 8}}>{session.topic}</h3>
      <p style={{color: 'var(--text2)', fontSize: 13, marginBottom: 16}}>
        {session.status} | {session.duration_seconds}s | {session.engine_type}
      </p>
      {session.data_summary && (
        <Section title="Data Summary"><p style={{color: 'var(--text)', fontSize: 14}}>{session.data_summary}</p></Section>
      )}
      {hypotheses.length > 0 && (
        <Section title="Hypotheses">
          {hypotheses.map((h: any, i: number) => (
            <div key={i} style={{background: 'var(--bg3)', borderRadius: 6, padding: 12, marginBottom: 8}}>
              <strong style={{color: 'var(--accent2)'}}>{h.id || `H${i+1}`}:</strong>
              <span style={{color: 'var(--text)', marginLeft: 8}}>{h.statement}</span>
              {h.test_plan && <p style={{color: 'var(--text2)', fontSize: 12, marginTop: 4}}>Test: {h.test_plan}</p>}
            </div>
          ))}
        </Section>
      )}
      {findings.length > 0 && (
        <Section title="Findings">
          {findings.map((f: any, i: number) => (
            <div key={i} style={{background: 'var(--bg3)', borderRadius: 6, padding: 12, marginBottom: 8}}>
              <ConfBadge confidence={f.confidence} />
              <span style={{color: 'var(--text)', marginLeft: 8}}>{f.finding}</span>
              {f.evidence && <p style={{color: 'var(--text2)', fontSize: 12, marginTop: 4}}>Evidence: {f.evidence}</p>}
            </div>
          ))}
        </Section>
      )}
      {nextDirs.length > 0 && (
        <Section title="Next Directions">
          {nextDirs.map((d: string, i: number) => (
            <div key={i} style={{color: 'var(--text2)', fontSize: 13, marginLeft: 12}}>- {d}</div>
          ))}
        </Section>
      )}
    </div>
  )
}

function QueueTab({pid}: {pid: number}) {
  const [items, setItems] = useState<QueueItem[]>([])
  const [topic, setTopic] = useState('')
  const [priority, setPriority] = useState(5)
  useEffect(() => { load() }, [pid])
  async function load() { setItems(await api.getQueue(pid)) }
  async function addItem() {
    if (!topic) return
    await api.addQueueItem(pid, {topic, priority})
    setTopic(''); setPriority(5); load()
  }
  const statusColor: Record<string, string> = {pending: 'var(--yellow)', picked: 'var(--blue)', completed: 'var(--green)', failed: 'var(--red)'}
  return (
    <div>
      <div style={{display: 'flex', gap: 8, marginBottom: 16}}>
        <input value={topic} onChange={e => setTopic(e.target.value)} placeholder="Research topic..."
          style={{flex: 1, background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 12px', color: 'var(--text)', fontSize: 14}} />
        <select value={priority} onChange={e => setPriority(Number(e.target.value))}
          style={{background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 12px', color: 'var(--text)', fontSize: 14}}>
          {[1,2,3,4,5,6,7,8,9,10].map(n => <option key={n} value={n}>P{n}</option>)}
        </select>
        <button onClick={addItem} style={{background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 6, padding: '8px 16px', cursor: 'pointer'}}>Add</button>
      </div>
      <table style={{width: '100%', borderCollapse: 'collapse'}}>
        <thead>
          <tr style={{borderBottom: '1px solid var(--border)'}}>
            {['Topic', 'Priority', 'Source', 'Status', 'Created'].map(h => (
              <th key={h} style={{textAlign: 'left', padding: '8px 12px', color: 'var(--text2)', fontSize: 12, fontWeight: 500}}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map(q => (
            <tr key={q.id} style={{borderBottom: '1px solid var(--border)'}}>
              <td style={{padding: '8px 12px', color: 'var(--text)', fontSize: 14}}>{q.topic}</td>
              <td style={{padding: '8px 12px', color: 'var(--text2)', fontSize: 13}}>P{q.priority}</td>
              <td style={{padding: '8px 12px', color: 'var(--text2)', fontSize: 13}}>{q.source}</td>
              <td style={{padding: '8px 12px'}}><span style={{color: statusColor[q.status] || 'var(--text2)', fontSize: 12}}>{q.status}</span></td>
              <td style={{padding: '8px 12px', color: 'var(--text2)', fontSize: 12}}>{q.created_at}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DatasetsTab({pid}: {pid: number}) {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  useEffect(() => { load() }, [pid])
  async function load() { setDatasets(await api.getDatasets(pid)) }
  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    await api.uploadDataset(pid, file)
    load()
  }
  return (
    <div>
      <div style={{marginBottom: 16}}>
        <input ref={fileRef} type="file" accept=".csv,.json,.xlsx" onChange={handleUpload} style={{display: 'none'}} />
        <button onClick={() => fileRef.current?.click()} style={{background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 6, padding: '8px 20px', cursor: 'pointer', fontSize: 14}}>
          Upload Dataset
        </button>
      </div>
      <div style={{display: 'flex', flexDirection: 'column', gap: 8}}>
        {datasets.map(d => {
          let schema: any[] = []
          try { schema = JSON.parse(d.schema_json || '[]') } catch {}
          return (
            <div key={d.id} style={{background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 14}}>
              <div style={{display: 'flex', justifyContent: 'space-between'}}>
                <span style={{color: 'var(--text)', fontWeight: 500}}>{d.name}</span>
                <span style={{color: 'var(--text2)', fontSize: 12}}>{d.row_count} rows | {d.source}</span>
              </div>
              {schema.length > 0 && (
                <div style={{display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8}}>
                  {schema.map((c: any, i: number) => (
                    <span key={i} style={{background: 'var(--bg3)', color: 'var(--text2)', fontSize: 11, padding: '2px 6px', borderRadius: 3}}>
                      {c.name}: {c.dtype}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function TeamTab({pid}: {pid: number}) {
  const [directives, setDirectives] = useState<Directive[]>([])
  const [memory, setMemory] = useState<MemoryEntry[]>([])
  const [runningSci, setRunningSci] = useState(false)
  const [runningDir, setRunningDir] = useState(false)
  const [msg, setMsg] = useState('')
  useEffect(() => { load() }, [pid])
  async function load() {
    const [d, m] = await Promise.all([api.getDirectives(pid), api.getMemory(pid)])
    setDirectives(d); setMemory(m)
  }
  async function runScientist() {
    setRunningSci(true); setMsg('')
    try {
      const r = await api.runScientist(pid)
      setMsg(`Scientist done: ${r.directives} directives, ${r.topics} topics`)
      load()
    } catch(e: any) { setMsg(`Error: ${e.message}`) }
    setRunningSci(false)
  }
  async function runDirector() {
    setRunningDir(true); setMsg('')
    try {
      const r = await api.runDirector(pid)
      setMsg(`Director done: ${r.findings_reviewed} reviewed, ${r.new_topics} new topics`)
      load()
    } catch(e: any) { setMsg(`Error: ${e.message}`) }
    setRunningDir(false)
  }
  return (
    <div>
      <div style={{display: 'flex', gap: 8, marginBottom: 16}}>
        <button onClick={runScientist} disabled={runningSci} style={{
          background: runningSci ? 'var(--bg3)' : 'var(--accent)', color: '#fff',
          border: 'none', borderRadius: 6, padding: '8px 16px', cursor: 'pointer', fontSize: 13,
        }}>{runningSci ? 'Running...' : 'Run Scientist'}</button>
        <button onClick={runDirector} disabled={runningDir} style={{
          background: runningDir ? 'var(--bg3)' : 'var(--blue)', color: '#fff',
          border: 'none', borderRadius: 6, padding: '8px 16px', cursor: 'pointer', fontSize: 13,
        }}>{runningDir ? 'Running...' : 'Run Director'}</button>
      </div>
      {msg && <p style={{color: 'var(--green)', fontSize: 13, marginBottom: 16}}>{msg}</p>}

      <Section title="Scientist Directives">
        {directives.map(d => (
          <div key={d.id} style={{background: 'var(--bg3)', borderRadius: 6, padding: 12, marginBottom: 8}}>
            <div style={{display: 'flex', justifyContent: 'space-between'}}>
              <span style={{color: 'var(--text)'}}>{d.directive}</span>
              <span style={{color: 'var(--text2)', fontSize: 12}}>P{d.priority}</span>
            </div>
          </div>
        ))}
      </Section>

      <Section title="Director Memory">
        {memory.map(m => (
          <div key={m.id} style={{background: 'var(--bg3)', borderRadius: 6, padding: 12, marginBottom: 8}}>
            <span style={{color: 'var(--yellow)', fontSize: 11, marginRight: 8}}>{m.kind}</span>
            <span style={{color: 'var(--text)', fontSize: 13}}>{m.content}</span>
            <span style={{color: 'var(--text2)', fontSize: 11, marginLeft: 8}}>{m.created_at}</span>
          </div>
        ))}
      </Section>
    </div>
  )
}

function Section({title, children}: {title: string; children: React.ReactNode}) {
  return (
    <div style={{marginBottom: 20}}>
      <h4 style={{color: 'var(--text2)', fontSize: 13, fontWeight: 500, marginBottom: 8, textTransform: 'uppercase'}}>{title}</h4>
      {children}
    </div>
  )
}
