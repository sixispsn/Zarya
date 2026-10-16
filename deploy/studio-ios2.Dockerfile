FROM zarya-release:20261005-samara-vk
USER root
ENV ZARYA_BUILD_COMMIT=studio-ios2-20261005
COPY app/ /app/app/
COPY demo/ /app/demo/
RUN chmod -R a+rX /app/app /app/demo
USER zarya
RUN python -c "from app.main import app; from app.intake.samara_study import load_case; assert load_case()"
