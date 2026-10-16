# Private snapshot archive only, over the verified three-block configurator.
FROM zarya-release:20260928-studio-configurator
USER root
ENV ZARYA_BUILD_COMMIT=pilot-objects-20260928
COPY app/main.py /app/app/main.py
COPY app/intake/pilot_objects.py app/intake/studio_store.py /app/app/intake/
COPY app/web/pilot_objects.py app/web/pilot.py app/web/studio.py /app/app/web/
COPY app/web/static/pilot_objects.js app/web/static/pilot_objects.css app/web/static/studio.js /app/app/web/static/
COPY app/web/templates/pilot_objects.html app/web/templates/pilot_snapshot_dialog.html app/web/templates/studio.html app/web/templates/studio_projects.html /app/app/web/templates/
RUN chmod -R a+rX /app/app
USER zarya
RUN python -c "from app.main import app; from app.intake.pilot_objects import make_snapshot; assert app and make_snapshot"
