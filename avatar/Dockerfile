FROM pytorch/pytorch:2.3.1-cuda12.1-cudnn8-runtime
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 libgl1 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY requirements-avatar.txt /tmp/requirements-avatar.txt
RUN python -m pip install -r /tmp/requirements-avatar.txt
COPY vendor/feathertalk/ /opt/FeatherTalk/
COPY engine/ /engine/
COPY runtime/ /lab/
COPY characters.py characters.json /lab/
WORKDIR /lab
ENV PYTHONPATH=/engine:/lab:/opt/FeatherTalk OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
CMD ["python", "/lab/server.py"]
