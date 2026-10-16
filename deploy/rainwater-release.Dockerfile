FROM zarya-release:20260930-metering-extras
USER root
ENV ZARYA_BUILD_COMMIT=rainwater-20260930
COPY app/calc/rainwater_reuse.py /app/app/calc/
COPY app/intake/request_dto.py app/intake/project_builder.py app/intake/yaml_io.py app/intake/studio_intake.py /app/app/intake/
COPY app/pz/project.py app/pz/generator.py app/pz/spec.py app/pz/commission.py app/pz/ios2_orchestrator.py app/pz/rainwater_reuse.py /app/app/pz/
COPY app/pz/templates/rainwater_reuse_body.html app/pz/templates/rainwater_reuse_calculation.html /app/app/pz/templates/
COPY app/web/wizard.py /app/app/web/
COPY app/web/static/studio_configurator.js app/web/static/studio.js app/web/static/studio.css /app/app/web/static/
COPY app/web/templates/studio.html /app/app/web/templates/
RUN chmod -R a+rX /app/app
USER zarya
RUN python -c "from app.main import app; from app.intake.pilot_access import REMEMBER_SECONDS; from app.calc.rainwater_reuse import assess, RainwaterReuseInput; assert REMEMBER_SECONDS == 2592000; assert assess(RainwaterReuseInput())['status'] == 'disabled'"
