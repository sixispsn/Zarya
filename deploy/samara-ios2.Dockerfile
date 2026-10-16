FROM zarya-release:20261002-section-design-ui
USER root
ENV ZARYA_BUILD_COMMIT=samara-ios2-20261004
COPY app/ /app/app/
COPY demo/ /app/demo/
RUN chmod -R a+rX /app/app /app/demo
USER zarya
RUN python -c "from app.main import app; from app.intake.samara_study import load_case; assert load_case()"
