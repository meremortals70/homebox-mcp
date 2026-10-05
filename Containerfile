# Homebox MCP Server - Containerfile
# Read-only MCP server for Homebox v0.26+ (Streamable HTTP on port 8031, path /mcp)
FROM python:3.12-slim

WORKDIR /app

# requirements.txt is a full `pip freeze` of a known-working environment (all versions pinned)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY homebox_mcp_server.py .

ENV PYTHONUNBUFFERED=1
EXPOSE 8031

CMD ["python", "homebox_mcp_server.py"]
