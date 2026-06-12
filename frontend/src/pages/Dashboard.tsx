import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { Project } from '../types'

export default function Dashboard() {
  const [projects, setProjects] = useState<Project[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [mission, setMission] = useState('')
  const [domain, setDomain] = useState('')
  const navigate = useNavigate()

  useEffect(() => { load() }, [])

  async function load() {
    const list = await api.listProjects()
    const detailed = await Promise.all(list.map((p: Project) => api.getProject(p.id)))
    setProjects(detailed)
  }

  async function handleCreate() {
    if (!name || !mission || !domain) return
    await api.createProject({ name, mission, domain })
    setShowCreate(false)
    setName(''); setMission(''); setDomain('')
    load()
  }

  const totalFindings = projects.reduce((s, p) => s + (p.stats?.findings_total || 0), 0)
  const totalSessions = projects.reduce((s, p) => s + (p.stats?.sessions_completed || 0), 0)

  return (
    <div style={{minHeight: '100vh', padding: '40px'}}>
      <div style={{maxWidth: 1200, margin: '0 auto'}}>
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 32}}>
          <div>
            <h1 style={{fontSize: 28, color: 'var(--accent2)', marginBottom: 4}}>
              AInstein
            </h1>
            <p style={{color: 'var(--text2)'}}>AI Deep Research Platform</p>
          </div>
          <button onClick={() => setShowCreate(true)} style={btnStyle}>
            + New Project
          </button>
        </div>

        <div style={{display: 'flex', gap: 16, marginBottom: 32}}>
          <StatCard label="Projects" value={projects.length} />
          <StatCard label="Sessions Completed" value={totalSessions} />
          <StatCard label="Total Findings" value={totalFindings} />
        </div>

        <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(350px, 1fr))', gap: 20}}>
          {projects.map(p => (
            <div key={p.id} onClick={() => navigate(`/project/${p.id}`)} style={cardStyle}>
              <h3 style={{marginBottom: 8, color: 'var(--accent2)'}}>{p.name}</h3>
              <p style={{color: 'var(--text2)', fontSize: 14, marginBottom: 12}}>{p.mission}</p>
              <div style={{display: 'flex', gap: 8, flexWrap: 'wrap'}}>
                <Badge label={p.domain} color="var(--blue)" />
                {p.stats && <>
                  <Badge label={`${p.stats.sessions_completed} sessions`} color="var(--green)" />
                  <Badge label={`${p.stats.findings_total} findings`} color="var(--yellow)" />
                  <Badge label={`${p.stats.queue_pending} pending`} color="var(--text2)" />
                </>}
              </div>
            </div>
          ))}
        </div>
      </div>

      {showCreate && (
        <div style={overlayStyle} onClick={() => setShowCreate(false)}>
          <div style={modalStyle} onClick={e => e.stopPropagation()}>
            <h2 style={{marginBottom: 20}}>Create Research Project</h2>
            <Field label="Project Name">
              <input value={name} onChange={e => setName(e.target.value)} style={inputStyle} placeholder="e.g. US Stock Momentum" />
            </Field>
            <Field label="Research Mission">
              <textarea value={mission} onChange={e => setMission(e.target.value)} style={{...inputStyle, height: 80}} placeholder="Long-term research goal..." />
            </Field>
            <Field label="Domain">
              <input value={domain} onChange={e => setDomain(e.target.value)} style={inputStyle} placeholder="e.g. quantitative finance, medical research" />
            </Field>
            <div style={{display: 'flex', gap: 12, marginTop: 20}}>
              <button onClick={handleCreate} style={btnStyle}>Create</button>
              <button onClick={() => setShowCreate(false)} style={{...btnStyle, background: 'var(--bg3)'}}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function StatCard({label, value}: {label: string; value: number}) {
  return (
    <div style={{background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: '16px 24px', flex: 1}}>
      <div style={{fontSize: 28, fontWeight: 700, color: 'var(--accent2)'}}>{value}</div>
      <div style={{color: 'var(--text2)', fontSize: 13}}>{label}</div>
    </div>
  )
}

function Field({label, children}: {label: string; children: React.ReactNode}) {
  return (
    <div style={{marginBottom: 16}}>
      <label style={{display: 'block', color: 'var(--text2)', fontSize: 13, marginBottom: 6}}>{label}</label>
      {children}
    </div>
  )
}

function Badge({label, color}: {label: string; color: string}) {
  return (
    <span style={{background: color + '22', color, fontSize: 12, padding: '2px 8px', borderRadius: 4}}>{label}</span>
  )
}

const btnStyle: React.CSSProperties = {
  background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 6,
  padding: '8px 20px', cursor: 'pointer', fontSize: 14,
}
const inputStyle: React.CSSProperties = {
  width: '100%', background: 'var(--bg)', border: '1px solid var(--border)',
  borderRadius: 6, padding: '8px 12px', color: 'var(--text)', fontSize: 14, outline: 'none',
}
const cardStyle: React.CSSProperties = {
  background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8,
  padding: 20, cursor: 'pointer',
}
const overlayStyle: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex',
  alignItems: 'center', justifyContent: 'center', zIndex: 100,
}
const modalStyle: React.CSSProperties = {
  background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 12,
  padding: 32, width: 480, maxWidth: '90vw',
}
