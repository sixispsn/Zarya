# Bounded update over the currently deployed runtime; no dependency/core changes.
FROM zarya-release:20260927-alpha002
USER root
ENV ZARYA_BUILD_COMMIT=pilot-access-20260927
COPY app/main.py /app/app/main.py
COPY app/intake/pilot_access.py /app/app/intake/pilot_access.py
COPY app/web/pilot.py app/web/studio.py /app/app/web/
COPY app/web/static/pilot.css app/web/static/pilot.js app/web/static/site.css /app/app/web/static/
COPY app/web/templates/pilot_login.html app/web/templates/site_assets.html app/web/templates/site_header.html app/web/templates/studio_projects.html /app/app/web/templates/
COPY scripts/pilot_access.py /app/scripts/pilot_access.py
RUN chmod -R a+rX /app/app /app/scripts
USER zarya
RUN python -c "from app.main import app; from scripts.pilot_access import main; assert app and main"
