# syntax=docker/dockerfile:1
# ==========================================
# P6-1 生产镜像：work-agent backend
#
# 体积/稳定性策略：
#   - torch CPU 预装（镜像比 CUDA 版小 ~2GB）
#   - embedding 模型默认不烘焙：由 compose 挂 HF 缓存卷，
#     生产首次启动自动下载一次（服务器需公网），后续重启复用
#   - 可选烘焙：docker build --build-arg BAKE_MODEL=1
# 安全：.env / 密钥 / 数据 / 日志绝不 COPY 进镜像（仅 src）
# ==========================================

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/.cache/huggingface \
    # 关键：代码位于 /app/src/work_agent，需让 uvicorn 可 import work_agent.main
    PYTHONPATH=/app/src

WORKDIR /app

# 系统依赖（最小）
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# torch CPU 先行安装（与开发环境一致；后续 pip 解析到已满足，不再拉取 CUDA 版）
RUN pip install --no-cache-dir \
        torch==2.13.0+cpu \
        --index-url https://download.pytorch.org/whl/cpu

# Python 运行时依赖（requirements.prod.txt 由 uv export 生成，torch 已调为 +cpu）
COPY requirements.prod.txt .
RUN pip install --no-cache-dir \
        -r requirements.prod.txt \
        --extra-index-url https://download.pytorch.org/whl/cpu

# 应用代码（仅 src；.env/密钥/测试数据/日志均不在镜像）
COPY src ./src

# 可选：构建期预下载 embedding 模型（默认关闭）
ARG BAKE_MODEL=0
RUN if [ "$BAKE_MODEL" = "1" ]; then \
        python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5')" \
    ; fi

EXPOSE 8000

# 单 worker：配置中心/Prompt 治理/熔断/健康指标为进程内状态，多 worker 缓存不一致
CMD ["uvicorn", "work_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
