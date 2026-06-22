import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import * as d3 from 'd3'
import { api, generatePaper, getPaperStatus, sharePaper } from '../api'
import type { Brain, CognitiveNode, KnowledgeGraph, PaperShare, ThinkingSummary } from '../types'
import ObserverPanel from '../components/ObserverPanel'
import { track } from '../tracking'

// ---------- 类型 ----------
interface GraphNode extends d3.SimulationNodeDatum, CognitiveNode {
  __entered?: boolean
}

interface GraphLink extends d3.SimulationLinkDatum<GraphNode> {
  id: number
  source: number | GraphNode
  target: number | GraphNode
  relation_type: string
  weight: number
}

// ---------- CE 类型映射 ----------
const CE_COLORS: Record<string, string> = {
  observation: '#64748b',
  question: '#f59e0b',
  hypothesis: '#8b5cf6',
  evidence: '#22c55e',
  counter_evidence: '#ef4444',
  inference: '#06b6d4',
  argument: '#3b82f6',
  conclusion: '#10b981',
  perspective: '#ec4899',
  insight: '#f97316',
  consensus: '#fbbf24',
  dissent: '#dc2626',
  tool_gap: '#a78bfa',
}

const CE_LABELS: Record<string, string> = {
  observation: '观察',
  question: '问题',
  hypothesis: '假设',
  evidence: '证据',
  counter_evidence: '反证',
  inference: '推论',
  argument: '论证',
  conclusion: '结论',
  perspective: '视角',
  insight: '洞察',
  consensus: '共识',
  dissent: '异见',
  tool_gap: '工具缺口',
}

const REL_LABELS: Record<string, string> = {
  supports: '支持',
  refutes: '反驳',
  derives_from: '推导自',
  contradicts: '矛盾',
  related_to: '关联',
  answers: '回答',
}

const nodeColor = (t: string) => CE_COLORS[t] || '#64748b'
const nodeRadius = (c: number) => 8 + 24 * Math.max(0, Math.min(1, c || 0))

function edgeStyle(t: string) {
  if (t === 'supports' || t === 'derives_from') return { color: '#22c55e', dash: '', marker: 'green' }
  if (t === 'refutes' || t === 'contradicts') return { color: '#ef4444', dash: '6,4', marker: 'red' }
  return { color: '#5b6175', dash: '', marker: 'gray' }
}

// ---------- 主组件 ----------
export default function BrainView() {
  const { brainId } = useParams()
  const bid = Number(brainId)
  const navigate = useNavigate()

  const [graph, setGraph] = useState<KnowledgeGraph>({ nodes: [], edges: [] })
  const [selected, setSelected] = useState<CognitiveNode | null>(null)
  const [hover, setHover] = useState<{ node: CognitiveNode; x: number; y: number } | null>(null)
  const [error, setError] = useState<string>('')
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date())
  const [isNarrow, setIsNarrow] = useState<boolean>(
    typeof window !== 'undefined' ? window.innerWidth < 1100 : false,
  )
  const [activeFilters, setActiveFilters] = useState<string[]>([])

  // ---------- 大脑信息 + 思考总结 ----------
  const [brain, setBrain] = useState<Brain | null>(null)
  const [thinkingSummary, setThinkingSummary] = useState<ThinkingSummary | null>(null)
  const [, setSummaryLoading] = useState(false)
  const [summaryExpanded, setSummaryExpanded] = useState(false)
  const brainState = brain?.state
  const brainMode: 'fast' | 'deep' = ((brain?.config as any)?.mode === 'fast') ? 'fast' : 'deep'
  const [fastRemain, setFastRemain] = useState<number | null>(null)

  // ---------- 研究报告生成状态机 ----------
  const [paperState, setPaperState] = useState<'idle' | 'processing' | 'done' | 'error'>('idle')
  const [paperTaskId, setPaperTaskId] = useState<string | null>(null)
  const [paperProgress, setPaperProgress] = useState<string>('')
  const [paperDownloadUrl, setPaperDownloadUrl] = useState<string>('')
  const [paperError, setPaperError] = useState<string>('')
  const paperPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 清理轮询 interval
  useEffect(() => {
    return () => {
      if (paperPollRef.current) clearInterval(paperPollRef.current)
    }
  }, [])

  // 页面查看埋点
  useEffect(() => {
    if (Number.isFinite(bid)) {
      track('page.view', { page: 'brain_view', brain_id: bid })
    }
  }, [bid])

  // 快思考模式倒计时（5 分钟兜底）
  useEffect(() => {
    if (brainMode !== 'fast' || brainState !== 'active' || !brain?.started_at) {
      setFastRemain(null)
      return
    }
    const startTs = new Date(brain.started_at.replace(' ', 'T') + 'Z').getTime()
    const tick = () => {
      const elapsed = (Date.now() - startTs) / 1000
      const remain = Math.max(0, Math.ceil(300 - elapsed))
      setFastRemain(remain)
    }
    tick()
    const t = window.setInterval(tick, 1000)
    return () => window.clearInterval(t)
  }, [brainMode, brainState, brain?.started_at])

  async function handleGeneratePaper() {
    try {
      setPaperState('processing')
      setPaperProgress('正在提交任务…')
      setPaperError('')
      const res = await generatePaper(bid)
      setPaperTaskId(res.task_id)

      // 启动轮询
      if (paperPollRef.current) clearInterval(paperPollRef.current)
      paperPollRef.current = setInterval(async () => {
        try {
          const status = await getPaperStatus(bid, res.task_id)
          if (status.status === 'done') {
            if (paperPollRef.current) clearInterval(paperPollRef.current)
            setPaperState('done')
            setPaperDownloadUrl(status.download_url || '')
            setPaperProgress('')
          } else if (status.status === 'error') {
            if (paperPollRef.current) clearInterval(paperPollRef.current)
            setPaperState('error')
            setPaperError(status.error || '生成失败')
            setPaperProgress('')
          } else {
            setPaperProgress(status.progress || '正在生成中…')
          }
        } catch (e: any) {
          if (paperPollRef.current) clearInterval(paperPollRef.current)
          setPaperState('error')
          setPaperError(e?.message || '轮询状态失败')
          setPaperProgress('')
        }
      }, 3000)
    } catch (e: any) {
      setPaperState('error')
      setPaperError(e?.message || '提交任务失败')
    }
  }

  function handleDownloadPaper() {
    if (paperDownloadUrl) {
      window.open(paperDownloadUrl, '_blank')
    }
  }

  // ---------- 论文分享 ----------
  const [share, setShare] = useState<PaperShare | null>(null)
  const [shareLoading, setShareLoading] = useState(false)
  const [shareError, setShareError] = useState('')
  const [shareCopied, setShareCopied] = useState(false)
  const [sharePanelOpen, setSharePanelOpen] = useState(false)

  const buildAbsoluteShareUrl = (path: string) => {
    if (typeof window === 'undefined') return path
    return `${window.location.origin}${path}`
  }

  async function handleSharePaper() {
    setShareError('')
    setShareLoading(true)
    try {
      const res = await sharePaper(bid)
      setShare(res)
      setSharePanelOpen(true)
      track('paper.share_clicked', { brain_id: bid, token: res.share_token })
    } catch (e: any) {
      setShareError(e?.message || '分享失败')
      setSharePanelOpen(true)
    } finally {
      setShareLoading(false)
    }
  }

  async function handleCopyShareLink() {
    if (!share?.url) return
    const fullUrl = buildAbsoluteShareUrl(share.url)
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(fullUrl)
      } else {
        const ta = document.createElement('textarea')
        ta.value = fullUrl
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        document.body.removeChild(ta)
      }
      setShareCopied(true)
      setTimeout(() => setShareCopied(false), 1800)
    } catch {
      setShareError('复制失败，请手动选中链接')
    }
  }

  // 监听窗口尺寸 → 切换观察员面板的布局（右侧 / 底部折叠）
  useEffect(() => {
    function onResize() {
      setIsNarrow(window.innerWidth < 1100)
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const containerRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const simRef = useRef<d3.Simulation<GraphNode, GraphLink> | null>(null)
  const nodeMapRef = useRef<Map<number, GraphNode>>(new Map())
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null)
  const userInteractedRef = useRef<boolean>(false)

  // ---------- 自动适配视图：根据所有节点 bounding box 计算 zoom transform ----------
  function fitAllNodes(animate: boolean = true) {
    if (!svgRef.current || !containerRef.current || !zoomRef.current) return
    const nodes = Array.from(nodeMapRef.current.values())
    if (!nodes.length) return
    const w = containerRef.current.clientWidth
    const h = containerRef.current.clientHeight
    if (!w || !h) return

    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
    for (const n of nodes) {
      if (typeof n.x !== 'number' || typeof n.y !== 'number') continue
      if (!isFinite(n.x) || !isFinite(n.y)) continue
      if (n.x < minX) minX = n.x
      if (n.x > maxX) maxX = n.x
      if (n.y < minY) minY = n.y
      if (n.y > maxY) maxY = n.y
    }
    if (!isFinite(minX) || !isFinite(maxX)) return

    const padding = 80
    const bboxWidth = (maxX - minX) + padding * 2
    const bboxHeight = (maxY - minY) + padding * 2
    if (bboxWidth <= 0 || bboxHeight <= 0) return

    const scale = Math.min(w / bboxWidth, h / bboxHeight, 1.5)
    const centerX = (minX + maxX) / 2
    const centerY = (minY + maxY) / 2

    const transform = d3.zoomIdentity
      .translate(w / 2, h / 2)
      .scale(scale)
      .translate(-centerX, -centerY)

    const svg = d3.select(svgRef.current)
    if (animate) {
      svg.transition().duration(750).call(zoomRef.current.transform as any, transform)
    } else {
      svg.call(zoomRef.current.transform as any, transform)
    }
  }

  // ---------- 拉取数据（每 10 秒轮询） ----------
  useEffect(() => {
    if (!bid || Number.isNaN(bid)) return
    let alive = true
    async function load() {
      try {
        // 一次性加载全部 CE 与 relations；后端无 limit 时返回所有数据
        const g = await api.getKnowledgeGraph(bid)
        if (!alive) return
        setGraph(g)
        setLastUpdate(new Date())
        setError('')
      } catch (e: any) {
        if (alive) setError(e?.message || '加载失败')
      }
    }
    load()
    const t = setInterval(load, 10000)
    return () => { alive = false; clearInterval(t) }
  }, [bid])

  // ---------- 拉取 brain 元信息（轮询，用于检测 state 变化） ----------
  useEffect(() => {
    if (!bid || Number.isNaN(bid)) return
    let alive = true
    async function loadBrain() {
      try {
        const b = await api.getBrain(bid)
        if (!alive) return
        setBrain(b)
      } catch {
        /* 忽略：brain 元信息失败不影响图谱展示 */
      }
    }
    loadBrain()
    const t = setInterval(loadBrain, 10000)
    return () => { alive = false; clearInterval(t) }
  }, [bid])

  // ---------- 当 brain 进入 paused/completed 时，拉取"想明白了什么"总结 ----------
  useEffect(() => {
    if (!bid || Number.isNaN(bid)) return
    if (brainState !== 'paused' && brainState !== 'completed') {
      // 思考中 / 未启动 / 归档 — 不展示总结
      setThinkingSummary(null)
      return
    }
    let alive = true
    async function loadSummary() {
      setSummaryLoading(true)
      try {
        const s = await api.getThinkingSummary(bid)
        if (!alive) return
        setThinkingSummary(s)
      } catch {
        if (alive) setThinkingSummary(null)
      } finally {
        if (alive) setSummaryLoading(false)
      }
    }
    loadSummary()
  }, [bid, brainState])

  // ---------- 节点统计 ----------
  const stats = useMemo(() => {
    const m: Record<string, number> = {}
    for (const n of graph.nodes) m[n.ce_type] = (m[n.ce_type] || 0) + 1
    return m
  }, [graph.nodes])

  // ---------- D3 渲染 ----------
  useEffect(() => {
    if (!svgRef.current || !containerRef.current) return
    const w = containerRef.current.clientWidth
    const h = containerRef.current.clientHeight

    // 合并节点：保留旧节点的 x/y/vx/vy，把新内容回填
    const merged: GraphNode[] = graph.nodes.map(n => {
      const old = nodeMapRef.current.get(n.id)
      if (old) {
        Object.assign(old, n)
        return old
      }
      const fresh: GraphNode = {
        ...n,
        x: w / 2 + (Math.random() - 0.5) * 120,
        y: h / 2 + (Math.random() - 0.5) * 120,
        __entered: false,
      }
      return fresh
    })
    const newMap = new Map<number, GraphNode>()
    merged.forEach(n => newMap.set(n.id, n))
    nodeMapRef.current = newMap

    // 识别种子节点：ce_type === 'question' 且 created_at 最早；
    // 当多个 question 的 created_at 完全相同（并列最早）时，用 id 最小作为 tiebreaker，
    // 保证全局唯一种子，避免出现"两个发光点"的视觉假象。
    let seedId: number | null = null
    let seedEarliest: string | undefined
    for (const n of merged) {
      if (n.ce_type !== 'question') continue
      if (!n.created_at) continue
      if (
        seedEarliest === undefined ||
        n.created_at < seedEarliest ||
        (n.created_at === seedEarliest && seedId !== null && n.id < seedId)
      ) {
        seedId = n.id
        seedEarliest = n.created_at
      }
    }

    // 固定种子节点在画布中央，清理其他被标记过的节点的 fx/fy
    for (const n of merged) {
      if (n.id === seedId) {
        n.fx = w / 2
        n.fy = h / 2
        ;(n as any).__seedFixed = true
      } else if ((n as any).__seedFixed) {
        n.fx = null
        n.fy = null
        ;(n as any).__seedFixed = false
      }
    }

    // 种子节点的尺寸/颜色覆盖普通逻辑
    const getRadius = (d: GraphNode) => (d.id === seedId ? 26 : nodeRadius(d.confidence))
    const getColor = (d: GraphNode) => (d.id === seedId ? '#FFD700' : nodeColor(d.ce_type))

    const links: GraphLink[] = graph.edges
      .filter(e => newMap.has(e.source_id) && newMap.has(e.target_id))
      .map(e => ({
        id: e.id,
        source: newMap.get(e.source_id)!,
        target: newMap.get(e.target_id)!,
        relation_type: e.relation_type,
        weight: e.weight,
      }))

    // 创建/更新 simulation
    if (!simRef.current) {
      simRef.current = d3
        .forceSimulation<GraphNode, GraphLink>(merged)
        .force(
          'link',
          d3.forceLink<GraphNode, GraphLink>(links).id(d => d.id).distance(d => 90 + 30 / Math.max(0.4, d.weight)).strength(0.45),
        )
        .force('charge', d3.forceManyBody<GraphNode>().strength(-260))
        .force('center', d3.forceCenter(w / 2, h / 2))
        .force('collision', d3.forceCollide<GraphNode>().radius(d => getRadius(d) + 6))
        .force('x', d3.forceX(w / 2).strength(0.04))
        .force('y', d3.forceY(h / 2).strength(0.04))
    } else {
      simRef.current.nodes(merged)
      const lf = simRef.current.force<d3.ForceLink<GraphNode, GraphLink>>('link')
      if (lf) lf.links(links)
      // 更新 collide 半径，确保新种子节点的更大半径生效
      simRef.current.force(
        'collision',
        d3.forceCollide<GraphNode>().radius(d => getRadius(d) + 6),
      )
      simRef.current.alpha(0.55).restart()
    }

    // ---------- SVG 选择与 join ----------
    const svg = d3.select(svgRef.current)
    svg.attr('viewBox', `0 0 ${w} ${h}`)
    const gRoot = svg.select<SVGGElement>('g.viewport')

    // links
    gRoot
      .select<SVGGElement>('g.links')
      .selectAll<SVGLineElement, GraphLink>('line')
      .data(links, (d: any) => d.id)
      .join(
        enter =>
          enter
            .append('line')
            .attr('stroke', d => edgeStyle(d.relation_type).color)
            .attr('stroke-dasharray', d => edgeStyle(d.relation_type).dash)
            .attr('stroke-width', d => 1 + Math.min(3, d.weight || 1))
            .attr('stroke-opacity', 0)
            .attr('marker-end', d => `url(#arrow-${edgeStyle(d.relation_type).marker})`)
            .call(s => s.transition().duration(700).attr('stroke-opacity', 0.55)),
        update =>
          update
            .attr('stroke', d => edgeStyle(d.relation_type).color)
            .attr('stroke-dasharray', d => edgeStyle(d.relation_type).dash)
            .attr('stroke-width', d => 1 + Math.min(3, d.weight || 1))
            .attr('marker-end', d => `url(#arrow-${edgeStyle(d.relation_type).marker})`),
        exit => exit.transition().duration(400).attr('stroke-opacity', 0).remove(),
      )

    // nodes
    const nodeSel = gRoot
      .select<SVGGElement>('g.nodes')
      .selectAll<SVGGElement, GraphNode>('g.node')
      .data(merged, (d: any) => d.id)
      .join(
        enter => {
          const g = enter
            .append('g')
            .attr('class', d => 'node' + (d.id === seedId ? ' seed' : ''))
            .attr('opacity', 0)
            .style('cursor', 'pointer')
          g.append('circle')
            .attr('class', d => 'halo' + (d.id === seedId ? ' seed-halo' : ''))
            .attr('r', d => getRadius(d) + 8)
            .attr('fill', d => getColor(d))
            .attr('opacity', d => (d.id === seedId ? 0.3 : 0.16))
          g.append('circle')
            .attr('class', d => 'core' + (d.id === seedId ? ' seed-core' : ''))
            .attr('r', d => getRadius(d))
            .attr('fill', d => getColor(d))
            .attr('stroke', d => (d.id === seedId ? '#FFE680' : '#0f1117'))
            .attr('stroke-width', d => (d.id === seedId ? 2 : 1.5))
          g.append('text')
            .attr('text-anchor', 'middle')
            .attr('dy', d => getRadius(d) + 14)
            .attr('fill', d => (d.id === seedId ? '#FFD700' : '#cbd5e1'))
            .attr('font-size', d => (d.id === seedId ? 12 : 11))
            .attr('font-weight', d => (d.id === seedId ? 600 : 400))
            .attr('pointer-events', 'none')
            .text(d => {
              const prefix = d.id === seedId ? '◆ ' : ''
              const t = d.title || ''
              return prefix + (t.length > 14 ? t.slice(0, 14) + '…' : t)
            })
          // 入场动画：从 0 透明 + 半径放大
          g.transition().duration(900).attr('opacity', 1)
          g.select<SVGCircleElement>('circle.halo')
            .attr('r', 0)
            .transition()
            .duration(900)
            .attr('r', d => getRadius(d) + 8)
          return g
        },
        update => {
          // 切换 seed class（极端情况：种子节点变更）
          update.attr('class', d => 'node' + (d.id === seedId ? ' seed' : ''))
          update
            .select<SVGCircleElement>('circle.core')
            .attr('class', d => 'core' + (d.id === seedId ? ' seed-core' : ''))
            .attr('stroke', d => (d.id === seedId ? '#FFE680' : '#0f1117'))
            .attr('stroke-width', d => (d.id === seedId ? 2 : 1.5))
            .transition()
            .duration(400)
            .attr('r', d => getRadius(d))
            .attr('fill', d => getColor(d))
          update
            .select<SVGCircleElement>('circle.halo')
            .attr('class', d => 'halo' + (d.id === seedId ? ' seed-halo' : ''))
            .attr('opacity', d => (d.id === seedId ? 0.3 : 0.16))
            .transition()
            .duration(400)
            .attr('r', d => getRadius(d) + 8)
            .attr('fill', d => getColor(d))
          update
            .select<SVGTextElement>('text')
            .attr('fill', d => (d.id === seedId ? '#FFD700' : '#cbd5e1'))
            .attr('font-size', d => (d.id === seedId ? 12 : 11))
            .attr('font-weight', d => (d.id === seedId ? 600 : 400))
            .text(d => {
              const prefix = d.id === seedId ? '◆ ' : ''
              const t = d.title || ''
              return prefix + (t.length > 14 ? t.slice(0, 14) + '…' : t)
            })
            .attr('dy', d => getRadius(d) + 14)
          return update
        },
        exit => exit.transition().duration(400).attr('opacity', 0).remove(),
      )

    // 兜底：每次渲染统一同步所有节点的 seed class，避免 enter/update 分支
    // 在某些边缘情况（如 simulation 重启、节点合并）下遗留旧种子标记导致出现多个发光点。
    gRoot
      .select<SVGGElement>('g.nodes')
      .selectAll<SVGGElement, GraphNode>('g.node')
      .classed('seed', d => d.id === seedId)
    gRoot
      .select<SVGGElement>('g.nodes')
      .selectAll<SVGCircleElement, GraphNode>('circle.core, circle.seed-core')
      .attr('class', d => 'core' + (d.id === seedId ? ' seed-core' : ''))
    gRoot
      .select<SVGGElement>('g.nodes')
      .selectAll<SVGCircleElement, GraphNode>('circle.halo, circle.seed-halo')
      .attr('class', d => 'halo' + (d.id === seedId ? ' seed-halo' : ''))

    // 拖拽
    const drag = d3
      .drag<SVGGElement, GraphNode>()
      .on('start', (event, d) => {
        if (!event.active) simRef.current?.alphaTarget(0.3).restart()
        d.fx = d.x
        d.fy = d.y
      })
      .on('drag', (event, d) => {
        d.fx = event.x
        d.fy = event.y
      })
      .on('end', (event, d) => {
        if (!event.active) simRef.current?.alphaTarget(0)
        d.fx = null
        d.fy = null
      })
    nodeSel.call(drag as any)

    // 悬停 / 点击
    nodeSel
      .on('mouseenter', function (event: MouseEvent, d) {
        setHover({ node: d, x: event.clientX, y: event.clientY })
      })
      .on('mousemove', function (event: MouseEvent, d) {
        setHover({ node: d, x: event.clientX, y: event.clientY })
      })
      .on('mouseleave', function () {
        setHover(null)
      })
      .on('click', function (event: MouseEvent, d) {
        event.stopPropagation()
        setSelected(prev => (prev && prev.id === d.id ? null : d))
      })

    // tick
    simRef.current.on('tick', () => {
      gRoot
        .select('g.links')
        .selectAll<SVGLineElement, GraphLink>('line')
        .attr('x1', d => (d.source as GraphNode).x!)
        .attr('y1', d => (d.source as GraphNode).y!)
        .attr('x2', d => (d.target as GraphNode).x!)
        .attr('y2', d => (d.target as GraphNode).y!)
      nodeSel.attr('transform', d => `translate(${d.x},${d.y})`)
    })

    // 一次性的 end 监听器：仅在本次 graph 数据稳定时 fit 一次，
    // 避免后续用户拖拽节点导致的 simulation restart 反复重置视图
    let fitted = false
    simRef.current.on('end', () => {
      if (fitted) return
      fitted = true
      fitAllNodes(true)
    })

    return () => {
      simRef.current?.on('tick', null)
      simRef.current?.on('end', null)
    }
  }, [graph])

  // ---------- 选中节点高亮 ----------
  useEffect(() => {
    if (!svgRef.current) return
    const svg = d3.select(svgRef.current)
    const allNodes = svg.selectAll<SVGGElement, GraphNode>('g.node')
    const allLinks = svg.selectAll<SVGLineElement, GraphLink>('g.links line')
    if (!selected) {
      allNodes.transition().duration(200).attr('opacity', 1)
      allNodes.select<SVGCircleElement>('circle.core').each(function () {
        const sel = d3.select(this)
        const isSeed = sel.classed('seed-core')
        sel.attr('stroke', isSeed ? '#FFE680' : '#0f1117').attr('stroke-width', isSeed ? 2 : 1.5)
      })
      allLinks.transition().duration(200).attr('stroke-opacity', 0.55)
      return
    }
    const id = selected.id
    const connected = new Set<number>([id])
    allLinks.each(function (d) {
      const s = (d.source as GraphNode).id
      const t = (d.target as GraphNode).id
      if (s === id) connected.add(t)
      if (t === id) connected.add(s)
    })
    allNodes.transition().duration(200).attr('opacity', d => (connected.has(d.id) ? 1 : 0.12))
    allNodes
      .select<SVGCircleElement>('circle.core')
      .each(function (d) {
        const sel = d3.select(this)
        const isSeed = sel.classed('seed-core')
        if (d.id === id) {
          sel.attr('stroke', '#fff').attr('stroke-width', 2.5)
        } else {
          sel.attr('stroke', isSeed ? '#FFE680' : '#0f1117').attr('stroke-width', isSeed ? 2 : 1.5)
        }
      })
    allLinks.transition().duration(200).attr('stroke-opacity', d => {
      const s = (d.source as GraphNode).id
      const t = (d.target as GraphNode).id
      return s === id || t === id ? 0.95 : 0.04
    })
  }, [selected, graph])

  // ---------- CE 类型筛选高亮 ----------
  useEffect(() => {
    if (!svgRef.current) return
    const svg = d3.select(svgRef.current)
    const allNodes = svg.selectAll<SVGGElement, GraphNode>('g.node')
    const allLinks = svg.selectAll<SVGLineElement, GraphLink>('g.links line')

    if (activeFilters.length === 0) {
      // 无筛选 → 恢复正常（但需尊重 selected 状态，只在无 selected 时恢复）
      if (!selected) {
        allNodes.transition().duration(200).attr('opacity', 1)
        allLinks.transition().duration(200).attr('stroke-opacity', 0.55)
      }
      return
    }
    // 有筛选 → 按类型设置透明度
    allNodes.transition().duration(200).attr('opacity', (d: any) =>
      activeFilters.includes(d.ce_type) ? 1 : 0.15,
    )
    allLinks.transition().duration(200).attr('stroke-opacity', (d: any) => {
      const srcType = (d.source as GraphNode).ce_type
      const tgtType = (d.target as GraphNode).ce_type
      return activeFilters.includes(srcType) || activeFilters.includes(tgtType) ? 0.6 : 0.08
    })
  }, [activeFilters, graph, selected])

  // ---------- 缩放 + 平移 ----------
  useEffect(() => {
    if (!svgRef.current) return
    const svg = d3.select(svgRef.current)
    const gRoot = svg.select<SVGGElement>('g.viewport')
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.05, 4])
      .filter((event: any) => {
        // 不让节点拖拽触发画布平移
        if (event.button) return false
        const target = event.target as Element
        if (target && target.closest('g.node')) return false
        return true
      })
      .on('start', (event: any) => {
        // 用户主动操作（鼠标/触控/滚轮）才标记，程序触发的 transition 不算
        if (event.sourceEvent) userInteractedRef.current = true
      })
      .on('zoom', event => {
        gRoot.attr('transform', event.transform.toString())
      })
    zoomRef.current = zoom
    svg.call(zoom as any)
    // 点击空白取消选中
    svg.on('click', () => setSelected(null))
    return () => {
      svg.on('.zoom', null)
      svg.on('click', null)
    }
  }, [])

  // ---------- 渲染 ----------
  return (
    <div style={pageStyle}>
      <header style={headerStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <button onClick={() => navigate('/')} style={backBtn}>
            &larr; 返回
          </button>
          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
              <span style={{ fontSize: 11, color: 'var(--text2)', letterSpacing: 3 }}>SILICON · BRAIN</span>
              <h1 style={{ fontSize: 20, color: 'var(--accent2)', margin: 0 }}>大脑 #{bid}</h1>
              <span style={pulseDot} title="实时同步中" />
              {brain?.brain_type !== 'master' && (
                <span style={modeBadgeStyle(brainMode)} title={brainMode === 'fast' ? '快思考模式：约 5 分钟内收敛' : '深度思考模式：5–60 分钟充分博弈'}>
                  {brainMode === 'fast' ? '⚡ 快思考' : '🧠 深度思考'}
                  {brainMode === 'fast' && fastRemain !== null && (
                    <span style={modeBadgeCountdownStyle}>
                      {'  '}剩余 {Math.floor(fastRemain / 60)}:{String(fastRemain % 60).padStart(2, '0')}
                    </span>
                  )}
                </span>
              )}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 2 }}>
              {(() => {
                const totalN = graph.total_nodes
                const totalE = graph.total_edges
                const loadedN = graph.nodes.length
                const loadedE = graph.edges.length
                const nodeText = typeof totalN === 'number'
                  ? (totalN > loadedN
                      ? `${totalN} 个认知元素（已加载 ${loadedN}）`
                      : `${totalN} 个认知元素`)
                  : `${loadedN} 个认知元素`
                const edgeText = typeof totalE === 'number'
                  ? (totalE > loadedE
                      ? `${totalE} 条关系（已加载 ${loadedE}）`
                      : `${totalE} 条关系`)
                  : `${loadedE} 条关系`
                return `${nodeText} · ${edgeText} · 上次同步 ${lastUpdate.toLocaleTimeString()}`
              })()}
            </div>
          </div>
        </div>

        {/* 研究报告按钮 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {paperState === 'error' && (
            <span style={{ fontSize: 11, color: '#ef4444', maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {paperError}
            </span>
          )}
          {paperState === 'idle' || paperState === 'error' ? (
            <button onClick={handleGeneratePaper} style={paperBtnStyle}>
              📄 生成研究报告
            </button>
          ) : paperState === 'processing' ? (
            <button disabled style={{ ...paperBtnStyle, opacity: 0.7, cursor: 'not-allowed' }}>
              <span className="paper-spinner" />
              {paperProgress || '生成中…'}
            </button>
          ) : paperState === 'done' ? (
            <button onClick={handleDownloadPaper} style={{ ...paperBtnStyle, background: '#166534', borderColor: '#22c55e' }}>
              📥 下载研究报告(PDF)
            </button>
          ) : null}
          {/* 公开分享按钮：paper 已生成过才启用 */}
          <button
            onClick={handleSharePaper}
            disabled={shareLoading || paperState === 'processing'}
            style={{
              ...paperBtnStyle,
              background: 'linear-gradient(135deg, rgba(99,102,241,0.18), rgba(236,72,153,0.18))',
              borderColor: 'rgba(129,140,248,0.55)',
              color: '#c7d2fe',
              opacity: shareLoading ? 0.7 : 1,
            }}
            title="生成公开分享链接"
          >
            {shareLoading ? <span className="paper-spinner" /> : '✨'} 分享论文
          </button>
        </div>
      </header>

      {sharePanelOpen && (
        <div style={sharePanelStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={shareBadgeStyle}>PUBLIC · LINK</span>
              <span style={{ fontSize: 13, color: '#e2e8f0', fontWeight: 500 }}>
                {shareError ? '生成分享链接失败' : '分享链接已准备就绪'}
              </span>
              {share && typeof share.view_count === 'number' && !shareError && (
                <span style={shareCountStyle}>· 已被查看 {share.view_count} 次</span>
              )}
            </div>
            <button onClick={() => setSharePanelOpen(false)} style={shareCloseBtn}>×</button>
          </div>
          {shareError ? (
            <div style={{ marginTop: 10, fontSize: 12, color: '#fca5a5' }}>{shareError}</div>
          ) : share ? (
            <div style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <input
                readOnly
                value={buildAbsoluteShareUrl(share.url)}
                onFocus={e => e.currentTarget.select()}
                style={shareInputStyle}
              />
              <button onClick={handleCopyShareLink} style={shareCopyBtnStyle}>
                {shareCopied ? '✓ 已复制' : '📋 复制链接'}
              </button>
              <a
                href={share.url}
                target="_blank"
                rel="noreferrer"
                style={shareOpenBtnStyle}
                onClick={() => track('paper.share_opened', { brain_id: bid, token: share.share_token })}
              >
                ↗ 预览
              </a>
              {share.pdf_url && (
                <a href={share.pdf_url} target="_blank" rel="noreferrer" style={shareOpenBtnStyle}>
                  📄 PDF
                </a>
              )}
            </div>
          ) : null}
        </div>
      )}

      {error && (
        <div style={{ padding: '6px 24px', background: '#ef444422', color: '#ef4444', fontSize: 12 }}>{error}</div>
      )}

      {thinkingSummary && (brainState === 'paused' || brainState === 'completed') && (
        <div style={summaryCard}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={summaryCardTitle}>🧠 大脑想明白了什么</h3>
            <button
              onClick={() => setSummaryExpanded(e => !e)}
              style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: 12 }}
            >
              {summaryExpanded ? '收起 ▲' : '展开详情 ▼'}
            </button>
          </div>

          {/* 核心答案 - 始终显示 */}
          <div style={coreAnswerStyle}>
            {thinkingSummary.core_answer}
          </div>

          {/* 展开后的详细内容 */}
          {summaryExpanded && (
            <>
              {/* 关键洞察 */}
              {thinkingSummary.key_insights.length > 0 && (
                <div style={sectionStyle}>
                  <h4 style={sectionTitle}>💡 关键洞察</h4>
                  <ul style={insightList}>
                    {thinkingSummary.key_insights.map((insight, i) => (
                      <li key={i} style={insightItem}>
                        <span style={{ flex: 1, lineHeight: 1.6, wordBreak: 'break-word' }}>{insight.summary}</span>
                        <span style={ceRef}>CE#{insight.ce_id} ({(insight.confidence * 100).toFixed(0)}%)</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* 被否定的假说 */}
              {thinkingSummary.refuted.length > 0 && (
                <div style={sectionStyle}>
                  <h4 style={sectionTitle}>❌ 被否定的假说</h4>
                  <ul style={refutedList}>
                    {thinkingSummary.refuted.map((r, i) => (
                      <li key={i} style={refutedItem}>
                        <span style={{ textDecoration: 'line-through', opacity: 0.7 }}>{r.claim}</span>
                        <span style={ceRef}>CE#{r.ce_id}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* 开放问题 */}
              {thinkingSummary.open_questions.length > 0 && (
                <div style={sectionStyle}>
                  <h4 style={sectionTitle}>❓ 尚存问题</h4>
                  <ul style={openQList}>
                    {thinkingSummary.open_questions.map((q, i) => (
                      <li key={i}>{q}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* 方法论突破 */}
              {thinkingSummary.methodology_note && (
                <div style={sectionStyle}>
                  <h4 style={sectionTitle}>🔬 方法论突破</h4>
                  <p style={methodNote}>{thinkingSummary.methodology_note}</p>
                </div>
              )}
            </>
          )}
        </div>
      )}

      <div style={{ flex: 1, position: 'relative', display: 'flex', flexDirection: isNarrow ? 'column' : 'row', minHeight: 0 }}>
        <div ref={containerRef} style={{ flex: '1 1 50%', position: 'relative', background: bgGradient, minHeight: 0, minWidth: 400 }}>
          {/* CE 类型筛选 toolbar */}
          <div style={filterBarStyle}>
            {Object.keys(CE_COLORS).map(k => {
              const count = stats[k] || 0
              const isActive = activeFilters.includes(k)
              const disabled = count === 0
              return (
                <button
                  key={k}
                  disabled={disabled}
                  onClick={() => {
                    if (disabled) return
                    setActiveFilters(prev =>
                      prev.includes(k) ? prev.filter(x => x !== k) : [...prev, k],
                    )
                  }}
                  style={{
                    fontSize: 11,
                    padding: '3px 8px',
                    borderRadius: 999,
                    background: disabled
                      ? 'rgba(100,116,139,0.1)'
                      : isActive
                        ? nodeColor(k) + '55'
                        : nodeColor(k) + '22',
                    color: disabled ? '#4a5568' : isActive ? '#fff' : nodeColor(k),
                    border: isActive
                      ? `1.5px solid ${nodeColor(k)}`
                      : '1px solid transparent',
                    cursor: disabled ? 'default' : 'pointer',
                    opacity: disabled ? 0.4 : 1,
                    whiteSpace: 'nowrap',
                    transition: 'all .15s ease',
                    lineHeight: 1.4,
                  }}
                >
                  {CE_LABELS[k]} {count}
                </button>
              )
            })}
          </div>
          <svg ref={svgRef} style={{ width: '100%', height: '100%', display: 'block' }}>
            <defs>
              <marker id="arrow-green" viewBox="0 -5 10 10" refX={20} refY={0} markerWidth={6} markerHeight={6} orient="auto">
                <path d="M0,-5L10,0L0,5" fill="#22c55e" />
              </marker>
              <marker id="arrow-red" viewBox="0 -5 10 10" refX={20} refY={0} markerWidth={6} markerHeight={6} orient="auto">
                <path d="M0,-5L10,0L0,5" fill="#ef4444" />
              </marker>
              <marker id="arrow-gray" viewBox="0 -5 10 10" refX={20} refY={0} markerWidth={6} markerHeight={6} orient="auto">
                <path d="M0,-5L10,0L0,5" fill="#5b6175" />
              </marker>
              <radialGradient id="vignette" cx="50%" cy="50%" r="60%">
                <stop offset="0%" stopColor="#1a1d27" stopOpacity={0} />
                <stop offset="100%" stopColor="#0f1117" stopOpacity={0.85} />
              </radialGradient>
              <pattern id="grid" width={40} height={40} patternUnits="userSpaceOnUse">
                <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1f2333" strokeWidth={0.5} />
              </pattern>
            </defs>
            <rect x={0} y={0} width="100%" height="100%" fill="url(#grid)" pointerEvents="none" />
            <rect x={0} y={0} width="100%" height="100%" fill="url(#vignette)" pointerEvents="none" />
            <g className="viewport">
              <g className="links" />
              <g className="nodes" />
            </g>
          </svg>

          {graph.nodes.length === 0 && !error && (
            <div style={emptyStyle}>
              <div style={{ fontSize: 12, color: 'var(--text2)', letterSpacing: 2, marginBottom: 8 }}>STANDBY</div>
              <div style={{ color: 'var(--text)' }}>大脑尚未产生任何认知元素</div>
              <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 6 }}>等待思考触发…</div>
            </div>
          )}

        </div>

        {/* 观察员视角面板 — 占满父级高度，内部自滚动 */}
        <div
          style={{
            ...observerWrap,
            flex: isNarrow ? 'none' : '1 1 50%',
            width: isNarrow ? '100%' : 'auto',
            minWidth: isNarrow ? 'auto' : 420,
            height: isNarrow ? '50vh' : '100%',
            maxHeight: isNarrow ? '50vh' : '100%',
            borderLeft: isNarrow ? 'none' : '1px solid var(--border)',
            borderTop: isNarrow ? '1px solid var(--border)' : 'none',
          }}
          onClick={e => e.stopPropagation()}
        >
          <ObserverPanel brainId={bid} defaultOpen={!isNarrow} brainState={brainState} />
        </div>

        {selected && (
          <aside style={panelStyle} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
              <span
                style={{
                  fontSize: 11,
                  padding: '3px 10px',
                  borderRadius: 4,
                  background: nodeColor(selected.ce_type) + '22',
                  color: nodeColor(selected.ce_type),
                  letterSpacing: 1,
                  textTransform: 'uppercase',
                }}
              >
                {CE_LABELS[selected.ce_type] || selected.ce_type}
              </span>
              <button onClick={() => setSelected(null)} style={closeBtn}>×</button>
            </div>
            <h3 style={{ color: 'var(--text)', fontSize: 16, marginBottom: 8, lineHeight: 1.4 }}>{selected.title}</h3>

            <div style={{ margin: '12px 0' }}>
              <div style={{ fontSize: 10, color: 'var(--text2)', letterSpacing: 1, marginBottom: 4 }}>
                CONFIDENCE · {(selected.confidence * 100).toFixed(0)}%
              </div>
              <div style={{ height: 4, background: 'var(--bg3)', borderRadius: 2, overflow: 'hidden' }}>
                <div
                  style={{
                    width: `${Math.max(0, Math.min(1, selected.confidence)) * 100}%`,
                    height: '100%',
                    background: nodeColor(selected.ce_type),
                    transition: 'width .4s ease',
                  }}
                />
              </div>
            </div>

            <p style={{ color: 'var(--text2)', fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
              {selected.content}
            </p>

            <div style={{ marginTop: 14, fontSize: 11, color: 'var(--text2)', display: 'flex', justifyContent: 'space-between' }}>
              <span>状态：{selected.status}</span>
              <span>{selected.created_at}</span>
            </div>

            {/* 邻居关系列表 */}
            <NeighborList graph={graph} selectedId={selected.id} onPick={setSelected} />

            {selected.metadata && selected.metadata !== '{}' && (
              <pre style={metaStyle}>{tryFormat(selected.metadata)}</pre>
            )}
          </aside>
        )}
      </div>

      {hover && !selected && (
        <div
          style={{
            position: 'fixed',
            left: hover.x + 14,
            top: hover.y + 14,
            pointerEvents: 'none',
            background: 'rgba(15,17,23,0.95)',
            border: `1px solid ${nodeColor(hover.node.ce_type)}66`,
            borderRadius: 6,
            padding: '8px 10px',
            maxWidth: 280,
            fontSize: 12,
            zIndex: 50,
            boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 4 }}>
            <span style={{ color: nodeColor(hover.node.ce_type), fontSize: 10, letterSpacing: 1 }}>
              {CE_LABELS[hover.node.ce_type] || hover.node.ce_type}
            </span>
            <span style={{ color: 'var(--text2)', fontSize: 10 }}>{(hover.node.confidence * 100).toFixed(0)}%</span>
          </div>
          <div style={{ color: 'var(--text)', fontWeight: 500, marginBottom: 4 }}>{hover.node.title}</div>
          <div style={{ color: 'var(--text2)', fontSize: 11, lineHeight: 1.4 }}>
            {hover.node.content && hover.node.content.length > 100
              ? hover.node.content.slice(0, 100) + '…'
              : hover.node.content}
          </div>
        </div>
      )}

      <style>{`
        @keyframes brainPulse { 0%, 100% { opacity: 0.55; transform: scale(1); } 50% { opacity: 1; transform: scale(1.25); } }
        @keyframes seedCorePulse {
          0%, 100% { filter: drop-shadow(0 0 6px #FFD700) drop-shadow(0 0 2px #FFA500); }
          50%      { filter: drop-shadow(0 0 18px #FFB300) drop-shadow(0 0 6px #FF8C00); }
        }
        @keyframes seedHaloPulse {
          0%, 100% { opacity: 0.25; transform: scale(1); }
          50%      { opacity: 0.55; transform: scale(1.18); }
        }
        @keyframes paperSpin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
        circle.seed-core {
          animation: seedCorePulse 2.4s ease-in-out infinite;
          transform-box: fill-box;
          transform-origin: center;
        }
        circle.seed-halo {
          animation: seedHaloPulse 2.4s ease-in-out infinite;
          transform-box: fill-box;
          transform-origin: center;
        }
        .paper-spinner {
          display: inline-block;
          width: 12px;
          height: 12px;
          border: 2px solid rgba(255,255,255,0.3);
          border-top-color: #fff;
          border-radius: 50%;
          animation: paperSpin 0.8s linear infinite;
          margin-right: 6px;
          vertical-align: middle;
        }
      `}</style>
    </div>
  )
}

// ---------- 子组件 ----------
function LegendLine({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4, fontSize: 11, color: 'var(--text2)' }}>
      <svg width={28} height={6}>
        <line x1={0} y1={3} x2={28} y2={3} stroke={color} strokeWidth={1.5} strokeDasharray={dashed ? '4,3' : ''} />
      </svg>
      {label}
    </div>
  )
}

function NeighborList({
  graph,
  selectedId,
  onPick,
}: {
  graph: KnowledgeGraph
  selectedId: number
  onPick: (n: CognitiveNode) => void
}) {
  const neighbors = useMemo(() => {
    const map = new Map<number, CognitiveNode>(graph.nodes.map(n => [n.id, n]))
    const out: { rel: string; dir: 'out' | 'in'; node: CognitiveNode }[] = []
    for (const e of graph.edges) {
      if (e.source_id === selectedId && map.has(e.target_id)) out.push({ rel: e.relation_type, dir: 'out', node: map.get(e.target_id)! })
      else if (e.target_id === selectedId && map.has(e.source_id)) out.push({ rel: e.relation_type, dir: 'in', node: map.get(e.source_id)! })
    }
    return out
  }, [graph, selectedId])

  if (!neighbors.length) return null
  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ fontSize: 10, color: 'var(--text2)', letterSpacing: 1, marginBottom: 6 }}>
        关联节点 · {neighbors.length}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {neighbors.map((nb, i) => (
          <button
            key={i}
            onClick={() => onPick(nb.node)}
            style={{
              textAlign: 'left',
              background: 'var(--bg3)',
              border: '1px solid var(--border)',
              borderLeft: `3px solid ${nodeColor(nb.node.ce_type)}`,
              color: 'var(--text)',
              padding: '6px 10px',
              borderRadius: 4,
              cursor: 'pointer',
              fontSize: 12,
            }}
          >
            <span style={{ color: 'var(--text2)', fontSize: 10, marginRight: 6 }}>
              {nb.dir === 'out' ? '→' : '←'} {REL_LABELS[nb.rel] || nb.rel}
            </span>
            {nb.node.title}
          </button>
        ))}
      </div>
    </div>
  )
}

function tryFormat(s: string) {
  try {
    return JSON.stringify(JSON.parse(s), null, 2)
  } catch {
    return s
  }
}

// ---------- 样式 ----------
const pageStyle: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  background: 'var(--bg)',
  display: 'flex',
  flexDirection: 'column',
  overflow: 'hidden',
}
const headerStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  padding: '12px 24px',
  borderBottom: '1px solid var(--border)',
  background: 'rgba(15,17,23,0.85)',
  backdropFilter: 'blur(10px)',
  zIndex: 10,
  flexShrink: 0,
}
const backBtn: React.CSSProperties = {
  background: 'var(--bg2)',
  border: '1px solid var(--border)',
  color: 'var(--text2)',
  borderRadius: 6,
  padding: '6px 12px',
  cursor: 'pointer',
  fontSize: 12,
}
const pulseDot: React.CSSProperties = {
  display: 'inline-block',
  width: 8,
  height: 8,
  borderRadius: 4,
  background: '#22c55e',
  boxShadow: '0 0 10px #22c55e',
  animation: 'brainPulse 1.6s ease-in-out infinite',
}
const bgGradient = `radial-gradient(ellipse at 50% 50%, #1a1d27 0%, #0f1117 70%)`
const filterBarStyle: React.CSSProperties = {
  position: 'absolute',
  top: 12,
  left: 12,
  right: 12,
  zIndex: 5,
  display: 'flex',
  flexWrap: 'wrap',
  gap: 4,
  padding: '6px 8px',
  background: 'rgba(15,17,23,0.75)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  backdropFilter: 'blur(8px)',
  WebkitBackdropFilter: 'blur(8px)',
}
const legendStyle: React.CSSProperties = {
  position: 'absolute',
  left: 16,
  bottom: 16,
  padding: '10px 14px',
  background: 'rgba(26,29,39,0.7)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  backdropFilter: 'blur(8px)',
}
const panelStyle: React.CSSProperties = {
  width: 360,
  padding: 20,
  borderLeft: '1px solid var(--border)',
  background: 'var(--bg2)',
  overflowY: 'auto',
  flexShrink: 0,
}
const closeBtn: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: 'var(--text2)',
  fontSize: 22,
  cursor: 'pointer',
  lineHeight: 1,
  padding: 0,
}
const emptyStyle: React.CSSProperties = {
  position: 'absolute',
  top: '50%',
  left: '50%',
  transform: 'translate(-50%, -50%)',
  textAlign: 'center',
}
const metaStyle: React.CSSProperties = {
  marginTop: 12,
  background: 'var(--bg3)',
  padding: 8,
  borderRadius: 6,
  fontSize: 11,
  color: 'var(--text2)',
  overflow: 'auto',
  maxHeight: 160,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-all',
}
const observerWrap: React.CSSProperties = {
  background: 'rgba(11,13,22,0.4)',
  padding: 6,
  display: 'flex',
  alignItems: 'stretch',
  overflow: 'hidden',
  minHeight: 0,
  boxSizing: 'border-box',
}
const paperBtnStyle: React.CSSProperties = {
  background: 'var(--bg2)',
  border: '1px solid var(--border)',
  color: '#e2e8f0',
  borderRadius: 8,
  padding: '8px 16px',
  cursor: 'pointer',
  fontSize: 13,
  fontWeight: 500,
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  transition: 'all .15s ease',
  whiteSpace: 'nowrap',
}

// ---------- "大脑想明白了什么" 总结卡片样式 ----------
const summaryCard: React.CSSProperties = {
  background: 'rgba(15, 23, 42, 0.85)',
  backdropFilter: 'blur(8px)',
  border: '1px solid rgba(99, 102, 241, 0.3)',
  borderRadius: 8,
  padding: '10px 16px',
  margin: '0 16px 4px',
}

const summaryCardTitle: React.CSSProperties = {
  margin: 0,
  fontSize: 14,
  fontWeight: 600,
  color: '#e2e8f0',
}

const coreAnswerStyle: React.CSSProperties = {
  fontSize: 13,
  lineHeight: 1.5,
  color: '#93c5fd',
  fontWeight: 500,
  padding: '8px 12px',
  background: 'rgba(59, 130, 246, 0.1)',
  borderRadius: 6,
  borderLeft: '3px solid #3b82f6',
  margin: '8px 0 0',
}

const sectionStyle: React.CSSProperties = { marginTop: 14 }
const sectionTitle: React.CSSProperties = { margin: '0 0 6px', fontSize: 13, fontWeight: 500, color: '#94a3b8' }
const insightList: React.CSSProperties = { listStyle: 'none', padding: 0, margin: 0 }
const insightItem: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'flex-start',
  padding: '6px 0',
  fontSize: 13,
  color: '#cbd5e1',
  gap: 12,
  borderBottom: '1px solid rgba(148, 163, 184, 0.1)',
}
const ceRef: React.CSSProperties = { fontSize: 11, color: '#64748b', marginLeft: 8, whiteSpace: 'nowrap', flexShrink: 0 }
const refutedList: React.CSSProperties = { listStyle: 'none', padding: 0, margin: 0 }
const refutedItem: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '4px 0', fontSize: 13, color: '#94a3b8' }
const openQList: React.CSSProperties = { listStyle: 'disc', paddingLeft: 18, margin: 0, fontSize: 13, color: '#cbd5e1' }
const methodNote: React.CSSProperties = { margin: 0, fontSize: 13, color: '#a5b4fc', fontStyle: 'italic' }

// ---------- 论文公开分享面板样式 ----------
const sharePanelStyle: React.CSSProperties = {
  margin: '8px 16px 0',
  padding: '12px 16px',
  borderRadius: 10,
  background: 'linear-gradient(135deg, rgba(99,102,241,0.10), rgba(236,72,153,0.08))',
  border: '1px solid rgba(129,140,248,0.35)',
  boxShadow: '0 8px 32px -16px rgba(99,102,241,0.6)',
}
const shareBadgeStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: 2,
  padding: '3px 8px',
  borderRadius: 999,
  background: 'rgba(129,140,248,0.18)',
  color: '#c7d2fe',
  border: '1px solid rgba(129,140,248,0.4)',
}
const shareCountStyle: React.CSSProperties = {
  fontSize: 12,
  color: '#94a3b8',
}
const shareInputStyle: React.CSSProperties = {
  flex: 1,
  minWidth: 240,
  background: '#0f1117',
  border: '1px solid #1f2333',
  color: '#cbd5e1',
  fontSize: 12,
  padding: '8px 10px',
  borderRadius: 6,
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
}
const shareCopyBtnStyle: React.CSSProperties = {
  background: '#1d4ed8',
  border: 'none',
  color: '#fff',
  fontSize: 12,
  padding: '8px 14px',
  borderRadius: 6,
  cursor: 'pointer',
  fontWeight: 500,
}
const shareOpenBtnStyle: React.CSSProperties = {
  background: 'transparent',
  border: '1px solid rgba(148,163,184,0.4)',
  color: '#cbd5e1',
  fontSize: 12,
  padding: '7px 12px',
  borderRadius: 6,
  textDecoration: 'none',
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
}
const shareCloseBtn: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#64748b',
  cursor: 'pointer',
  fontSize: 22,
  lineHeight: 1,
  padding: 0,
}


// 快思考模式 badge 样式
const modeBadgeStyle = (mode: 'fast' | 'deep'): React.CSSProperties => ({
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
  padding: '3px 10px',
  borderRadius: 999,
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: 1,
  border: mode === 'fast'
    ? '1px solid rgba(251,191,36,0.55)'
    : '1px solid rgba(129,140,248,0.55)',
  background: mode === 'fast'
    ? 'linear-gradient(135deg, rgba(251,191,36,0.18), rgba(249,115,22,0.18))'
    : 'linear-gradient(135deg, rgba(99,102,241,0.18), rgba(236,72,153,0.18))',
  color: mode === 'fast' ? '#fbbf24' : '#c7d2fe',
})
const modeBadgeCountdownStyle: React.CSSProperties = {
  marginLeft: 4,
  fontFamily: 'ui-monospace, SFMono-Regular, monospace',
  color: 'var(--text2)',
  fontWeight: 500,
}
