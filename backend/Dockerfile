# syntax=docker/dockerfile:1
# Keep the Python patch version recorded by the frozen calibrations.
ARG PYTHON_IMAGE=python:3.11.9-slim-bookworm
FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    TORCH_HOME=/tmp/torch \
    MPLCONFIGDIR=/tmp/matplotlib \
    OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --home-dir /home/inspector inspector

# CPU wheels only. Cached independently of application sources; no train extras.
COPY backend/requirements.txt backend/requirements-cpu.txt /tmp/requirements/
RUN --mount=type=cache,target=/tmp/.cache/pip \
    python -m pip install --only-binary=:all: \
      'torch==2.15.0+cpu' 'torchvision==0.29.2+cpu' \
      --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install --only-binary=:all: -r /tmp/requirements/requirements-cpu.txt \
    && python -m pip check \
    && python -c "import torch,torchvision,importlib.metadata as m; assert torch.version.cuda is None; assert torch.__version__ == '2.15.0+cpu'; assert torchvision.__version__ == '0.29.2+cpu'; assert not any(d.metadata['Name'].lower().startswith(('nvidia-', 'cuda-', 'triton')) for d in m.distributions())"

COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY backend/__init__.py ./backend/__init__.py
COPY backend/app/ ./backend/app/
COPY deployment/healthcheck.py ./deployment/healthcheck.py
COPY deployment/__init__.py deployment/validate_portability.py ./deployment/
# Editable mapping is intentional: scientific PROJECT paths must remain /app,
# and source SHA256 checks must read the original files, not relocated modules.
RUN --mount=type=cache,target=/tmp/.cache/pip \
    python -m pip install --no-deps --no-build-isolation -e . \
    && python -c "from pathlib import Path; from resilientinspect.evaluation import evaluate_transfer; assert evaluate_transfer.PROJECT == Path('/app'); from backend.app.main import app; assert app is not None"

USER inspector
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=90s --retries=6 \
    CMD ["python", "/app/deployment/healthcheck.py"]
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
