FROM confluentinc/cp-kafka-connect-base:7.7.1

RUN confluent-hub install --no-prompt confluentinc/kafka-connect-s3:latest

ENV CONNECT_PLUGIN_PATH="/usr/share/java,/usr/share/confluent-hub-components"
