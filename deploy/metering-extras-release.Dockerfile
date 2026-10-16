# Bounded catalogue/UI update on the already deployed metering release.
FROM zarya-release:20260930-metering-options
USER root
ENV ZARYA_BUILD_COMMIT=metering-extras-20260930
COPY app/data/metering_extras.json app/data/metering_extras.py /app/app/data/
COPY app/intake/studio_intake.py app/intake/studio_project.py /app/app/intake/
COPY app/pz/metering_extras.py app/pz/metering_options.py app/pz/metering_detail_data.py app/pz/metering_rules.py app/pz/metering_spec.py app/pz/generator.py app/pz/spec.py /app/app/pz/
COPY app/pz/templates/spec.css /app/app/pz/templates/
COPY app/web/static/studio.css app/web/static/studio.js /app/app/web/static/
COPY app/web/templates/studio.html /app/app/web/templates/
RUN chmod -R a+rX /app/app
USER zarya
RUN python -c "from app.main import app; from app.intake.pilot_access import REMEMBER_SECONDS; from app.data.metering_extras import get_metering_extras_catalogue; assert REMEMBER_SECONDS == 2592000; assert len(get_metering_extras_catalogue()['products']) == 11"
