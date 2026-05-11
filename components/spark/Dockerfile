FROM apache/spark:3.5.0

USER root
COPY hadoop-aws-3.3.4.jar /opt/spark/jars/
COPY aws-java-sdk-bundle-1.12.262.jar /opt/spark/jars/
COPY demoforge-start-standalone.sh /opt/spark/demoforge-start-standalone.sh
RUN chmod 0555 /opt/spark/demoforge-start-standalone.sh \
    && chown spark:spark /opt/spark/demoforge-start-standalone.sh
USER spark
