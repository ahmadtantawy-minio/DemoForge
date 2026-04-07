FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
EXPOSE 8080 9000 9001 5000
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile"]
