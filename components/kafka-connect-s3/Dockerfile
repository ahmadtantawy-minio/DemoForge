FROM confluentinc/cp-kafka-connect-base:7.7.1

RUN confluent-hub install --no-prompt aiven/aiven-kafka-connect-s3:0.14.0

ENV CONNECT_PLUGIN_PATH="/usr/share/java,/usr/share/confluent-hub-components"
