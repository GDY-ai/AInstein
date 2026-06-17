#!/usr/bin/env bash
#
# AInstein 一键部署脚本
# 用法: ./scripts/deploy.sh [--force] [--skip-deps] [--skip-frontend] [--local-build] [--help]
#
# 部署目标固定为生产环境: root@47.253.15.17:/opt/ainstein
#
set -euo pipefail

# ---------- 颜色输出 ----------
if [[ -t 1 ]]; then
    C_RED=$'\033[0;31m'
    C_GREEN=$'\033[0;32m'
    C_YELLOW=$'\033[0;33m'
    C_BLUE=$'\033[0;34m'
    C_CYAN=$'\033[0;36m'
    C_BOLD=$'\033[1m'
    C_RESET=$'\033[0m'
else
    C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''; C_CYAN=''; C_BOLD=''; C_RESET=''
fi

log()      { printf "${C_CYAN}[%s]${C_RESET} %s\n" "$(date +%H:%M:%S)" "$*"; }
info()     { printf "${C_BLUE}ℹ${C_RESET}  %s\n" "$*"; }
ok()       { printf "${C_GREEN}✔${C_RESET}  %s\n" "$*"; }
warn()     { printf "${C_YELLOW}⚠${C_RESET}  %s\n" "$*"; }
err()      { printf "${C_RED}✘${C_RESET}  %s\n" "$*" >&2; }
section()  { printf "\n${C_BOLD}${C_BLUE}▶ %s${C_RESET}\n" "$*"; }

# ---------- 默认配置 ----------
FORCE=0
SKIP_DEPS=0
SKIP_FRONTEND=0
LOCAL_BUILD=0
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---------- 帮助 ----------
print_help() {
    cat <<EOF
${C_BOLD}AInstein 一键部署脚本${C_RESET}

用法:
  $(basename "$0") [选项]

选项:
  --force             跳过本地 git 状态干净检查
  --skip-deps         跳过 pip 依赖安装
  --skip-frontend     跳过前端构建
  --local-build       在本地构建前端，再 rsync 到服务器（默认在服务器构建）
  -h, --help          显示此帮助

示例:
  $(basename "$0")                    # 部署到生产
  $(basename "$0") --force --skip-deps

部署目标:
  root@47.253.15.17:/opt/ainstein  (生产, 美国 Virginia)
EOF
}

# ---------- 参数解析 ----------
for arg in "$@"; do
    case "$arg" in
        --force)        FORCE=1 ;;
        --skip-deps)    SKIP_DEPS=1 ;;
        --skip-frontend) SKIP_FRONTEND=1 ;;
        --local-build)  LOCAL_BUILD=1 ;;
        -h|--help)      print_help; exit 0 ;;
        *)              err "未知参数: $arg"; print_help; exit 1 ;;
    esac
done

# ---------- 环境配置（硬编码生产）----------
SERVER_HOST="47.253.15.17"
SERVER_USER="root"
ENV_LABEL="生产环境 (Production - 47.253.15.17)"
REMOTE="${SERVER_USER}@${SERVER_HOST}"
REMOTE_PATH="/opt/ainstein"
SERVICE_NAME="ainstein"
PORT=9089
HEALTH_URL_LOCAL="http://localhost:${PORT}/ainstein/api/health"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)

# ---------- 部署横幅 ----------
cat <<EOF

${C_BOLD}${C_CYAN}╔══════════════════════════════════════════════╗
║       AInstein 一键部署                       ║
╚══════════════════════════════════════════════╝${C_RESET}
  目标环境 : ${C_BOLD}${ENV_LABEL}${C_RESET}
  服务器   : ${REMOTE}
  远程路径 : ${REMOTE_PATH}
  服务     : systemd ${SERVICE_NAME} (端口 ${PORT})
  本地路径 : ${PROJECT_ROOT}
EOF

warn "⚠️  你正在部署到 ${C_BOLD}生产环境${C_RESET}！"
if [[ -t 0 ]]; then
    read -r -p "确认继续部署? 输入 'yes' 继续: " confirm
    if [[ "$confirm" != "yes" ]]; then
        err "部署已取消"
        exit 1
    fi
fi

cd "$PROJECT_ROOT"

# ---------- 1. 本地检查 ----------
section "Step 1/6 — 本地检查"

# 安全检查：禁止同步 .env 和 HANDOFF.md
DANGEROUS_FILES=(.env HANDOFF.md)
for f in "${DANGEROUS_FILES[@]}"; do
    if [[ -e "$f" ]]; then
        info "检测到 $f （将被 rsync 排除）"
    fi
done

# git 状态检查
if command -v git >/dev/null 2>&1 && [[ -d .git ]]; then
    if [[ $FORCE -eq 0 ]]; then
        if ! git diff --quiet || ! git diff --cached --quiet; then
            err "本地存在未提交的修改。请先 commit/stash，或使用 --force 跳过此检查。"
            git status --short
            exit 1
        fi
        ok "git 工作区干净"
    else
        warn "已使用 --force，跳过 git 状态检查"
    fi
    GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    info "git: ${GIT_BRANCH} @ ${GIT_SHA}"
else
    warn "未检测到 git 仓库，跳过 git 检查"
fi

# 依赖工具检查
for tool in rsync ssh; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        err "缺少必需工具: $tool"
        exit 1
    fi
done
ok "本地工具齐全 (rsync, ssh)"

# ---------- 2. 本地前端构建（可选）----------
if [[ $LOCAL_BUILD -eq 1 && $SKIP_FRONTEND -eq 0 ]]; then
    section "Step 2/6 — 本地构建前端"
    if [[ ! -d frontend ]]; then
        err "未找到 frontend/ 目录"
        exit 1
    fi
    (cd frontend && npm install && npm run build)
    ok "前端本地构建完成 → frontend/dist/"
else
    section "Step 2/6 — 跳过本地前端构建（将在服务器构建）"
fi

# ---------- 3. rsync 同步代码 ----------
section "Step 3/6 — 同步代码到 ${REMOTE}:${REMOTE_PATH}"

RSYNC_EXCLUDES=(
    --exclude='.git/'
    --exclude='.gitignore'
    --exclude='data/'
    --exclude='.env'
    --exclude='.env.*'
    --exclude='HANDOFF.md'
    --exclude='node_modules/'
    --exclude='__pycache__/'
    --exclude='*.pyc'
    --exclude='*.db'
    --exclude='*.db-journal'
    --exclude='*.db-wal'
    --exclude='*.db-shm'
    --exclude='venv/'
    --exclude='.venv/'
    --exclude='._*'
    --exclude='.DS_Store'
    --exclude='.qoder/'
    --exclude='.idea/'
    --exclude='.vscode/'
    --exclude='*.bak'
)

# 当不在本地构建时，也排除 dist/
if [[ $LOCAL_BUILD -eq 0 ]]; then
    RSYNC_EXCLUDES+=(--exclude='frontend/dist/')
fi

# 确保远程目录存在
ssh "${SSH_OPTS[@]}" "$REMOTE" "mkdir -p ${REMOTE_PATH}"

rsync -az --delete --human-readable \
    "${RSYNC_EXCLUDES[@]}" \
    -e "ssh ${SSH_OPTS[*]}" \
    "${PROJECT_ROOT}/" "${REMOTE}:${REMOTE_PATH}/"

ok "代码同步完成"

# ---------- 4. 远程依赖安装 + 前端构建 + 重启 ----------
section "Step 4/6 — 远程构建与重启"

REMOTE_SCRIPT=$(cat <<REMOTE_EOF
set -euo pipefail
cd ${REMOTE_PATH}

echo "[remote] 当前目录: \$(pwd)"
echo "[remote] 部署时间: \$(date '+%Y-%m-%d %H:%M:%S')"

# Python 依赖
if [[ ${SKIP_DEPS} -eq 0 ]]; then
    echo "[remote] 安装 Python 依赖..."
    pip3 install --quiet -r requirements.txt
    echo "[remote] ✔ Python 依赖完成"
else
    echo "[remote] ⚠ 跳过 pip 依赖安装"
fi

# 前端构建
if [[ ${SKIP_FRONTEND} -eq 0 && ${LOCAL_BUILD} -eq 0 ]]; then
    echo "[remote] 构建前端..."
    cd frontend
    npm install --silent --no-audit --no-fund
    npm run build
    cd ..
    echo "[remote] ✔ 前端构建完成"
else
    echo "[remote] ⚠ 跳过远程前端构建"
fi

# 重启服务
echo "[remote] 重启 systemd ${SERVICE_NAME}..."
systemctl restart ${SERVICE_NAME}
sleep 2
systemctl is-active --quiet ${SERVICE_NAME} && echo "[remote] ✔ 服务已激活" || (echo "[remote] ✘ 服务未激活" && systemctl status ${SERVICE_NAME} --no-pager -l | tail -n 30 && exit 1)
REMOTE_EOF
)

ssh "${SSH_OPTS[@]}" "$REMOTE" "bash -s" <<< "$REMOTE_SCRIPT"
ok "远程构建与服务重启完成"

# ---------- 5. 健康检查 ----------
section "Step 5/6 — 健康检查"
info "等待服务就绪..."

HEALTH_OK=0
for i in 1 2 3 4 5 6 7 8 9 10; do
    sleep 2
    if RESPONSE=$(ssh "${SSH_OPTS[@]}" "$REMOTE" "curl -fsS --max-time 5 ${HEALTH_URL_LOCAL}" 2>/dev/null); then
        ok "健康检查通过 (尝试 ${i}/10)"
        echo "    └─ ${RESPONSE}"
        HEALTH_OK=1
        break
    else
        warn "尝试 ${i}/10 失败，重试中..."
    fi
done

if [[ $HEALTH_OK -eq 0 ]]; then
    err "健康检查失败！请检查服务日志:"
    err "  ssh ${REMOTE} 'journalctl -u ${SERVICE_NAME} -n 50 --no-pager'"
    exit 1
fi

# ---------- 6. 完成 ----------
section "Step 6/6 — 部署完成"
cat <<EOF

${C_GREEN}${C_BOLD}🚀 AInstein 部署成功！${C_RESET}

  环境       : ${ENV_LABEL}
  服务器     : ${REMOTE}
  健康检查   : ${HEALTH_URL_LOCAL}
  Git        : ${GIT_BRANCH:-?} @ ${GIT_SHA:-?}
  完成时间   : $(date '+%Y-%m-%d %H:%M:%S')

常用命令:
  查看日志: ssh ${REMOTE} 'journalctl -u ${SERVICE_NAME} -f'
  服务状态: ssh ${REMOTE} 'systemctl status ${SERVICE_NAME}'
  重启服务: ssh ${REMOTE} 'systemctl restart ${SERVICE_NAME}'

EOF
