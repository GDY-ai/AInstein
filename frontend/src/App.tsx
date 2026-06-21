import { Routes, Route, Navigate } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import ProjectDetail from './pages/ProjectDetail'
import BrainView from './pages/BrainView'
import Login from './pages/Login'
import BrainList from './pages/BrainList'
import CreateBrain from './pages/CreateBrain'
import BigScreen from './pages/BigScreen'
import Discoveries from './pages/Discoveries'
import AdminDashboard from './pages/AdminDashboard'
import { getToken } from './api'

function RequireAuth({ children }: { children: JSX.Element }) {
  const token = getToken()
  if (!token) return <Navigate to="/login" replace />
  return children
}

export default function App() {
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
      <Route path="/admin/bigscreen" element={<BigScreen />} />
      <Route
        path="/admin/dashboard"
        element={
          <RequireAuth>
            <AdminDashboard />
          </RequireAuth>
        }
      />
      <Route path="/discoveries" element={<Discoveries />} />
      {/* Legacy routes preserved for backward compatibility */}
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/project/:id" element={<ProjectDetail />} />
    </Routes>
  )
}
