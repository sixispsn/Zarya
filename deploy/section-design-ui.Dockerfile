FROM zarya-release:20261002-section-design
USER root
ENV ZARYA_BUILD_COMMIT=section-design-ui-20261002
COPY app/web/static/studio.css /app/app/web/static/
COPY app/web/templates/studio.html /app/app/web/templates/
RUN chmod a+r /app/app/web/static/studio.css /app/app/web/templates/studio.html
USER zarya
