FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && useradd --uid 1000 --create-home lab \
    && mkdir /data && chown lab:lab /data
USER lab
EXPOSE 8091
CMD ["python", "-m", "sim_engine.workflow_lab.cli", "fixtures", "--host", "0.0.0.0", "--db", "/data/fixtures.sqlite"]
