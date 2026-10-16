# Bounded UI/privacy update over the verified personal-access runtime.
FROM zarya-release:20260927-pilot-access
USER root
ENV ZARYA_BUILD_COMMIT=pilot-feedback-20260927
COPY app/intake/pilot_feedback.py app/intake/studio_store.py /app/app/intake/
COPY app/web/pilot.py app/web/studio.py /app/app/web/
COPY app/web/static/pilot_feedback.css app/web/static/pilot_feedback.js app/web/static/studio.css app/web/static/studio.js /app/app/web/static/
COPY app/web/templates/pilot_feedback.html app/web/templates/pilot_feedback_dialog.html app/web/templates/site_assets.html app/web/templates/site_header.html app/web/templates/studio.html /app/app/web/templates/
RUN chmod -R a+rX /app/app
USER zarya
RUN python -c "from app.main import app; from app.intake.pilot_feedback import FeedbackStore; assert app and FeedbackStore"
