FROM zarya-release:20260930-rainwater-pump
USER root
ENV ZARYA_BUILD_COMMIT=rainwater-treatment-20261001
COPY app/data/rainwater_treatment.py /app/app/data/
COPY app/calc/rainwater_treatment.py app/calc/rainwater_pump.py app/calc/rainwater_reuse.py /app/app/calc/
COPY app/intake/studio_intake.py /app/app/intake/
COPY app/web/static/studio_configurator.js app/web/static/studio.js /app/app/web/static/
COPY app/web/templates/studio.html /app/app/web/templates/
COPY app/pz/rainwater_reuse.py app/pz/generator.py app/pz/commission.py /app/app/pz/
COPY app/pz/templates/rainwater_reuse_body.html app/pz/templates/rainwater_reuse_calculation.html /app/app/pz/templates/
RUN chmod -R a+rX /app/app
USER zarya
RUN python -c "from app.main import app; from app.intake.pilot_access import REMEMBER_SECONDS; from app.calc.rainwater_reuse import assess, RainwaterReuseInput; assert REMEMBER_SECONDS == 2592000; assert assess(RainwaterReuseInput())['treatment']['status'] == 'not_configured'"
