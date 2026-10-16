FROM zarya-release:20261002-unified-section
USER root
ENV ZARYA_BUILD_COMMIT=section-design-20261002
COPY app/pz/wastewater_presentation.py app/pz/wastewater_graphic_exports.py app/pz/residential_concept_section.py app/pz/wastewater_drafting.py /app/app/pz/
COPY app/intake/studio_section.py app/intake/studio_intake.py /app/app/intake/
COPY app/web/static/studio_configurator.js app/web/static/studio.js /app/app/web/static/
COPY app/web/templates/studio.html /app/app/web/templates/
RUN chmod -R a+rX /app/app
USER zarya
RUN python -c "from app.main import app; from app.intake.pilot_access import REMEMBER_SECONDS; from app.pz.wastewater_presentation import SectionMainInput; assert REMEMBER_SECONDS == 2592000; assert SectionMainInput(dn_mm=150, slope=.02).dn_mm == 150"
