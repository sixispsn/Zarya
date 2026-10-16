# Private opt-in PDF bundles only, over the verified pilot object archive.
FROM zarya-release:20260928-pilot-objects
USER root
ENV ZARYA_BUILD_COMMIT=pilot-attachments-20260928
COPY app/main.py /app/app/main.py
COPY app/intake/pilot_attachments.py app/intake/pilot_pdf_probe.py /app/app/intake/
COPY app/web/pilot_attachments.py app/web/pilot_objects.py app/web/pilot.py /app/app/web/
COPY app/web/static/pilot_attachments.js app/web/static/pilot_objects.css /app/app/web/static/
COPY app/web/templates/pilot_attachment_dialog.html app/web/templates/pilot_objects.html /app/app/web/templates/
RUN chmod -R a+rX /app/app
USER zarya
RUN python -c "from app.main import app; from app.intake.pilot_attachments import PilotAttachmentStore; assert app and PilotAttachmentStore"
