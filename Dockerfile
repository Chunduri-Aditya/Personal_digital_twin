# Digital twin app container. Ollama and LM Studio are NOT containerized here: LM Studio has no official
# Docker/headless image (it's a GUI app) and always has to run natively on the host, so this image only
# replaces the Python/Gradio setup step, not the model-server step (docs/MODEL_SETUP.md covers that).
#
# Build:  docker build -t twin-app .
# Run:    docker run -p 7861:7861 twin-app
#         (native Linux Docker, not Docker Desktop, also needs: --add-host=host.docker.internal:host-gateway)
#
# Versions pinned to what docs/REPLICATE_ON_MAC.md section 9.1 confirmed working against the restyled CSS,
# which keys on Gradio 6.27.0's DOM (requirements.txt itself intentionally stays unpinned, "gradio>=6,<7", so
# it is not used directly here).
FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    "gradio==6.27.0" "gradio_client==2.7.0" "openai==2.15.0" "httpx==0.28.1" \
    "numpy==2.3.5" "anthropic==1.5.0" "pillow==11.3.0" "pypdf==6.18.1"

COPY . .

ENV PYTHONUTF8=1 \
    GRADIO_ANALYTICS_ENABLED=False \
    TWIN_OLLAMA_URL=http://host.docker.internal:11434 \
    TWIN_LMS_URL=http://host.docker.internal:1234

EXPOSE 7861

CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "7861"]
