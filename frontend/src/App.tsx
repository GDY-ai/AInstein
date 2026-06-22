import { useEffect, useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import ProjectDetail from './pages/ProjectDetail'
import BrainView from './pages/BrainView'
import Login from './pages/Login'
import BrainList from './pages/BrainList'
import CreateBrain from './pages/CreateBrain'
import BigScreen from './pages/BigScreen'
import Discoveries from './pages/Discoveries'
import MasterDaily from './pages/MasterDaily'
import AdminDashboard from './pages/AdminDashboard'
import { api, getStoredUser, getToken, setStoredUser, setToken } from './api'

function RequireAuth({ children }: { children: JSX.Element }) {
  const token = getToken()
  if (!token) return <Navigate to="/login" replace />
  return children
}

/**
 * 管理员路由守卫：未登录跳 /login；已登录但非 admin 角色跳回 /brains。
 * 用于保护「态势大屏 / 发现广场 / 运营仪表盘」入口。
 */
function RequireAdmin({ children }: { children: JSX.Element }) {
  const token = getToken()
  if (!token) return <Navigate to="/login" replace />
  const user = getStoredUser()
  const isAdmin = (user?.role || '').toLowerCase() === 'admin'
  if (!isAdmin) return <Navigate to="/brains" replace />
  return children
}

/**
 * 拦截 GitHub OAuth 回调中的 ?token=... 参数：
 * - 写入 localStorage（沿用密码登录的存储约定）
 * - 异步调用 /auth/me 拉取用户档案
 * - 用 history.replaceState 清掉 URL 参数，避免泄漏 / 刷新重复处理
 * 该 effect 只在首次挂载时运行，对未登录页（/login）也生效，
 * 因为 callback 重定向后浏览器先到达任意路由再被 React Router 接管。
 */
function useOAuthTokenCapture(): boolean {
  const [pending, setPending] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    return new URLSearchParams(window.location.search).has('token')
  })

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const token = params.get('token')
    if (!token) return
    setToken(token)
    // 拉取用户信息（失败也不阻塞跳转）
    api.me()
      .then((res) => setStoredUser(res.user))
      .catch(() => { /* 静默：token 已落库，下次 401 会自动清 */ })
      .finally(() => {
        // 清掉 URL 上的 token 参数；保留 hash & 其它非敏感参数
        params.delete('token')
        const qs = params.toString()
        const url = window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash
        window.history.replaceState({}, '', url)
        setPending(false)
      })
  }, [])

  return pending
}

export default function App() {
  const oauthPending = useOAuthTokenCapture()
  if (oauthPending) {
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: 'var(--text2)', fontSize: 13, letterSpacing: 2,
      }}>
        正在完成 GitHub 登录…
      </div>
    )
  }
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          getToken() ? <Navigate to="/brains" replace /> : <Navigate to="/login" replace />
        }
      />
      <Route
        path="/brains"
        element={
          <RequireAuth>
            <BrainList />
          </RequireAuth>
        }
      />
      <Route
        path="/brains/new"
        element={
          <RequireAuth>
            <CreateBrain />
          </RequireAuth>
        }
      />
      <Route
        path="/brain/:brainId"
        element={
          <RequireAuth>
            <BrainView />
          </RequireAuth>
        }
      />
      <Route
        path="/admin/bigscreen"
        element={
          <RequireAdmin>
            <BigScreen />
          </RequireAdmin>
        }
      />
      <Route
        path="/admin/dashboard"
        element={
          <RequireAdmin>
            <AdminDashboard />
          </RequireAdmin>
        }
      />
      <Route
        path="/discoveries"
        element={
          <RequireAdmin>
            <Discoveries />
          </RequireAdmin>
        }
      />
      <Route path="/master-daily" element={<MasterDaily />} />
      {/* Legacy routes preserved for backward compatibility */}
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/project/:id" element={<ProjectDetail />} />
    </Routes>
  )
}
