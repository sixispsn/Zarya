FROM zarya-release:20261001-rainwater-treatment
USER root
ENV ZARYA_BUILD_COMMIT=pdf-rain-design-20261002
COPY app/calc/rainwater_design.py app/calc/rainwater_reuse.py /app/app/calc/
COPY app/intake/studio_intake.py /app/app/intake/
COPY app/web/studio.py app/web/pilot.py /app/app/web/
COPY app/web/static/studio.js app/web/static/studio.css app/web/static/studio_configurator.js /app/app/web/static/
COPY app/web/templates/studio.html /app/app/web/templates/
COPY app/pz/commission.py app/pz/generator.py app/pz/ios2_orchestrator.py /app/app/pz/
COPY app/pz/templates/rainwater_design.html app/pz/templates/rainwater_reuse_body.html app/pz/templates/rainwater_reuse_calculation.html app/pz/templates/subitems_residential.html app/pz/templates/subitems_public.html /app/app/pz/templates/
RUN chmod -R a+rX /app/app
USER zarya
RUN python -c "from app.main import app; from app.intake.pilot_access import REMEMBER_SECONDS; from app.calc.rainwater_reuse import assess, RainwaterReuseInput; from app.web.pilot import _WRITE; assert REMEMBER_SECONDS == 2592000; assert assess(RainwaterReuseInput())['design']['status'] == 'disabled'; assert ('POST', '/studio/api/rainwater/review') in _WRITE"
