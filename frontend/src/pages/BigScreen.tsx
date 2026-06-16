import { useEffect, useRef, useState, useCallback } from 'react';
import { api } from '../api';
import type { Brain } from '../types';

// ===================== 类型定义 =====================

interface GraphNode {
  id: number;
  brain: Brain;
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  color: string;
  glowColor: string;
  isMaster: boolean;
  ownerIndex: number; // 用于水平分组的 owner 索引
  ownerCount: number; // 同 owner 的总数（用于簇宽度估算）
  ownerSlot: number;  // 在 owner 内部的序号
}

interface GraphEdge {
  source: GraphNode;
  target: GraphNode;
  particles: Particle[];
}

interface Particle {
  t: number; // 0~1 progress along edge
  speed: number;
  size: number;
  alpha: number;
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

const OWNER_COLORS = [
  '#00d4ff', '#ff6b9d', '#c084fc', '#34d399',
  '#fbbf24', '#f97316', '#06b6d4', '#a78bfa',
  '#fb7185', '#4ade80', '#38bdf8', '#e879f9',
];

const STATE_COLORS: Record<string, string> = {
  active: '#00ff88',
  thinking: '#00ff88',
  dormant: '#4488ff',
  paused: '#4488ff',
  completed: '#ffffff',
  archived: '#666666',
  gestating: '#fbbf24',
};

// 布局区域比例（相对于画布高度）
const MASTER_Y_RATIO = 0.16;       // 主脑固定 Y 位置
const BRANCH_Y_TOP_RATIO = 0.42;   // 分支区域上界
const BRANCH_Y_BOT_RATIO = 0.86;   // 分支区域下界
const BRANCH_Y_CENTER_RATIO = 0.64; // 分支重力锚点（向下偏置）

// ===================== 力导向算法 =====================

function applyForces(
  nodes: GraphNode[],
  edges: GraphEdge[],
  width: number,
  height: number,
  ownerCount: number,
) {
  const masterX = width / 2;
  const masterY = height * MASTER_Y_RATIO;
  const branchTop = height * BRANCH_Y_TOP_RATIO;
  const branchBot = height * BRANCH_Y_BOT_RATIO;
  const branchCenterY = height * BRANCH_Y_CENTER_RATIO;

  const repulsion = 6500;
  const damping = 0.88;
  const xSpring = 0.012;       // 水平弹簧力（向 owner 锚点）
  const yGravity = 0.006;      // 垂直向下重力（向 branchCenterY 收拢）
  const edgeSpringX = 0.0003;  // 连线的横向拉力（很弱，避免分支被拉到主脑下方）

  // 计算 owner 的 X 锚点：均匀分布在画布宽度内（带边距）
  const margin = Math.max(120, width * 0.08);
  const usableWidth = width - margin * 2;
  const ownerAnchor = (idx: number, slot: number, slotsInOwner: number) => {
    if (ownerCount <= 1) {
      // 单 owner：根据 slot 在整宽内分散
      const t = slotsInOwner > 1 ? slot / (slotsInOwner - 1) : 0.5;
      return margin + t * usableWidth;
    }
    const groupCenter = margin + (idx + 0.5) * (usableWidth / ownerCount);
    // 同 owner 在簇内偏移（紧凑居中）
    const clusterSpread = Math.min(160, usableWidth / ownerCount * 0.7);
    const clusterT = slotsInOwner > 1 ? (slot / (slotsInOwner - 1) - 0.5) : 0;
    return groupCenter + clusterT * clusterSpread;
  };

  // 节点间斥力（X 与 Y 都生效，让分支不重叠）
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i];
      const b = nodes[j];
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const force = repulsion / (dist * dist);
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      if (!a.isMaster) { a.vx -= fx; a.vy -= fy; }
      if (!b.isMaster) { b.vx += fx; b.vy += fy; }
    }
  }

  // 连线弹簧力：仅作用于 X 方向上的轻微拉力，避免上下被强行拉拢
  for (const edge of edges) {
    if (edge.source.isMaster && !edge.target.isMaster) {
      const dx = edge.target.x - edge.source.x;
      // 让分支轻微向主脑正下方靠拢，但只在 X 上施力
      edge.target.vx -= dx * edgeSpringX;
    }
  }

  // 对分支节点：水平向 owner 锚点弹簧力 + 垂直向下重力
  for (const node of nodes) {
    if (node.isMaster) continue;
    const targetX = ownerAnchor(node.ownerIndex, node.ownerSlot, node.ownerCount);
    node.vx += (targetX - node.x) * xSpring;
    node.vy += (branchCenterY - node.y) * yGravity;
  }

  // 应用速度并约束
  for (const node of nodes) {
    if (node.isMaster) {
      node.x = masterX;
      node.y = masterY;
      node.vx = 0;
      node.vy = 0;
      continue;
    }
    node.vx *= damping;
    node.vy *= damping;
    node.x += node.vx;
    node.y += node.vy;
    // X 边界
    const mx = node.radius + 16;
    node.x = Math.max(mx, Math.min(width - mx, node.x));
    // Y 限制在分支区域内
    if (node.y < branchTop) {
      node.y = branchTop;
      if (node.vy < 0) node.vy = 0;
    }
    if (node.y > branchBot) {
      node.y = branchBot;
      if (node.vy > 0) node.vy = 0;
    }
  }
}

// ===================== 组件 =====================

export default function BigScreen() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animFrameRef = useRef<number>(0);
  const nodesRef = useRef<GraphNode[]>([]);
  const edgesRef = useRef<GraphEdge[]>([]);
  const bgStarsRef = useRef<BgStar[]>([]);
  const ownerCountRef = useRef<number>(1);
  const mouseRef = useRef<{ x: number; y: number }>({ x: -1000, y: -1000 });
  const hoveredNodeRef = useRef<GraphNode | null>(null);
  const [hoveredBrain, setHoveredBrain] = useState<Brain | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [stats, setStats] = useState({ total: 0, active: 0, totalCE: 0 });
  const [loading, setLoading] = useState(true);
  const scaleRef = useRef(1);
  const offsetRef = useRef({ x: 0, y: 0 });
  const dragRef = useRef<{ dragging: boolean; lastX: number; lastY: number }>({ dragging: false, lastX: 0, lastY: 0 });
  const timeRef = useRef(0);

  // Build graph from brains data
  const buildGraph = useCallback((brains: Brain[], width: number, height: number) => {
    const ownerColorMap = new Map<string, string>();
    const ownerIndexMap = new Map<string, number>();
    const ownerSlotCounter = new Map<string, number>();
    const ownerTotalMap = new Map<string, number>();
    let colorIdx = 0;
    const masterX = width / 2;
    const masterY = height * MASTER_Y_RATIO;
    const branchTop = height * BRANCH_Y_TOP_RATIO;
    const branchBot = height * BRANCH_Y_BOT_RATIO;

    const nodes: GraphNode[] = [];
    const edges: GraphEdge[] = [];

    // Sort: master first, then group by owner so cluster stays together
    const sorted = [...brains].sort((a, b) => {
      if (a.brain_type === 'master') return -1;
      if (b.brain_type === 'master') return 1;
      const oa = a.owner_username || 'unknown';
      const ob = b.owner_username || 'unknown';
      if (oa !== ob) return oa.localeCompare(ob);
      return a.id - b.id;
    });

    // 预先统计每个 owner 下的分支总数（不含 master）
    for (const brain of sorted) {
      if (brain.brain_type === 'master') continue;
      const owner = brain.owner_username || 'unknown';
      ownerTotalMap.set(owner, (ownerTotalMap.get(owner) || 0) + 1);
    }

    // 为非 master owner 建立索引顺序
    let nonMasterOwnerIdx = 0;

    for (const brain of sorted) {
      const owner = brain.owner_username || 'unknown';
      if (!ownerColorMap.has(owner)) {
        ownerColorMap.set(owner, OWNER_COLORS[colorIdx % OWNER_COLORS.length]);
        colorIdx++;
      }

      const isMaster = brain.brain_type === 'master';
      // 主脑稍微更大（俯瞰感）
      const radius = isMaster ? 62 : 18 + Math.min((brain.think_count || 0) * 0.5, 22);
      const color = isMaster ? '#ffcc00' : ownerColorMap.get(owner)!;
      const stateColor = STATE_COLORS[brain.state] || '#666666';

      let ownerIndex = 0;
      let ownerSlot = 0;
      const ownerCount = ownerTotalMap.get(owner) || 1;
      if (!isMaster) {
        if (!ownerIndexMap.has(owner)) {
          ownerIndexMap.set(owner, nonMasterOwnerIdx++);
        }
        ownerIndex = ownerIndexMap.get(owner)!;
        ownerSlot = ownerSlotCounter.get(owner) || 0;
        ownerSlotCounter.set(owner, ownerSlot + 1);
      }

      // 初始位置：master 顶部居中；branch 在下方区域内随机散布
      const initX = isMaster
        ? masterX
        : 80 + Math.random() * (width - 160);
      const initY = isMaster
        ? masterY
        : branchTop + Math.random() * (branchBot - branchTop);

      nodes.push({
        id: brain.id,
        brain,
        x: initX,
        y: initY,
        vx: 0,
        vy: 0,
        radius,
        color,
        glowColor: stateColor,
        isMaster,
        ownerIndex,
        ownerCount,
        ownerSlot,
      });
    }

    ownerCountRef.current = Math.max(1, nonMasterOwnerIdx);

    // Build edges: master → branches
    const masterNode = nodes.find(n => n.isMaster);
    if (masterNode) {
      for (const node of nodes) {
        if (!node.isMaster) {
          const particles: Particle[] = [];
          for (let i = 0; i < 4; i++) {
            particles.push({
              t: Math.random(),
              speed: 0.0025 + Math.random() * 0.0035,
              size: 1.8 + Math.random() * 2,
              alpha: 0.55 + Math.random() * 0.4,
            });
          }
          edges.push({ source: masterNode, target: node, particles });
        }
      }
    }

    nodesRef.current = nodes;
    edgesRef.current = edges;
  }, []);

  // Generate background stars
  const generateBgStars = useCallback((width: number, height: number) => {
    const stars: BgStar[] = [];
    for (let i = 0; i < 320; i++) {
      stars.push({
        x: Math.random() * width,
        y: Math.random() * height,
        size: Math.random() * 1.5 + 0.5,
        alpha: Math.random() * 0.8 + 0.2,
        twinkleSpeed: 0.01 + Math.random() * 0.03,
        twinklePhase: Math.random() * Math.PI * 2,
      });
    }
    bgStarsRef.current = stars;
  }, []);

  // Fetch data
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

  // Animation loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const render = () => {
      const w = canvas.width;
      const h = canvas.height;
      timeRef.current += 1;

      // Apply forces
      applyForces(nodesRef.current, edgesRef.current, w, h, ownerCountRef.current);

      ctx.save();
      // Clear
      ctx.fillStyle = '#000011';
      ctx.fillRect(0, 0, w, h);

      // 顶部辐射状渐变（从主脑位置发散，强化"天眼俯瞰"）
      const masterPx = w / 2;
      const masterPy = h * MASTER_Y_RATIO;
      const bgGrad = ctx.createRadialGradient(masterPx, masterPy, 0, masterPx, masterPy, w * 0.85);
      bgGrad.addColorStop(0, 'rgba(40, 30, 80, 0.45)');
      bgGrad.addColorStop(0.4, 'rgba(15, 20, 50, 0.25)');
      bgGrad.addColorStop(1, 'rgba(0, 0, 10, 0)');
      ctx.fillStyle = bgGrad;
      ctx.fillRect(0, 0, w, h);

      // 底部分支区域微亮的"地平面"光晕
      const floorGrad = ctx.createLinearGradient(0, h * 0.55, 0, h);
      floorGrad.addColorStop(0, 'rgba(20, 30, 70, 0)');
      floorGrad.addColorStop(1, 'rgba(20, 40, 90, 0.25)');
      ctx.fillStyle = floorGrad;
      ctx.fillRect(0, h * 0.55, w, h * 0.45);

      // Apply pan/zoom
      ctx.translate(offsetRef.current.x, offsetRef.current.y);
      ctx.scale(scaleRef.current, scaleRef.current);

      // Background stars
      for (const star of bgStarsRef.current) {
        const twinkle = Math.sin(timeRef.current * star.twinkleSpeed + star.twinklePhase) * 0.3 + 0.7;
        ctx.beginPath();
        ctx.arc(star.x, star.y, star.size, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(200, 220, 255, ${star.alpha * twinkle})`;
        ctx.fill();
      }

      // Draw edges with particles (slight curves from master downward)
      for (const edge of edgesRef.current) {
        const { source, target } = edge;
        const sx = source.x;
        const sy = source.y;
        const tx = target.x;
        const ty = target.y;

        // 控制点：在路径中段、向横向偏移制造柔和弧线
        const midX = (sx + tx) / 2;
        const midY = (sy + ty) / 2;
        const dxAbs = tx - sx;
        // 弧线弯曲度：与水平距离成比例，且让左/右分支自然外扩
        const curveBias = Math.sign(dxAbs) * Math.min(Math.abs(dxAbs) * 0.18, 80);
        const cpX = midX + curveBias;
        const cpY = midY + 30; // 略微向下凹陷

        // Edge line
        const edgeGrad = ctx.createLinearGradient(sx, sy, tx, ty);
        edgeGrad.addColorStop(0, 'rgba(255, 210, 80, 0.45)');
        edgeGrad.addColorStop(0.6, `${target.color}55`);
        edgeGrad.addColorStop(1, `${target.color}22`);
        ctx.beginPath();
        ctx.moveTo(sx, sy);
        ctx.quadraticCurveTo(cpX, cpY, tx, ty);
        ctx.strokeStyle = edgeGrad;
        ctx.lineWidth = 1.2;
        ctx.shadowBlur = 6;
        ctx.shadowColor = 'rgba(255, 200, 80, 0.35)';
        ctx.stroke();
        ctx.shadowBlur = 0;

        // Particles along curved edge (top → bottom)
        for (const p of edge.particles) {
          p.t += p.speed;
          if (p.t > 1) p.t -= 1;
          const t = p.t;
          const oneMt = 1 - t;
          // 二次贝塞尔曲线点公式
          const px = oneMt * oneMt * sx + 2 * oneMt * t * cpX + t * t * tx;
          const py = oneMt * oneMt * sy + 2 * oneMt * t * cpY + t * t * ty;
          const pAlpha = p.alpha * Math.sin(t * Math.PI);
          // 粒子双层：内核 + 外晕
          ctx.beginPath();
          ctx.arc(px, py, p.size * 2.4, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(255, 220, 120, ${pAlpha * 0.25})`;
          ctx.fill();
          ctx.beginPath();
          ctx.arc(px, py, p.size, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(255, 240, 180, ${pAlpha})`;
          ctx.fill();
        }
      }

      // Draw nodes
      const hovered = hoveredNodeRef.current;
      for (const node of nodesRef.current) {
        const { x, y, radius, color, glowColor, isMaster, brain } = node;
        const isHovered = hovered === node;
        const pulse = Math.sin(timeRef.current * 0.05) * 0.2 + 0.8;
        const isActive = brain.state === 'active' || brain.state === 'thinking';

        // Glow
        const glowRadius = isMaster ? radius * 3.4 : radius * 2;
        const glowIntensity = isMaster ? 0.45 : (isActive ? 0.3 * pulse : 0.15);
        const grad = ctx.createRadialGradient(x, y, radius * 0.5, x, y, glowRadius);
        grad.addColorStop(0, glowColor + (isMaster ? '88' : '66'));
        grad.addColorStop(0.5, glowColor + '22');
        grad.addColorStop(1, 'transparent');
        ctx.beginPath();
        ctx.arc(x, y, glowRadius, 0, Math.PI * 2);
        ctx.fillStyle = grad;
        ctx.globalAlpha = glowIntensity + (isHovered ? 0.3 : 0);
        ctx.fill();
        ctx.globalAlpha = 1;

        // 主脑专属：脉冲辐射光环
        if (isMaster) {
          for (let r = 0; r < 3; r++) {
            const ringPhase = (timeRef.current * 0.012 + r * 0.45) % 1;
            const ringR = radius + ringPhase * radius * 2.8;
            const ringAlpha = (1 - ringPhase) * 0.35;
            ctx.beginPath();
            ctx.arc(x, y, ringR, 0, Math.PI * 2);
            ctx.strokeStyle = `rgba(255, 220, 120, ${ringAlpha})`;
            ctx.lineWidth = 1.2;
            ctx.stroke();
          }
        }

        // Node body
        const bodyGrad = ctx.createRadialGradient(x - radius * 0.3, y - radius * 0.3, 0, x, y, radius);
        bodyGrad.addColorStop(0, isMaster ? '#fff8e0' : lightenColor(color, 40));
        bodyGrad.addColorStop(0.7, color);
        bodyGrad.addColorStop(1, darkenColor(color, 30));
        ctx.beginPath();
        ctx.arc(x, y, radius * (isHovered ? 1.15 : 1), 0, Math.PI * 2);
        ctx.fillStyle = bodyGrad;
        ctx.fill();

        // Active ring pulse
        if (isActive && !isMaster) {
          const ringRadius = radius + 5 + Math.sin(timeRef.current * 0.08) * 3;
          ctx.beginPath();
          ctx.arc(x, y, ringRadius, 0, Math.PI * 2);
          ctx.strokeStyle = `${glowColor}${Math.round(pulse * 80).toString(16).padStart(2, '0')}`;
          ctx.lineWidth = 2;
          ctx.stroke();
        }

        // Master corona effect（保留日冕）
        if (isMaster) {
          for (let i = 0; i < 12; i++) {
            const angle = (timeRef.current * 0.008) + (i * Math.PI * 2 / 12);
            const coronaLen = radius + 18 + Math.sin(timeRef.current * 0.03 + i) * 12;
            const cx2 = x + Math.cos(angle) * coronaLen;
            const cy2 = y + Math.sin(angle) * coronaLen;
            ctx.beginPath();
            ctx.moveTo(x + Math.cos(angle) * radius, y + Math.sin(angle) * radius);
            ctx.lineTo(cx2, cy2);
            ctx.strokeStyle = `rgba(255, 200, 50, ${0.32 + Math.sin(timeRef.current * 0.05 + i) * 0.22})`;
            ctx.lineWidth = 2;
            ctx.stroke();
          }
        }

        // Label
        ctx.fillStyle = '#ffffff';
        ctx.font = isMaster ? 'bold 16px sans-serif' : '11px sans-serif';
        ctx.textAlign = 'center';
        // 主脑标签放在节点上方（避免被日冕遮挡），分支标签在节点下方
        const labelY = isMaster ? y - radius - 22 : y + radius + 16;
        ctx.fillText(
          brain.name.length > 14 ? brain.name.slice(0, 14) + '…' : brain.name,
          x,
          labelY,
        );
      }

      ctx.restore();
      animFrameRef.current = requestAnimationFrame(render);
    };

    animFrameRef.current = requestAnimationFrame(render);
    return () => cancelAnimationFrame(animFrameRef.current);
  }, []);

  // Mouse events
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const getTransformedPos = (clientX: number, clientY: number) => {
      const x = (clientX - offsetRef.current.x) / scaleRef.current;
      const y = (clientY - offsetRef.current.y) / scaleRef.current;
      return { x, y };
    };

    const handleMouseMove = (e: MouseEvent) => {
      mouseRef.current = { x: e.clientX, y: e.clientY };

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
        if (Math.sqrt(dx * dx + dy * dy) < node.radius + 5) {
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
      // Zoom toward cursor
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

  // Resize
  useEffect(() => {
    const handleResize = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      generateBgStars(canvas.width, canvas.height);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [generateBgStars]);

  return (
    <div style={{ width: '100vw', height: '100vh', overflow: 'hidden', background: '#000011', position: 'relative' }}>
      <canvas
        ref={canvasRef}
        style={{ display: 'block', width: '100%', height: '100%' }}
      />

      {/* Loading */}
      {loading && (
        <div style={{
          position: 'absolute', inset: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#4488ff', fontSize: 18, fontFamily: 'sans-serif',
        }}>
          正在加载大脑拓扑数据…
        </div>
      )}

      {/* Title */}
      <div style={{
        position: 'absolute', top: 24, left: '50%', transform: 'translateX(-50%)',
        color: '#ffffff', fontSize: 20, fontWeight: 700, letterSpacing: 4,
        fontFamily: 'sans-serif', textShadow: '0 0 20px rgba(100,150,255,0.5)',
        opacity: 0.9, pointerEvents: 'none',
      }}>
        ✦ AInstein · 硅基大脑拓扑全景 ✦
      </div>

      {/* Stats Overlay */}
      <div style={{
        position: 'absolute', bottom: 30, left: 30,
        color: '#aaccff', fontSize: 13, fontFamily: 'monospace',
        background: 'rgba(0,5,20,0.7)', borderRadius: 8, padding: '12px 18px',
        border: '1px solid rgba(60,100,200,0.3)', backdropFilter: 'blur(6px)',
        pointerEvents: 'none',
      }}>
        <div style={{ marginBottom: 4 }}>
          <span style={{ color: '#4488ff' }}>■</span> 大脑总数：<span style={{ color: '#fff', fontWeight: 600 }}>{stats.total}</span>
        </div>
        <div style={{ marginBottom: 4 }}>
          <span style={{ color: '#00ff88' }}>■</span> 活跃中：<span style={{ color: '#00ff88', fontWeight: 600 }}>{stats.active}</span>
        </div>
        <div>
          <span style={{ color: '#c084fc' }}>■</span> 认知元素：<span style={{ color: '#c084fc', fontWeight: 600 }}>{stats.totalCE}</span>
        </div>
      </div>

      {/* Tooltip */}
      {hoveredBrain && (
        <div style={{
          position: 'absolute',
          left: tooltipPos.x,
          top: tooltipPos.y,
          background: 'rgba(5, 10, 30, 0.92)',
          border: '1px solid rgba(80,140,255,0.4)',
          borderRadius: 8,
          padding: '12px 16px',
          color: '#ddeeff',
          fontSize: 12,
          fontFamily: 'monospace',
          pointerEvents: 'none',
          backdropFilter: 'blur(8px)',
          maxWidth: 300,
          zIndex: 999,
        }}>
          <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 6, color: '#fff' }}>
            {hoveredBrain.name}
          </div>
          <div style={{ marginBottom: 3, color: '#88aacc' }}>
            {hoveredBrain.seed_question?.slice(0, 60)}{(hoveredBrain.seed_question?.length || 0) > 60 ? '…' : ''}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '3px 12px', marginTop: 6 }}>
            <span>状态：<b style={{ color: STATE_COLORS[hoveredBrain.state] || '#fff' }}>{hoveredBrain.state}</b></span>
            <span>类型：{hoveredBrain.brain_type || 'standalone'}</span>
            <span>思考轮次：{hoveredBrain.think_count ?? 0}</span>
            <span>CE 数量：{hoveredBrain.ce_count ?? 0}</span>
            <span>Agent 数：{hoveredBrain.agent_count ?? 0}</span>
            <span>Owner：{hoveredBrain.owner_username || '—'}</span>
          </div>
          <div style={{ marginTop: 6, color: '#667788', fontSize: 11 }}>
            创建于 {hoveredBrain.created_at?.slice(0, 16).replace('T', ' ')}
          </div>
        </div>
      )}
    </div>
  );
}

// ===================== 工具函数 =====================

function lightenColor(hex: string, percent: number): string {
  const num = parseInt(hex.replace('#', ''), 16);
  const r = Math.min(255, ((num >> 16) & 0xff) + percent);
  const g = Math.min(255, ((num >> 8) & 0xff) + percent);
  const b = Math.min(255, (num & 0xff) + percent);
  return `rgb(${r},${g},${b})`;
}

function darkenColor(hex: string, percent: number): string {
  const num = parseInt(hex.replace('#', ''), 16);
  const r = Math.max(0, ((num >> 16) & 0xff) - percent);
  const g = Math.max(0, ((num >> 8) & 0xff) - percent);
  const b = Math.max(0, (num & 0xff) - percent);
  return `rgb(${r},${g},${b})`;
}
