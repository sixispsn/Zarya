FROM zarya-release:20260928-pilot-admin
USER root
ENV ZARYA_BUILD_COMMIT=remember-device-20260929
COPY app/intake/pilot_access.py /app/app/intake/pilot_access.py
COPY app/web/pilot.py /app/app/web/pilot.py
COPY app/web/templates/pilot_login.html /app/app/web/templates/pilot_login.html
COPY app/web/static/pilot.js app/web/static/pilot.css /app/app/web/static/
RUN chmod -R a+rX /app/app
USER zarya
RUN python -c "from app.main import app; from app.intake.pilot_access import REMEMBER_SECONDS; assert app and REMEMBER_SECONDS == 2592000"
