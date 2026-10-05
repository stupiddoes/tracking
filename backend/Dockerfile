FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app app
# WeasyPrint lays out the photo book PDF; Noto CJK supplies Chinese fonts that get embedded in it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f
# The app user has no home; give fontconfig a writable cache so fonts are not rescanned per PDF.
ENV XDG_CACHE_HOME=/tmp/.cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=app:app . .
RUN python manage.py collectstatic --noinput
USER app
EXPOSE 8765
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8765"]
