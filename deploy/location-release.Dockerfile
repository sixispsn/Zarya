# Bounded UI/reference-geography update. No engineering files are copied.
FROM zarya-release:20260929-remember-device
USER root
ENV ZARYA_BUILD_COMMIT=site-location-20260929
COPY app/main.py /app/app/main.py
COPY app/intake/site_location.py /app/app/intake/site_location.py
COPY app/web/studio.py app/web/studio_location.py app/web/pilot.py /app/app/web/
COPY app/web/static/studio.js app/web/static/studio_location.js app/web/static/studio_location.css /app/app/web/static/
COPY app/web/static/vendor/leaflet /app/app/web/static/vendor/leaflet
COPY app/web/templates/studio.html app/web/templates/studio_location.html /app/app/web/templates/
RUN chmod -R a+rX /app/app
USER zarya
RUN python -c "from app.main import app; from app.intake.pilot_access import REMEMBER_SECONDS; assert REMEMBER_SECONDS == 2592000; assert any(r.path == '/studio/api/location' for r in app.routes)"
