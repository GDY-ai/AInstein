import { useEffect, useRef, useState, useCallback } from 'react';
import { api } from '../api';
import type { Brain } from '../types';

// ===================== 类型定义 =====================

interface GraphNode {
  id: number;
  brain: Brain;
  // 极坐标（绕主脑环绕）
  angle: number;
  vAngle: number;
  targetAngle: number;
  orbitR: number;
  // 屏幕坐标缓存
  x: number;
  y: number;
  radius: number;
  color: string;
  isMaster: boolean;
  ownerSlot: number;
}

interface FiberPulse {
  t: number;
  speed: number;
  alpha: number;
}

interface GraphEdge {
  source: GraphNode;
  target: GraphNode;
  curlSign: number;
  curlAmount: number;
  curlPhase: number;
  pulses: FiberPulse[];
}

interface BgStar {
  x: number;
  y: number;
  size: number;
  alpha: number;
  twinkleSpeed: number;
  twinklePhase: number;
}

// ===================== 常量 =====================

const SPHERE_COLORS = [
  '#4fd1c5', '#6b46c1', '#ed8936', '#90cdf4', '#d53f8c', '#a0aec0',
  '#81e6d9', '#9f7aea', '#f6ad55', '#bee3f8', '#f687b3', '#cbd5e0',
];

const STATE_COLORS: Record<string, string> = {
  active: '#7be3d3',
  thinking: '#7be3d3',
  dormant: '#7aa3d6',
  paused: '#7aa3d6',
  completed: '#dfe7f3',
  archived: '#5b6478',
  gestating: '#f6c179',
};

// ===================== 大脑写实形状（贝塞尔路径） =====================

// 大脑侧面外轮廓控制点（归一化到 [-1, 1]，y 向下为正）
// 顺时针：起点位于额叶前下方
const BRAIN_OUTLINE: Array<[number, number]> = [
  [-0.74,  0.18],   // 0  额叶前下
  [-0.82, -0.06],   // 1  额叶前缘
  [-0.84, -0.34],   // 2  额叶前缘上升
  [-0.74, -0.60],   // 3  额叶前上
  [-0.58, -0.78],   // 4  额叶顶（饱满圆润）
  [-0.36, -0.86],   // 5  额顶交界
  [-0.10, -0.88],   // 6  顶叶顶（最高点）
  [ 0.18, -0.84],   // 7  顶叶
  [ 0.42, -0.74],   // 8  顶枕交界
  [ 0.60, -0.56],   // 9  枕叶上
  [ 0.74, -0.30],   // 10 枕叶后
  [ 0.78, -0.05],   // 11 枕叶下后
  [ 0.72,  0.13],   // 12 枕叶底
  [ 0.58,  0.20],   // 13 小脑分界凹陷
  [ 0.70,  0.34],   // 14 小脑外缘
  [ 0.66,  0.50],   // 15 小脑下
  [ 0.48,  0.56],   // 16 小脑左下
  [ 0.30,  0.50],   // 17 小脑根（凹）
  [ 0.20,  0.62],   // 18 脑干右
  [ 0.02,  0.66],   // 19 脑干底
  [-0.18,  0.58],   // 20 脑干左
  [-0.34,  0.48],   // 21 颞叶下
  [-0.54,  0.44],   // 22 颞叶
  [-0.70,  0.36],   // 23 颞叶前下
  [-0.78,  0.28],   // 24 颞叶前
];

// 脑沟曲线：每条由 [起点, 控制点1, 控制点2, 终点] 组成（归一化坐标）
const BRAIN_SULCI: Array<[
  [number, number], [number, number], [number, number], [number, number]
]> = [
  // 中央沟（Rolando）：从顶部偏前向下弯曲
  [[-0.05, -0.82], [-0.10, -0.50], [-0.16, -0.20], [-0.18,  0.05]],
  // 外侧裂（Sylvian）：水平大沟分隔颞叶
  [[-0.62,  0.02], [-0.32, -0.12], [ 0.02, -0.06], [ 0.32,  0.06]],
  // 额前沟
  [[-0.58, -0.50], [-0.55, -0.34], [-0.50, -0.18], [-0.44, -0.04]],
  // 额上沟
  [[-0.34, -0.74], [-0.32, -0.55], [-0.28, -0.36], [-0.24, -0.18]],
  // 顶枕沟
  [[ 0.22, -0.72], [ 0.28, -0.50], [ 0.34, -0.28], [ 0.38, -0.06]],
  // 颞上沟
  [[-0.44,  0.16], [-0.20,  0.10], [ 0.04,  0.18], [ 0.26,  0.22]],
  // 颞下沟
  [[-0.32,  0.30], [-0.12,  0.28], [ 0.06,  0.32], [ 0.20,  0.34]],
  // 扣带沟（弧形横贯顶部内侧）
  [[-0.42, -0.40], [-0.18, -0.52], [ 0.14, -0.50], [ 0.34, -0.42]],
  // 枕侧小沟
  [[ 0.50, -0.48], [ 0.56, -0.32], [ 0.60, -0.16], [ 0.62,  0.00]],
  // 额下沟
  [[-0.66, -0.18], [-0.56, -0.06], [-0.46,  0.04], [-0.36,  0.10]],
];

// 小脑横纹（独立的密集弧线，模拟小脑叶片）
const CEREBELLUM_LINES: Array<[
  [number, number], [number, number], [number, number], [number, number]
]> = [
  [[ 0.34,  0.26], [ 0.46,  0.24], [ 0.58,  0.28], [ 0.66,  0.34]],
  [[ 0.32,  0.36], [ 0.46,  0.34], [ 0.58,  0.38], [ 0.64,  0.44]],
  [[ 0.34,  0.46], [ 0.46,  0.44], [ 0.56,  0.46], [ 0.60,  0.50]],
];

// ===================== 径向力布局 =====================

function applyRadialForces(nodes: GraphNode[], width: number, height: number) {
  const cx = width / 2;
  const cy = height / 2;
  const minSide = Math.min(width, height);
  const orbitR = minSide * 0.36;

  const branches = nodes.filter(n => !n.isMaster);
  const N = branches.length;

  const angularRepulsion = 0.0009;
  const angularDamping = 0.86;
  const targetSpring = 0.012;

  for (let i = 0; i < N; i++) {
    const a = branches[i];
    a.orbitR = orbitR;

    let dAngle = a.targetAngle - a.angle;
    while (dAngle > Math.PI) dAngle -= Math.PI * 2;
    while (dAngle < -Math.PI) dAngle += Math.PI * 2;
    a.vAngle += dAngle * targetSpring;

    for (let j = 0; j < N; j++) {
      if (i === j) continue;
      const b = branches[j];
      let diff = a.angle - b.angle;
      while (diff > Math.PI) diff -= Math.PI * 2;
      while (diff < -Math.PI) diff += Math.PI * 2;
      const absDiff = Math.abs(diff) + 0.0001;
      const force = angularRepulsion / (absDiff * absDiff);
      a.vAngle += Math.sign(diff) * force;
    }

    a.vAngle *= angularDamping;
    a.angle += a.vAngle;
  }

  for (const node of nodes) {
    if (node.isMaster) {
      node.x = cx;
      node.y = cy;
      node.angle = 0;
      node.vAngle = 0;
      continue;
    }
    // 椭圆轨道（横向稍宽）
    const ex = orbitR * 1.05;
    const ey = orbitR * 0.78;
    node.x = cx + Math.cos(node.angle) * ex;
    node.y = cy + Math.sin(node.angle) * ey;
  }
}

// ===================== 组件 =====================

export default function BigScreen() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animFrameRef = useRef<number>(0);
  const nodesRef = useRef<GraphNode[]>([]);
  const edgesRef = useRef<GraphEdge[]>([]);
  const bgStarsRef = useRef<BgStar[]>([]);
  const hoveredNodeRef = useRef<GraphNode | null>(null);
  const [hoveredBrain, setHoveredBrain] = useState<Brain | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [stats, setStats] = useState({ total: 0, active: 0, totalCE: 0 });
  const [loading, setLoading] = useState(true);
  const scaleRef = useRef(1);
  const offsetRef = useRef({ x: 0, y: 0 });
  const dragRef = useRef<{ dragging: boolean; lastX: number; lastY: number }>({ dragging: false, lastX: 0, lastY: 0 });
  const timeRef = useRef(0);

  // ===== 构建图 =====
  const buildGraph = useCallback((brains: Brain[], width: number, height: number) => {
    const cx = width / 2;
    const cy = height / 2;
    const orbitR = Math.min(width, height) * 0.36;

    const nodes: GraphNode[] = [];
    const edges: GraphEdge[] = [];

    const sorted = [...brains].sort((a, b) => {
      if (a.brain_type === 'master') return -1;
      if (b.brain_type === 'master') return 1;
      const oa = a.owner_username || 'unknown';
      const ob = b.owner_username || 'unknown';
      if (oa !== ob) return oa.localeCompare(ob);
      return a.id - b.id;
    });

    const branches = sorted.filter(b => b.brain_type !== 'master');
    const N = Math.max(1, branches.length);

    let masterNode: GraphNode | null = null;
    let branchSlot = 0;

    for (const brain of sorted) {
      const isMaster = brain.brain_type === 'master';
      const radius = isMaster
        ? Math.min(220, Math.max(150, Math.min(width, height) * 0.18))
        : 28 + Math.min((brain.think_count || 0) * 0.18, 7);
      const color = isMaster ? '#cfe4ff' : SPHERE_COLORS[branchSlot % SPHERE_COLORS.length];

      let angle = 0;
      let targetAngle = 0;
      if (!isMaster) {
        const t = branchSlot / N;
        targetAngle = -Math.PI / 2 + t * Math.PI * 2;
        angle = targetAngle + (Math.random() - 0.5) * 0.2;
      }

      const node: GraphNode = {
        id: brain.id,
        brain,
        angle,
        vAngle: 0,
        targetAngle,
        orbitR,
        x: isMaster ? cx : cx + Math.cos(angle) * orbitR * 1.05,
        y: isMaster ? cy : cy + Math.sin(angle) * orbitR * 0.78,
        radius,
        color,
        isMaster,
        ownerSlot: branchSlot,
      };
      nodes.push(node);
      if (isMaster) masterNode = node;
      else branchSlot++;
    }

    if (masterNode) {
      for (const node of nodes) {
        if (node.isMaster) continue;
        const pulses: FiberPulse[] = [];
        const pn = 2 + Math.floor(Math.random() * 2);
        for (let i = 0; i < pn; i++) {
          pulses.push({
            t: Math.random(),
            speed: 0.0018 + Math.random() * 0.0022,
            alpha: 0.25 + Math.random() * 0.12,
          });
        }
        edges.push({
          source: masterNode,
          target: node,
          curlSign: Math.random() > 0.5 ? 1 : -1,
          curlAmount: 50 + Math.random() * 90,
          curlPhase: Math.random() * Math.PI * 2,
          pulses,
        });
      }
    }

    nodesRef.current = nodes;
    edgesRef.current = edges;
  }, []);

  // ===== 背景星空 =====
  const generateBgStars = useCallback((width: number, height: number) => {
    const stars: BgStar[] = [];
    for (let i = 0; i < 80; i++) {
      stars.push({
        x: Math.random() * width,
        y: Math.random() * height,
        size: 0.3 + Math.random() * 0.7,
        alpha: 0.2 + Math.random() * 0.3,
        twinkleSpeed: 0.004 + Math.random() * 0.012,
        twinklePhase: Math.random() * Math.PI * 2,
      });
    }
    bgStarsRef.current = stars;
  }, []);

  // ===== 数据加载 =====
  useEffect(() => {
    const fetchData = async () => {
      try {
        const resp = await api.listBrains({ all: true });
        const brains = resp.items || [];
        const canvas = canvasRef.current;
        if (!canvas) return;
        const w = window.innerWidth;
        const h = window.innerHeight;
        canvas.width = w;
        canvas.height = h;

        buildGraph(brains, w, h);
        generateBgStars(w, h);

        const activeCount = brains.filter(b => b.state === 'active' || b.state === 'thinking').length;
        const totalCE = brains.reduce((sum, b) => sum + (b.ce_count || 0), 0);
        setStats({ total: brains.length, active: activeCount, totalCE });
        setLoading(false);
      } catch (err) {
        console.error('BigScreen: Failed to fetch brains', err);
        setLoading(false);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [buildGraph, generateBgStars]);

  // ===== 渲染循环 =====
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const render = () => {
      const w = canvas.width;
      const h = canvas.height;
      timeRef.current += 1;
      const t = timeRef.current;

      applyRadialForces(nodesRef.current, w, h);

      ctx.save();

      // ===== 背景 =====
      ctx.fillStyle = '#0a0e1a';
      ctx.fillRect(0, 0, w, h);

      const cx = w / 2;
      const cy = h / 2;
      const fog = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(w, h) * 0.7);
      fog.addColorStop(0, 'rgba(100, 150, 200, 0.04)');
      fog.addColorStop(0.5, 'rgba(60, 90, 140, 0.02)');
      fog.addColorStop(1, 'rgba(0, 0, 0, 0)');
      ctx.fillStyle = fog;
      ctx.fillRect(0, 0, w, h);

      const bottomFog = ctx.createLinearGradient(0, h * 0.55, 0, h);
      bottomFog.addColorStop(0, 'rgba(40, 50, 90, 0)');
      bottomFog.addColorStop(1, 'rgba(70, 90, 140, 0.10)');
      ctx.fillStyle = bottomFog;
      ctx.fillRect(0, h * 0.55, w, h * 0.45);

      const leftFog = ctx.createLinearGradient(0, 0, w * 0.3, 0);
      leftFog.addColorStop(0, 'rgba(50, 40, 80, 0.08)');
      leftFog.addColorStop(1, 'rgba(50, 40, 80, 0)');
      ctx.fillStyle = leftFog;
      ctx.fillRect(0, 0, w * 0.3, h);

      const rightFog = ctx.createLinearGradient(w * 0.7, 0, w, 0);
      rightFog.addColorStop(0, 'rgba(40, 50, 90, 0)');
      rightFog.addColorStop(1, 'rgba(40, 50, 90, 0.08)');
      ctx.fillStyle = rightFog;
      ctx.fillRect(w * 0.7, 0, w * 0.3, h);

      // 平移/缩放
      ctx.translate(offsetRef.current.x, offsetRef.current.y);
      ctx.scale(scaleRef.current, scaleRef.current);

      // 星空
      for (const star of bgStarsRef.current) {
        const tw = Math.sin(t * star.twinkleSpeed + star.twinklePhase) * 0.25 + 0.75;
        ctx.beginPath();
        ctx.arc(star.x, star.y, star.size, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(210, 225, 245, ${star.alpha * tw})`;
        ctx.fill();
      }

      // 神经纤维
      drawFibers(ctx, edgesRef.current, t);

      // 主脑（写实贝塞尔大脑）
      const masterNode = nodesRef.current.find(n => n.isMaster);
      if (masterNode) {
        drawBrain(ctx, masterNode.x, masterNode.y, masterNode.radius, t);
      }

      // 分支球体
      const hovered = hoveredNodeRef.current;
      for (const node of nodesRef.current) {
        if (node.isMaster) continue;
        const isActive = node.brain.state === 'active' || node.brain.state === 'thinking';
        drawSphere(ctx, node, t, isActive, hovered === node);
      }

      // 标签
      ctx.font = '11px "Inter", "Helvetica Neue", sans-serif';
      ctx.textAlign = 'center';
      for (const node of nodesRef.current) {
        if (node.isMaster) continue;
        const name = node.brain.name;
        const display = name.length > 14 ? name.slice(0, 14) + '…' : name;
        const labelY = node.y + node.radius + 18;
        ctx.fillStyle = 'rgba(220, 230, 245, 0.85)';
        ctx.shadowBlur = 8;
        ctx.shadowColor = 'rgba(20, 30, 50, 0.9)';
        ctx.fillText(display, node.x, labelY);
        ctx.shadowBlur = 0;
      }
      if (masterNode) {
        ctx.font = '13px "Inter", "Helvetica Neue", sans-serif';
        ctx.fillStyle = 'rgba(200, 230, 255, 0.85)';
        ctx.shadowBlur = 12;
        ctx.shadowColor = 'rgba(120, 180, 255, 0.6)';
        ctx.fillText(
          masterNode.brain.name,
          masterNode.x,
          masterNode.y + masterNode.radius + 32,
        );
        ctx.shadowBlur = 0;
      }

      ctx.restore();
      animFrameRef.current = requestAnimationFrame(render);
    };

    animFrameRef.current = requestAnimationFrame(render);
    return () => cancelAnimationFrame(animFrameRef.current);
  }, []);

  // ===== 鼠标交互 =====
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const getTransformedPos = (clientX: number, clientY: number) => {
      const x = (clientX - offsetRef.current.x) / scaleRef.current;
      const y = (clientY - offsetRef.current.y) / scaleRef.current;
      return { x, y };
    };

    const handleMouseMove = (e: MouseEvent) => {
      if (dragRef.current.dragging) {
        offsetRef.current.x += e.clientX - dragRef.current.lastX;
        offsetRef.current.y += e.clientY - dragRef.current.lastY;
        dragRef.current.lastX = e.clientX;
        dragRef.current.lastY = e.clientY;
        return;
      }

      const pos = getTransformedPos(e.clientX, e.clientY);
      let found: GraphNode | null = null;
      for (const node of nodesRef.current) {
        const dx = pos.x - node.x;
        const dy = pos.y - node.y;
        if (Math.sqrt(dx * dx + dy * dy) < node.radius + 6) {
          found = node;
          break;
        }
      }
      hoveredNodeRef.current = found;
      if (found) {
        setHoveredBrain(found.brain);
        setTooltipPos({ x: e.clientX + 15, y: e.clientY + 15 });
        canvas.style.cursor = 'pointer';
      } else {
        setHoveredBrain(null);
        canvas.style.cursor = 'grab';
      }
    };

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      const newScale = Math.max(0.3, Math.min(3, scaleRef.current * delta));
      const mx = e.clientX;
      const my = e.clientY;
      offsetRef.current.x = mx - (mx - offsetRef.current.x) * (newScale / scaleRef.current);
      offsetRef.current.y = my - (my - offsetRef.current.y) * (newScale / scaleRef.current);
      scaleRef.current = newScale;
    };

    const handleMouseDown = (e: MouseEvent) => {
      if (!hoveredNodeRef.current) {
        dragRef.current = { dragging: true, lastX: e.clientX, lastY: e.clientY };
        canvas.style.cursor = 'grabbing';
      }
    };

    const handleMouseUp = () => {
      dragRef.current.dragging = false;
      canvas.style.cursor = hoveredNodeRef.current ? 'pointer' : 'grab';
    };

    canvas.addEventListener('mousemove', handleMouseMove);
    canvas.addEventListener('wheel', handleWheel, { passive: false });
    canvas.addEventListener('mousedown', handleMouseDown);
    canvas.addEventListener('mouseup', handleMouseUp);
    canvas.addEventListener('mouseleave', handleMouseUp);

    return () => {
      canvas.removeEventListener('mousemove', handleMouseMove);
      canvas.removeEventListener('wheel', handleWheel);
      canvas.removeEventListener('mousedown', handleMouseDown);
      canvas.removeEventListener('mouseup', handleMouseUp);
      canvas.removeEventListener('mouseleave', handleMouseUp);
    };
  }, []);

  // ===== 窗口缩放 =====
  useEffect(() => {
    const handleResize = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      generateBgStars(canvas.width, canvas.height);
      const master = nodesRef.current.find(n => n.isMaster);
      if (master) {
        master.radius = Math.min(220, Math.max(150, Math.min(canvas.width, canvas.height) * 0.18));
      }
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [generateBgStars]);

  return (
    <div style={{
      width: '100vw', height: '100vh', overflow: 'hidden',
      background: '#0a0e1a', position: 'relative',
    }}>
      <canvas
        ref={canvasRef}
        style={{ display: 'block', width: '100%', height: '100%' }}
      />

      {loading && (
        <div style={{
          position: 'absolute', inset: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#7aa3d6', fontSize: 16, fontFamily: '"Inter", sans-serif',
          letterSpacing: 4,
        }}>
          正在加载大脑拓扑数据…
        </div>
      )}

      <div style={{
        position: 'absolute', top: 28, left: '50%', transform: 'translateX(-50%)',
        color: 'rgba(220, 235, 255, 0.9)', fontSize: 18, fontWeight: 500,
        letterSpacing: 6,
        fontFamily: '"Inter", "Helvetica Neue", sans-serif',
        textShadow: '0 0 24px rgba(120, 180, 255, 0.45)',
        pointerEvents: 'none',
      }}>
        AInstein · 硅基大脑态势全景
      </div>

      <div style={{
        position: 'absolute', top: 60, left: '50%', transform: 'translateX(-50%)',
        width: 120, height: 1,
        background: 'linear-gradient(90deg, transparent, rgba(150,200,255,0.5), transparent)',
        pointerEvents: 'none',
      }} />

      <div style={{
        position: 'absolute', bottom: 32, left: 32,
        color: '#a8bdd8', fontSize: 12, fontFamily: '"JetBrains Mono", "Menlo", monospace',
        background: 'rgba(15, 22, 38, 0.55)', borderRadius: 6, padding: '14px 20px',
        border: '1px solid rgba(120, 160, 220, 0.18)',
        backdropFilter: 'blur(10px)',
        boxShadow: '0 4px 24px rgba(0, 0, 0, 0.4)',
        pointerEvents: 'none',
        letterSpacing: 0.5,
      }}>
        <div style={{ marginBottom: 6, display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 6, height: 6, background: '#90cdf4', borderRadius: 1, display: 'inline-block' }} />
          <span style={{ color: '#7a8da8' }}>大脑总数</span>
          <span style={{ color: '#e0ecff', fontWeight: 500 }}>{stats.total}</span>
        </div>
        <div style={{ marginBottom: 6, display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 6, height: 6, background: '#7be3d3', borderRadius: 1, display: 'inline-block' }} />
          <span style={{ color: '#7a8da8' }}>活跃中  </span>
          <span style={{ color: '#7be3d3', fontWeight: 500 }}>{stats.active}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 6, height: 6, background: '#c3a5e8', borderRadius: 1, display: 'inline-block' }} />
          <span style={{ color: '#7a8da8' }}>认知元素</span>
          <span style={{ color: '#c3a5e8', fontWeight: 500 }}>{stats.totalCE}</span>
        </div>
      </div>

      <div style={{
        position: 'absolute', bottom: 32, right: 32,
        color: 'rgba(150, 180, 220, 0.4)', fontSize: 10,
        fontFamily: '"JetBrains Mono", monospace', letterSpacing: 2,
        pointerEvents: 'none',
      }}>
        TOPOLOGY · LIVE FEED
      </div>

      {hoveredBrain && (
        <div style={{
          position: 'absolute',
          left: tooltipPos.x,
          top: tooltipPos.y,
          background: 'rgba(15, 22, 38, 0.92)',
          border: '1px solid rgba(120, 160, 220, 0.35)',
          borderRadius: 6,
          padding: '14px 18px',
          color: '#dce6f5',
          fontSize: 12,
          fontFamily: '"JetBrains Mono", "Menlo", monospace',
          pointerEvents: 'none',
          backdropFilter: 'blur(10px)',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.5)',
          maxWidth: 320,
          zIndex: 999,
        }}>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 6, color: '#f0f6ff', letterSpacing: 0.5 }}>
            {hoveredBrain.name}
          </div>
          <div style={{ marginBottom: 8, color: '#8aa0c0', fontSize: 11, lineHeight: 1.5 }}>
            {hoveredBrain.seed_question?.slice(0, 70)}{(hoveredBrain.seed_question?.length || 0) > 70 ? '…' : ''}
          </div>
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 14px',
            paddingTop: 8, borderTop: '1px solid rgba(120,160,220,0.15)',
          }}>
            <span><span style={{ color: '#6a7a96' }}>状态</span> <b style={{ color: STATE_COLORS[hoveredBrain.state] || '#fff' }}>{hoveredBrain.state}</b></span>
            <span><span style={{ color: '#6a7a96' }}>类型</span> {hoveredBrain.brain_type || 'standalone'}</span>
            <span><span style={{ color: '#6a7a96' }}>思考</span> {hoveredBrain.think_count ?? 0}</span>
            <span><span style={{ color: '#6a7a96' }}>CE</span> {hoveredBrain.ce_count ?? 0}</span>
            <span><span style={{ color: '#6a7a96' }}>Agent</span> {hoveredBrain.agent_count ?? 0}</span>
            <span><span style={{ color: '#6a7a96' }}>Owner</span> {hoveredBrain.owner_username || '—'}</span>
          </div>
          <div style={{ marginTop: 8, color: '#5a6a86', fontSize: 10 }}>
            创建于 {hoveredBrain.created_at?.slice(0, 16).replace('T', ' ')}
          </div>
        </div>
      )}
    </div>
  );
}

// ===================== 绘制：写实大脑（贝塞尔曲线） =====================

function drawBrain(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  size: number,
  t: number,
) {
  // 微弱呼吸脉动
  const breathe = 1 + Math.sin(t * 0.020) * 0.018;
  const s = size * breathe;

  ctx.save();
  ctx.translate(cx, cy);

  // ---- 外圈柔光晕（强化体积感）----
  const auraR = s * 1.55;
  const aura = ctx.createRadialGradient(0, 0, s * 0.85, 0, 0, auraR);
  aura.addColorStop(0, 'rgba(150, 200, 255, 0.18)');
  aura.addColorStop(0.5, 'rgba(120, 170, 230, 0.07)');
  aura.addColorStop(1, 'rgba(0, 0, 0, 0)');
  ctx.fillStyle = aura;
  ctx.beginPath();
  ctx.arc(0, 0, auraR, 0, Math.PI * 2);
  ctx.fill();

  // ---- 用 Catmull-Rom → 三次贝塞尔 平滑闭合大脑轮廓 ----
  const buildOutlinePath = () => {
    const pts = BRAIN_OUTLINE;
    const n = pts.length;
    const tension = 0.5;
    ctx.beginPath();
    ctx.moveTo(pts[0][0] * s, pts[0][1] * s);
    for (let i = 0; i < n; i++) {
      const pPrev = pts[(i - 1 + n) % n];
      const pCur  = pts[i];
      const pNext = pts[(i + 1) % n];
      const pNxt2 = pts[(i + 2) % n];
      const cp1x = (pCur[0]  + (pNext[0] - pPrev[0]) * tension / 3) * s;
      const cp1y = (pCur[1]  + (pNext[1] - pPrev[1]) * tension / 3) * s;
      const cp2x = (pNext[0] - (pNxt2[0] - pCur[0])  * tension / 3) * s;
      const cp2y = (pNext[1] - (pNxt2[1] - pCur[1])  * tension / 3) * s;
      ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, pNext[0] * s, pNext[1] * s);
    }
    ctx.closePath();
  };

  // ---- 主体填充：径向渐变模拟 3D 半透明体积 ----
  buildOutlinePath();
  const body = ctx.createRadialGradient(
    -s * 0.18, -s * 0.22, 0,
    0, 0, s * 0.95,
  );
  body.addColorStop(0,    'rgba(210, 232, 255, 0.30)');
  body.addColorStop(0.45, 'rgba(150, 182, 226, 0.18)');
  body.addColorStop(0.80, 'rgba(90, 120, 170, 0.10)');
  body.addColorStop(1,    'rgba(40, 60, 100, 0.04)');
  ctx.fillStyle = body;
  ctx.fill();

  // ---- 轮廓发光描边 ----
  buildOutlinePath();
  ctx.shadowBlur = 14;
  ctx.shadowColor = 'rgba(150, 200, 255, 0.5)';
  ctx.strokeStyle = 'rgba(190, 222, 255, 0.6)';
  ctx.lineWidth = 1.4;
  ctx.stroke();
  ctx.shadowBlur = 0;

  // ---- 内部沟回纹理（裁剪到大脑轮廓内）----
  ctx.save();
  buildOutlinePath();
  ctx.clip();

  // 内部柔光（中心更亮，强化球体感）
  const inner = ctx.createRadialGradient(-s * 0.12, -s * 0.18, 0, 0, 0, s * 0.85);
  inner.addColorStop(0,   'rgba(220, 235, 255, 0.10)');
  inner.addColorStop(0.6, 'rgba(160, 190, 230, 0.04)');
  inner.addColorStop(1,   'rgba(80, 110, 160, 0)');
  ctx.fillStyle = inner;
  ctx.fillRect(-s * 1.2, -s * 1.2, s * 2.4, s * 2.4);

  // 脑沟暗影（先画暗一档，制造凹陷感）
  ctx.strokeStyle = 'rgba(40, 70, 120, 0.32)';
  ctx.lineWidth = Math.max(0.6, s * 0.005);
  for (const sul of BRAIN_SULCI) {
    ctx.beginPath();
    ctx.moveTo(sul[0][0] * s + s * 0.006, sul[0][1] * s + s * 0.010);
    ctx.bezierCurveTo(
      sul[1][0] * s + s * 0.006, sul[1][1] * s + s * 0.010,
      sul[2][0] * s + s * 0.006, sul[2][1] * s + s * 0.010,
      sul[3][0] * s + s * 0.006, sul[3][1] * s + s * 0.010,
    );
    ctx.stroke();
  }

  // 脑沟主线（亮色，弧形发光）
  ctx.strokeStyle = 'rgba(150, 188, 230, 0.42)';
  ctx.lineWidth = Math.max(0.9, s * 0.007);
  ctx.shadowBlur = 4;
  ctx.shadowColor = 'rgba(120, 170, 220, 0.35)';
  for (const sul of BRAIN_SULCI) {
    ctx.beginPath();
    ctx.moveTo(sul[0][0] * s, sul[0][1] * s);
    ctx.bezierCurveTo(
      sul[1][0] * s, sul[1][1] * s,
      sul[2][0] * s, sul[2][1] * s,
      sul[3][0] * s, sul[3][1] * s,
    );
    ctx.stroke();
  }
  ctx.shadowBlur = 0;

  // 小脑分界线（半月弧，把小脑从主脑分出）
  ctx.strokeStyle = 'rgba(130, 170, 220, 0.55)';
  ctx.lineWidth = Math.max(1.0, s * 0.008);
  ctx.beginPath();
  ctx.moveTo(0.58 * s, 0.20 * s);
  ctx.bezierCurveTo(
    0.42 * s, 0.30 * s,
    0.32 * s, 0.42 * s,
    0.30 * s, 0.50 * s,
  );
  ctx.stroke();

  // 小脑横纹
  ctx.strokeStyle = 'rgba(140, 178, 222, 0.36)';
  ctx.lineWidth = Math.max(0.7, s * 0.005);
  for (const c of CEREBELLUM_LINES) {
    ctx.beginPath();
    ctx.moveTo(c[0][0] * s, c[0][1] * s);
    ctx.bezierCurveTo(
      c[1][0] * s, c[1][1] * s,
      c[2][0] * s, c[2][1] * s,
      c[3][0] * s, c[3][1] * s,
    );
    ctx.stroke();
  }

  // 脑干竖纹
  ctx.strokeStyle = 'rgba(140, 175, 220, 0.32)';
  ctx.lineWidth = Math.max(0.6, s * 0.004);
  ctx.beginPath();
  ctx.moveTo(-0.05 * s, 0.42 * s);
  ctx.lineTo(-0.02 * s, 0.62 * s);
  ctx.moveTo( 0.06 * s, 0.42 * s);
  ctx.lineTo( 0.10 * s, 0.62 * s);
  ctx.stroke();

  ctx.restore();

  // ---- 顶部高光弧（玻璃质感）----
  ctx.save();
  buildOutlinePath();
  ctx.clip();
  const hi = ctx.createRadialGradient(
    -s * 0.28, -s * 0.48, 0,
    -s * 0.28, -s * 0.48, s * 0.78,
  );
  hi.addColorStop(0,   'rgba(255, 255, 255, 0.20)');
  hi.addColorStop(0.5, 'rgba(255, 255, 255, 0.05)');
  hi.addColorStop(1,   'rgba(255, 255, 255, 0)');
  ctx.fillStyle = hi;
  ctx.fillRect(-s * 1.2, -s * 1.2, s * 2.4, s * 2.4);
  ctx.restore();

  // ---- 中心微辉（脉动呼吸）----
  const pulseAlpha = 0.05 + Math.sin(t * 0.024) * 0.03;
  const core = ctx.createRadialGradient(0, 0, 0, 0, 0, s * 0.55);
  core.addColorStop(0, `rgba(200, 230, 255, ${pulseAlpha})`);
  core.addColorStop(1, 'rgba(200, 230, 255, 0)');
  ctx.fillStyle = core;
  ctx.beginPath();
  ctx.ellipse(0, 0, s * 0.55, s * 0.42, 0, 0, Math.PI * 2);
  ctx.fill();

  ctx.restore();
}

// ===================== 绘制：3D 抛光球体 =====================

function drawSphere(
  ctx: CanvasRenderingContext2D,
  node: GraphNode,
  t: number,
  isActive: boolean,
  isHovered: boolean,
) {
  const { x, y, color } = node;
  const r = node.radius * (isHovered ? 1.08 : 1);

  // 底部投影
  ctx.save();
  const shadowGrad = ctx.createRadialGradient(x, y + r * 0.95, 0, x, y + r * 0.95, r * 1.2);
  shadowGrad.addColorStop(0, 'rgba(0, 0, 0, 0.35)');
  shadowGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
  ctx.fillStyle = shadowGrad;
  ctx.beginPath();
  ctx.ellipse(x, y + r * 0.95, r * 1.0, r * 0.25, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  // 球体主渐变
  const dark = darkenHex(color, 55);
  const mid = color;
  const light = lightenHex(color, 35);

  const hlX = x - r * 0.35;
  const hlY = y - r * 0.4;
  const bodyGrad = ctx.createRadialGradient(hlX, hlY, r * 0.05, x, y, r * 1.05);
  bodyGrad.addColorStop(0, light);
  bodyGrad.addColorStop(0.35, mid);
  bodyGrad.addColorStop(1, dark);

  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fillStyle = bodyGrad;
  ctx.fill();

  // 底部环境光反射
  ctx.save();
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.clip();
  const rim = ctx.createRadialGradient(x, y + r * 0.6, r * 0.1, x, y + r * 0.6, r * 1.1);
  rim.addColorStop(0, 'rgba(255, 255, 255, 0)');
  rim.addColorStop(0.7, 'rgba(255, 255, 255, 0)');
  rim.addColorStop(0.92, rgbaFromHex(lightenHex(color, 50), 0.35));
  rim.addColorStop(1, 'rgba(255, 255, 255, 0)');
  ctx.fillStyle = rim;
  ctx.fillRect(x - r, y - r, r * 2, r * 2);
  ctx.restore();

  // 高光镜面亮点
  ctx.save();
  ctx.beginPath();
  ctx.arc(x - r * 0.38, y - r * 0.42, r * 0.18, 0, Math.PI * 2);
  const spec = ctx.createRadialGradient(
    x - r * 0.38, y - r * 0.42, 0,
    x - r * 0.38, y - r * 0.42, r * 0.18,
  );
  spec.addColorStop(0, 'rgba(255, 255, 255, 0.85)');
  spec.addColorStop(0.5, 'rgba(255, 255, 255, 0.25)');
  spec.addColorStop(1, 'rgba(255, 255, 255, 0)');
  ctx.fillStyle = spec;
  ctx.fill();
  ctx.restore();

  // active 流光漫反射
  if (isActive) {
    ctx.save();
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.clip();
    const flowAngle = (t * 0.012) % (Math.PI * 2);
    const fx = x + Math.cos(flowAngle) * r * 0.2;
    const fy = y + Math.sin(flowAngle) * r * 0.2 - r * 0.1;
    const flow = ctx.createRadialGradient(fx, fy, 0, fx, fy, r * 0.9);
    flow.addColorStop(0, rgbaFromHex(lightenHex(color, 60), 0.20));
    flow.addColorStop(0.5, rgbaFromHex(lightenHex(color, 30), 0.08));
    flow.addColorStop(1, 'rgba(255, 255, 255, 0)');
    ctx.fillStyle = flow;
    ctx.fillRect(x - r, y - r, r * 2, r * 2);
    ctx.restore();
  }

  // 边缘暗轮廓
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.strokeStyle = rgbaFromHex(darkenHex(color, 70), 0.4);
  ctx.lineWidth = 0.6;
  ctx.stroke();

  // hover 柔光
  if (isHovered) {
    const hover = ctx.createRadialGradient(x, y, r, x, y, r * 1.6);
    hover.addColorStop(0, rgbaFromHex(color, 0.4));
    hover.addColorStop(1, 'rgba(0, 0, 0, 0)');
    ctx.beginPath();
    ctx.arc(x, y, r * 1.6, 0, Math.PI * 2);
    ctx.fillStyle = hover;
    ctx.fill();
  }
}

// ===================== 绘制：神经纤维 =====================

function drawFibers(ctx: CanvasRenderingContext2D, edges: GraphEdge[], t: number) {
  ctx.save();
  ctx.shadowBlur = 4;
  ctx.shadowColor = 'rgba(150, 200, 255, 0.3)';

  for (const edge of edges) {
    const { source, target, curlSign, curlAmount, curlPhase } = edge;
    const sxC = source.x;
    const syC = source.y;
    const txC = target.x;
    const tyC = target.y;

    const dx = txC - sxC;
    const dy = tyC - syC;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const ux = dx / dist;
    const uy = dy / dist;

    // 起止点偏移到球体表面
    const sx = sxC + ux * source.radius * 0.9;
    const sy = syC + uy * source.radius * 0.9;
    const tx = txC - ux * target.radius * 0.95;
    const ty = tyC - uy * target.radius * 0.95;

    const nx = -uy;
    const ny = ux;

    const breath = Math.sin(t * 0.015 + curlPhase) * 0.3 + 1;
    const cp1Off = curlAmount * 0.7 * breath * curlSign;
    const cp2Off = curlAmount * 0.5 * breath * (-curlSign);

    const cp1x = sx + dx * 0.30 + nx * cp1Off;
    const cp1y = sy + dy * 0.30 + ny * cp1Off;
    const cp2x = sx + dx * 0.70 + nx * cp2Off;
    const cp2y = sy + dy * 0.70 + ny * cp2Off;

    // 主线
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, tx, ty);
    ctx.strokeStyle = 'rgba(180, 220, 255, 0.25)';
    ctx.lineWidth = 0.9;
    ctx.stroke();

    // 极淡辉光叠加
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, tx, ty);
    ctx.strokeStyle = 'rgba(200, 230, 255, 0.08)';
    ctx.lineWidth = 2.5;
    ctx.stroke();

    // 沿线脉冲点
    for (const p of edge.pulses) {
      p.t += p.speed;
      if (p.t > 1) p.t -= 1;
      const u = p.t;
      const omU = 1 - u;
      const px = omU * omU * omU * sx
        + 3 * omU * omU * u * cp1x
        + 3 * omU * u * u * cp2x
        + u * u * u * tx;
      const py = omU * omU * omU * sy
        + 3 * omU * omU * u * cp1y
        + 3 * omU * u * u * cp2y
        + u * u * u * ty;
      const fade = Math.sin(u * Math.PI);
      ctx.beginPath();
      ctx.arc(px, py, 1.5, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(220, 240, 255, ${p.alpha * fade})`;
      ctx.fill();
    }
  }

  ctx.restore();
}

// ===================== 颜色工具 =====================

function lightenHex(hex: string, percent: number): string {
  const num = parseInt(hex.replace('#', ''), 16);
  const r = Math.min(255, ((num >> 16) & 0xff) + percent);
  const g = Math.min(255, ((num >> 8) & 0xff) + percent);
  const b = Math.min(255, (num & 0xff) + percent);
  return `rgb(${r},${g},${b})`;
}

function darkenHex(hex: string, percent: number): string {
  const num = parseInt(hex.replace('#', ''), 16);
  const r = Math.max(0, ((num >> 16) & 0xff) - percent);
  const g = Math.max(0, ((num >> 8) & 0xff) - percent);
  const b = Math.max(0, (num & 0xff) - percent);
  return `rgb(${r},${g},${b})`;
}

function rgbaFromHex(input: string, alpha: number): string {
  let r = 255, g = 255, b = 255;
  if (input.startsWith('#')) {
    const num = parseInt(input.replace('#', ''), 16);
    r = (num >> 16) & 0xff;
    g = (num >> 8) & 0xff;
    b = num & 0xff;
  } else if (input.startsWith('rgb')) {
    const m = input.match(/\d+/g);
    if (m && m.length >= 3) {
      r = parseInt(m[0], 10);
      g = parseInt(m[1], 10);
      b = parseInt(m[2], 10);
    }
  }
  return `rgba(${r},${g},${b},${alpha})`;
}
