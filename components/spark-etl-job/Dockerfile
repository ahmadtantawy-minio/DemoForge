FROM apache/spark:3.5.0

USER root
ADD https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/3.3.4/hadoop-aws-3.3.4.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/1.12.262/aws-java-sdk-bundle-1.12.262.jar /opt/spark/jars/
# Ship Iceberg runtime jars so spark-submit does not need Ivy/Maven at runtime (avoids missing ~/.ivy2/cache).
ADD https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-3.5_2.12/1.5.0/iceberg-spark-runtime-3.5_2.12-1.5.0.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-aws-bundle/1.5.0/iceberg-aws-bundle-1.5.0.jar /opt/spark/jars/

COPY jobs/ /opt/demoforge/jobs/
COPY entrypoint.sh /opt/demoforge/entrypoint.sh
# ADD leaves these jars root-owned; the driver runs as USER spark — without chown/chmod, bash -r fails and Java URLClassLoader cannot read bytes → S3A CNFE.
RUN chmod +x /opt/demoforge/entrypoint.sh && chown -R spark:spark /opt/demoforge \
    && mkdir -p /home/spark/.ivy2/cache /home/spark/.ivy2/jars \
    && chown -R spark:spark /home/spark \
    && chown spark:spark \
        /opt/spark/jars/hadoop-aws-3.3.4.jar \
        /opt/spark/jars/aws-java-sdk-bundle-1.12.262.jar \
        /opt/spark/jars/iceberg-spark-runtime-3.5_2.12-1.5.0.jar \
        /opt/spark/jars/iceberg-aws-bundle-1.5.0.jar \
    && chmod 0644 \
        /opt/spark/jars/hadoop-aws-3.3.4.jar \
        /opt/spark/jars/aws-java-sdk-bundle-1.12.262.jar \
        /opt/spark/jars/iceberg-spark-runtime-3.5_2.12-1.5.0.jar \
        /opt/spark/jars/iceberg-aws-bundle-1.5.0.jar

USER spark
ENTRYPOINT ["/opt/demoforge/entrypoint.sh"]
