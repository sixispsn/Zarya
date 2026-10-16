# UI and intake metadata only, over the verified private pilot release.
FROM zarya-release:20260927-pilot-feedback
USER root
ENV ZARYA_BUILD_COMMIT=studio-configurator-20260928
COPY app/intake/studio_intake.py app/intake/studio_project.py /app/app/intake/
COPY app/web/studio.py /app/app/web/studio.py
COPY app/web/static/studio.js app/web/static/studio.css app/web/static/studio_configurator.js /app/app/web/static/
COPY app/web/templates/studio.html /app/app/web/templates/studio.html
RUN chmod -R a+rX /app/app
USER zarya
RUN python -c "from app.main import app; from app.intake.studio_intake import context_issues; assert app and context_issues"
