#!/bin/bash

# JARVIS 一键启动/关闭脚本

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT=9529
FRONTEND_PORT=8529

start() {
    echo "🚀 启动 JARVIS 服务..."

    # 启动后端
    echo "📦 启动后端 (端口 $BACKEND_PORT)..."
    cd "$BASE_DIR"
    source venv/bin/activate 2>/dev/null || true
    nohup python -m uvicorn jarvis.main:app --host 0.0.0.0 --port $BACKEND_PORT > logs/backend.log 2>&1 &
    echo $! > logs/backend.pid
    echo "✅ 后端已启动 (PID: $(cat logs/backend.pid))"

    # 等待后端启动
    sleep 2

    # 启动前端
    echo "🎨 启动前端 (端口 $FRONTEND_PORT)..."
    cd "$BASE_DIR/frontend"
    nohup npm run dev -- --port $FRONTEND_PORT > ../logs/frontend.log 2>&1 &
    echo $! > ../logs/frontend.pid
    echo "✅ 前端已启动 (PID: $(cat ../logs/frontend.pid))"

    echo ""
    echo "✨ JARVIS 服务已全部启动!"
    echo "   后端: http://localhost:$BACKEND_PORT"
    echo "   前端: http://localhost:$FRONTEND_PORT"
}

stop() {
    echo "🛑 停止 JARVIS 服务..."

    # 停止后端
    if [ -f logs/backend.pid ]; then
        BACKEND_PID=$(cat logs/backend.pid)
        if kill -0 $BACKEND_PID 2>/dev/null; then
            kill -9 $BACKEND_PID 2>/dev/null
            echo "✅ 后端已停止 (PID: $BACKEND_PID)"
        fi
        rm -f logs/backend.pid
    fi

    # 停止前端
    if [ -f logs/frontend.pid ]; then
        FRONTEND_PID=$(cat logs/frontend.pid)
        if kill -0 $FRONTEND_PID 2>/dev/null; then
            kill -9 $FRONTEND_PID 2>/dev/null
            echo "✅ 前端已停止 (PID: $FRONTEND_PID)"
        fi
        rm -f logs/frontend.pid
    fi

    # 强制清理残留进程
    pkill -f "uvicorn jarvis.main:app" 2>/dev/null
    pkill -f "vite" 2>/dev/null

    echo "✨ JARVIS 服务已全部停止!"
}

status() {
    echo "📊 服务状态检查..."

    if [ -f logs/backend.pid ]; then
        BACKEND_PID=$(cat logs/backend.pid)
        if kill -0 $BACKEND_PID 2>/dev/null; then
            echo "✅ 后端运行中 (PID: $BACKEND_PID, 端口: $BACKEND_PORT)"
        else
            echo "❌ 后端未运行 (PID文件过期)"
        fi
    else
        # 检查是否有进程在跑
        if pgrep -f "uvicorn jarvis.main:app" > /dev/null; then
            echo "✅ 后端运行中 (进程存在)"
        else
            echo "❌ 后端未运行"
        fi
    fi

    if [ -f logs/frontend.pid ]; then
        FRONTEND_PID=$(cat logs/frontend.pid)
        if kill -0 $FRONTEND_PID 2>/dev/null; then
            echo "✅ 前端运行中 (PID: $FRONTEND_PID, 端口: $FRONTEND_PORT)"
        else
            echo "❌ 前端未运行 (PID文件过期)"
        fi
    else
        if pgrep -f "vite" > /dev/null; then
            echo "✅ 前端运行中 (进程存在)"
        else
            echo "❌ 前端未运行"
        fi
    fi
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        stop
        sleep 1
        start
        ;;
    status)
        status
        ;;
    *)
        echo "用法: jarvis.sh {start|stop|restart|status}"
        echo ""
        echo "  start   - 启动所有服务 (后端 + 前端)"
        echo "  stop    - 停止所有服务"
        echo "  restart - 重启所有服务"
        echo "  status  - 查看服务状态"
        exit 1
        ;;
esac