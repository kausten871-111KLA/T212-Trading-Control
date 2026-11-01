FROM python:3.12-slim
LABEL org.opencontainers.image.title="TradingAgents research-only lab"
LABEL org.opencontainers.image.revision="e8f5503e9b86d5c2710b0c76b1f686703968c9df"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /opt/tradingagents
COPY . /opt/tradingagents/
RUN python -m pip install --no-cache-dir ".[dev]"
RUN python -c "import tradingagents; assert tradingagents.__version__ == '0.7.0'; print('TRADINGAGENTS_IMPORT_PASS',tradingagents.__version__)"
CMD ["python", "-m", "pytest", "tests", "-q", "-m", "not integration"]
