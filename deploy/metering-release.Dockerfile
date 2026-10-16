# Bounded water-meter detail/specification/options release; preserve live auth.
FROM zarya-release:20260929-site-location
USER root
ENV ZARYA_BUILD_COMMIT=metering-options-20260930
COPY app/data/metering_products.json app/data/metering_products.py /app/app/data/
COPY app/intake/project_builder.py app/intake/request_dto.py app/intake/studio_intake.py app/intake/studio_project.py app/intake/yaml_io.py /app/app/intake/
COPY app/pz/aux_schemes.py app/pz/commission.py app/pz/generator.py app/pz/ios2_orchestrator.py app/pz/project.py app/pz/spec.py /app/app/pz/
COPY app/pz/metering_accessories.py app/pz/metering_catalogue_sheet.py app/pz/metering_chain.py app/pz/metering_connection_sheet.py app/pz/metering_connections.py app/pz/metering_detail.py app/pz/metering_detail_data.py app/pz/metering_options.py app/pz/metering_pipe_sheet.py app/pz/metering_pipes.py app/pz/metering_product_selection.py app/pz/metering_reducers.py app/pz/metering_rules.py app/pz/metering_rules_sheet.py app/pz/metering_spec.py /app/app/pz/
COPY app/pz/templates/meter_table.html app/pz/templates/spec_table.html /app/app/pz/templates/
COPY app/web/static/studio.css app/web/static/studio.js app/web/static/studio_configurator.js /app/app/web/static/
COPY app/web/templates/studio.html /app/app/web/templates/
RUN chmod -R a+rX /app/app
USER zarya
RUN python -c "from app.main import app; from app.intake.pilot_access import REMEMBER_SECONDS; from app.pz.metering_options import METERING_OPTIONS; assert REMEMBER_SECONDS == 2592000; assert len(METERING_OPTIONS) == 8; assert any(r.path == '/studio/api/location' for r in app.routes)"
