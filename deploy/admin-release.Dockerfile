# Authentication, private pilot administration and immutable result history only.
FROM zarya-release:20260928-pilot-attachments
USER root
ENV ZARYA_BUILD_COMMIT=pilot-admin-20260928 ZARYA_REQUIRE_PILOT=1
RUN touch /app/.require-personal-auth
COPY app/main.py /app/app/main.py
COPY app/intake/pilot_admin.py app/intake/pilot_capture.py app/intake/pilot_objects.py app/intake/studio_store.py /app/app/intake/
COPY app/web/pilot_admin.py app/web/pilot.py app/web/pilot_objects.py app/web/studio.py /app/app/web/
COPY app/web/static/pilot_admin.js app/web/static/pilot_admin.css app/web/static/pilot.js app/web/static/studio.js app/web/static/studio_projects.js /app/app/web/static/
COPY app/web/templates/pilot_admin.html app/web/templates/pilot_participation.html app/web/templates/pilot_login.html app/web/templates/pilot_objects.html app/web/templates/site_header.html app/web/templates/studio.html app/web/templates/studio_projects.html /app/app/web/templates/
RUN chmod -R a+rX /app/app && chmod 444 /app/.require-personal-auth
USER zarya
RUN python -c "from app.main import app; from app.intake.pilot_capture import PilotCaptureStore; assert app and PilotCaptureStore"
