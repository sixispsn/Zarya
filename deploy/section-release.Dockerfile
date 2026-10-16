FROM zarya-release:20261002-pdf-rain-design
USER root
ENV ZARYA_BUILD_COMMIT=unified-section-20261002
COPY app/pz/wastewater_presentation.py app/pz/wastewater_graphic_exports.py app/pz/project.py app/pz/commission.py app/pz/ios2_orchestrator.py /app/app/pz/
COPY app/intake/request_dto.py app/intake/project_builder.py app/intake/yaml_io.py app/intake/studio_intake.py app/intake/studio_section.py app/intake/studio_project.py /app/app/intake/
COPY app/web/studio.py app/web/wizard.py /app/app/web/
RUN chmod -R a+rX /app/app
USER zarya
RUN python -c "from app.main import app; from app.intake.pilot_access import REMEMBER_SECONDS; from app.pz.wastewater_presentation import RepresentativeSectionInput; assert REMEMBER_SECONDS == 2592000; assert RepresentativeSectionInput.from_mapping({'mode':'representative'}).basement_kind == 'unknown'"
